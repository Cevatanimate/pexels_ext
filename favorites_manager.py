# SPDX-License-Identifier: GPL-3.0-or-later
"""
Favorites Manager for Pexels Extension.

Provides comprehensive favorites management including:
- Adding/removing favorites
- Category organization
- Tag management
- Search and filtering
- Bulk operations
"""

import time
import threading
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass

from .models import (
    FavoriteItem,
    Category,
    PhotoData,
    SortOrder,
    FilterType,
    generate_uuid
)
from .logger import logger


@dataclass
class FavoriteFilter:
    """Filter criteria for favorites."""
    category_id: Optional[str] = None
    tags: Optional[List[str]] = None
    photographer: Optional[str] = None
    min_width: Optional[int] = None
    min_height: Optional[int] = None
    search_query: Optional[str] = None
    sort_by: SortOrder = SortOrder.DATE_DESC
    
    def matches(self, favorite: FavoriteItem) -> bool:
        """Check if a favorite matches this filter."""
        # Category filter
        if self.category_id:
            if self.category_id == '__uncategorized__':
                if favorite.category_id and favorite.category_id != '__uncategorized__':
                    return False
            elif self.category_id == '__recent__':
                week_ago = time.time() - (7 * 24 * 60 * 60)
                if favorite.added_at < week_ago:
                    return False
            elif self.category_id == '__most_used__':
                if favorite.use_count == 0:
                    return False
            elif favorite.category_id != self.category_id:
                return False
        
        # Tags filter
        if self.tags:
            if not any(tag in favorite.tags for tag in self.tags):
                return False
        
        # Photographer filter
        if self.photographer:
            if self.photographer.lower() not in favorite.photographer.lower():
                return False
        
        # Dimension filters
        if self.min_width and favorite.width < self.min_width:
            return False
        if self.min_height and favorite.height < self.min_height:
            return False
        
        # Search query
        if self.search_query:
            query = self.search_query.lower()
            searchable = f"{favorite.photographer} {' '.join(favorite.tags)} {favorite.notes}".lower()
            if query not in searchable:
                return False
        
        return True


class FavoritesManager:
    """
    Thread-safe favorites manager.
    
    Implements singleton pattern for global access.
    
    Features:
    - Add/remove favorites
    - Category management
    - Tag management
    - Search and filtering
    - Bulk operations
    - Cache integration
    
    Usage:
        favorites = FavoritesManager()
        
        # Add a favorite
        favorites.add_favorite(pexels_id, thumb_url, full_url, photographer)
        
        # Get all favorites
        all_favs = favorites.get_all()
        
        # Get favorites by category
        nature_favs = favorites.get_by_category("nature")
        
        # Search favorites
        results = favorites.search("sunset")
    """
    
    _instance: Optional['FavoritesManager'] = None
    _instance_lock: threading.Lock = threading.Lock()
    
    def __new__(cls) -> 'FavoritesManager':
        """Singleton pattern implementation."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance
    
    def __init__(self):
        """Initialize the favorites manager."""
        if self._initialized:
            return
        
        self._initialized = True
        self._lock = threading.RLock()
        
        # Database manager (lazy initialization)
        self._db_manager = None
        
        # Memory cache for quick access
        self._favorites_cache: Dict[int, FavoriteItem] = {}  # pexels_id -> FavoriteItem
        self._categories_cache: Dict[str, Category] = {}  # id -> Category
        
        # Initialize
        self._init_database()
        self._load_cache()
    
    def _init_database(self) -> None:
        """Initialize database connection."""
        try:
            from .database_manager import get_database_manager
            self._db_manager = get_database_manager()
            logger.debug("Favorites manager database initialized")
        except Exception as e:
            logger.warning(f"Database not available for favorites: {e}")
            self._db_manager = None
    
    def _load_cache(self) -> None:
        """Load favorites and categories into memory cache."""
        if not self._db_manager:
            return
        
        try:
            # Load all favorites
            favorites = self._db_manager.get_all_favorites()
            for fav in favorites:
                self._favorites_cache[fav.pexels_id] = fav
            
            # Load all categories
            categories = self._db_manager.get_all_categories()
            for cat in categories:
                self._categories_cache[cat.id] = cat
            
            logger.debug(f"Loaded {len(self._favorites_cache)} favorites, {len(self._categories_cache)} categories")
            
        except Exception as e:
            logger.error(f"Failed to load favorites cache: {e}")
    
    # ========================================================================
    # Favorite Operations
    # ========================================================================
    
    def add_favorite(
        self,
        pexels_id: int,
        thumb_url: str,
        full_url: str,
        photographer: str = "",
        width: int = 0,
        height: int = 0,
        category_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        notes: str = ""
    ) -> Optional[FavoriteItem]:
        """
        Add an image to favorites.
        
        Args:
            pexels_id: Pexels image ID
            thumb_url: Thumbnail URL
            full_url: Full resolution URL
            photographer: Photographer name
            width: Image width
            height: Image height
            category_id: Optional category ID
            tags: Optional list of tags
            notes: Optional notes
            
        Returns:
            FavoriteItem if successful, None otherwise
        """
        with self._lock:
            # Check if already favorited
            if pexels_id in self._favorites_cache:
                logger.debug(f"Image {pexels_id} already in favorites")
                return self._favorites_cache[pexels_id]
            
            # Create favorite item
            favorite = FavoriteItem(
                id=generate_uuid(),
                pexels_id=pexels_id,
                thumb_url=thumb_url,
                full_url=full_url,
                photographer=photographer,
                width=width,
                height=height,
                category_id=category_id,
                tags=tags or [],
                notes=notes,
                added_at=time.time(),
                last_used=None,
                use_count=0,
                cached_thumb_path=None,
                cached_full_path=None
            )
            
            # Save to database
            if self._db_manager:
                if not self._db_manager.insert_favorite(favorite):
                    logger.error(f"Failed to save favorite {pexels_id} to database")
                    return None
            
            # Add to cache
            self._favorites_cache[pexels_id] = favorite
            
            logger.info(f"Added favorite: {pexels_id} by {photographer}")
            
            return favorite
    
    def add_favorite_from_photo(
        self,
        photo: PhotoData,
        category_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        notes: str = ""
    ) -> Optional[FavoriteItem]:
        """
        Add a favorite from PhotoData object.
        
        Args:
            photo: PhotoData object
            category_id: Optional category ID
            tags: Optional list of tags
            notes: Optional notes
            
        Returns:
            FavoriteItem if successful, None otherwise
        """
        return self.add_favorite(
            pexels_id=photo.id,
            thumb_url=photo.src.get('medium', photo.src.get('small', '')),
            full_url=photo.src.get('original', photo.src.get('large2x', '')),
            photographer=photo.photographer,
            width=photo.width,
            height=photo.height,
            category_id=category_id,
            tags=tags,
            notes=notes
        )
    
    def remove_favorite(self, pexels_id: int) -> bool:
        """
        Remove an image from favorites.
        
        Args:
            pexels_id: Pexels image ID
            
        Returns:
            True if removed successfully
        """
        with self._lock:
            if pexels_id not in self._favorites_cache:
                return False
            
            # Remove from database
            if self._db_manager:
                if not self._db_manager.delete_favorite_by_pexels_id(pexels_id):
                    logger.error(f"Failed to remove favorite {pexels_id} from database")
                    return False
            
            # Remove from cache
            del self._favorites_cache[pexels_id]
            
            logger.info(f"Removed favorite: {pexels_id}")
            
            return True
    
    def toggle_favorite(
        self,
        pexels_id: int,
        thumb_url: str = "",
        full_url: str = "",
        photographer: str = "",
        width: int = 0,
        height: int = 0
    ) -> Tuple[bool, Optional[FavoriteItem]]:
        """
        Toggle favorite status.
        
        Args:
            pexels_id: Pexels image ID
            thumb_url: Thumbnail URL (for adding)
            full_url: Full resolution URL (for adding)
            photographer: Photographer name (for adding)
            width: Image width (for adding)
            height: Image height (for adding)
            
        Returns:
            Tuple of (is_now_favorite, FavoriteItem or None)
        """
        if self.is_favorite(pexels_id):
            self.remove_favorite(pexels_id)
            return (False, None)
        else:
            favorite = self.add_favorite(
                pexels_id=pexels_id,
                thumb_url=thumb_url,
                full_url=full_url,
                photographer=photographer,
                width=width,
                height=height
            )
            return (True, favorite)
    
    def is_favorite(self, pexels_id: int) -> bool:
        """
        Check if an image is favorited.
        
        Args:
            pexels_id: Pexels image ID
            
        Returns:
            True if favorited
        """
        with self._lock:
            return pexels_id in self._favorites_cache
    
    def get_favorite(self, pexels_id: int) -> Optional[FavoriteItem]:
        """
        Get a favorite by Pexels ID.
        
        Args:
            pexels_id: Pexels image ID
            
        Returns:
            FavoriteItem or None
        """
        with self._lock:
            return self._favorites_cache.get(pexels_id)
    
    def get_favorite_by_id(self, favorite_id: str) -> Optional[FavoriteItem]:
        """
        Get a favorite by its internal ID.
        
        Args:
            favorite_id: Internal favorite ID
            
        Returns:
            FavoriteItem or None
        """
        with self._lock:
            for fav in self._favorites_cache.values():
                if fav.id == favorite_id:
                    return fav
            return None
    
    def update_favorite(
        self,
        pexels_id: int,
        category_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        notes: Optional[str] = None
    ) -> bool:
        """
        Update a favorite's metadata.
        
        Args:
            pexels_id: Pexels image ID
            category_id: New category ID (None = don't change)
            tags: New tags list (None = don't change)
            notes: New notes (None = don't change)
            
        Returns:
            True if updated successfully
        """
        with self._lock:
            if pexels_id not in self._favorites_cache:
                return False
            
            favorite = self._favorites_cache[pexels_id]
            
            # Update fields
            if category_id is not None:
                favorite.category_id = category_id
                if self._db_manager:
                    self._db_manager.update_favorite_category(favorite.id, category_id)
            
            if tags is not None:
                favorite.tags = tags
                if self._db_manager:
                    self._db_manager.update_favorite_tags(favorite.id, tags)
            
            if notes is not None:
                favorite.notes = notes
                if self._db_manager:
                    self._db_manager.update_favorite_notes(favorite.id, notes)
            
            return True
    
    def record_use(self, pexels_id: int) -> bool:
        """
        Record that a favorite was used (imported).
        
        Args:
            pexels_id: Pexels image ID
            
        Returns:
            True if recorded successfully
        """
        with self._lock:
            if pexels_id not in self._favorites_cache:
                return False
            
            favorite = self._favorites_cache[pexels_id]
            favorite.last_used = time.time()
            favorite.use_count += 1
            
            if self._db_manager:
                self._db_manager.update_favorite_use(favorite.id)
            
            return True
    
    # ========================================================================
    # Query Operations
    # ========================================================================
    
    def get_all(
        self,
        sort_by: SortOrder = SortOrder.DATE_DESC,
        limit: Optional[int] = None,
        offset: int = 0
    ) -> List[FavoriteItem]:
        """
        Get all favorites.
        
        Args:
            sort_by: Sort order
            limit: Maximum number to return
            offset: Number to skip
            
        Returns:
            List of favorites
        """
        with self._lock:
            favorites = list(self._favorites_cache.values())
            
            # Sort
            favorites = self._sort_favorites(favorites, sort_by)
            
            # Apply offset and limit
            if offset:
                favorites = favorites[offset:]
            if limit:
                favorites = favorites[:limit]
            
            return favorites
    
    def get_by_category(
        self,
        category_id: str,
        sort_by: SortOrder = SortOrder.DATE_DESC
    ) -> List[FavoriteItem]:
        """
        Get favorites in a specific category.
        
        Args:
            category_id: Category ID
            sort_by: Sort order
            
        Returns:
            List of favorites
        """
        with self._lock:
            filter_obj = FavoriteFilter(category_id=category_id, sort_by=sort_by)
            favorites = [f for f in self._favorites_cache.values() if filter_obj.matches(f)]
            return self._sort_favorites(favorites, sort_by)
    
    def get_by_tags(
        self,
        tags: List[str],
        match_all: bool = False,
        sort_by: SortOrder = SortOrder.DATE_DESC
    ) -> List[FavoriteItem]:
        """
        Get favorites with specific tags.
        
        Args:
            tags: List of tags to match
            match_all: If True, must match all tags; if False, match any
            sort_by: Sort order
            
        Returns:
            List of favorites
        """
        with self._lock:
            if match_all:
                favorites = [
                    f for f in self._favorites_cache.values()
                    if all(tag in f.tags for tag in tags)
                ]
            else:
                favorites = [
                    f for f in self._favorites_cache.values()
                    if any(tag in f.tags for tag in tags)
                ]
            
            return self._sort_favorites(favorites, sort_by)
    
    def get_by_photographer(
        self,
        photographer: str,
        sort_by: SortOrder = SortOrder.DATE_DESC
    ) -> List[FavoriteItem]:
        """
        Get favorites by a specific photographer.
        
        Args:
            photographer: Photographer name (partial match)
            sort_by: Sort order
            
        Returns:
            List of favorites
        """
        with self._lock:
            photographer_lower = photographer.lower()
            favorites = [
                f for f in self._favorites_cache.values()
                if photographer_lower in f.photographer.lower()
            ]
            return self._sort_favorites(favorites, sort_by)
    
    def search(
        self,
        query: str,
        sort_by: SortOrder = SortOrder.DATE_DESC
    ) -> List[FavoriteItem]:
        """
        Search favorites by query.
        
        Args:
            query: Search query
            sort_by: Sort order
            
        Returns:
            List of matching favorites
        """
        with self._lock:
            filter_obj = FavoriteFilter(search_query=query, sort_by=sort_by)
            favorites = [f for f in self._favorites_cache.values() if filter_obj.matches(f)]
            return self._sort_favorites(favorites, sort_by)
    
    def filter(
        self,
        filter_criteria: FavoriteFilter
    ) -> List[FavoriteItem]:
        """
        Filter favorites by criteria.
        
        Args:
            filter_criteria: Filter criteria
            
        Returns:
            List of matching favorites
        """
        with self._lock:
            favorites = [f for f in self._favorites_cache.values() if filter_criteria.matches(f)]
            return self._sort_favorites(favorites, filter_criteria.sort_by)
    
    def get_recent(self, days: int = 7, limit: int = 50) -> List[FavoriteItem]:
        """
        Get recently added favorites.
        
        Args:
            days: Number of days to look back
            limit: Maximum number to return
            
        Returns:
            List of recent favorites
        """
        cutoff = time.time() - (days * 24 * 60 * 60)
        
        with self._lock:
            favorites = [
                f for f in self._favorites_cache.values()
                if f.added_at >= cutoff
            ]
            favorites = self._sort_favorites(favorites, SortOrder.DATE_DESC)
            return favorites[:limit]
    
    def get_most_used(self, limit: int = 50) -> List[FavoriteItem]:
        """
        Get most frequently used favorites.
        
        Args:
            limit: Maximum number to return
            
        Returns:
            List of most used favorites
        """
        with self._lock:
            favorites = [
                f for f in self._favorites_cache.values()
                if f.use_count > 0
            ]
            favorites = self._sort_favorites(favorites, SortOrder.USE_COUNT_DESC)
            return favorites[:limit]
    
    def _sort_favorites(
        self,
        favorites: List[FavoriteItem],
        sort_by: SortOrder
    ) -> List[FavoriteItem]:
        """Sort favorites by specified order."""
        if sort_by == SortOrder.DATE_DESC:
            return sorted(favorites, key=lambda f: f.added_at, reverse=True)
        elif sort_by == SortOrder.DATE_ASC:
            return sorted(favorites, key=lambda f: f.added_at)
        elif sort_by == SortOrder.NAME_ASC:
            return sorted(favorites, key=lambda f: f.photographer.lower())
        elif sort_by == SortOrder.NAME_DESC:
            return sorted(favorites, key=lambda f: f.photographer.lower(), reverse=True)
        elif sort_by == SortOrder.USE_COUNT_DESC:
            return sorted(favorites, key=lambda f: f.use_count, reverse=True)
        elif sort_by == SortOrder.USE_COUNT_ASC:
            return sorted(favorites, key=lambda f: f.use_count)
        elif sort_by == SortOrder.SIZE_DESC:
            return sorted(favorites, key=lambda f: f.width * f.height, reverse=True)
        elif sort_by == SortOrder.SIZE_ASC:
            return sorted(favorites, key=lambda f: f.width * f.height)
        else:
            return favorites
    
    # ========================================================================
    # Category Operations
    # ========================================================================
    
    def create_category(
        self,
        name: str,
        color: str = "#808080",
        icon: str = "COLLECTION_NEW"
    ) -> Optional[Category]:
        """
        Create a new category.
        
        Args:
            name: Category name
            color: Category color (hex)
            icon: Blender icon name
            
        Returns:
            Category if successful, None otherwise
        """
        with self._lock:
            # Check if name already exists
            for cat in self._categories_cache.values():
                if cat.name.lower() == name.lower():
                    logger.warning(f"Category '{name}' already exists")
                    return cat
            
            # Create category
            category = Category(
                id=generate_uuid(),
                name=name,
                color=color,
                icon=icon,
                created_at=time.time(),
                sort_order=len(self._categories_cache),
                item_count=0
            )
            
            # Save to database
            if self._db_manager:
                if not self._db_manager.insert_category(category):
                    logger.error(f"Failed to save category '{name}' to database")
                    return None
            
            # Add to cache
            self._categories_cache[category.id] = category
            
            logger.info(f"Created category: {name}")
            
            return category
    
    def delete_category(self, category_id: str) -> bool:
        """
        Delete a category.
        
        Favorites in this category will become uncategorized.
        
        Args:
            category_id: Category ID
            
        Returns:
            True if deleted successfully
        """
        with self._lock:
            if category_id not in self._categories_cache:
                return False
            
            # Don't allow deleting default categories
            category = self._categories_cache[category_id]
            if category_id in ('__uncategorized__', '__recent__', '__most_used__'):
                logger.warning(f"Cannot delete default category: {category.name}")
                return False
            
            # Update favorites in this category
            for fav in self._favorites_cache.values():
                if fav.category_id == category_id:
                    fav.category_id = None
            
            # Delete from database
            if self._db_manager:
                if not self._db_manager.delete_category(category_id):
                    logger.error(f"Failed to delete category from database")
                    return False
            
            # Remove from cache
            del self._categories_cache[category_id]
            
            logger.info(f"Deleted category: {category.name}")
            
            return True
    
    def rename_category(self, category_id: str, new_name: str) -> bool:
        """
        Rename a category.
        
        Args:
            category_id: Category ID
            new_name: New name
            
        Returns:
            True if renamed successfully
        """
        with self._lock:
            if category_id not in self._categories_cache:
                return False
            
            category = self._categories_cache[category_id]
            category.name = new_name
            
            if self._db_manager:
                self._db_manager.rename_category(category_id, new_name)
            
            return True
    
    def get_category(self, category_id: str) -> Optional[Category]:
        """
        Get a category by ID.
        
        Args:
            category_id: Category ID
            
        Returns:
            Category or None
        """
        with self._lock:
            return self._categories_cache.get(category_id)
    
    def get_all_categories(self) -> List[Category]:
        """
        Get all categories with item counts.
        
        Returns:
            List of categories
        """
        with self._lock:
            # Update item counts
            for cat in self._categories_cache.values():
                if cat.id == '__uncategorized__':
                    cat.item_count = sum(
                        1 for f in self._favorites_cache.values()
                        if not f.category_id or f.category_id == '__uncategorized__'
                    )
                elif cat.id == '__recent__':
                    week_ago = time.time() - (7 * 24 * 60 * 60)
                    cat.item_count = sum(
                        1 for f in self._favorites_cache.values()
                        if f.added_at >= week_ago
                    )
                elif cat.id == '__most_used__':
                    cat.item_count = sum(
                        1 for f in self._favorites_cache.values()
                        if f.use_count > 0
                    )
                else:
                    cat.item_count = sum(
                        1 for f in self._favorites_cache.values()
                        if f.category_id == cat.id
                    )
            
            # Sort by sort_order
            return sorted(self._categories_cache.values(), key=lambda c: c.sort_order)
    
    def move_to_category(self, pexels_id: int, category_id: str) -> bool:
        """
        Move a favorite to a category.
        
        Args:
            pexels_id: Pexels image ID
            category_id: Target category ID
            
        Returns:
            True if moved successfully
        """
        return self.update_favorite(pexels_id, category_id=category_id)
    
    # ========================================================================
    # Tag Operations
    # ========================================================================
    
    def add_tag(self, pexels_id: int, tag: str) -> bool:
        """
        Add a tag to a favorite.
        
        Args:
            pexels_id: Pexels image ID
            tag: Tag to add
            
        Returns:
            True if added successfully
        """
        with self._lock:
            if pexels_id not in self._favorites_cache:
                return False
            
            favorite = self._favorites_cache[pexels_id]
            
            if tag not in favorite.tags:
                favorite.tags.append(tag)
                
                if self._db_manager:
                    self._db_manager.update_favorite_tags(favorite.id, favorite.tags)
            
            return True
    
    def remove_tag(self, pexels_id: int, tag: str) -> bool:
        """
        Remove a tag from a favorite.
        
        Args:
            pexels_id: Pexels image ID
            tag: Tag to remove
            
        Returns:
            True if removed successfully
        """
        with self._lock:
            if pexels_id not in self._favorites_cache:
                return False
            
            favorite = self._favorites_cache[pexels_id]
            
            if tag in favorite.tags:
                favorite.tags.remove(tag)
                
                if self._db_manager:
                    self._db_manager.update_favorite_tags(favorite.id, favorite.tags)
            
            return True
    
    def set_tags(self, pexels_id: int, tags: List[str]) -> bool:
        """
        Set all tags for a favorite.
        
        Args:
            pexels_id: Pexels image ID
            tags: List of tags
            
        Returns:
            True if set successfully
        """
        return self.update_favorite(pexels_id, tags=tags)
    
    def get_all_tags(self) -> List[Tuple[str, int]]:
        """
        Get all unique tags with usage counts.
        
        Returns:
            List of (tag, count) tuples sorted by count
        """
        with self._lock:
            tag_counts: Dict[str, int] = {}
            
            for fav in self._favorites_cache.values():
                for tag in fav.tags:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
            
            return sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
    
    # ========================================================================
    # Bulk Operations
    # ========================================================================
    
    def bulk_add_to_category(
        self,
        pexels_ids: List[int],
        category_id: str
    ) -> int:
        """
        Add multiple favorites to a category.
        
        Args:
            pexels_ids: List of Pexels image IDs
            category_id: Target category ID
            
        Returns:
            Number of favorites moved
        """
        count = 0
        for pexels_id in pexels_ids:
            if self.move_to_category(pexels_id, category_id):
                count += 1
        return count
    
    def bulk_add_tag(self, pexels_ids: List[int], tag: str) -> int:
        """
        Add a tag to multiple favorites.
        
        Args:
            pexels_ids: List of Pexels image IDs
            tag: Tag to add
            
        Returns:
            Number of favorites updated
        """
        count = 0
        for pexels_id in pexels_ids:
            if self.add_tag(pexels_id, tag):
                count += 1
        return count
    
    def bulk_remove(self, pexels_ids: List[int]) -> int:
        """
        Remove multiple favorites.
        
        Args:
            pexels_ids: List of Pexels image IDs
            
        Returns:
            Number of favorites removed
        """
        count = 0
        for pexels_id in pexels_ids:
            if self.remove_favorite(pexels_id):
                count += 1
        return count
    
    # ========================================================================
    # Statistics
    # ========================================================================
    
    def get_count(self) -> int:
        """Get total number of favorites."""
        with self._lock:
            return len(self._favorites_cache)
    
    def get_category_count(self) -> int:
        """Get total number of categories."""
        with self._lock:
            return len(self._categories_cache)
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get favorites statistics.
        
        Returns:
            Dictionary with statistics
        """
        with self._lock:
            total = len(self._favorites_cache)
            categorized = sum(
                1 for f in self._favorites_cache.values()
                if f.category_id and f.category_id != '__uncategorized__'
            )
            tagged = sum(
                1 for f in self._favorites_cache.values()
                if f.tags
            )
            used = sum(
                1 for f in self._favorites_cache.values()
                if f.use_count > 0
            )
            total_uses = sum(f.use_count for f in self._favorites_cache.values())
            
            return {
                'total_favorites': total,
                'categorized': categorized,
                'uncategorized': total - categorized,
                'tagged': tagged,
                'untagged': total - tagged,
                'used': used,
                'unused': total - used,
                'total_uses': total_uses,
                'categories': len(self._categories_cache),
                'unique_tags': len(self.get_all_tags())
            }
    
    # ========================================================================
    # Cache Integration
    # ========================================================================
    
    def update_cached_paths(
        self,
        pexels_id: int,
        thumb_path: Optional[str] = None,
        full_path: Optional[str] = None
    ) -> bool:
        """
        Update cached file paths for a favorite.
        
        Args:
            pexels_id: Pexels image ID
            thumb_path: Path to cached thumbnail
            full_path: Path to cached full image
            
        Returns:
            True if updated successfully
        """
        with self._lock:
            if pexels_id not in self._favorites_cache:
                return False
            
            favorite = self._favorites_cache[pexels_id]
            
            if thumb_path is not None:
                favorite.cached_thumb_path = thumb_path
            
            if full_path is not None:
                favorite.cached_full_path = full_path
            
            # Update in database
            if self._db_manager:
                self._db_manager.insert_favorite(favorite)
            
            return True
    
    def refresh_cache(self) -> None:
        """Refresh the in-memory cache from database."""
        self._favorites_cache.clear()
        self._categories_cache.clear()
        self._load_cache()


# Global instance
favorites_manager = FavoritesManager()


def get_favorites_manager() -> FavoritesManager:
    """
    Get the global favorites manager instance.
    
    Returns:
        FavoritesManager instance
    """
    return favorites_manager