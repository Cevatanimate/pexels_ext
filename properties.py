# SPDX-License-Identifier: GPL-3.0-or-later
"""
Blender property groups and data structures.

Provides property groups for storing Pexels image data, addon state,
and user preferences with thread-safe access patterns.
"""

import threading
from typing import Optional, List, Tuple, Any

import bpy

from .logger import logger


# Thread lock for enum items access
_enum_items_lock = threading.RLock()

# Cache for enum items to prevent race conditions
_cached_enum_items: List[Tuple[str, str, str, int, int]] = []
_cached_enum_items_hash: int = 0


class PEXELS_Item(bpy.types.PropertyGroup):
    """Property group for storing individual Pexels image data."""
    
    item_id: bpy.props.IntProperty(
        name="Image ID",
        description="Pexels image ID"
    )
    
    thumb_url: bpy.props.StringProperty(
        name="Thumbnail URL",
        description="URL for image thumbnail"
    )
    
    full_url: bpy.props.StringProperty(
        name="Full Image URL", 
        description="URL for full-size image"
    )
    
    photographer: bpy.props.StringProperty(
        name="Photographer",
        description="Name of the photographer"
    )
    
    width: bpy.props.IntProperty(
        name="Width",
        description="Image width in pixels"
    )
    
    height: bpy.props.IntProperty(
        name="Height", 
        description="Image height in pixels"
    )


def _get_preview_manager():
    """
    Safely get the preview manager.
    
    Returns:
        PreviewManager instance or None
    """
    try:
        from .utils import preview_manager
        return preview_manager
    except ImportError:
        return None


def _compute_items_hash(items) -> int:
    """
    Compute a hash of the items collection for cache invalidation.
    
    Args:
        items: Collection of PEXELS_Item
        
    Returns:
        Hash value
    """
    try:
        if not items:
            return 0
        return hash(tuple(item.item_id for item in items))
    except Exception:
        return 0


def pexels_enum_items(self, context) -> List[Tuple[str, str, str, int, int]]:
    """
    EnumProperty items callback for template_icon_view.

    This function is called by Blender's RNA system to populate the enum items.
    It should be a standalone function, not a method of the class.
    
    Thread-safe implementation with caching to prevent race conditions.

    Args:
        self: The property group instance (PEXELS_State)
        context: Blender context (may be None)

    Returns:
        list: List of enum items for image selection
    """
    global _cached_enum_items, _cached_enum_items_hash
    
    items = []
    
    # Handle edge cases gracefully
    if self is None or not hasattr(self, 'items'):
        return items
    
    with _enum_items_lock:
        try:
            # Check if we need to rebuild the cache
            current_hash = _compute_items_hash(self.items)
            
            if current_hash == _cached_enum_items_hash and _cached_enum_items:
                return _cached_enum_items
            
            # Get preview manager safely
            preview_mgr = _get_preview_manager()
            if preview_mgr is None:
                return items
            
            # Build new items list
            for i, item in enumerate(self.items):
                # Validate item data before creating enum item
                if not hasattr(item, 'item_id') or not item.item_id:
                    continue

                image_id = str(item.item_id)
                icon_id = preview_mgr.get_preview_icon(image_id)

                # Only include items that have valid preview icons
                if icon_id and icon_id > 0:
                    # Format: (identifier, name, description, icon, number)
                    items.append((
                        image_id,
                        f"{item.item_id}",
                        item.photographer or "Unknown photographer",
                        icon_id,
                        i
                    ))
            
            # Update cache
            _cached_enum_items = items
            _cached_enum_items_hash = current_hash
            
        except Exception as e:
            # Log error but don't crash - return empty list
            logger.warning(f"Error generating enum items: {e}")
            return []

    return items


def clear_enum_cache():
    """Clear the enum items cache. Call when items change."""
    global _cached_enum_items, _cached_enum_items_hash
    with _enum_items_lock:
        _cached_enum_items = []
        _cached_enum_items_hash = 0


class PEXELS_State(bpy.types.PropertyGroup):
    """Main state property group for the Pexels addon."""

    query: bpy.props.StringProperty(
        name="Search Query",
        description="Enter keywords to search for images (e.g., 'nature', 'architecture', 'abstract')",
        default=""
    )

    # Rate limit properties
    rate_limit: bpy.props.IntProperty(
        name="Rate Limit",
        description="Total number of requests allowed per month",
        default=20000
    )

    rate_remaining: bpy.props.IntProperty(
        name="Rate Remaining",
        description="Number of requests remaining this month",
        default=20000
    )

    rate_reset_timestamp: bpy.props.IntProperty(
        name="Rate Reset Timestamp",
        description="UNIX timestamp when the monthly limit resets",
        default=0
    )
    
    page: bpy.props.IntProperty(
        name="Current Page",
        description="Current page of search results",
        default=1,
        min=1
    )
    
    total_results: bpy.props.IntProperty(
        name="Total Results",
        description="Total number of search results available",
        default=0
    )
    
    is_loading: bpy.props.BoolProperty(
        name="Loading State",
        description="Whether a search operation is currently in progress",
        default=False
    )
    
    # Progress tracking properties
    loading_progress: bpy.props.FloatProperty(
        name="Loading Progress",
        description="Current loading progress",
        default=0.0,
        min=0.0,
        max=100.0,
        subtype='PERCENTAGE'
    )
    
    loading_message: bpy.props.StringProperty(
        name="Loading Message",
        description="Current loading status message",
        default=""
    )
    
    # Caching progress tracking properties
    caching_in_progress: bpy.props.BoolProperty(
        name="Caching In Progress",
        description="Whether image caching is currently in progress",
        default=False
    )
    
    caching_progress: bpy.props.FloatProperty(
        name="Caching Progress",
        description="Current caching progress percentage",
        default=0.0,
        min=0.0,
        max=100.0,
        subtype='PERCENTAGE'
    )
    
    caching_current_file: bpy.props.StringProperty(
        name="Current File",
        description="Name of the file currently being cached",
        default=""
    )
    
    caching_eta_seconds: bpy.props.IntProperty(
        name="ETA Seconds",
        description="Estimated time remaining in seconds",
        default=0,
        min=0
    )
    
    caching_items_done: bpy.props.IntProperty(
        name="Items Done",
        description="Number of items that have been cached",
        default=0,
        min=0
    )
    
    caching_items_total: bpy.props.IntProperty(
        name="Items Total",
        description="Total number of items to cache",
        default=0,
        min=0
    )
    
    caching_speed_bytes: bpy.props.FloatProperty(
        name="Caching Speed",
        description="Current download speed in bytes per second",
        default=0.0,
        min=0.0
    )
    
    caching_error_message: bpy.props.StringProperty(
        name="Caching Error",
        description="Error message if caching failed",
        default=""
    )
    
    # Search results collection
    items: bpy.props.CollectionProperty(
        type=PEXELS_Item,
        name="Search Results",
        description="Collection of found images"
    )
    
    # Selected preview (Pexels ID as string) - using private attribute for better control
    selected_icon: bpy.props.EnumProperty(
        name="Selected Image",
        description="Currently selected image from search results",
        items=pexels_enum_items,
        get=lambda self: self._get_selected_icon(),
        set=lambda self, value: self._set_selected_icon(value)
    )
    
    def _get_selected_icon(self) -> str:
        """
        Get the selected icon value safely.
        
        Returns:
            Selected icon identifier or empty string
        """
        value = getattr(self, '_selected_icon', None)
        if value is None:
            return ''
        return value
    
    def _set_selected_icon(self, value: str) -> None:
        """
        Set the selected icon value with validation.
        
        Args:
            value: The enum value to set
        """
        validated = self._validate_selected_icon(value)
        self._selected_icon = validated
    
    def clear_results(self):
        """Clear all search results and reset state."""
        # Clear enum cache first to prevent race conditions
        clear_enum_cache()
        
        # Clear items
        self.items.clear()
        self.total_results = 0
        
        # Reset selected icon to None to avoid enum validation errors
        self._selected_icon = None
        
        # Clear preview manager
        preview_mgr = _get_preview_manager()
        if preview_mgr:
            preview_mgr.clear_previews()
        
        logger.debug("Search results cleared")
    
    def get_selected_item(self) -> Optional['PEXELS_Item']:
        """
        Get the currently selected PEXELS_Item.

        Returns:
            PEXELS_Item or None: Selected item or None if no selection
        """
        current_selection = getattr(self, '_selected_icon', None)
        if not current_selection:
            return None

        try:
            selected_id = int(current_selection)
            return next((item for item in self.items if item.item_id == selected_id), None)
        except (ValueError, AttributeError, TypeError):
            return None

    def _validate_selected_icon(self, value: str) -> Optional[str]:
        """
        Validate and clean the selected_icon value.

        Args:
            value: The enum value to validate

        Returns:
            str or None: Valid enum value or None if invalid
        """
        if not value:
            return None

        # Check if the value exists in current enum items
        try:
            # Get context safely
            context = None
            try:
                context = bpy.context
            except Exception:
                pass
            
            # Get enum items with thread safety
            with _enum_items_lock:
                enum_items = pexels_enum_items(self, context)
                valid_identifiers = {item[0] for item in enum_items}

            if value in valid_identifiers:
                return value
            else:
                # Value is not in current enum items, reset to None
                return None
        except Exception as e:
            # If there's any error getting enum items, reset to None
            logger.warning(f"Error validating selected icon: {e}")
            return None

    def refresh_enum_items(self, context):
        """
        Force refresh of enum items to reflect updated preview icons.

        Args:
            context: Blender context
        """
        try:
            # Clear the cache to force regeneration
            clear_enum_cache()
            
            # Force enum items regeneration by triggering the callback
            enum_items = pexels_enum_items(self, context)

            # If we have cached previews but no enum items, force UI refresh
            if not enum_items and self.items:
                preview_mgr = _get_preview_manager()
                if preview_mgr is None:
                    return
                
                # Check if any items now have valid preview icons
                has_valid_previews = any(
                    preview_mgr.get_preview_icon(str(item.item_id))
                    for item in self.items
                )

                if has_valid_previews:
                    # Force a more aggressive refresh by temporarily changing selection
                    current_selection = getattr(self, '_selected_icon', None)
                    self._selected_icon = None

                    # Small delay to ensure the change propagates
                    def delayed_refresh():
                        try:
                            if current_selection:
                                # Re-validate the selection
                                with _enum_items_lock:
                                    valid_items = pexels_enum_items(self, context)
                                    valid_ids = {item[0] for item in valid_items}
                                if current_selection in valid_ids:
                                    self._selected_icon = current_selection
                                elif valid_items:
                                    self._selected_icon = valid_items[0][0]
                        except Exception as e:
                            logger.warning(f"Error in delayed refresh: {e}")
                        return None  # Don't repeat timer

                    # Use a timer to delay the refresh slightly
                    bpy.app.timers.register(delayed_refresh, first_interval=0.01)
                    
        except Exception as e:
            logger.warning(f"Error refreshing enum items: {e}")


class PEXELS_AddonPrefs(bpy.types.AddonPreferences):
    """Addon preferences for API configuration and settings."""
    
    bl_idname = __package__
    
    api_key: bpy.props.StringProperty(
        name="Pexels API Key",
        description="Get your free API key at https://www.pexels.com/api/new/",
        subtype='PASSWORD'
    )
    
    max_results: bpy.props.IntProperty(
        name="Results per Page",
        description="Number of images to fetch per search (1-80)",
        default=50,
        min=1,
        max=80
    )
    
    cache_thumbnails: bpy.props.BoolProperty(
        name="Cache Thumbnails",
        description="Cache downloaded thumbnails for faster loading",
        default=True
    )
    
    default_plane_size: bpy.props.FloatProperty(
        name="Default Plane Size",
        description="Default size for imported image planes",
        default=2.0,
        min=0.01,
        max=100.0
    )
    
    def draw(self, context):
        """Draw the preferences panel."""
        layout = self.layout
        main_col = layout.column()
        
        # API Key section
        self._draw_api_section(main_col)
        
        # Search Settings section  
        self._draw_settings_section(main_col)
        
        # Import Settings section
        self._draw_import_section(main_col)
        
        # Usage Instructions section
        self._draw_usage_section(main_col)
    
    def _draw_api_section(self, layout):
        """Draw API configuration section."""
        api_box = layout.box()
        api_box.label(text="🔑 API Configuration", icon='KEYFRAME_HLT')
        api_box.prop(self, "api_key")
        
        if not self.api_key:
            warning_row = api_box.row()
            warning_row.alert = True
            warning_row.label(text="⚠ API key required to search images", icon='ERROR')
        
        info_col = api_box.column(align=True)
        info_col.label(text="Get your free API key at:")
        info_col.label(text="https://www.pexels.com/api/new/")
    
    def _draw_settings_section(self, layout):
        """Draw search settings section."""
        settings_box = layout.box()
        settings_box.label(text="🔍 Search Settings", icon='VIEWZOOM')
        
        settings_col = settings_box.column(align=True)
        settings_col.prop(self, "max_results")
        settings_col.prop(self, "cache_thumbnails")
    
    def _draw_import_section(self, layout):
        """Draw import settings section."""
        import_box = layout.box()
        import_box.label(text="⬇ Import Settings", icon='IMPORT')
        import_box.prop(self, "default_plane_size")
    
    def _draw_usage_section(self, layout):
        """Draw usage instructions section."""
        usage_box = layout.box()
        usage_box.label(text="📖 How to Use", icon='QUESTION')
        
        usage_col = usage_box.column(align=True)
        usage_col.label(text="1. Set your API key above")
        usage_col.label(text="2. Open 3D View > N-Panel > Pexels tab")
        usage_col.label(text="3. Search and import high-quality images")
        usage_col.label(text="4. All images are free to use commercially")


# Property group classes for registration
property_classes = (
    PEXELS_Item,
    PEXELS_State,
    PEXELS_AddonPrefs,
)
