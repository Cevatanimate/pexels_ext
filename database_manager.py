# SPDX-License-Identifier: GPL-3.0-or-later
"""
SQLite Database Manager for Pexels Extension.

Provides persistent storage for cache metadata, favorites, categories,
search history, and settings using SQLite with thread-safe operations.
"""

import os
import sqlite3
import threading
import time
import json
import tempfile
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager

from .models import (
    EnhancedCacheEntry,
    CachedSearchResult,
    PhotoData,
    FavoriteItem,
    Category,
    SearchHistoryEntry,
    CacheStatistics,
    RetentionPolicy,
    CacheType,
    generate_uuid
)
from . import logger


class DatabaseManager:
    """
    Thread-safe SQLite database manager for cache metadata.
    
    Implements singleton pattern for global access.
    
    Features:
    - Thread-safe operations with connection pooling
    - Automatic schema creation and migration
    - CRUD operations for all data types
    - Efficient querying with indexes
    - Transaction support
    
    Usage:
        db = DatabaseManager()
        
        # Store cache entry
        db.insert_cache_entry(entry)
        
        # Query favorites
        favorites = db.get_all_favorites()
        
        # Record search history
        db.insert_search_history(entry)
    """
    
    _instance: Optional['DatabaseManager'] = None
    _instance_lock: threading.Lock = threading.Lock()
    
    # Database configuration
    DATABASE_FILENAME = "pexels_cache.db"
    SCHEMA_VERSION = 1
    
    def __new__(cls) -> 'DatabaseManager':
        """Singleton pattern implementation."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance
    
    def __init__(self):
        """Initialize the database manager."""
        if self._initialized:
            return
        
        self._initialized = True
        
        # Thread-local storage for connections
        self._local = threading.local()
        self._lock = threading.RLock()
        
        # Database path
        self._db_path = self._get_database_path()
        
        # Initialize database
        self._init_database()
    
    def _get_database_path(self) -> str:
        """
        Get the database file path.
        
        Tries to use Blender's user directory, falls back to system temp.
        
        Returns:
            Path to database file
        """
        db_dir = None
        
        # Try Blender's user directory first
        try:
            import bpy
            user_path = bpy.utils.resource_path('USER')
            db_dir = os.path.join(user_path, "cache", "pexels_cache")
        except (ImportError, Exception):
            pass
        
        # Fall back to system temp directory
        if db_dir is None:
            db_dir = os.path.join(tempfile.gettempdir(), "pexels_cache")
        
        # Create directory if it doesn't exist
        os.makedirs(db_dir, exist_ok=True)
        
        return os.path.join(db_dir, self.DATABASE_FILENAME)
    
    def _get_connection(self) -> sqlite3.Connection:
        """
        Get a thread-local database connection.
        
        Returns:
            SQLite connection for current thread
        """
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            self._local.connection = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                timeout=30.0
            )
            self._local.connection.row_factory = sqlite3.Row
            # Enable foreign keys
            self._local.connection.execute("PRAGMA foreign_keys = ON")
        
        return self._local.connection
    
    @contextmanager
    def _transaction(self):
        """
        Context manager for database transactions.
        
        Yields:
            Database cursor
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error("Database transaction failed", exception=e)
            raise
        finally:
            cursor.close()
    
    def _init_database(self) -> None:
        """Initialize database schema."""
        with self._lock:
            try:
                with self._transaction() as cursor:
                    # Create tables
                    self._create_tables(cursor)
                    
                    # Check and run migrations
                    self._run_migrations(cursor)
                    
                logger.debug(f"Database initialized: {self._db_path}")
                
            except Exception as e:
                logger.error("Failed to initialize database", exception=e)
                raise
    
    def _create_tables(self, cursor: sqlite3.Cursor) -> None:
        """Create database tables if they don't exist."""
        
        # Schema version table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at REAL NOT NULL
            )
        """)
        
        # Cache entries table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cache_entries (
                id TEXT PRIMARY KEY,
                cache_key TEXT UNIQUE NOT NULL,
                file_path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                content_type TEXT DEFAULT '',
                original_url TEXT DEFAULT '',
                variant TEXT DEFAULT '',
                created_at REAL NOT NULL,
                last_accessed REAL NOT NULL,
                expires_at REAL,
                access_count INTEGER DEFAULT 0,
                cache_type TEXT DEFAULT 'THUMBNAIL',
                metadata TEXT DEFAULT '{}'
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_cache_key 
            ON cache_entries(cache_key)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_cache_expires 
            ON cache_entries(expires_at)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_cache_accessed 
            ON cache_entries(last_accessed)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_cache_type 
            ON cache_entries(cache_type)
        """)
        
        # Search results cache table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS search_cache (
                id TEXT PRIMARY KEY,
                query TEXT NOT NULL,
                query_hash TEXT NOT NULL,
                page INTEGER NOT NULL,
                per_page INTEGER NOT NULL,
                total_results INTEGER NOT NULL,
                results_json TEXT NOT NULL,
                cached_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                access_count INTEGER DEFAULT 0,
                last_accessed REAL,
                UNIQUE(query_hash, page, per_page)
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_search_hash 
            ON search_cache(query_hash)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_search_expires 
            ON search_cache(expires_at)
        """)
        
        # Categories table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                color TEXT DEFAULT '#808080',
                icon TEXT DEFAULT 'COLLECTION_NEW',
                created_at REAL NOT NULL,
                sort_order INTEGER DEFAULT 0
            )
        """)
        
        # Favorites table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                id TEXT PRIMARY KEY,
                pexels_id INTEGER NOT NULL UNIQUE,
                thumb_url TEXT NOT NULL,
                full_url TEXT NOT NULL,
                photographer TEXT DEFAULT '',
                width INTEGER DEFAULT 0,
                height INTEGER DEFAULT 0,
                category_id TEXT,
                tags TEXT DEFAULT '[]',
                notes TEXT DEFAULT '',
                added_at REAL NOT NULL,
                last_used REAL,
                use_count INTEGER DEFAULT 0,
                cached_thumb_path TEXT,
                cached_full_path TEXT,
                FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_favorites_pexels 
            ON favorites(pexels_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_favorites_category 
            ON favorites(category_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_favorites_added 
            ON favorites(added_at)
        """)
        
        # Tags table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                use_count INTEGER DEFAULT 0,
                created_at REAL NOT NULL
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tags_name 
            ON tags(name)
        """)
        
        # Favorite-tag junction table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS favorite_tags (
                favorite_id TEXT NOT NULL,
                tag_id TEXT NOT NULL,
                PRIMARY KEY (favorite_id, tag_id),
                FOREIGN KEY (favorite_id) REFERENCES favorites(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
            )
        """)
        
        # Search history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS search_history (
                id TEXT PRIMARY KEY,
                query TEXT NOT NULL,
                query_hash TEXT NOT NULL,
                result_count INTEGER NOT NULL,
                searched_at REAL NOT NULL,
                page INTEGER DEFAULT 1,
                per_page INTEGER DEFAULT 50,
                cached_result_id TEXT,
                FOREIGN KEY (cached_result_id) REFERENCES search_cache(id) ON DELETE SET NULL
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_history_time 
            ON search_history(searched_at)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_history_query 
            ON search_history(query_hash)
        """)
        
        # Settings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        
        # Statistics table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS statistics (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                cache_hits INTEGER DEFAULT 0,
                cache_misses INTEGER DEFAULT 0,
                memory_hits INTEGER DEFAULT 0,
                disk_hits INTEGER DEFAULT 0,
                updated_at REAL NOT NULL
            )
        """)
        
        # Initialize statistics row
        cursor.execute("""
            INSERT OR IGNORE INTO statistics (id, updated_at)
            VALUES (1, ?)
        """, (time.time(),))
        
        # Insert default categories
        self._insert_default_categories(cursor)
    
    def _insert_default_categories(self, cursor: sqlite3.Cursor) -> None:
        """Insert default categories if they don't exist."""
        default_categories = Category.create_default_categories()
        
        for cat in default_categories:
            cursor.execute("""
                INSERT OR IGNORE INTO categories (id, name, color, icon, created_at, sort_order)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (cat.id, cat.name, cat.color, cat.icon, cat.created_at, cat.sort_order))
    
    def _run_migrations(self, cursor: sqlite3.Cursor) -> None:
        """Run database migrations if needed."""
        # Get current schema version
        cursor.execute("SELECT MAX(version) FROM schema_version")
        row = cursor.fetchone()
        current_version = row[0] if row and row[0] else 0
        
        # Run migrations
        if current_version < self.SCHEMA_VERSION:
            # Future migrations would go here
            pass
        
        # Update schema version
        if current_version < self.SCHEMA_VERSION:
            cursor.execute("""
                INSERT INTO schema_version (version, applied_at)
                VALUES (?, ?)
            """, (self.SCHEMA_VERSION, time.time()))
    
    # ========================================================================
    # Cache Entry Operations
    # ========================================================================
    
    def insert_cache_entry(self, entry: EnhancedCacheEntry) -> bool:
        """
        Insert or update a cache entry.
        
        Args:
            entry: Cache entry to insert
            
        Returns:
            True if successful
        """
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    INSERT OR REPLACE INTO cache_entries
                    (id, cache_key, file_path, size_bytes, content_type, original_url,
                     variant, created_at, last_accessed, expires_at, access_count,
                     cache_type, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    entry.id,
                    entry.cache_key,
                    entry.file_path,
                    entry.size_bytes,
                    entry.content_type,
                    entry.original_url,
                    entry.variant,
                    entry.created_at,
                    entry.last_accessed,
                    entry.expires_at,
                    entry.access_count,
                    entry.cache_type.name,
                    json.dumps(entry.metadata)
                ))
            return True
        except Exception as e:
            logger.error("Failed to insert cache entry", exception=e)
            return False
    
    def get_cache_entry(self, cache_key: str) -> Optional[EnhancedCacheEntry]:
        """
        Get a cache entry by key.
        
        Args:
            cache_key: Cache key to look up
            
        Returns:
            Cache entry or None if not found
        """
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    SELECT * FROM cache_entries WHERE cache_key = ?
                """, (cache_key,))
                row = cursor.fetchone()
                
                if row:
                    return self._row_to_cache_entry(row)
                return None
        except Exception as e:
            logger.error("Failed to get cache entry", exception=e)
            return None
    
    def get_cache_entry_by_id(self, entry_id: str) -> Optional[EnhancedCacheEntry]:
        """Get a cache entry by ID."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    SELECT * FROM cache_entries WHERE id = ?
                """, (entry_id,))
                row = cursor.fetchone()
                
                if row:
                    return self._row_to_cache_entry(row)
                return None
        except Exception as e:
            logger.error("Failed to get cache entry by ID", exception=e)
            return None
    
    def update_cache_access(self, cache_key: str) -> bool:
        """
        Update last accessed time and increment access count.
        
        Args:
            cache_key: Cache key to update
            
        Returns:
            True if successful
        """
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    UPDATE cache_entries
                    SET last_accessed = ?, access_count = access_count + 1
                    WHERE cache_key = ?
                """, (time.time(), cache_key))
            return True
        except Exception as e:
            logger.error("Failed to update cache access", exception=e)
            return False
    
    def delete_cache_entry(self, cache_key: str) -> bool:
        """
        Delete a cache entry.
        
        Args:
            cache_key: Cache key to delete
            
        Returns:
            True if successful
        """
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    DELETE FROM cache_entries WHERE cache_key = ?
                """, (cache_key,))
            return True
        except Exception as e:
            logger.error("Failed to delete cache entry", exception=e)
            return False
    
    def get_expired_cache_entries(self) -> List[EnhancedCacheEntry]:
        """Get all expired cache entries."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    SELECT * FROM cache_entries
                    WHERE expires_at IS NOT NULL AND expires_at < ?
                """, (time.time(),))
                rows = cursor.fetchall()
                return [self._row_to_cache_entry(row) for row in rows]
        except Exception as e:
            logger.error("Failed to get expired cache entries", exception=e)
            return []
    
    def get_cache_entries_by_type(self, cache_type: CacheType) -> List[EnhancedCacheEntry]:
        """Get all cache entries of a specific type."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    SELECT * FROM cache_entries WHERE cache_type = ?
                    ORDER BY last_accessed DESC
                """, (cache_type.name,))
                rows = cursor.fetchall()
                return [self._row_to_cache_entry(row) for row in rows]
        except Exception as e:
            logger.error("Failed to get cache entries by type", exception=e)
            return []
    
    def get_oldest_cache_entries(self, limit: int = 100) -> List[EnhancedCacheEntry]:
        """Get oldest cache entries by last access time."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    SELECT * FROM cache_entries
                    ORDER BY last_accessed ASC
                    LIMIT ?
                """, (limit,))
                rows = cursor.fetchall()
                return [self._row_to_cache_entry(row) for row in rows]
        except Exception as e:
            logger.error("Failed to get oldest cache entries", exception=e)
            return []
    
    def get_total_cache_size(self) -> int:
        """Get total size of all cached files in bytes."""
        try:
            with self._transaction() as cursor:
                cursor.execute("SELECT SUM(size_bytes) FROM cache_entries")
                row = cursor.fetchone()
                return row[0] if row and row[0] else 0
        except Exception as e:
            logger.error("Failed to get total cache size", exception=e)
            return 0
    
    def get_cache_entry_count(self) -> int:
        """Get total number of cache entries."""
        try:
            with self._transaction() as cursor:
                cursor.execute("SELECT COUNT(*) FROM cache_entries")
                row = cursor.fetchone()
                return row[0] if row else 0
        except Exception as e:
            logger.error("Failed to get cache entry count", exception=e)
            return 0
    
    def _row_to_cache_entry(self, row: sqlite3.Row) -> EnhancedCacheEntry:
        """Convert database row to EnhancedCacheEntry."""
        return EnhancedCacheEntry(
            id=row['id'],
            cache_key=row['cache_key'],
            file_path=row['file_path'],
            size_bytes=row['size_bytes'],
            content_type=row['content_type'] or '',
            original_url=row['original_url'] or '',
            variant=row['variant'] or '',
            created_at=row['created_at'],
            last_accessed=row['last_accessed'],
            expires_at=row['expires_at'],
            access_count=row['access_count'] or 0,
            cache_type=CacheType[row['cache_type']] if row['cache_type'] else CacheType.THUMBNAIL,
            metadata=json.loads(row['metadata']) if row['metadata'] else {}
        )
    
    # ========================================================================
    # Search Cache Operations
    # ========================================================================
    
    def insert_search_result(self, result: CachedSearchResult) -> bool:
        """
        Insert or update a cached search result.
        
        Args:
            result: Search result to cache
            
        Returns:
            True if successful
        """
        try:
            with self._transaction() as cursor:
                # Serialize photos to JSON
                photos_json = json.dumps([p.to_dict() for p in result.photos])
                
                cursor.execute("""
                    INSERT OR REPLACE INTO search_cache
                    (id, query, query_hash, page, per_page, total_results,
                     results_json, cached_at, expires_at, access_count, last_accessed)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    result.id,
                    result.query,
                    result.query_hash,
                    result.page,
                    result.per_page,
                    result.total_results,
                    photos_json,
                    result.cached_at,
                    result.expires_at,
                    result.access_count,
                    result.last_accessed
                ))
            return True
        except Exception as e:
            logger.error("Failed to insert search result", exception=e)
            return False
    
    def get_search_result(self, query: str, page: int, per_page: int) -> Optional[CachedSearchResult]:
        """
        Get a cached search result.
        
        Args:
            query: Search query
            page: Page number
            per_page: Results per page
            
        Returns:
            Cached search result or None if not found/expired
        """
        try:
            query_hash = CachedSearchResult.generate_query_hash(query, page, per_page)
            
            with self._transaction() as cursor:
                cursor.execute("""
                    SELECT * FROM search_cache
                    WHERE query_hash = ? AND page = ? AND per_page = ?
                    AND expires_at > ?
                """, (query_hash, page, per_page, time.time()))
                row = cursor.fetchone()
                
                if row:
                    # Update access stats
                    cursor.execute("""
                        UPDATE search_cache
                        SET access_count = access_count + 1, last_accessed = ?
                        WHERE id = ?
                    """, (time.time(), row['id']))
                    
                    return self._row_to_search_result(row)
                return None
        except Exception as e:
            logger.error("Failed to get search result", exception=e)
            return None
    
    def get_search_result_by_id(self, result_id: str) -> Optional[CachedSearchResult]:
        """Get a cached search result by ID."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    SELECT * FROM search_cache WHERE id = ?
                """, (result_id,))
                row = cursor.fetchone()
                
                if row:
                    return self._row_to_search_result(row)
                return None
        except Exception as e:
            logger.error("Failed to get search result by ID", exception=e)
            return None
    
    def delete_search_result(self, result_id: str) -> bool:
        """Delete a cached search result."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    DELETE FROM search_cache WHERE id = ?
                """, (result_id,))
            return True
        except Exception as e:
            logger.error("Failed to delete search result", exception=e)
            return False
    
    def delete_expired_search_results(self) -> int:
        """Delete all expired search results."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    DELETE FROM search_cache WHERE expires_at < ?
                """, (time.time(),))
                return cursor.rowcount
        except Exception as e:
            logger.error("Failed to delete expired search results", exception=e)
            return 0
    
    def get_search_cache_count(self) -> int:
        """Get number of cached search results."""
        try:
            with self._transaction() as cursor:
                cursor.execute("SELECT COUNT(*) FROM search_cache")
                row = cursor.fetchone()
                return row[0] if row else 0
        except Exception as e:
            logger.error("Failed to get search cache count", exception=e)
            return 0
    
    def _row_to_search_result(self, row: sqlite3.Row) -> CachedSearchResult:
        """Convert database row to CachedSearchResult."""
        photos_data = json.loads(row['results_json'])
        photos = [PhotoData.from_dict(p) for p in photos_data]
        
        return CachedSearchResult(
            id=row['id'],
            query=row['query'],
            query_hash=row['query_hash'],
            page=row['page'],
            per_page=row['per_page'],
            total_results=row['total_results'],
            photos=photos,
            cached_at=row['cached_at'],
            expires_at=row['expires_at'],
            access_count=row['access_count'] or 0,
            last_accessed=row['last_accessed']
        )
    
    # ========================================================================
    # Favorites Operations
    # ========================================================================
    
    def insert_favorite(self, favorite: FavoriteItem) -> bool:
        """
        Insert or update a favorite.
        
        Args:
            favorite: Favorite item to insert
            
        Returns:
            True if successful
        """
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    INSERT OR REPLACE INTO favorites
                    (id, pexels_id, thumb_url, full_url, photographer, width, height,
                     category_id, tags, notes, added_at, last_used, use_count,
                     cached_thumb_path, cached_full_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    favorite.id,
                    favorite.pexels_id,
                    favorite.thumb_url,
                    favorite.full_url,
                    favorite.photographer,
                    favorite.width,
                    favorite.height,
                    favorite.category_id,
                    json.dumps(favorite.tags),
                    favorite.notes,
                    favorite.added_at,
                    favorite.last_used,
                    favorite.use_count,
                    favorite.cached_thumb_path,
                    favorite.cached_full_path
                ))
            return True
        except Exception as e:
            logger.error("Failed to insert favorite", exception=e)
            return False
    
    def get_favorite(self, favorite_id: str) -> Optional[FavoriteItem]:
        """Get a favorite by ID."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    SELECT * FROM favorites WHERE id = ?
                """, (favorite_id,))
                row = cursor.fetchone()
                
                if row:
                    return self._row_to_favorite(row)
                return None
        except Exception as e:
            logger.error("Failed to get favorite", exception=e)
            return None
    
    def get_favorite_by_pexels_id(self, pexels_id: int) -> Optional[FavoriteItem]:
        """Get a favorite by Pexels ID."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    SELECT * FROM favorites WHERE pexels_id = ?
                """, (pexels_id,))
                row = cursor.fetchone()
                
                if row:
                    return self._row_to_favorite(row)
                return None
        except Exception as e:
            logger.error("Failed to get favorite by Pexels ID", exception=e)
            return None
    
    def is_favorite(self, pexels_id: int) -> bool:
        """Check if an image is favorited."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    SELECT 1 FROM favorites WHERE pexels_id = ?
                """, (pexels_id,))
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error("Failed to check favorite status", exception=e)
            return False
    
    def delete_favorite(self, favorite_id: str) -> bool:
        """Delete a favorite by ID."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    DELETE FROM favorites WHERE id = ?
                """, (favorite_id,))
            return True
        except Exception as e:
            logger.error("Failed to delete favorite", exception=e)
            return False
    
    def delete_favorite_by_pexels_id(self, pexels_id: int) -> bool:
        """Delete a favorite by Pexels ID."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    DELETE FROM favorites WHERE pexels_id = ?
                """, (pexels_id,))
            return True
        except Exception as e:
            logger.error("Failed to delete favorite by Pexels ID", exception=e)
            return False
    
    def get_all_favorites(self, limit: int = None, offset: int = 0) -> List[FavoriteItem]:
        """Get all favorites."""
        try:
            with self._transaction() as cursor:
                if limit:
                    cursor.execute("""
                        SELECT * FROM favorites
                        ORDER BY added_at DESC
                        LIMIT ? OFFSET ?
                    """, (limit, offset))
                else:
                    cursor.execute("""
                        SELECT * FROM favorites
                        ORDER BY added_at DESC
                    """)
                rows = cursor.fetchall()
                return [self._row_to_favorite(row) for row in rows]
        except Exception as e:
            logger.error("Failed to get all favorites", exception=e)
            return []
    
    def get_favorites_by_category(self, category_id: str) -> List[FavoriteItem]:
        """Get favorites in a specific category."""
        try:
            with self._transaction() as cursor:
                if category_id == '__uncategorized__':
                    cursor.execute("""
                        SELECT * FROM favorites
                        WHERE category_id IS NULL OR category_id = '__uncategorized__'
                        ORDER BY added_at DESC
                    """)
                elif category_id == '__recent__':
                    # Last 7 days
                    week_ago = time.time() - (7 * 24 * 60 * 60)
                    cursor.execute("""
                        SELECT * FROM favorites
                        WHERE added_at > ?
                        ORDER BY added_at DESC
                    """, (week_ago,))
                elif category_id == '__most_used__':
                    cursor.execute("""
                        SELECT * FROM favorites
                        WHERE use_count > 0
                        ORDER BY use_count DESC
                        LIMIT 50
                    """)
                else:
                    cursor.execute("""
                        SELECT * FROM favorites
                        WHERE category_id = ?
                        ORDER BY added_at DESC
                    """, (category_id,))
                rows = cursor.fetchall()
                return [self._row_to_favorite(row) for row in rows]
        except Exception as e:
            logger.error("Failed to get favorites by category", exception=e)
            return []
    
    def update_favorite_use(self, favorite_id: str) -> bool:
        """Update last used time and increment use count."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    UPDATE favorites
                    SET last_used = ?, use_count = use_count + 1
                    WHERE id = ?
                """, (time.time(), favorite_id))
            return True
        except Exception as e:
            logger.error("Failed to update favorite use", exception=e)
            return False
    
    def update_favorite_category(self, favorite_id: str, category_id: str) -> bool:
        """Update favorite's category."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    UPDATE favorites SET category_id = ? WHERE id = ?
                """, (category_id, favorite_id))
            return True
        except Exception as e:
            logger.error("Failed to update favorite category", exception=e)
            return False
    
    def update_favorite_tags(self, favorite_id: str, tags: List[str]) -> bool:
        """Update favorite's tags."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    UPDATE favorites SET tags = ? WHERE id = ?
                """, (json.dumps(tags), favorite_id))
            return True
        except Exception as e:
            logger.error("Failed to update favorite tags", exception=e)
            return False
    
    def update_favorite_notes(self, favorite_id: str, notes: str) -> bool:
        """Update favorite's notes."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    UPDATE favorites SET notes = ? WHERE id = ?
                """, (notes, favorite_id))
            return True
        except Exception as e:
            logger.error("Failed to update favorite notes", exception=e)
            return False
    
    def get_favorites_count(self) -> int:
        """Get total number of favorites."""
        try:
            with self._transaction() as cursor:
                cursor.execute("SELECT COUNT(*) FROM favorites")
                row = cursor.fetchone()
                return row[0] if row else 0
        except Exception as e:
            logger.error("Failed to get favorites count", exception=e)
            return 0
    
    def search_favorites(self, query: str) -> List[FavoriteItem]:
        """Search favorites by photographer name or tags."""
        try:
            search_term = f"%{query}%"
            with self._transaction() as cursor:
                cursor.execute("""
                    SELECT * FROM favorites
                    WHERE photographer LIKE ? OR tags LIKE ? OR notes LIKE ?
                    ORDER BY added_at DESC
                """, (search_term, search_term, search_term))
                rows = cursor.fetchall()
                return [self._row_to_favorite(row) for row in rows]
        except Exception as e:
            logger.error("Failed to search favorites", exception=e)
            return []
    
    def _row_to_favorite(self, row: sqlite3.Row) -> FavoriteItem:
        """Convert database row to FavoriteItem."""
        return FavoriteItem(
            id=row['id'],
            pexels_id=row['pexels_id'],
            thumb_url=row['thumb_url'],
            full_url=row['full_url'],
            photographer=row['photographer'] or '',
            width=row['width'] or 0,
            height=row['height'] or 0,
            category_id=row['category_id'],
            tags=json.loads(row['tags']) if row['tags'] else [],
            notes=row['notes'] or '',
            added_at=row['added_at'],
            last_used=row['last_used'],
            use_count=row['use_count'] or 0,
            cached_thumb_path=row['cached_thumb_path'],
            cached_full_path=row['cached_full_path']
        )
    
    # ========================================================================
    # Category Operations
    # ========================================================================
    
    def insert_category(self, category: Category) -> bool:
        """Insert or update a category."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    INSERT OR REPLACE INTO categories
                    (id, name, color, icon, created_at, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    category.id,
                    category.name,
                    category.color,
                    category.icon,
                    category.created_at,
                    category.sort_order
                ))
            return True
        except Exception as e:
            logger.error("Failed to insert category", exception=e)
            return False
    
    def get_category(self, category_id: str) -> Optional[Category]:
        """Get a category by ID."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    SELECT c.*, COUNT(f.id) as item_count
                    FROM categories c
                    LEFT JOIN favorites f ON f.category_id = c.id
                    WHERE c.id = ?
                    GROUP BY c.id
                """, (category_id,))
                row = cursor.fetchone()
                
                if row:
                    return self._row_to_category(row)
                return None
        except Exception as e:
            logger.error("Failed to get category", exception=e)
            return None
    
    def get_all_categories(self) -> List[Category]:
        """Get all categories with item counts."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    SELECT c.*, COUNT(f.id) as item_count
                    FROM categories c
                    LEFT JOIN favorites f ON f.category_id = c.id
                    GROUP BY c.id
                    ORDER BY c.sort_order, c.name
                """)
                rows = cursor.fetchall()
                return [self._row_to_category(row) for row in rows]
        except Exception as e:
            logger.error("Failed to get all categories", exception=e)
            return []
    
    def delete_category(self, category_id: str) -> bool:
        """Delete a category (favorites will have category_id set to NULL)."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    DELETE FROM categories WHERE id = ?
                """, (category_id,))
            return True
        except Exception as e:
            logger.error("Failed to delete category", exception=e)
            return False
    
    def rename_category(self, category_id: str, new_name: str) -> bool:
        """Rename a category."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    UPDATE categories SET name = ? WHERE id = ?
                """, (new_name, category_id))
            return True
        except Exception as e:
            logger.error("Failed to rename category", exception=e)
            return False
    
    def _row_to_category(self, row: sqlite3.Row) -> Category:
        """Convert database row to Category."""
        return Category(
            id=row['id'],
            name=row['name'],
            color=row['color'] or '#808080',
            icon=row['icon'] or 'COLLECTION_NEW',
            created_at=row['created_at'],
            sort_order=row['sort_order'] or 0,
            item_count=row['item_count'] if 'item_count' in row.keys() else 0
        )
    
    # ========================================================================
    # Search History Operations
    # ========================================================================
    
    def insert_search_history(self, entry: SearchHistoryEntry) -> bool:
        """Insert a search history entry."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    INSERT INTO search_history
                    (id, query, query_hash, result_count, searched_at, page, per_page, cached_result_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    entry.id,
                    entry.query,
                    entry.query_hash,
                    entry.result_count,
                    entry.searched_at,
                    entry.page,
                    entry.per_page,
                    entry.cached_result_id
                ))
            return True
        except Exception as e:
            logger.error("Failed to insert search history", exception=e)
            return False
    
    def get_search_history(self, limit: int = 100, offset: int = 0) -> List[SearchHistoryEntry]:
        """Get search history entries."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    SELECT * FROM search_history
                    ORDER BY searched_at DESC
                    LIMIT ? OFFSET ?
                """, (limit, offset))
                rows = cursor.fetchall()
                return [self._row_to_history_entry(row) for row in rows]
        except Exception as e:
            logger.error("Failed to get search history", exception=e)
            return []
    
    def get_search_history_today(self) -> List[SearchHistoryEntry]:
        """Get today's search history."""
        try:
            import datetime
            today_start = datetime.datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            ).timestamp()
            
            with self._transaction() as cursor:
                cursor.execute("""
                    SELECT * FROM search_history
                    WHERE searched_at >= ?
                    ORDER BY searched_at DESC
                """, (today_start,))
                rows = cursor.fetchall()
                return [self._row_to_history_entry(row) for row in rows]
        except Exception as e:
            logger.error("Failed to get today's search history", exception=e)
            return []
    
    def get_search_history_this_week(self) -> List[SearchHistoryEntry]:
        """Get this week's search history."""
        try:
            week_ago = time.time() - (7 * 24 * 60 * 60)
            
            with self._transaction() as cursor:
                cursor.execute("""
                    SELECT * FROM search_history
                    WHERE searched_at >= ?
                    ORDER BY searched_at DESC
                """, (week_ago,))
                rows = cursor.fetchall()
                return [self._row_to_history_entry(row) for row in rows]
        except Exception as e:
            logger.error("Failed to get this week's search history", exception=e)
            return []
    
    def delete_search_history_entry(self, entry_id: str) -> bool:
        """Delete a search history entry."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    DELETE FROM search_history WHERE id = ?
                """, (entry_id,))
            return True
        except Exception as e:
            logger.error("Failed to delete search history entry", exception=e)
            return False
    
    def clear_search_history(self) -> int:
        """Clear all search history."""
        try:
            with self._transaction() as cursor:
                cursor.execute("DELETE FROM search_history")
                return cursor.rowcount
        except Exception as e:
            logger.error("Failed to clear search history", exception=e)
            return 0
    
    def cleanup_old_history(self, days: int = 30) -> int:
        """Delete history entries older than specified days."""
        try:
            cutoff = time.time() - (days * 24 * 60 * 60)
            
            with self._transaction() as cursor:
                cursor.execute("""
                    DELETE FROM search_history WHERE searched_at < ?
                """, (cutoff,))
                return cursor.rowcount
        except Exception as e:
            logger.error("Failed to cleanup old history", exception=e)
            return 0
    
    def get_search_history_count(self) -> int:
        """Get total number of history entries."""
        try:
            with self._transaction() as cursor:
                cursor.execute("SELECT COUNT(*) FROM search_history")
                row = cursor.fetchone()
                return row[0] if row else 0
        except Exception as e:
            logger.error("Failed to get search history count", exception=e)
            return 0
    
    def get_popular_queries(self, limit: int = 10) -> List[Tuple[str, int]]:
        """Get most popular search queries."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    SELECT query, COUNT(*) as count
                    FROM search_history
                    GROUP BY query
                    ORDER BY count DESC
                    LIMIT ?
                """, (limit,))
                rows = cursor.fetchall()
                return [(row['query'], row['count']) for row in rows]
        except Exception as e:
            logger.error("Failed to get popular queries", exception=e)
            return []
    
    def _row_to_history_entry(self, row: sqlite3.Row) -> SearchHistoryEntry:
        """Convert database row to SearchHistoryEntry."""
        return SearchHistoryEntry(
            id=row['id'],
            query=row['query'],
            query_hash=row['query_hash'],
            result_count=row['result_count'],
            searched_at=row['searched_at'],
            page=row['page'] or 1,
            per_page=row['per_page'] or 50,
            cached_result_id=row['cached_result_id']
        )
    
    # ========================================================================
    # Statistics Operations
    # ========================================================================
    
    def record_cache_hit(self, from_memory: bool = False) -> None:
        """Record a cache hit."""
        try:
            with self._transaction() as cursor:
                if from_memory:
                    cursor.execute("""
                        UPDATE statistics
                        SET cache_hits = cache_hits + 1,
                            memory_hits = memory_hits + 1,
                            updated_at = ?
                        WHERE id = 1
                    """, (time.time(),))
                else:
                    cursor.execute("""
                        UPDATE statistics
                        SET cache_hits = cache_hits + 1,
                            disk_hits = disk_hits + 1,
                            updated_at = ?
                        WHERE id = 1
                    """, (time.time(),))
        except Exception as e:
            logger.error("Failed to record cache hit", exception=e)
    
    def record_cache_miss(self) -> None:
        """Record a cache miss."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    UPDATE statistics
                    SET cache_misses = cache_misses + 1, updated_at = ?
                    WHERE id = 1
                """, (time.time(),))
        except Exception as e:
            logger.error("Failed to record cache miss", exception=e)
    
    def get_statistics(self, policy: RetentionPolicy = None) -> CacheStatistics:
        """Get comprehensive cache statistics."""
        try:
            if policy is None:
                policy = RetentionPolicy.default()
            
            with self._transaction() as cursor:
                # Get statistics row
                cursor.execute("SELECT * FROM statistics WHERE id = 1")
                stats_row = cursor.fetchone()
                
                # Get counts
                cursor.execute("SELECT COUNT(*) FROM cache_entries")
                cache_count = cursor.fetchone()[0] or 0
                
                cursor.execute("SELECT SUM(size_bytes) FROM cache_entries")
                disk_used = cursor.fetchone()[0] or 0
                
                cursor.execute("SELECT COUNT(*) FROM search_cache")
                search_count = cursor.fetchone()[0] or 0
                
                cursor.execute("SELECT COUNT(*) FROM favorites")
                favorites_count = cursor.fetchone()[0] or 0
                
                cursor.execute("SELECT COUNT(*) FROM search_history")
                history_count = cursor.fetchone()[0] or 0
                
                return CacheStatistics(
                    disk_used_bytes=disk_used,
                    disk_max_bytes=policy.max_disk_size_bytes,
                    memory_items=0,  # Will be updated by cache manager
                    memory_max_items=policy.max_memory_items,
                    total_cached_images=cache_count,
                    total_cached_searches=search_count,
                    total_favorites=favorites_count,
                    total_history_entries=history_count,
                    cache_hits=stats_row['cache_hits'] if stats_row else 0,
                    cache_misses=stats_row['cache_misses'] if stats_row else 0,
                    memory_hits=stats_row['memory_hits'] if stats_row else 0,
                    disk_hits=stats_row['disk_hits'] if stats_row else 0
                )
        except Exception as e:
            logger.error("Failed to get statistics", exception=e)
            return CacheStatistics(
                disk_used_bytes=0,
                disk_max_bytes=500 * 1024 * 1024,
                memory_items=0,
                memory_max_items=100,
                total_cached_images=0,
                total_cached_searches=0,
                total_favorites=0,
                total_history_entries=0,
                cache_hits=0,
                cache_misses=0,
                memory_hits=0,
                disk_hits=0
            )
    
    def reset_statistics(self) -> bool:
        """Reset all statistics."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    UPDATE statistics
                    SET cache_hits = 0, cache_misses = 0,
                        memory_hits = 0, disk_hits = 0,
                        updated_at = ?
                    WHERE id = 1
                """, (time.time(),))
            return True
        except Exception as e:
            logger.error("Failed to reset statistics", exception=e)
            return False
    
    # ========================================================================
    # Settings Operations
    # ========================================================================
    
    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a setting value."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    SELECT value FROM settings WHERE key = ?
                """, (key,))
                row = cursor.fetchone()
                
                if row:
                    return json.loads(row['value'])
                return default
        except Exception as e:
            logger.error("Failed to get setting", exception=e)
            return default
    
    def set_setting(self, key: str, value: Any) -> bool:
        """Set a setting value."""
        try:
            with self._transaction() as cursor:
                cursor.execute("""
                    INSERT OR REPLACE INTO settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                """, (key, json.dumps(value), time.time()))
            return True
        except Exception as e:
            logger.error("Failed to set setting", exception=e)
            return False
    
    def get_retention_policy(self) -> RetentionPolicy:
        """Get the current retention policy."""
        policy_dict = self.get_setting('retention_policy')
        if policy_dict:
            return RetentionPolicy.from_dict(policy_dict)
        return RetentionPolicy.default()
    
    def set_retention_policy(self, policy: RetentionPolicy) -> bool:
        """Set the retention policy."""
        return self.set_setting('retention_policy', policy.to_dict())
    
    # ========================================================================
    # Cleanup Operations
    # ========================================================================
    
    def vacuum(self) -> bool:
        """Vacuum the database to reclaim space."""
        try:
            conn = self._get_connection()
            conn.execute("VACUUM")
            return True
        except Exception as e:
            logger.error("Failed to vacuum database", exception=e)
            return False
    
    def close(self) -> None:
        """Close the database connection."""
        if hasattr(self._local, 'connection') and self._local.connection:
            try:
                self._local.connection.close()
            except Exception:
                pass
            self._local.connection = None
    
    def get_database_path(self) -> str:
        """Get the database file path."""
        return self._db_path


# Global instance
database_manager = None


def get_database_manager() -> DatabaseManager:
    """
    Get the global database manager instance.
    
    Returns:
        DatabaseManager instance
    """
    global database_manager
    if database_manager is None:
        database_manager = DatabaseManager()
    return database_manager