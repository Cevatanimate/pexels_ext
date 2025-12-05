# SPDX-License-Identifier: GPL-3.0-or-later
"""
History Manager for Pexels Extension.

Provides search history tracking and management including:
- Recording search queries
- Timeline visualization data
- Popular queries tracking
- History replay functionality
- Cleanup and retention
"""

import time
import threading
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import (
    SearchHistoryEntry,
    CachedSearchResult,
    generate_uuid
)
from . import logger


@dataclass
class HistoryGroup:
    """Group of history entries for timeline display."""
    date: str  # YYYY-MM-DD
    label: str  # "Today", "Yesterday", "Monday", etc.
    entries: List[SearchHistoryEntry]
    
    @property
    def count(self) -> int:
        return len(self.entries)


class HistoryManager:
    """
    Thread-safe search history manager.
    
    Implements singleton pattern for global access.
    
    Features:
    - Record search queries
    - Timeline grouping
    - Popular queries
    - History replay
    - Automatic cleanup
    
    Usage:
        history = HistoryManager()
        
        # Record a search
        history.record_search("sunset", 100, page=1)
        
        # Get recent history
        recent = history.get_recent(limit=20)
        
        # Get timeline groups
        timeline = history.get_timeline()
        
        # Get popular queries
        popular = history.get_popular_queries()
    """
    
    _instance: Optional['HistoryManager'] = None
    _instance_lock: threading.Lock = threading.Lock()
    
    # Configuration
    MAX_HISTORY_ENTRIES = 1000
    DEFAULT_RETENTION_DAYS = 30
    
    def __new__(cls) -> 'HistoryManager':
        """Singleton pattern implementation."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance
    
    def __init__(self):
        """Initialize the history manager."""
        if self._initialized:
            return
        
        self._initialized = True
        self._lock = threading.RLock()
        
        # Database manager (lazy initialization)
        self._db_manager = None
        
        # Memory cache for recent history
        self._recent_cache: List[SearchHistoryEntry] = []
        self._cache_limit = 100
        
        # Popular queries cache
        self._popular_cache: List[Tuple[str, int]] = []
        self._popular_cache_time: float = 0
        self._popular_cache_ttl = 300  # 5 minutes
        
        # Initialize
        self._init_database()
        self._load_recent_cache()
    
    def _init_database(self) -> None:
        """Initialize database connection."""
        try:
            from .database_manager import get_database_manager
            self._db_manager = get_database_manager()
            logger.debug("History manager database initialized")
        except Exception as e:
            logger.warning(f"Database not available for history: {e}")
            self._db_manager = None
    
    def _load_recent_cache(self) -> None:
        """Load recent history into memory cache."""
        if not self._db_manager:
            return
        
        try:
            self._recent_cache = self._db_manager.get_search_history(
                limit=self._cache_limit
            )
            logger.debug(f"Loaded {len(self._recent_cache)} history entries")
        except Exception as e:
            logger.error(f"Failed to load history cache: {e}")
    
    # ========================================================================
    # Recording
    # ========================================================================
    
    def record_search(
        self,
        query: str,
        result_count: int,
        page: int = 1,
        per_page: int = 50,
        cached_result_id: Optional[str] = None
    ) -> Optional[SearchHistoryEntry]:
        """
        Record a search query.
        
        Args:
            query: Search query
            result_count: Number of results
            page: Page number
            per_page: Results per page
            cached_result_id: ID of cached result (if any)
            
        Returns:
            SearchHistoryEntry if successful
        """
        with self._lock:
            # Create entry
            entry = SearchHistoryEntry.create(
                query=query,
                result_count=result_count,
                page=page,
                per_page=per_page,
                cached_result_id=cached_result_id
            )
            
            # Save to database
            if self._db_manager:
                if not self._db_manager.insert_search_history(entry):
                    logger.error(f"Failed to save history entry")
                    return None
            
            # Add to cache
            self._recent_cache.insert(0, entry)
            
            # Trim cache
            if len(self._recent_cache) > self._cache_limit:
                self._recent_cache = self._recent_cache[:self._cache_limit]
            
            # Invalidate popular cache
            self._popular_cache_time = 0
            
            logger.debug(f"Recorded search: '{query}' ({result_count} results)")
            
            return entry
    
    def record_search_from_result(
        self,
        result: CachedSearchResult
    ) -> Optional[SearchHistoryEntry]:
        """
        Record a search from a cached result.
        
        Args:
            result: Cached search result
            
        Returns:
            SearchHistoryEntry if successful
        """
        return self.record_search(
            query=result.query,
            result_count=result.total_results,
            page=result.page,
            per_page=result.per_page,
            cached_result_id=result.id
        )
    
    # ========================================================================
    # Retrieval
    # ========================================================================
    
    def get_recent(self, limit: int = 20) -> List[SearchHistoryEntry]:
        """
        Get recent search history.
        
        Args:
            limit: Maximum number of entries
            
        Returns:
            List of history entries
        """
        with self._lock:
            if len(self._recent_cache) >= limit:
                return self._recent_cache[:limit]
            
            # Need to fetch from database
            if self._db_manager:
                entries = self._db_manager.get_search_history(limit=limit)
                return entries
            
            return self._recent_cache[:limit]
    
    def get_today(self) -> List[SearchHistoryEntry]:
        """
        Get today's search history.
        
        Returns:
            List of today's history entries
        """
        if self._db_manager:
            return self._db_manager.get_search_history_today()
        
        # Filter from cache
        today_start = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
        
        with self._lock:
            return [e for e in self._recent_cache if e.searched_at >= today_start]
    
    def get_this_week(self) -> List[SearchHistoryEntry]:
        """
        Get this week's search history.
        
        Returns:
            List of this week's history entries
        """
        if self._db_manager:
            return self._db_manager.get_search_history_this_week()
        
        # Filter from cache
        week_ago = time.time() - (7 * 24 * 60 * 60)
        
        with self._lock:
            return [e for e in self._recent_cache if e.searched_at >= week_ago]
    
    def get_by_query(self, query: str, limit: int = 50) -> List[SearchHistoryEntry]:
        """
        Get history entries for a specific query.
        
        Args:
            query: Search query
            limit: Maximum number of entries
            
        Returns:
            List of matching history entries
        """
        with self._lock:
            query_lower = query.lower()
            matches = [
                e for e in self._recent_cache
                if e.query.lower() == query_lower
            ]
            
            if len(matches) >= limit:
                return matches[:limit]
            
            # Need more from database
            if self._db_manager:
                all_entries = self._db_manager.get_search_history(limit=500)
                matches = [
                    e for e in all_entries
                    if e.query.lower() == query_lower
                ]
                return matches[:limit]
            
            return matches
    
    def search_history(self, query: str, limit: int = 50) -> List[SearchHistoryEntry]:
        """
        Search history entries by partial query match.
        
        Args:
            query: Search term
            limit: Maximum number of entries
            
        Returns:
            List of matching history entries
        """
        with self._lock:
            query_lower = query.lower()
            matches = [
                e for e in self._recent_cache
                if query_lower in e.query.lower()
            ]
            return matches[:limit]
    
    # ========================================================================
    # Timeline
    # ========================================================================
    
    def get_timeline(self, days: int = 7) -> List[HistoryGroup]:
        """
        Get history grouped by date for timeline display.
        
        Args:
            days: Number of days to include
            
        Returns:
            List of HistoryGroup objects
        """
        # Get all entries for the period
        if self._db_manager:
            entries = self._db_manager.get_search_history(limit=500)
        else:
            entries = self._recent_cache
        
        # Filter by date range
        cutoff = time.time() - (days * 24 * 60 * 60)
        entries = [e for e in entries if e.searched_at >= cutoff]
        
        # Group by date
        groups: Dict[str, List[SearchHistoryEntry]] = {}
        
        for entry in entries:
            date_str = datetime.fromtimestamp(entry.searched_at).strftime('%Y-%m-%d')
            if date_str not in groups:
                groups[date_str] = []
            groups[date_str].append(entry)
        
        # Create HistoryGroup objects
        result = []
        today = datetime.now().date()
        
        for date_str in sorted(groups.keys(), reverse=True):
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
            
            # Generate label
            if date == today:
                label = "Today"
            elif date == today - timedelta(days=1):
                label = "Yesterday"
            elif (today - date).days < 7:
                label = date.strftime('%A')  # Day name
            else:
                label = date.strftime('%B %d')  # Month Day
            
            result.append(HistoryGroup(
                date=date_str,
                label=label,
                entries=groups[date_str]
            ))
        
        return result
    
    def get_hourly_distribution(self, days: int = 7) -> Dict[int, int]:
        """
        Get search distribution by hour of day.
        
        Args:
            days: Number of days to analyze
            
        Returns:
            Dictionary mapping hour (0-23) to search count
        """
        # Get entries
        if self._db_manager:
            entries = self._db_manager.get_search_history(limit=1000)
        else:
            entries = self._recent_cache
        
        # Filter by date range
        cutoff = time.time() - (days * 24 * 60 * 60)
        entries = [e for e in entries if e.searched_at >= cutoff]
        
        # Count by hour
        distribution = {h: 0 for h in range(24)}
        
        for entry in entries:
            hour = datetime.fromtimestamp(entry.searched_at).hour
            distribution[hour] += 1
        
        return distribution
    
    # ========================================================================
    # Popular Queries
    # ========================================================================
    
    def get_popular_queries(self, limit: int = 10) -> List[Tuple[str, int]]:
        """
        Get most popular search queries.
        
        Args:
            limit: Maximum number of queries
            
        Returns:
            List of (query, count) tuples
        """
        # Check cache
        if (time.time() - self._popular_cache_time) < self._popular_cache_ttl:
            return self._popular_cache[:limit]
        
        # Fetch from database
        if self._db_manager:
            popular = self._db_manager.get_popular_queries(limit=limit)
        else:
            # Calculate from cache
            query_counts: Dict[str, int] = {}
            for entry in self._recent_cache:
                query_counts[entry.query] = query_counts.get(entry.query, 0) + 1
            
            popular = sorted(
                query_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )[:limit]
        
        # Update cache
        self._popular_cache = popular
        self._popular_cache_time = time.time()
        
        return popular[:limit]
    
    def get_unique_queries(self, limit: int = 100) -> List[str]:
        """
        Get unique search queries.
        
        Args:
            limit: Maximum number of queries
            
        Returns:
            List of unique queries
        """
        seen = set()
        unique = []
        
        for entry in self._recent_cache:
            if entry.query not in seen:
                seen.add(entry.query)
                unique.append(entry.query)
                if len(unique) >= limit:
                    break
        
        return unique
    
    def get_query_suggestions(self, prefix: str, limit: int = 10) -> List[str]:
        """
        Get query suggestions based on prefix.
        
        Args:
            prefix: Query prefix
            limit: Maximum number of suggestions
            
        Returns:
            List of suggested queries
        """
        prefix_lower = prefix.lower()
        
        # Get unique queries that start with prefix
        seen = set()
        suggestions = []
        
        for entry in self._recent_cache:
            if entry.query.lower().startswith(prefix_lower):
                if entry.query not in seen:
                    seen.add(entry.query)
                    suggestions.append(entry.query)
                    if len(suggestions) >= limit:
                        break
        
        return suggestions
    
    # ========================================================================
    # Replay
    # ========================================================================
    
    def get_entry_by_id(self, entry_id: str) -> Optional[SearchHistoryEntry]:
        """
        Get a history entry by ID.
        
        Args:
            entry_id: Entry ID
            
        Returns:
            SearchHistoryEntry or None
        """
        with self._lock:
            for entry in self._recent_cache:
                if entry.id == entry_id:
                    return entry
            return None
    
    def get_cached_result_for_entry(
        self,
        entry: SearchHistoryEntry
    ) -> Optional[CachedSearchResult]:
        """
        Get the cached search result for a history entry.
        
        Args:
            entry: History entry
            
        Returns:
            CachedSearchResult or None
        """
        if not entry.cached_result_id:
            return None
        
        if self._db_manager:
            return self._db_manager.get_search_result_by_id(entry.cached_result_id)
        
        return None
    
    # ========================================================================
    # Deletion
    # ========================================================================
    
    def delete_entry(self, entry_id: str) -> bool:
        """
        Delete a history entry.
        
        Args:
            entry_id: Entry ID
            
        Returns:
            True if deleted successfully
        """
        with self._lock:
            # Remove from cache
            self._recent_cache = [
                e for e in self._recent_cache
                if e.id != entry_id
            ]
            
            # Remove from database
            if self._db_manager:
                return self._db_manager.delete_search_history_entry(entry_id)
            
            return True
    
    def delete_by_query(self, query: str) -> int:
        """
        Delete all history entries for a query.
        
        Args:
            query: Search query
            
        Returns:
            Number of entries deleted
        """
        with self._lock:
            query_lower = query.lower()
            
            # Find matching entries
            to_delete = [
                e for e in self._recent_cache
                if e.query.lower() == query_lower
            ]
            
            # Remove from cache
            self._recent_cache = [
                e for e in self._recent_cache
                if e.query.lower() != query_lower
            ]
            
            # Remove from database
            count = 0
            if self._db_manager:
                for entry in to_delete:
                    if self._db_manager.delete_search_history_entry(entry.id):
                        count += 1
            else:
                count = len(to_delete)
            
            return count
    
    def clear_all(self) -> int:
        """
        Clear all search history.
        
        Returns:
            Number of entries cleared
        """
        with self._lock:
            count = len(self._recent_cache)
            self._recent_cache.clear()
            
            if self._db_manager:
                count = self._db_manager.clear_search_history()
            
            # Clear popular cache
            self._popular_cache.clear()
            self._popular_cache_time = 0
            
            logger.info(f"Cleared {count} history entries")
            
            return count
    
    def cleanup_old(self, days: int = None) -> int:
        """
        Remove history entries older than specified days.
        
        Args:
            days: Number of days to keep (None = use default)
            
        Returns:
            Number of entries removed
        """
        if days is None:
            days = self.DEFAULT_RETENTION_DAYS
        
        with self._lock:
            cutoff = time.time() - (days * 24 * 60 * 60)
            
            # Remove from cache
            old_count = len(self._recent_cache)
            self._recent_cache = [
                e for e in self._recent_cache
                if e.searched_at >= cutoff
            ]
            cache_removed = old_count - len(self._recent_cache)
            
            # Remove from database
            db_removed = 0
            if self._db_manager:
                db_removed = self._db_manager.cleanup_old_history(days)
            
            total_removed = max(cache_removed, db_removed)
            
            if total_removed > 0:
                logger.info(f"Cleaned up {total_removed} old history entries")
            
            return total_removed
    
    # ========================================================================
    # Statistics
    # ========================================================================
    
    def get_count(self) -> int:
        """Get total number of history entries."""
        if self._db_manager:
            return self._db_manager.get_search_history_count()
        return len(self._recent_cache)
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get history statistics.
        
        Returns:
            Dictionary with statistics
        """
        entries = self._recent_cache
        
        if not entries:
            return {
                'total_entries': 0,
                'unique_queries': 0,
                'total_results_found': 0,
                'avg_results_per_search': 0,
                'searches_today': 0,
                'searches_this_week': 0,
                'most_popular_query': None,
                'most_popular_count': 0
            }
        
        # Calculate statistics
        unique_queries = len(set(e.query for e in entries))
        total_results = sum(e.result_count for e in entries)
        avg_results = total_results / len(entries) if entries else 0
        
        # Today's searches
        today_start = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
        searches_today = sum(1 for e in entries if e.searched_at >= today_start)
        
        # This week's searches
        week_ago = time.time() - (7 * 24 * 60 * 60)
        searches_week = sum(1 for e in entries if e.searched_at >= week_ago)
        
        # Most popular
        popular = self.get_popular_queries(limit=1)
        most_popular = popular[0] if popular else (None, 0)
        
        return {
            'total_entries': self.get_count(),
            'unique_queries': unique_queries,
            'total_results_found': total_results,
            'avg_results_per_search': round(avg_results, 1),
            'searches_today': searches_today,
            'searches_this_week': searches_week,
            'most_popular_query': most_popular[0],
            'most_popular_count': most_popular[1]
        }
    
    # ========================================================================
    # Cache Management
    # ========================================================================
    
    def refresh_cache(self) -> None:
        """Refresh the in-memory cache from database."""
        self._recent_cache.clear()
        self._popular_cache.clear()
        self._popular_cache_time = 0
        self._load_recent_cache()


# Global instance
history_manager = None


def get_history_manager() -> HistoryManager:
    """
    Get the global history manager instance.
    
    Returns:
        HistoryManager instance
    """
    global history_manager
    if history_manager is None:
        history_manager = HistoryManager()
    return history_manager