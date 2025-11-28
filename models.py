# SPDX-License-Identifier: GPL-3.0-or-later
"""
Data models for the Pexels Extension caching system.

Provides dataclasses and enums for cache entries, favorites, categories,
search history, and configuration with full type hints and validation.
"""

import time
import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum, auto


class CacheType(Enum):
    """Types of cached content."""
    THUMBNAIL = auto()
    FULL_IMAGE = auto()
    SEARCH_RESULT = auto()
    PREVIEW = auto()


class SortOrder(Enum):
    """Sort order options for listings."""
    NEWEST_FIRST = auto()
    OLDEST_FIRST = auto()
    NAME_ASC = auto()
    NAME_DESC = auto()
    SIZE_ASC = auto()
    SIZE_DESC = auto()
    MOST_USED = auto()
    RECENTLY_USED = auto()


class FilterType(Enum):
    """Filter types for cache browser."""
    ALL = auto()
    IMAGES = auto()
    THUMBNAILS = auto()
    SEARCH_RESULTS = auto()
    FAVORITES = auto()


# ============================================================================
# Cache Entry Models
# ============================================================================

@dataclass
class EnhancedCacheEntry:
    """
    Enhanced cache entry with full metadata.
    
    Attributes:
        id: Unique entry identifier
        cache_key: Hash key for cache lookup
        file_path: Path to cached file on disk
        size_bytes: Size of cached data in bytes
        content_type: MIME type of content
        original_url: Original URL of the resource
        variant: Cache variant (e.g., 'thumb', 'full')
        created_at: Timestamp when entry was created
        last_accessed: Timestamp of last access
        expires_at: Timestamp when entry expires (None = never)
        access_count: Number of times accessed
        cache_type: Type of cached content
        metadata: Additional metadata dictionary
    """
    id: str
    cache_key: str
    file_path: str
    size_bytes: int
    content_type: str
    original_url: str
    variant: str
    created_at: float
    last_accessed: float
    expires_at: Optional[float]
    access_count: int
    cache_type: CacheType
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_expired(self) -> bool:
        """Check if this cache entry has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at
    
    @property
    def age_seconds(self) -> float:
        """Get age of entry in seconds."""
        return time.time() - self.created_at
    
    @property
    def age_days(self) -> float:
        """Get age of entry in days."""
        return self.age_seconds / 86400
    
    @property
    def time_until_expiry(self) -> Optional[float]:
        """Get time until expiry in seconds, or None if no expiry."""
        if self.expires_at is None:
            return None
        return max(0, self.expires_at - time.time())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'id': self.id,
            'cache_key': self.cache_key,
            'file_path': self.file_path,
            'size_bytes': self.size_bytes,
            'content_type': self.content_type,
            'original_url': self.original_url,
            'variant': self.variant,
            'created_at': self.created_at,
            'last_accessed': self.last_accessed,
            'expires_at': self.expires_at,
            'access_count': self.access_count,
            'cache_type': self.cache_type.name,
            'metadata': self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EnhancedCacheEntry':
        """Create from dictionary."""
        cache_type = data.get('cache_type', 'THUMBNAIL')
        if isinstance(cache_type, str):
            cache_type = CacheType[cache_type]
        
        return cls(
            id=data['id'],
            cache_key=data['cache_key'],
            file_path=data['file_path'],
            size_bytes=data['size_bytes'],
            content_type=data.get('content_type', ''),
            original_url=data.get('original_url', ''),
            variant=data.get('variant', ''),
            created_at=data['created_at'],
            last_accessed=data['last_accessed'],
            expires_at=data.get('expires_at'),
            access_count=data.get('access_count', 0),
            cache_type=cache_type,
            metadata=data.get('metadata', {})
        )


@dataclass
class PhotoData:
    """
    Photo data from Pexels API response.
    
    Attributes:
        id: Pexels photo ID
        width: Image width in pixels
        height: Image height in pixels
        url: Pexels page URL
        photographer: Photographer name
        photographer_url: Photographer's Pexels profile URL
        photographer_id: Photographer's Pexels ID
        avg_color: Average color hex code
        src: Dictionary of image URLs at different sizes
        liked: Whether user has liked the photo
        alt: Alt text description
    """
    id: int
    width: int
    height: int
    url: str
    photographer: str
    photographer_url: str
    photographer_id: int
    avg_color: str
    src: Dict[str, str]
    liked: bool = False
    alt: str = ""
    
    @property
    def thumb_url(self) -> str:
        """Get thumbnail URL."""
        return (
            self.src.get('medium') or
            self.src.get('small') or
            self.src.get('tiny') or
            ''
        )
    
    @property
    def full_url(self) -> str:
        """Get full-size image URL."""
        return (
            self.src.get('large2x') or
            self.src.get('original') or
            self.src.get('large') or
            ''
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'id': self.id,
            'width': self.width,
            'height': self.height,
            'url': self.url,
            'photographer': self.photographer,
            'photographer_url': self.photographer_url,
            'photographer_id': self.photographer_id,
            'avg_color': self.avg_color,
            'src': self.src,
            'liked': self.liked,
            'alt': self.alt
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PhotoData':
        """Create from dictionary (API response format)."""
        return cls(
            id=int(data.get('id', 0)),
            width=int(data.get('width', 0)),
            height=int(data.get('height', 0)),
            url=data.get('url', ''),
            photographer=data.get('photographer', ''),
            photographer_url=data.get('photographer_url', ''),
            photographer_id=int(data.get('photographer_id', 0)),
            avg_color=data.get('avg_color', ''),
            src=data.get('src', {}),
            liked=data.get('liked', False),
            alt=data.get('alt', '')
        )


@dataclass
class CachedSearchResult:
    """
    Cached search result with photos.
    
    Attributes:
        id: Unique cache entry ID
        query: Original search query
        query_hash: Hash of query for lookup
        page: Page number
        per_page: Results per page
        total_results: Total results available
        photos: List of photo data
        cached_at: Timestamp when cached
        expires_at: Timestamp when cache expires
        access_count: Number of times accessed
        last_accessed: Timestamp of last access
    """
    id: str
    query: str
    query_hash: str
    page: int
    per_page: int
    total_results: int
    photos: List[PhotoData]
    cached_at: float
    expires_at: float
    access_count: int = 0
    last_accessed: Optional[float] = None
    
    def is_expired(self) -> bool:
        """Check if this cached result has expired."""
        return time.time() > self.expires_at
    
    @property
    def photo_count(self) -> int:
        """Get number of photos in this result."""
        return len(self.photos)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'id': self.id,
            'query': self.query,
            'query_hash': self.query_hash,
            'page': self.page,
            'per_page': self.per_page,
            'total_results': self.total_results,
            'photos': [p.to_dict() for p in self.photos],
            'cached_at': self.cached_at,
            'expires_at': self.expires_at,
            'access_count': self.access_count,
            'last_accessed': self.last_accessed
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CachedSearchResult':
        """Create from dictionary."""
        photos = [
            PhotoData.from_dict(p) if isinstance(p, dict) else p
            for p in data.get('photos', [])
        ]
        
        return cls(
            id=data['id'],
            query=data['query'],
            query_hash=data['query_hash'],
            page=data['page'],
            per_page=data['per_page'],
            total_results=data['total_results'],
            photos=photos,
            cached_at=data['cached_at'],
            expires_at=data['expires_at'],
            access_count=data.get('access_count', 0),
            last_accessed=data.get('last_accessed')
        )
    
    @staticmethod
    def generate_query_hash(query: str, page: int, per_page: int) -> str:
        """Generate a hash for query lookup."""
        content = f"{query.lower().strip()}:{page}:{per_page}"
        return hashlib.sha256(content.encode('utf-8')).hexdigest()[:32]
    
    @classmethod
    def create(
        cls,
        query: str,
        page: int,
        per_page: int,
        total_results: int,
        photos: List[PhotoData],
        ttl_seconds: float = 86400  # 24 hours default
    ) -> 'CachedSearchResult':
        """
        Create a new cached search result.
        
        Args:
            query: Search query
            page: Page number
            per_page: Results per page
            total_results: Total results available
            photos: List of PhotoData objects
            ttl_seconds: Time-to-live in seconds (default 24 hours)
            
        Returns:
            New CachedSearchResult instance
        """
        now = time.time()
        return cls(
            id=str(uuid.uuid4()),
            query=query,
            query_hash=cls.generate_query_hash(query, page, per_page),
            page=page,
            per_page=per_page,
            total_results=total_results,
            photos=photos,
            cached_at=now,
            expires_at=now + ttl_seconds,
            access_count=0,
            last_accessed=now
        )


# ============================================================================
# Favorites Models
# ============================================================================

@dataclass
class FavoriteItem:
    """
    User favorite with full metadata.
    
    Attributes:
        id: Unique favorite ID
        pexels_id: Original Pexels image ID
        thumb_url: Thumbnail URL
        full_url: Full image URL
        photographer: Photographer name
        width: Image width
        height: Image height
        category_id: Category assignment (optional)
        tags: User-defined tags
        notes: User notes
        added_at: Timestamp when favorited
        last_used: Last time imported/used
        use_count: Number of times used
        cached_thumb_path: Local thumbnail path
        cached_full_path: Local full image path
    """
    id: str
    pexels_id: int
    thumb_url: str
    full_url: str
    photographer: str
    width: int
    height: int
    category_id: Optional[str]
    tags: List[str]
    notes: str
    added_at: float
    last_used: Optional[float]
    use_count: int
    cached_thumb_path: Optional[str] = None
    cached_full_path: Optional[str] = None
    
    @property
    def has_cached_thumbnail(self) -> bool:
        """Check if thumbnail is cached locally."""
        return self.cached_thumb_path is not None
    
    @property
    def has_cached_full(self) -> bool:
        """Check if full image is cached locally."""
        return self.cached_full_path is not None
    
    @property
    def aspect_ratio(self) -> float:
        """Get image aspect ratio."""
        if self.height == 0:
            return 1.0
        return self.width / self.height
    
    @property
    def resolution(self) -> str:
        """Get resolution string."""
        return f"{self.width}x{self.height}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'id': self.id,
            'pexels_id': self.pexels_id,
            'thumb_url': self.thumb_url,
            'full_url': self.full_url,
            'photographer': self.photographer,
            'width': self.width,
            'height': self.height,
            'category_id': self.category_id,
            'tags': self.tags,
            'notes': self.notes,
            'added_at': self.added_at,
            'last_used': self.last_used,
            'use_count': self.use_count,
            'cached_thumb_path': self.cached_thumb_path,
            'cached_full_path': self.cached_full_path
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FavoriteItem':
        """Create from dictionary."""
        return cls(
            id=data['id'],
            pexels_id=data['pexels_id'],
            thumb_url=data['thumb_url'],
            full_url=data['full_url'],
            photographer=data.get('photographer', ''),
            width=data.get('width', 0),
            height=data.get('height', 0),
            category_id=data.get('category_id'),
            tags=data.get('tags', []),
            notes=data.get('notes', ''),
            added_at=data['added_at'],
            last_used=data.get('last_used'),
            use_count=data.get('use_count', 0),
            cached_thumb_path=data.get('cached_thumb_path'),
            cached_full_path=data.get('cached_full_path')
        )
    
    @classmethod
    def from_photo_data(cls, photo: PhotoData, category_id: str = None) -> 'FavoriteItem':
        """Create favorite from PhotoData."""
        return cls(
            id=str(uuid.uuid4()),
            pexels_id=photo.id,
            thumb_url=photo.thumb_url,
            full_url=photo.full_url,
            photographer=photo.photographer,
            width=photo.width,
            height=photo.height,
            category_id=category_id,
            tags=[],
            notes='',
            added_at=time.time(),
            last_used=None,
            use_count=0
        )


@dataclass
class Category:
    """
    Favorite category for organization.
    
    Attributes:
        id: Unique category ID
        name: Display name
        color: Color code for UI (hex)
        icon: Blender icon identifier
        created_at: Creation timestamp
        sort_order: Display order
        item_count: Number of items (computed)
    """
    id: str
    name: str
    color: str
    icon: str
    created_at: float
    sort_order: int
    item_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'id': self.id,
            'name': self.name,
            'color': self.color,
            'icon': self.icon,
            'created_at': self.created_at,
            'sort_order': self.sort_order,
            'item_count': self.item_count
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Category':
        """Create from dictionary."""
        return cls(
            id=data['id'],
            name=data['name'],
            color=data.get('color', '#808080'),
            icon=data.get('icon', 'COLLECTION_NEW'),
            created_at=data['created_at'],
            sort_order=data.get('sort_order', 0),
            item_count=data.get('item_count', 0)
        )
    
    @classmethod
    def create_default_categories(cls) -> List['Category']:
        """Create default system categories."""
        now = time.time()
        return [
            cls(
                id='__uncategorized__',
                name='Uncategorized',
                color='#808080',
                icon='QUESTION',
                created_at=now,
                sort_order=0
            ),
            cls(
                id='__recent__',
                name='Recently Added',
                color='#4CAF50',
                icon='TIME',
                created_at=now,
                sort_order=1
            ),
            cls(
                id='__most_used__',
                name='Most Used',
                color='#2196F3',
                icon='SOLO_ON',
                created_at=now,
                sort_order=2
            )
        ]


# ============================================================================
# Search History Models
# ============================================================================

@dataclass
class SearchHistoryEntry:
    """
    Search history entry.
    
    Attributes:
        id: Unique entry ID
        query: Search query text
        query_hash: Hash for lookup
        result_count: Number of results found
        searched_at: Timestamp of search
        page: Page number searched
        per_page: Results per page
        cached_result_id: ID of cached result (if available)
    """
    id: str
    query: str
    query_hash: str
    result_count: int
    searched_at: float
    page: int
    per_page: int
    cached_result_id: Optional[str] = None
    
    @property
    def age_seconds(self) -> float:
        """Get age in seconds."""
        return time.time() - self.searched_at
    
    @property
    def age_days(self) -> float:
        """Get age in days."""
        return self.age_seconds / 86400
    
    @property
    def is_today(self) -> bool:
        """Check if search was today."""
        import datetime
        search_date = datetime.datetime.fromtimestamp(self.searched_at).date()
        today = datetime.datetime.now().date()
        return search_date == today
    
    @property
    def is_this_week(self) -> bool:
        """Check if search was this week."""
        return self.age_days <= 7
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'id': self.id,
            'query': self.query,
            'query_hash': self.query_hash,
            'result_count': self.result_count,
            'searched_at': self.searched_at,
            'page': self.page,
            'per_page': self.per_page,
            'cached_result_id': self.cached_result_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SearchHistoryEntry':
        """Create from dictionary."""
        return cls(
            id=data['id'],
            query=data['query'],
            query_hash=data['query_hash'],
            result_count=data['result_count'],
            searched_at=data['searched_at'],
            page=data.get('page', 1),
            per_page=data.get('per_page', 50),
            cached_result_id=data.get('cached_result_id')
        )
    
    @classmethod
    def create(cls, query: str, result_count: int, page: int = 1,
               per_page: int = 50, cached_result_id: str = None) -> 'SearchHistoryEntry':
        """Create a new history entry."""
        query_hash = CachedSearchResult.generate_query_hash(query, page, per_page)
        return cls(
            id=str(uuid.uuid4()),
            query=query,
            query_hash=query_hash,
            result_count=result_count,
            searched_at=time.time(),
            page=page,
            per_page=per_page,
            cached_result_id=cached_result_id
        )


# ============================================================================
# Statistics and Configuration Models
# ============================================================================

@dataclass
class CacheStatistics:
    """
    Comprehensive cache statistics.
    
    Attributes:
        disk_used_bytes: Bytes used on disk
        disk_max_bytes: Maximum disk cache size
        memory_items: Items in memory cache
        memory_max_items: Maximum memory items
        total_cached_images: Total cached images
        total_cached_searches: Total cached searches
        total_favorites: Total favorites
        total_history_entries: Total history entries
        cache_hits: Total cache hits
        cache_misses: Total cache misses
        memory_hits: Hits from memory cache
        disk_hits: Hits from disk cache
    """
    disk_used_bytes: int
    disk_max_bytes: int
    memory_items: int
    memory_max_items: int
    total_cached_images: int
    total_cached_searches: int
    total_favorites: int
    total_history_entries: int
    cache_hits: int
    cache_misses: int
    memory_hits: int
    disk_hits: int
    
    @property
    def disk_used_mb(self) -> float:
        """Get disk usage in MB."""
        return self.disk_used_bytes / (1024 * 1024)
    
    @property
    def disk_max_mb(self) -> float:
        """Get max disk size in MB."""
        return self.disk_max_bytes / (1024 * 1024)
    
    @property
    def disk_used_percent(self) -> float:
        """Get disk usage percentage."""
        if self.disk_max_bytes == 0:
            return 0.0
        return (self.disk_used_bytes / self.disk_max_bytes) * 100
    
    @property
    def memory_used_percent(self) -> float:
        """Get memory usage percentage."""
        if self.memory_max_items == 0:
            return 0.0
        return (self.memory_items / self.memory_max_items) * 100
    
    @property
    def hit_rate_percent(self) -> float:
        """Get cache hit rate percentage."""
        total = self.cache_hits + self.cache_misses
        if total == 0:
            return 0.0
        return (self.cache_hits / total) * 100
    
    @property
    def total_requests(self) -> int:
        """Get total cache requests."""
        return self.cache_hits + self.cache_misses
    
    @property
    def api_calls_saved(self) -> int:
        """Estimate of API calls saved by caching."""
        return self.cache_hits
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'disk_used_bytes': self.disk_used_bytes,
            'disk_max_bytes': self.disk_max_bytes,
            'disk_used_mb': self.disk_used_mb,
            'disk_max_mb': self.disk_max_mb,
            'disk_used_percent': self.disk_used_percent,
            'memory_items': self.memory_items,
            'memory_max_items': self.memory_max_items,
            'memory_used_percent': self.memory_used_percent,
            'total_cached_images': self.total_cached_images,
            'total_cached_searches': self.total_cached_searches,
            'total_favorites': self.total_favorites,
            'total_history_entries': self.total_history_entries,
            'cache_hits': self.cache_hits,
            'cache_misses': self.cache_misses,
            'memory_hits': self.memory_hits,
            'disk_hits': self.disk_hits,
            'hit_rate_percent': self.hit_rate_percent,
            'total_requests': self.total_requests,
            'api_calls_saved': self.api_calls_saved
        }


@dataclass
class RetentionPolicy:
    """
    Configurable cache retention policy.
    
    Attributes:
        max_disk_size_mb: Maximum disk cache size in MB
        max_memory_items: Maximum items in memory cache
        default_ttl_days: Default TTL for cached items in days
        favorites_ttl_days: TTL for favorites (longer retention)
        search_cache_ttl_hours: TTL for search results in hours
        history_retention_days: How long to keep search history
        cleanup_threshold_percent: Start cleanup when usage exceeds this
        cleanup_target_percent: Clean down to this percentage
        preserve_favorites: Don't delete favorites during cleanup
        auto_cleanup_enabled: Enable automatic cleanup
        cleanup_on_startup: Clean expired items on addon startup
    """
    max_disk_size_mb: int = 500
    max_memory_items: int = 100
    default_ttl_days: int = 7
    favorites_ttl_days: int = 365
    search_cache_ttl_hours: int = 24
    history_retention_days: int = 30
    cleanup_threshold_percent: float = 80.0
    cleanup_target_percent: float = 60.0
    preserve_favorites: bool = True
    auto_cleanup_enabled: bool = True
    cleanup_on_startup: bool = True
    
    @property
    def max_disk_size_bytes(self) -> int:
        """Get max disk size in bytes."""
        return self.max_disk_size_mb * 1024 * 1024
    
    @property
    def default_ttl_seconds(self) -> float:
        """Get default TTL in seconds."""
        return self.default_ttl_days * 24 * 60 * 60
    
    @property
    def favorites_ttl_seconds(self) -> float:
        """Get favorites TTL in seconds."""
        return self.favorites_ttl_days * 24 * 60 * 60
    
    @property
    def search_cache_ttl_seconds(self) -> float:
        """Get search cache TTL in seconds."""
        return self.search_cache_ttl_hours * 60 * 60
    
    @property
    def history_retention_seconds(self) -> float:
        """Get history retention in seconds."""
        return self.history_retention_days * 24 * 60 * 60
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'max_disk_size_mb': self.max_disk_size_mb,
            'max_memory_items': self.max_memory_items,
            'default_ttl_days': self.default_ttl_days,
            'favorites_ttl_days': self.favorites_ttl_days,
            'search_cache_ttl_hours': self.search_cache_ttl_hours,
            'history_retention_days': self.history_retention_days,
            'cleanup_threshold_percent': self.cleanup_threshold_percent,
            'cleanup_target_percent': self.cleanup_target_percent,
            'preserve_favorites': self.preserve_favorites,
            'auto_cleanup_enabled': self.auto_cleanup_enabled,
            'cleanup_on_startup': self.cleanup_on_startup
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RetentionPolicy':
        """Create from dictionary."""
        return cls(
            max_disk_size_mb=data.get('max_disk_size_mb', 500),
            max_memory_items=data.get('max_memory_items', 100),
            default_ttl_days=data.get('default_ttl_days', 7),
            favorites_ttl_days=data.get('favorites_ttl_days', 365),
            search_cache_ttl_hours=data.get('search_cache_ttl_hours', 24),
            history_retention_days=data.get('history_retention_days', 30),
            cleanup_threshold_percent=data.get('cleanup_threshold_percent', 80.0),
            cleanup_target_percent=data.get('cleanup_target_percent', 60.0),
            preserve_favorites=data.get('preserve_favorites', True),
            auto_cleanup_enabled=data.get('auto_cleanup_enabled', True),
            cleanup_on_startup=data.get('cleanup_on_startup', True)
        )
    
    @classmethod
    def default(cls) -> 'RetentionPolicy':
        """Get default retention policy."""
        return cls()
    
    @classmethod
    def aggressive(cls) -> 'RetentionPolicy':
        """Get aggressive cleanup policy (smaller cache)."""
        return cls(
            max_disk_size_mb=200,
            max_memory_items=50,
            default_ttl_days=3,
            search_cache_ttl_hours=6,
            cleanup_threshold_percent=70.0,
            cleanup_target_percent=50.0
        )
    
    @classmethod
    def generous(cls) -> 'RetentionPolicy':
        """Get generous policy (larger cache, longer retention)."""
        return cls(
            max_disk_size_mb=1000,
            max_memory_items=200,
            default_ttl_days=14,
            search_cache_ttl_hours=48,
            cleanup_threshold_percent=90.0,
            cleanup_target_percent=70.0
        )


# ============================================================================
# Utility Functions
# ============================================================================

def generate_cache_key(identifier: str, variant: str = "") -> str:
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


def generate_uuid() -> str:
    """Generate a new UUID string."""
    return str(uuid.uuid4())


def format_bytes(size_bytes: int) -> str:
    """
    Format bytes as human-readable string.
    
    Args:
        size_bytes: Size in bytes
        
    Returns:
        Formatted string (e.g., "1.5 MB")
    """
    if size_bytes <= 0:
        return "0 B"
    
    units = [
        (1024 ** 3, "GB"),
        (1024 ** 2, "MB"),
        (1024, "KB"),
        (1, "B")
    ]
    
    for threshold, unit in units:
        if size_bytes >= threshold:
            value = size_bytes / threshold
            if value >= 100:
                return f"{int(value)} {unit}"
            elif value >= 10:
                return f"{value:.1f} {unit}"
            else:
                return f"{value:.2f} {unit}"
    
    return f"{int(size_bytes)} B"


def format_timestamp(timestamp: float) -> str:
    """
    Format timestamp as human-readable date/time.
    
    Args:
        timestamp: Unix timestamp
        
    Returns:
        Formatted date/time string
    """
    import datetime
    dt = datetime.datetime.fromtimestamp(timestamp)
    return dt.strftime("%Y-%m-%d %H:%M")


def format_relative_time(timestamp: float) -> str:
    """
    Format timestamp as relative time (e.g., "2 hours ago").
    
    Args:
        timestamp: Unix timestamp
        
    Returns:
        Relative time string
    """
    seconds = time.time() - timestamp
    
    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif seconds < 604800:
        days = int(seconds / 86400)
        return f"{days} day{'s' if days != 1 else ''} ago"
    else:
        weeks = int(seconds / 604800)
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"