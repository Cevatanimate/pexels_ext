# SPDX-License-Identifier: GPL-3.0-or-later
"""
Cache Browser UI for Pexels Extension.

Provides comprehensive UI panels for:
- Cache overview and statistics
- Favorites management
- Search history timeline
- Storage management
- Settings configuration
"""

import bpy
from bpy.types import Panel, Operator, UIList, PropertyGroup
from bpy.props import (
    StringProperty,
    IntProperty,
    BoolProperty,
    EnumProperty,
    FloatProperty,
    CollectionProperty,
    PointerProperty
)

from .models import format_bytes, format_relative_time, SortOrder
from . import logger


# =============================================================================
# Property Groups for UI State
# =============================================================================

class PEXELS_FavoriteUIItem(PropertyGroup):
    """UI representation of a favorite item."""
    id: StringProperty(name="ID")
    pexels_id: IntProperty(name="Pexels ID")
    thumb_url: StringProperty(name="Thumbnail URL")
    photographer: StringProperty(name="Photographer")
    width: IntProperty(name="Width")
    height: IntProperty(name="Height")
    category_id: StringProperty(name="Category ID")
    tags: StringProperty(name="Tags")  # Comma-separated
    notes: StringProperty(name="Notes")
    added_at: FloatProperty(name="Added At")
    use_count: IntProperty(name="Use Count")
    is_selected: BoolProperty(name="Selected", default=False)


class PEXELS_CategoryUIItem(PropertyGroup):
    """UI representation of a category."""
    id: StringProperty(name="ID")
    name: StringProperty(name="Name")
    color: StringProperty(name="Color")
    icon: StringProperty(name="Icon")
    item_count: IntProperty(name="Item Count")


class PEXELS_HistoryUIItem(PropertyGroup):
    """UI representation of a history entry."""
    id: StringProperty(name="ID")
    query: StringProperty(name="Query")
    result_count: IntProperty(name="Result Count")
    searched_at: FloatProperty(name="Searched At")
    time_label: StringProperty(name="Time Label")


class PEXELS_CacheBrowserState(PropertyGroup):
    """State for cache browser UI."""
    
    # Active tab
    active_tab: EnumProperty(
        name="Active Tab",
        items=[
            ('OVERVIEW', "Overview", "Cache overview and statistics", 'INFO', 0),
            ('FAVORITES', "Favorites", "Manage favorite images", 'SOLO_ON', 1),
            ('HISTORY', "History", "Search history timeline", 'TIME', 2),
            ('SETTINGS', "Settings", "Cache settings", 'PREFERENCES', 3),
        ],
        default='OVERVIEW'
    )
    
    # Favorites state
    favorites_category_filter: StringProperty(
        name="Category Filter",
        default=""
    )
    favorites_search_query: StringProperty(
        name="Search",
        default=""
    )
    favorites_sort_order: EnumProperty(
        name="Sort By",
        items=[
            ('DATE_DESC', "Newest First", "Sort by date added (newest first)"),
            ('DATE_ASC', "Oldest First", "Sort by date added (oldest first)"),
            ('NAME_ASC', "Name A-Z", "Sort by photographer name"),
            ('NAME_DESC', "Name Z-A", "Sort by photographer name (reverse)"),
            ('USE_COUNT_DESC', "Most Used", "Sort by use count"),
            ('SIZE_DESC', "Largest", "Sort by image size"),
        ],
        default='DATE_DESC'
    )
    favorites_view_mode: EnumProperty(
        name="View Mode",
        items=[
            ('GRID', "Grid", "Grid view with thumbnails", 'IMGDISPLAY', 0),
            ('LIST', "List", "List view with details", 'LISTTYPE', 1),
        ],
        default='GRID'
    )
    favorites_selected_index: IntProperty(name="Selected Index", default=-1)
    
    # History state
    history_filter_days: EnumProperty(
        name="Time Range",
        items=[
            ('1', "Today", "Show today's searches"),
            ('7', "This Week", "Show this week's searches"),
            ('30', "This Month", "Show this month's searches"),
            ('0', "All Time", "Show all searches"),
        ],
        default='7'
    )
    history_search_query: StringProperty(
        name="Search History",
        default=""
    )
    
    # Settings state
    max_disk_size_mb: IntProperty(
        name="Max Disk Cache (MB)",
        default=500,
        min=100,
        max=5000
    )
    max_memory_items: IntProperty(
        name="Max Memory Items",
        default=100,
        min=10,
        max=1000
    )
    thumbnail_ttl_days: IntProperty(
        name="Thumbnail TTL (Days)",
        default=7,
        min=1,
        max=365
    )
    search_ttl_hours: IntProperty(
        name="Search Cache TTL (Hours)",
        default=1,
        min=1,
        max=168
    )
    history_retention_days: IntProperty(
        name="History Retention (Days)",
        default=30,
        min=1,
        max=365
    )
    auto_cleanup_enabled: BoolProperty(
        name="Auto Cleanup",
        default=True
    )
    
    # UI collections
    favorites_items: CollectionProperty(type=PEXELS_FavoriteUIItem)
    categories_items: CollectionProperty(type=PEXELS_CategoryUIItem)
    history_items: CollectionProperty(type=PEXELS_HistoryUIItem)


# =============================================================================
# UI Lists
# =============================================================================

class PEXELS_UL_FavoritesList(UIList):
    """UI List for favorites."""
    
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            
            # Selection checkbox
            row.prop(item, "is_selected", text="", icon='CHECKBOX_HLT' if item.is_selected else 'CHECKBOX_DEHLT')
            
            # Thumbnail placeholder
            row.label(text="", icon='IMAGE_DATA')
            
            # Info
            col = row.column()
            col.label(text=f"#{item.pexels_id}")
            col.label(text=item.photographer, icon='USER')
            
            # Dimensions
            row.label(text=f"{item.width}x{item.height}")
            
            # Use count
            if item.use_count > 0:
                row.label(text=str(item.use_count), icon='IMPORT')
            
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='IMAGE_DATA')


class PEXELS_UL_CategoriesList(UIList):
    """UI List for categories."""
    
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            
            # Icon
            row.label(text="", icon=item.icon if item.icon else 'COLLECTION_NEW')
            
            # Name and count
            row.label(text=item.name)
            row.label(text=f"({item.item_count})")


class PEXELS_UL_HistoryList(UIList):
    """UI List for search history."""
    
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            
            # Search icon
            row.label(text="", icon='VIEWZOOM')
            
            # Query
            row.label(text=item.query)
            
            # Result count
            row.label(text=f"{item.result_count} results")
            
            # Time
            row.label(text=item.time_label)


# =============================================================================
# Operators
# =============================================================================

class PEXELS_OT_RefreshCacheStats(Operator):
    """Refresh cache statistics"""
    bl_idname = "pexels.refresh_cache_stats"
    bl_label = "Refresh Statistics"
    bl_description = "Refresh cache statistics"
    
    def execute(self, context):
        try:
            from .cache_manager import get_cache_manager
            cache_manager = get_cache_manager()
            stats = cache_manager.get_statistics()
            
            self.report({'INFO'}, f"Cache: {format_bytes(stats.disk_used_bytes)} used")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to refresh stats: {e}")
            return {'CANCELLED'}


class PEXELS_OT_ClearCache(Operator):
    """Clear cache"""
    bl_idname = "pexels.clear_cache"
    bl_label = "Clear Cache"
    bl_description = "Clear all cached data"
    bl_options = {'REGISTER', 'UNDO'}
    
    cache_type: EnumProperty(
        name="Cache Type",
        items=[
            ('ALL', "All", "Clear all caches"),
            ('IMAGES', "Images", "Clear image cache only"),
            ('SEARCHES', "Searches", "Clear search cache only"),
            ('HISTORY', "History", "Clear search history only"),
        ],
        default='ALL'
    )
    
    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)
    
    def execute(self, context):
        try:
            from .cache_manager import get_cache_manager
            from .history_manager import get_history_manager
            
            cache_manager = get_cache_manager()
            history_manager = get_history_manager()
            
            if self.cache_type in ('ALL', 'IMAGES'):
                mem_cleared, disk_cleared = cache_manager.clear()
                self.report({'INFO'}, f"Cleared {disk_cleared} cached images")
            
            if self.cache_type in ('ALL', 'SEARCHES'):
                search_cleared = cache_manager.clear_search_cache()
                self.report({'INFO'}, f"Cleared {search_cleared} cached searches")
            
            if self.cache_type in ('ALL', 'HISTORY'):
                history_cleared = history_manager.clear_all()
                self.report({'INFO'}, f"Cleared {history_cleared} history entries")
            
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to clear cache: {e}")
            return {'CANCELLED'}


class PEXELS_OT_CleanupCache(Operator):
    """Cleanup expired cache entries"""
    bl_idname = "pexels.cleanup_cache"
    bl_label = "Cleanup Cache"
    bl_description = "Remove expired cache entries"
    
    def execute(self, context):
        try:
            from .cache_manager import get_cache_manager
            from .history_manager import get_history_manager
            
            cache_manager = get_cache_manager()
            history_manager = get_history_manager()
            
            results = cache_manager.full_cleanup()
            history_cleaned = history_manager.cleanup_old()
            
            total = results['expired_images'] + results['expired_searches'] + history_cleaned
            
            self.report({'INFO'}, f"Cleaned up {total} expired entries")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to cleanup: {e}")
            return {'CANCELLED'}


class PEXELS_OT_VacuumDatabase(Operator):
    """Vacuum database to reclaim space"""
    bl_idname = "pexels.vacuum_database"
    bl_label = "Optimize Database"
    bl_description = "Vacuum database to reclaim disk space"
    
    def execute(self, context):
        try:
            from .cache_manager import get_cache_manager
            cache_manager = get_cache_manager()
            
            if cache_manager.vacuum_database():
                self.report({'INFO'}, "Database optimized successfully")
            else:
                self.report({'WARNING'}, "Database optimization not available")
            
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to optimize: {e}")
            return {'CANCELLED'}


class PEXELS_OT_LoadFavorites(Operator):
    """Load favorites into UI"""
    bl_idname = "pexels.load_favorites"
    bl_label = "Load Favorites"
    bl_description = "Load favorites from database"
    
    def execute(self, context):
        try:
            from .favorites_manager import get_favorites_manager
            
            favorites_manager = get_favorites_manager()
            state = context.scene.pexels_cache_browser
            
            # Clear existing items
            state.favorites_items.clear()
            
            # Get sort order
            sort_order = SortOrder[state.favorites_sort_order]
            
            # Get favorites
            if state.favorites_category_filter:
                favorites = favorites_manager.get_by_category(
                    state.favorites_category_filter,
                    sort_by=sort_order
                )
            elif state.favorites_search_query:
                favorites = favorites_manager.search(
                    state.favorites_search_query,
                    sort_by=sort_order
                )
            else:
                favorites = favorites_manager.get_all(sort_by=sort_order)
            
            # Add to UI collection
            for fav in favorites:
                item = state.favorites_items.add()
                item.id = fav.id
                item.pexels_id = fav.pexels_id
                item.thumb_url = fav.thumb_url
                item.photographer = fav.photographer
                item.width = fav.width
                item.height = fav.height
                item.category_id = fav.category_id or ""
                item.tags = ",".join(fav.tags)
                item.notes = fav.notes
                item.added_at = fav.added_at
                item.use_count = fav.use_count
            
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to load favorites: {e}")
            return {'CANCELLED'}


class PEXELS_OT_LoadCategories(Operator):
    """Load categories into UI"""
    bl_idname = "pexels.load_categories"
    bl_label = "Load Categories"
    bl_description = "Load categories from database"
    
    def execute(self, context):
        try:
            from .favorites_manager import get_favorites_manager
            
            favorites_manager = get_favorites_manager()
            state = context.scene.pexels_cache_browser
            
            # Clear existing items
            state.categories_items.clear()
            
            # Get categories
            categories = favorites_manager.get_all_categories()
            
            # Add to UI collection
            for cat in categories:
                item = state.categories_items.add()
                item.id = cat.id
                item.name = cat.name
                item.color = cat.color
                item.icon = cat.icon
                item.item_count = cat.item_count
            
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to load categories: {e}")
            return {'CANCELLED'}


class PEXELS_OT_LoadHistory(Operator):
    """Load search history into UI"""
    bl_idname = "pexels.load_history"
    bl_label = "Load History"
    bl_description = "Load search history from database"
    
    def execute(self, context):
        try:
            from .history_manager import get_history_manager
            
            history_manager = get_history_manager()
            state = context.scene.pexels_cache_browser
            
            # Clear existing items
            state.history_items.clear()
            
            # Get history based on filter
            days = int(state.history_filter_days)
            if days == 0:
                entries = history_manager.get_recent(limit=100)
            elif days == 1:
                entries = history_manager.get_today()
            else:
                entries = history_manager.get_this_week() if days == 7 else history_manager.get_recent(limit=100)
            
            # Filter by search query
            if state.history_search_query:
                query_lower = state.history_search_query.lower()
                entries = [e for e in entries if query_lower in e.query.lower()]
            
            # Add to UI collection
            for entry in entries:
                item = state.history_items.add()
                item.id = entry.id
                item.query = entry.query
                item.result_count = entry.result_count
                item.searched_at = entry.searched_at
                item.time_label = format_relative_time(entry.searched_at)
            
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to load history: {e}")
            return {'CANCELLED'}


class PEXELS_OT_RemoveFavorite(Operator):
    """Remove a favorite"""
    bl_idname = "pexels.remove_favorite"
    bl_label = "Remove Favorite"
    bl_description = "Remove image from favorites"
    bl_options = {'REGISTER', 'UNDO'}
    
    pexels_id: IntProperty(name="Pexels ID")
    
    def execute(self, context):
        try:
            from .favorites_manager import get_favorites_manager
            
            favorites_manager = get_favorites_manager()
            
            if favorites_manager.remove_favorite(self.pexels_id):
                self.report({'INFO'}, "Removed from favorites")
                # Refresh UI
                bpy.ops.pexels.load_favorites()
            else:
                self.report({'WARNING'}, "Favorite not found")
            
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to remove favorite: {e}")
            return {'CANCELLED'}


class PEXELS_OT_RemoveSelectedFavorites(Operator):
    """Remove selected favorites"""
    bl_idname = "pexels.remove_selected_favorites"
    bl_label = "Remove Selected"
    bl_description = "Remove selected favorites"
    bl_options = {'REGISTER', 'UNDO'}
    
    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)
    
    def execute(self, context):
        try:
            from .favorites_manager import get_favorites_manager
            
            favorites_manager = get_favorites_manager()
            state = context.scene.pexels_cache_browser
            
            # Get selected IDs
            selected_ids = [
                item.pexels_id for item in state.favorites_items
                if item.is_selected
            ]
            
            if not selected_ids:
                self.report({'WARNING'}, "No favorites selected")
                return {'CANCELLED'}
            
            # Remove
            count = favorites_manager.bulk_remove(selected_ids)
            
            self.report({'INFO'}, f"Removed {count} favorites")
            
            # Refresh UI
            bpy.ops.pexels.load_favorites()
            
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to remove favorites: {e}")
            return {'CANCELLED'}


class PEXELS_OT_CreateCategory(Operator):
    """Create a new category"""
    bl_idname = "pexels.create_category"
    bl_label = "Create Category"
    bl_description = "Create a new favorites category"
    bl_options = {'REGISTER', 'UNDO'}
    
    name: StringProperty(name="Name", default="New Category")
    color: StringProperty(name="Color", default="#808080")
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)
    
    def execute(self, context):
        try:
            from .favorites_manager import get_favorites_manager
            
            favorites_manager = get_favorites_manager()
            
            category = favorites_manager.create_category(
                name=self.name,
                color=self.color
            )
            
            if category:
                self.report({'INFO'}, f"Created category: {self.name}")
                bpy.ops.pexels.load_categories()
            else:
                self.report({'WARNING'}, "Category already exists")
            
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to create category: {e}")
            return {'CANCELLED'}


class PEXELS_OT_DeleteCategory(Operator):
    """Delete a category"""
    bl_idname = "pexels.delete_category"
    bl_label = "Delete Category"
    bl_description = "Delete a favorites category"
    bl_options = {'REGISTER', 'UNDO'}
    
    category_id: StringProperty(name="Category ID")
    
    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)
    
    def execute(self, context):
        try:
            from .favorites_manager import get_favorites_manager
            
            favorites_manager = get_favorites_manager()
            
            if favorites_manager.delete_category(self.category_id):
                self.report({'INFO'}, "Category deleted")
                bpy.ops.pexels.load_categories()
                bpy.ops.pexels.load_favorites()
            else:
                self.report({'WARNING'}, "Cannot delete this category")
            
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to delete category: {e}")
            return {'CANCELLED'}


class PEXELS_OT_ReplaySearch(Operator):
    """Replay a search from history"""
    bl_idname = "pexels.replay_search"
    bl_label = "Replay Search"
    bl_description = "Replay this search query"
    
    query: StringProperty(name="Query")
    
    def execute(self, context):
        try:
            # Set the search query in the main addon state
            if hasattr(context.scene, 'pexels_state'):
                context.scene.pexels_state.search_query = self.query
                self.report({'INFO'}, f"Search query set to: {self.query}")
            
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to replay search: {e}")
            return {'CANCELLED'}


class PEXELS_OT_DeleteHistoryEntry(Operator):
    """Delete a history entry"""
    bl_idname = "pexels.delete_history_entry"
    bl_label = "Delete Entry"
    bl_description = "Delete this history entry"
    
    entry_id: StringProperty(name="Entry ID")
    
    def execute(self, context):
        try:
            from .history_manager import get_history_manager
            
            history_manager = get_history_manager()
            
            if history_manager.delete_entry(self.entry_id):
                self.report({'INFO'}, "History entry deleted")
                bpy.ops.pexels.load_history()
            
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to delete entry: {e}")
            return {'CANCELLED'}


class PEXELS_OT_SaveCacheSettings(Operator):
    """Save cache settings"""
    bl_idname = "pexels.save_cache_settings"
    bl_label = "Save Settings"
    bl_description = "Save cache settings"
    
    def execute(self, context):
        try:
            from .cache_manager import get_cache_manager
            from .models import RetentionPolicy
            
            cache_manager = get_cache_manager()
            state = context.scene.pexels_cache_browser
            
            # Create retention policy
            policy = RetentionPolicy(
                max_disk_size_bytes=state.max_disk_size_mb * 1024 * 1024,
                max_memory_items=state.max_memory_items,
                thumbnail_ttl_seconds=state.thumbnail_ttl_days * 24 * 60 * 60,
                full_image_ttl_seconds=state.thumbnail_ttl_days * 24 * 60 * 60 * 2,
                search_ttl_seconds=state.search_ttl_hours * 60 * 60,
                history_retention_days=state.history_retention_days,
                auto_cleanup_enabled=state.auto_cleanup_enabled
            )
            
            # Apply policy
            cache_manager.set_retention_policy(policy)
            
            self.report({'INFO'}, "Settings saved")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to save settings: {e}")
            return {'CANCELLED'}


# =============================================================================
# Panels
# =============================================================================

class PEXELS_PT_CacheBrowserMain(Panel):
    """Main cache browser panel"""
    bl_label = "Cache Browser"
    bl_idname = "PEXELS_PT_cache_browser_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Pexels"
    bl_options = {'DEFAULT_CLOSED'}
    
    def draw(self, context):
        layout = self.layout
        state = context.scene.pexels_cache_browser
        
        # Tab selector
        row = layout.row(align=True)
        row.prop(state, "active_tab", expand=True)


class PEXELS_PT_CacheOverview(Panel):
    """Cache overview panel"""
    bl_label = "Overview"
    bl_idname = "PEXELS_PT_cache_overview"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Pexels"
    bl_parent_id = "PEXELS_PT_cache_browser_main"
    
    @classmethod
    def poll(cls, context):
        state = context.scene.pexels_cache_browser
        return state.active_tab == 'OVERVIEW'
    
    def draw(self, context):
        layout = self.layout
        
        try:
            from .cache_manager import get_cache_manager
            from .favorites_manager import get_favorites_manager
            from .history_manager import get_history_manager
            
            cache_manager = get_cache_manager()
            favorites_manager = get_favorites_manager()
            history_manager = get_history_manager()
            
            stats = cache_manager.get_statistics()
            
            # Storage overview
            box = layout.box()
            box.label(text="Storage", icon='DISK_DRIVE')
            
            col = box.column(align=True)
            
            # Disk usage bar
            disk_percent = (stats.disk_used_bytes / stats.disk_max_bytes * 100) if stats.disk_max_bytes > 0 else 0
            col.label(text=f"Disk: {format_bytes(stats.disk_used_bytes)} / {format_bytes(stats.disk_max_bytes)}")
            col.progress(factor=disk_percent / 100, type='BAR', text=f"{disk_percent:.1f}%")
            
            # Memory usage
            mem_percent = (stats.memory_items / stats.memory_max_items * 100) if stats.memory_max_items > 0 else 0
            col.label(text=f"Memory: {stats.memory_items} / {stats.memory_max_items} items")
            col.progress(factor=mem_percent / 100, type='BAR', text=f"{mem_percent:.1f}%")
            
            # Statistics
            box = layout.box()
            box.label(text="Statistics", icon='INFO')
            
            col = box.column(align=True)
            col.label(text=f"Cached Images: {stats.total_cached_images}")
            col.label(text=f"Cached Searches: {stats.total_cached_searches}")
            col.label(text=f"Favorites: {stats.total_favorites}")
            col.label(text=f"History Entries: {stats.total_history_entries}")
            
            # Hit rate
            if stats.cache_hits + stats.cache_misses > 0:
                hit_rate = stats.cache_hits / (stats.cache_hits + stats.cache_misses) * 100
                col.separator()
                col.label(text=f"Cache Hit Rate: {hit_rate:.1f}%")
                col.label(text=f"  Memory Hits: {stats.memory_hits}")
                col.label(text=f"  Disk Hits: {stats.disk_hits}")
            
            # Actions
            box = layout.box()
            box.label(text="Actions", icon='TOOL_SETTINGS')
            
            col = box.column(align=True)
            col.operator("pexels.refresh_cache_stats", icon='FILE_REFRESH')
            col.operator("pexels.cleanup_cache", icon='BRUSH_DATA')
            col.operator("pexels.vacuum_database", icon='PACKAGE')
            
            col.separator()
            
            row = col.row(align=True)
            op = row.operator("pexels.clear_cache", text="Clear Images", icon='TRASH')
            op.cache_type = 'IMAGES'
            op = row.operator("pexels.clear_cache", text="Clear All", icon='CANCEL')
            op.cache_type = 'ALL'
            
        except Exception as e:
            layout.label(text=f"Error: {e}", icon='ERROR')


class PEXELS_PT_CacheFavorites(Panel):
    """Favorites management panel"""
    bl_label = "Favorites"
    bl_idname = "PEXELS_PT_cache_favorites"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Pexels"
    bl_parent_id = "PEXELS_PT_cache_browser_main"
    
    @classmethod
    def poll(cls, context):
        state = context.scene.pexels_cache_browser
        return state.active_tab == 'FAVORITES'
    
    def draw(self, context):
        layout = self.layout
        state = context.scene.pexels_cache_browser
        
        # Toolbar
        row = layout.row(align=True)
        row.operator("pexels.load_favorites", text="", icon='FILE_REFRESH')
        row.prop(state, "favorites_search_query", text="", icon='VIEWZOOM')
        row.prop(state, "favorites_sort_order", text="")
        row.prop(state, "favorites_view_mode", text="", expand=True)
        
        # Categories
        box = layout.box()
        row = box.row()
        row.label(text="Categories", icon='OUTLINER_COLLECTION')
        row.operator("pexels.create_category", text="", icon='ADD')
        
        # Category list
        if len(state.categories_items) > 0:
            col = box.column(align=True)
            for cat in state.categories_items:
                row = col.row(align=True)
                
                # Category button
                icon = cat.icon if cat.icon else 'COLLECTION_NEW'
                op = row.operator("pexels.load_favorites", text=f"{cat.name} ({cat.item_count})", icon=icon)
                
                # Delete button (for non-default categories)
                if cat.id not in ('__uncategorized__', '__recent__', '__most_used__'):
                    op = row.operator("pexels.delete_category", text="", icon='X')
                    op.category_id = cat.id
        else:
            box.operator("pexels.load_categories", text="Load Categories")
        
        # Favorites list
        box = layout.box()
        row = box.row()
        row.label(text=f"Favorites ({len(state.favorites_items)})", icon='SOLO_ON')
        
        if len(state.favorites_items) > 0:
            # Bulk actions
            row = box.row(align=True)
            row.operator("pexels.remove_selected_favorites", text="Remove Selected", icon='TRASH')
            
            # List
            box.template_list(
                "PEXELS_UL_FavoritesList",
                "",
                state,
                "favorites_items",
                state,
                "favorites_selected_index",
                rows=5
            )
        else:
            box.label(text="No favorites yet", icon='INFO')
            box.operator("pexels.load_favorites", text="Load Favorites")


class PEXELS_PT_CacheHistory(Panel):
    """Search history panel"""
    bl_label = "History"
    bl_idname = "PEXELS_PT_cache_history"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Pexels"
    bl_parent_id = "PEXELS_PT_cache_browser_main"
    
    @classmethod
    def poll(cls, context):
        state = context.scene.pexels_cache_browser
        return state.active_tab == 'HISTORY'
    
    def draw(self, context):
        layout = self.layout
        state = context.scene.pexels_cache_browser
        
        # Toolbar
        row = layout.row(align=True)
        row.operator("pexels.load_history", text="", icon='FILE_REFRESH')
        row.prop(state, "history_search_query", text="", icon='VIEWZOOM')
        row.prop(state, "history_filter_days", text="")
        
        # Popular queries
        try:
            from .history_manager import get_history_manager
            history_manager = get_history_manager()
            
            popular = history_manager.get_popular_queries(limit=5)
            
            if popular:
                box = layout.box()
                box.label(text="Popular Searches", icon='SOLO_ON')
                
                col = box.column(align=True)
                for query, count in popular:
                    row = col.row(align=True)
                    op = row.operator("pexels.replay_search", text=f"{query} ({count})", icon='VIEWZOOM')
                    op.query = query
        except Exception:
            pass
        
        # History list
        box = layout.box()
        row = box.row()
        row.label(text=f"Recent Searches ({len(state.history_items)})", icon='TIME')
        
        if len(state.history_items) > 0:
            # Clear button
            op = row.operator("pexels.clear_cache", text="", icon='TRASH')
            op.cache_type = 'HISTORY'
            
            # List
            box.template_list(
                "PEXELS_UL_HistoryList",
                "",
                state,
                "history_items",
                state,
                "favorites_selected_index",  # Reuse index
                rows=8
            )
        else:
            box.label(text="No search history", icon='INFO')
            box.operator("pexels.load_history", text="Load History")


class PEXELS_PT_CacheSettings(Panel):
    """Cache settings panel"""
    bl_label = "Settings"
    bl_idname = "PEXELS_PT_cache_settings"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Pexels"
    bl_parent_id = "PEXELS_PT_cache_browser_main"
    
    @classmethod
    def poll(cls, context):
        state = context.scene.pexels_cache_browser
        return state.active_tab == 'SETTINGS'
    
    def draw(self, context):
        layout = self.layout
        state = context.scene.pexels_cache_browser
        
        # Storage limits
        box = layout.box()
        box.label(text="Storage Limits", icon='DISK_DRIVE')
        
        col = box.column(align=True)
        col.prop(state, "max_disk_size_mb")
        col.prop(state, "max_memory_items")
        
        # TTL settings
        box = layout.box()
        box.label(text="Cache Duration", icon='TIME')
        
        col = box.column(align=True)
        col.prop(state, "thumbnail_ttl_days")
        col.prop(state, "search_ttl_hours")
        col.prop(state, "history_retention_days")
        
        # Auto cleanup
        box = layout.box()
        box.label(text="Maintenance", icon='TOOL_SETTINGS')
        
        col = box.column(align=True)
        col.prop(state, "auto_cleanup_enabled")
        
        # Save button
        layout.separator()
        layout.operator("pexels.save_cache_settings", icon='FILE_TICK')


# =============================================================================
# Registration
# =============================================================================

classes = [
    # Property Groups
    PEXELS_FavoriteUIItem,
    PEXELS_CategoryUIItem,
    PEXELS_HistoryUIItem,
    PEXELS_CacheBrowserState,
    
    # UI Lists
    PEXELS_UL_FavoritesList,
    PEXELS_UL_CategoriesList,
    PEXELS_UL_HistoryList,
    
    # Operators
    PEXELS_OT_RefreshCacheStats,
    PEXELS_OT_ClearCache,
    PEXELS_OT_CleanupCache,
    PEXELS_OT_VacuumDatabase,
    PEXELS_OT_LoadFavorites,
    PEXELS_OT_LoadCategories,
    PEXELS_OT_LoadHistory,
    PEXELS_OT_RemoveFavorite,
    PEXELS_OT_RemoveSelectedFavorites,
    PEXELS_OT_CreateCategory,
    PEXELS_OT_DeleteCategory,
    PEXELS_OT_ReplaySearch,
    PEXELS_OT_DeleteHistoryEntry,
    PEXELS_OT_SaveCacheSettings,
    
    # Panels
    PEXELS_PT_CacheBrowserMain,
    PEXELS_PT_CacheOverview,
    PEXELS_PT_CacheFavorites,
    PEXELS_PT_CacheHistory,
    PEXELS_PT_CacheSettings,
]


def register():
    """Register cache browser UI classes."""
    for cls in classes:
        bpy.utils.register_class(cls)
    
    # Add state to scene
    bpy.types.Scene.pexels_cache_browser = PointerProperty(type=PEXELS_CacheBrowserState)
    
    logger.debug("Cache browser UI registered")


def unregister():
    """Unregister cache browser UI classes."""
    # Remove state from scene
    if hasattr(bpy.types.Scene, 'pexels_cache_browser'):
        del bpy.types.Scene.pexels_cache_browser
    
    # Unregister classes in reverse order
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    
    logger.debug("Cache browser UI unregistered")