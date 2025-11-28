"""
Cache Manager for Pexels Extension.

Provides a two-tier caching system with memory LRU cache and disk cache.
Thread-safe implementation with configurable limits and automatic cleanup.
"""

import os
import json
import hashlib
import time
import threading
import tempfile
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, Tuple
from collections import OrderedDict
from pathlib import Path


@dataclass
class CacheEntry:
    """
    Represents a cache entry with metadata.
    
    Attributes:
        key: Unique cache key (hash)
        file_path: Path to cached file on disk
        size_bytes: Size of cached data in bytes
        created_at: Timestamp when entry was created
        last_accessed: Timestamp of last access
        expires_at: Timestamp when entry expires (None = never)
        metadata: Additional metadata (e.g., original URL, content type)
    """
    key: str
    file_path: str
    size_bytes: int
    created_at: float
    last_accessed: float
    expires_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_expired(self) -> bool:
        """Check if this cache entry has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'key': self.key,
            'file_path': self.file_path,
            'size_bytes': self.size_bytes,
            'created_at': self.created_at,
            'last_accessed': self.last_accessed,
            'expires_at': self.expires_at,
            'metadata': self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CacheEntry':
        """Create CacheEntry from dictionary."""
        return cls(
            key=data['key'],
            file_path=data['file_path'],
            size_bytes=data['size_bytes'],
            created_at=data['created_at'],
            last_accessed=data['last_accessed'],
            expires_at=data.get('expires_at'),
            metadata=data.get('metadata', {})
        )


class LRUCache:
    """
    Thread-safe LRU (Least Recently Used) memory cache.
    
    Uses OrderedDict to maintain access order for efficient LRU eviction.
    """
    
    def __init__(self, max_items: int = 100):
        """
        Initialize LRU cache.
        
        Args:
            max_items: Maximum number of items to store
        """
        self._max_items = max_items
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._lock = threading.RLock()
    
    def get(self, key: str) -> Optional[bytes]:
        """
        Get item from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached data or None if not found
        """
        with self._lock:
            if key in self._cache:
                # Move to end (most recently used)
                self._cache.move_to_end(key)
                return self._cache[key]
            return None
    
    def put(self, key: str, data: bytes) -> None:
        """
        Put item in cache.
        
        Args:
            key: Cache key
            data: Data to cache
        """
        with self._lock:
            if key in self._cache:
                # Update existing and move to end
                self._cache.move_to_end(key)
                self._cache[key] = data
            else:
                # Add new item
                self._cache[key] = data
                
                # Evict oldest if over limit
                while len(self._cache) > self._max_items:
                    self._cache.popitem(last=False)
    
    def remove(self, key: str) -> bool:
        """
        Remove item from cache.
        
        Args:
            key: Cache key
            
        Returns:
            True if item was removed
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def clear(self) -> None:
        """Clear all items from cache."""
        with self._lock:
            self._cache.clear()
    
    def __len__(self) -> int:
        """Get number of items in cache."""
        with self._lock:
            return len(self._cache)
    
    def __contains__(self, key: str) -> bool:
        """Check if key is in cache."""
        with self._lock:
            return key in self._cache


class CacheStats:
    """Thread-safe cache statistics tracker."""
    
    def __init__(self):
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._memory_hits = 0
        self._disk_hits = 0
    
    def record_hit(self, from_memory: bool = False) -> None:
        """Record a cache hit."""
        with self._lock:
            self._hits += 1
            if from_memory:
                self._memory_hits += 1
            else:
                self._disk_hits += 1
    
    def record_miss(self) -> None:
        """Record a cache miss."""
        with self._lock:
            self._misses += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current statistics."""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0.0
            return {
                'hits': self._hits,
                'misses': self._misses,
                'memory_hits': self._memory_hits,
                'disk_hits': self._disk_hits,
                'total_requests': total,
                'hit_rate_percent': hit_rate
            }
    
    def reset(self) -> None:
        """Reset statistics."""
        with self._lock:
            self._hits = 0
            self._misses = 0
            self._memory_hits = 0
            self._disk_hits = 0


class CacheManager:
    """
    Thread-safe two-tier cache manager with memory LRU and disk caching.
    
    Implements singleton pattern for global access.
    
    Features:
    - Memory LRU cache for fast access
    - Disk cache for persistence
    - Configurable size limits
    - Automatic LRU eviction
    - TTL (time-to-live) support
    - Cache statistics tracking
    
    Usage:
        cache_manager = CacheManager()
        
        # Store data
        cache_manager.put("https://example.com/image.jpg", image_bytes)
        
        # Retrieve data
        data = cache_manager.get("https://example.com/image.jpg")
        
        # Check if cached
        if cache_manager.has("https://example.com/image.jpg"):
            ...
    """
    
    _instance: Optional['CacheManager'] = None
    _instance_lock: threading.Lock = threading.Lock()
    
    # Default configuration
    DEFAULT_CACHE_DIR = "pexels_cache"
    MAX_DISK_SIZE_MB = 500  # Maximum disk cache size in MB
    MAX_MEMORY_ITEMS = 100  # Maximum items in memory cache
    DEFAULT_TTL_DAYS = 7    # Default TTL in days
    INDEX_FILENAME = "cache_index.json"
    
    def __new__(cls) -> 'CacheManager':
        """Singleton pattern implementation."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance
    
    def __init__(self):
        """Initialize the cache manager."""
        if self._initialized:
            return
        
        self._initialized = True
        
        # Cache directory
        self._cache_dir = self._get_cache_directory()
        self._index_file = os.path.join(self._cache_dir, self.INDEX_FILENAME)
        
        # Disk cache index
        self._index: Dict[str, CacheEntry] = {}
        self._index_lock = threading.RLock()
        
        # Memory LRU cache
        self._memory_cache = LRUCache(max_items=self.MAX_MEMORY_ITEMS)
        
        # Statistics
        self._stats = CacheStats()
        
        # Load existing index
        self._load_index()
    
    def _get_cache_directory(self) -> str:
        """
        Get or create the cache directory.
        
        Tries to use Blender's user directory, falls back to system temp.
        
        Returns:
            Path to cache directory
        """
        cache_dir = None
        
        # Try Blender's user directory first
        try:
            import bpy
            user_path = bpy.utils.resource_path('USER')
            cache_dir = os.path.join(user_path, "cache", self.DEFAULT_CACHE_DIR)
        except (ImportError, Exception):
            pass
        
        # Fall back to system temp directory
        if cache_dir is None:
            cache_dir = os.path.join(tempfile.gettempdir(), self.DEFAULT_CACHE_DIR)
        
        # Create directory if it doesn't exist
        os.makedirs(cache_dir, exist_ok=True)
        
        return cache_dir
    
    def _load_index(self) -> None:
        """Load cache index from disk."""
        with self._index_lock:
            if os.path.exists(self._index_file):
                try:
                    with open(self._index_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        for key, entry_data in data.items():
                            entry = CacheEntry.from_dict(entry_data)
                            # Verify file still exists
                            if os.path.exists(entry.file_path):
                                self._index[key] = entry
                except (json.JSONDecodeError, IOError, KeyError) as e:
                    print(f"[CacheManager] Failed to load cache index: {e}")
                    self._index = {}
    
    def _save_index(self) -> None:
        """Save cache index to disk."""
        with self._index_lock:
            try:
                data = {key: entry.to_dict() for key, entry in self._index.items()}
                with open(self._index_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
            except IOError as e:
                print(f"[CacheManager] Failed to save cache index: {e}")
    
    def _generate_key(self, identifier: str, variant: str = "") -> str:
        """
        Generate a cache key from identifier and variant.
        
        Args:
            identifier: Primary identifier (e.g., URL)
            variant: Optional variant (e.g., "thumb", "full")
            
        Returns:
            SHA256 hash key (32 characters)
        """
        content = f"{identifier}:{variant}" if variant else identifier
        return hashlib.sha256(content.encode('utf-8')).hexdigest()[:32]
    
    def _get_file_extension(self, identifier: str, metadata: Optional[Dict] = None) -> str:
        """
        Determine file extension for cached file.
        
        Args:
            identifier: Original identifier (e.g., URL)
            metadata: Optional metadata with content type
            
        Returns:
            File extension including dot (e.g., ".jpg")
        """
        # Try to get from metadata
        if metadata and 'content_type' in metadata:
            content_type = metadata['content_type'].lower()
            type_map = {
                'image/jpeg': '.jpg',
                'image/png': '.png',
                'image/gif': '.gif',
                'image/webp': '.webp',
                'image/svg+xml': '.svg',
            }
            if content_type in type_map:
                return type_map[content_type]
        
        # Try to extract from URL
        try:
            from urllib.parse import urlparse
            path = urlparse(identifier).path
            ext = os.path.splitext(path)[1].lower()
            if ext in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp'):
                return ext
        except Exception:
            pass
        
        # Default to .cache
        return '.cache'
    
    def get(self, identifier: str, variant: str = "", cache_type: str = 'both') -> Optional[bytes]:
        """
        Get cached data.
        
        Args:
            identifier: Primary identifier (e.g., URL)
            variant: Optional variant (e.g., "thumb", "full")
            cache_type: 'memory', 'disk', or 'both'
            
        Returns:
            Cached data or None if not found
        """
        key = self._generate_key(identifier, variant)
        
        # Check memory cache first
        if cache_type in ('memory', 'both'):
            data = self._memory_cache.get(key)
            if data is not None:
                self._stats.record_hit(from_memory=True)
                return data
        
        # Check disk cache
        if cache_type in ('disk', 'both'):
            with self._index_lock:
                if key in self._index:
                    entry = self._index[key]
                    
                    # Check if expired
                    if entry.is_expired():
                        self._remove_entry(key)
                        self._stats.record_miss()
                        return None
                    
                    # Check if file exists
                    if not os.path.exists(entry.file_path):
                        self._remove_entry(key)
                        self._stats.record_miss()
                        return None
                    
                    # Read from disk
                    try:
                        with open(entry.file_path, 'rb') as f:
                            data = f.read()
                        
                        # Update last accessed time
                        entry.last_accessed = time.time()
                        self._save_index()
                        
                        # Add to memory cache
                        self._memory_cache.put(key, data)
                        
                        self._stats.record_hit(from_memory=False)
                        return data
                        
                    except IOError as e:
                        print(f"[CacheManager] Failed to read cache file: {e}")
                        self._remove_entry(key)
        
        self._stats.record_miss()
        return None
    
    def put(
        self,
        identifier: str,
        data: bytes,
        variant: str = "",
        cache_type: str = 'both',
        ttl: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Store data in cache.
        
        Args:
            identifier: Primary identifier (e.g., URL)
            data: Data to cache
            variant: Optional variant (e.g., "thumb", "full")
            cache_type: 'memory', 'disk', or 'both'
            ttl: Time-to-live in seconds (None = use default)
            metadata: Additional metadata to store
            
        Returns:
            Cache key
        """
        key = self._generate_key(identifier, variant)
        
        # Add to memory cache
        if cache_type in ('memory', 'both'):
            self._memory_cache.put(key, data)
        
        # Add to disk cache
        if cache_type in ('disk', 'both'):
            ext = self._get_file_extension(identifier, metadata)
            file_path = os.path.join(self._cache_dir, f"{key}{ext}")
            
            with self._index_lock:
                try:
                    # Write data to disk
                    with open(file_path, 'wb') as f:
                        f.write(data)
                    
                    # Calculate expiry time
                    expires_at = None
                    if ttl is not None:
                        expires_at = time.time() + ttl
                    elif self.DEFAULT_TTL_DAYS > 0:
                        expires_at = time.time() + (self.DEFAULT_TTL_DAYS * 24 * 60 * 60)
                    
                    # Create index entry
                    entry = CacheEntry(
                        key=key,
                        file_path=file_path,
                        size_bytes=len(data),
                        created_at=time.time(),
                        last_accessed=time.time(),
                        expires_at=expires_at,
                        metadata=metadata or {}
                    )
                    
                    # Store original identifier in metadata
                    entry.metadata['original_identifier'] = identifier
                    if variant:
                        entry.metadata['variant'] = variant
                    
                    self._index[key] = entry
                    self._save_index()
                    
                    # Cleanup if needed
                    self._cleanup_if_needed()
                    
                except IOError as e:
                    print(f"[CacheManager] Failed to write cache file: {e}")
        
        return key
    
    def has(self, identifier: str, variant: str = "") -> bool:
        """
        Check if identifier is cached.
        
        Args:
            identifier: Primary identifier (e.g., URL)
            variant: Optional variant
            
        Returns:
            True if cached and not expired
        """
        key = self._generate_key(identifier, variant)
        
        # Check memory cache
        if key in self._memory_cache:
            return True
        
        # Check disk cache
        with self._index_lock:
            if key in self._index:
                entry = self._index[key]
                if not entry.is_expired() and os.path.exists(entry.file_path):
                    return True
                else:
                    self._remove_entry(key)
        
        return False
    
    def get_file_path(self, identifier: str, variant: str = "") -> Optional[str]:
        """
        Get the file path for cached data without loading it.
        
        Args:
            identifier: Primary identifier (e.g., URL)
            variant: Optional variant
            
        Returns:
            File path or None if not cached
        """
        key = self._generate_key(identifier, variant)
        
        with self._index_lock:
            if key in self._index:
                entry = self._index[key]
                if not entry.is_expired() and os.path.exists(entry.file_path):
                    return entry.file_path
                else:
                    self._remove_entry(key)
        
        return None
    
    def invalidate(self, identifier: str, variant: str = "") -> bool:
        """
        Invalidate (remove) a cache entry.
        
        Args:
            identifier: Primary identifier (e.g., URL)
            variant: Optional variant
            
        Returns:
            True if entry was removed
        """
        key = self._generate_key(identifier, variant)
        
        # Remove from memory cache
        self._memory_cache.remove(key)
        
        # Remove from disk cache
        return self._remove_entry(key)
    
    def _remove_entry(self, key: str) -> bool:
        """
        Remove a cache entry by key.
        
        Args:
            key: Cache key
            
        Returns:
            True if entry was removed
        """
        with self._index_lock:
            if key in self._index:
                entry = self._index[key]
                
                # Delete file
                try:
                    if os.path.exists(entry.file_path):
                        os.remove(entry.file_path)
                except OSError as e:
                    print(f"[CacheManager] Failed to delete cache file: {e}")
                
                # Remove from index
                del self._index[key]
                self._save_index()
                return True
        
        return False
    
    def _cleanup_if_needed(self) -> None:
        """Cleanup cache if size exceeds limit."""
        with self._index_lock:
            total_size = sum(e.size_bytes for e in self._index.values())
            max_size = self.MAX_DISK_SIZE_MB * 1024 * 1024
            
            if total_size > max_size:
                # Sort by last accessed (oldest first)
                sorted_entries = sorted(
                    self._index.items(),
                    key=lambda x: x[1].last_accessed
                )
                
                # Remove oldest until under 80% of limit
                target_size = max_size * 0.8
                while total_size > target_size and sorted_entries:
                    key, entry = sorted_entries.pop(0)
                    total_size -= entry.size_bytes
                    self._remove_entry(key)
    
    def cleanup_expired(self) -> int:
        """
        Remove all expired cache entries.
        
        Returns:
            Number of entries removed
        """
        removed_count = 0
        
        with self._index_lock:
            expired_keys = [
                key for key, entry in self._index.items()
                if entry.is_expired()
            ]
            
            for key in expired_keys:
                if self._remove_entry(key):
                    removed_count += 1
        
        return removed_count
    
    def clear(self, cache_type: str = 'both') -> Tuple[int, int]:
        """
        Clear cache.
        
        Args:
            cache_type: 'memory', 'disk', or 'both'
            
        Returns:
            Tuple of (memory_items_cleared, disk_items_cleared)
        """
        memory_cleared = 0
        disk_cleared = 0
        
        if cache_type in ('memory', 'both'):
            memory_cleared = len(self._memory_cache)
            self._memory_cache.clear()
        
        if cache_type in ('disk', 'both'):
            with self._index_lock:
                disk_cleared = len(self._index)
                
                # Delete all cache files
                for entry in self._index.values():
                    try:
                        if os.path.exists(entry.file_path):
                            os.remove(entry.file_path)
                    except OSError:
                        pass
                
                # Clear index
                self._index.clear()
                self._save_index()
        
        return memory_cleared, disk_cleared
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive cache statistics.
        
        Returns:
            Dictionary with cache statistics
        """
        with self._index_lock:
            total_disk_size = sum(e.size_bytes for e in self._index.values())
            
            stats = self._stats.get_stats()
            stats.update({
                'memory_items': len(self._memory_cache),
                'memory_max_items': self.MAX_MEMORY_ITEMS,
                'disk_items': len(self._index),
                'disk_size_bytes': total_disk_size,
                'disk_size_mb': total_disk_size / (1024 * 1024),
                'disk_max_size_mb': self.MAX_DISK_SIZE_MB,
                'cache_directory': self._cache_dir
            })
            
            return stats
    
    def get_cache_directory(self) -> str:
        """
        Get the cache directory path.
        
        Returns:
            Path to cache directory
        """
        return self._cache_dir


# Global instance
cache_manager = CacheManager()


def get_cache_manager() -> CacheManager:
    """
    Get the global cache manager instance.
    
    Returns:
        CacheManager instance
    """
    return cache_manager