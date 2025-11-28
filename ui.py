# SPDX-License-Identifier: GPL-3.0-or-later
"""
User interface panels and components for the Pexels addon.

Provides panels for searching, browsing, and importing images from Pexels
with proper null checks, error state display, progress indicators,
and favorites management integration.

IMPROVED: Better visual hierarchy, clearer error messages, and
operation status display for async operations.
"""

import bpy

from .progress_tracker import progress_tracker, ProgressStatus
from .logger import logger
from .utils import format_eta, format_speed, truncate_filename, format_progress_items

# Import favorites manager for favorite status checking
try:
    from .operators import is_favorite, ENHANCED_CACHING_AVAILABLE
except ImportError:
    ENHANCED_CACHING_AVAILABLE = False
    def is_favorite(pexels_id):
        return False


def get_preferences(context):
    """
    Safely get addon preferences.
    
    Args:
        context: Blender context
        
    Returns:
        Addon preferences or None if not available
    """
    try:
        if context is None:
            return None
        if not hasattr(context, 'preferences'):
            return None
        if context.preferences is None:
            return None
        if not hasattr(context.preferences, 'addons'):
            return None
        if __package__ not in context.preferences.addons:
            return None
        return context.preferences.addons[__package__].preferences
    except Exception:
        return None


def get_state(context):
    """
    Safely get addon state.
    
    Args:
        context: Blender context
        
    Returns:
        Addon state or None if not available
    """
    try:
        if context is None:
            return None
        if not hasattr(context, 'scene'):
            return None
        if context.scene is None:
            return None
        return getattr(context.scene, 'pexels_state', None)
    except Exception:
        return None


class PEXELS_PT_Panel(bpy.types.Panel):
    """Main Pexels panel in the 3D View N-Panel."""
    
    bl_label = "Pexels Image Search"
    bl_idname = "PEXELS_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Pexels"
    
    def draw(self, context):
        """Draw the main panel."""
        layout = self.layout
        
        # Safely get state and preferences
        state = get_state(context)
        prefs = get_preferences(context)
        
        # Handle missing state
        if state is None:
            self._draw_error_state(layout, "Addon state not available. Try restarting Blender.")
            return
        
        # Handle missing preferences
        if prefs is None:
            self._draw_error_state(layout, "Addon preferences not available.")
            return
        
        # Check if API key is configured
        if not prefs.api_key:
            self._draw_api_key_warning(layout)
            return
        
        # Draw operation status banner if there's an error
        if state.operation_status == 'ERROR' and state.last_error_message:
            self._draw_operation_error(layout, state)
        
        # Draw main interface sections
        self._draw_search_section(layout, state, prefs)
        
        # Draw progress/loading indicator based on operation status
        if state.is_loading or state.operation_status in ('SEARCHING', 'DOWNLOADING', 'IMPORTING'):
            self._draw_progress_indicator(layout, state)
            return
        
        # Draw error state if progress tracker has error
        progress_state = progress_tracker.get_progress()
        if progress_state.has_error():
            self._draw_error_state(layout, progress_state.error_message)
        
        # Draw results or help
        if state.items:
            self._draw_results_section(layout, state)
            self._draw_selected_image_details(layout, state)
        elif state.query:
            self._draw_no_results_message(layout)
        else:
            self._draw_help_section(layout)
    
    def _draw_operation_error(self, layout, state):
        """Draw operation error banner that can be dismissed."""
        error_box = layout.box()
        error_box.alert = True
        
        # Header row with dismiss button
        header_row = error_box.row()
        header_row.label(text="Operation Error", icon='ERROR')
        
        # Error message
        error_col = error_box.column(align=True)
        self._draw_wrapped_text(error_col, state.last_error_message, max_width=40)
        
        # Clear error button
        clear_row = error_box.row()
        clear_row.operator("pexels.clear_error", text="Dismiss", icon='X')
    
    def _draw_wrapped_text(self, layout, text: str, max_width: int = 40):
        """Draw text wrapped to fit within max_width characters."""
        words = text.split()
        line = ""
        for word in words:
            if len(line) + len(word) + 1 > max_width:
                if line:
                    layout.label(text=line)
                line = word
            else:
                line = f"{line} {word}".strip() if line else word
        if line:
            layout.label(text=line)
    
    def _draw_error_state(self, layout, message: str):
        """Draw error state message."""
        error_box = layout.box()
        error_box.alert = True
        error_box.label(text="Error", icon='ERROR')
        
        # Split long messages into multiple lines
        self._draw_wrapped_text(error_box, message, max_width=40)
    
    def _draw_api_key_warning(self, layout):
        """Draw API key requirement warning."""
        warning_box = layout.box()
        warning_box.label(text="API Key Required", icon='ERROR')
        
        info_col = warning_box.column(align=True)
        info_col.label(text="Set your Pexels API key in")
        info_col.label(text="Add-on Preferences first")
        
        warning_box.separator()
        warning_box.operator("pexels.open_preferences", text="Open Preferences", icon='PREFERENCES')
    
    def _draw_search_section(self, layout, state, prefs):
        """Draw search interface section."""
        # Search box with clear visual hierarchy
        search_box = layout.box()
        
        # Header
        header_row = search_box.row()
        header_row.label(text="Search Images", icon='VIEWZOOM')
        
        # Search input
        search_col = search_box.column(align=True)
        search_col.prop(state, "query", text="")
        
        # Search and cancel buttons
        button_row = search_col.row(align=True)
        button_row.scale_y = 1.3
        
        if state.is_loading or state.operation_status in ('SEARCHING', 'DOWNLOADING'):
            button_row.operator("pexels.cancel", text="Cancel", icon='CANCEL')
        else:
            button_row.operator("pexels.search", text="Search", icon='VIEWZOOM')
        
        # Results info and pagination (only show if we have results)
        if state.total_results > 0:
            search_box.separator()
            self._draw_results_info(search_box, state)
            self._draw_pagination_controls(search_box, state)

        # Rate limit indicator (subtle, at bottom)
        self._draw_rate_limit_indicator(search_box, state)
    
    def _draw_results_info(self, layout, state):
        """Draw results information."""
        info_row = layout.row(align=True)
        results_text = f"Showing {len(state.items)} of {state.total_results} results"
        info_row.label(text=results_text, icon='IMAGE_DATA')
    
    def _draw_pagination_controls(self, layout, state):
        """Draw pagination navigation controls."""
        nav_row = layout.row(align=True)
        
        # Previous page button
        prev_col = nav_row.column(align=True)
        prev_col.enabled = state.page > 1
        prev_op = prev_col.operator("pexels.page", text="", icon='TRIA_LEFT')
        prev_op.direction = 'PREV'
        
        # Page indicator
        page_col = nav_row.column(align=True)
        page_col.alignment = 'CENTER'
        page_col.label(text=f"Page {state.page}")
        
        # Next page button
        next_col = nav_row.column(align=True)
        next_op = next_col.operator("pexels.page", text="", icon='TRIA_RIGHT')
        next_op.direction = 'NEXT'

    def _draw_rate_limit_indicator(self, layout, state):
        """Draw rate limit status indicator."""
        # Only show if we have rate limit data
        if state.rate_limit <= 0:
            return

        # Calculate usage percentage
        usage_percent = ((state.rate_limit - state.rate_remaining) / state.rate_limit) * 100

        # Only show warning if usage is high
        if usage_percent < 75:
            return
        
        layout.separator()
        rate_row = layout.row(align=True)

        # Choose icon and color based on remaining requests
        if state.rate_remaining == 0:
            rate_row.alert = True
            rate_row.label(text="Rate limit exceeded!", icon='ERROR')
        elif usage_percent >= 90:
            rate_row.alert = True
            rate_row.label(text=f"{state.rate_remaining} requests left", icon='ERROR')
        else:
            rate_row.label(text=f"{state.rate_remaining} requests left", icon='INFO')
    
    def _draw_progress_indicator(self, layout, state):
        """Draw progress indicator with cancel button."""
        progress_box = layout.box()
        
        # Get progress state
        progress_state = progress_tracker.get_progress()
        
        # Status header based on operation type
        status_text = "Processing..."
        status_icon = 'FILE_REFRESH'
        
        if state.operation_status == 'SEARCHING':
            status_text = "Searching..."
        elif state.operation_status == 'DOWNLOADING':
            status_text = "Downloading..."
        elif state.operation_status == 'IMPORTING':
            status_text = "Importing..."
        elif progress_state.status == ProgressStatus.ERROR:
            status_text = "Error"
            status_icon = 'ERROR'
        elif progress_state.status == ProgressStatus.CANCELLED:
            status_text = "Cancelled"
            status_icon = 'CANCEL'
        
        progress_box.label(text=status_text, icon=status_icon)
        
        # Current item
        if progress_state.current_item:
            item_row = progress_box.row()
            truncated = truncate_filename(progress_state.current_item, max_length=35)
            item_row.label(text=truncated)
        
        # Progress bar
        if progress_state.total_items > 0:
            progress_row = progress_box.row()
            progress_row.prop(
                state,
                "loading_progress",
                text=f"{progress_state.percentage:.0f}%"
            )
            
            # Update the property value
            try:
                state.loading_progress = progress_state.percentage
            except Exception:
                pass
        
        # ETA and stats
        if progress_state.total_items > 0:
            stats_row = progress_box.row()
            stats_row.label(text=f"ETA: {progress_tracker.format_eta()}")
            stats_row.label(text=f"{progress_state.completed_items}/{progress_state.total_items}")
        
        # Cancel button
        progress_box.separator()
        cancel_row = progress_box.row()
        cancel_row.scale_y = 1.2
        cancel_row.operator("pexels.cancel", text="Cancel", icon='CANCEL')
    
    def _draw_results_section(self, layout, state):
        """Draw image results gallery."""
        results_box = layout.box()
        
        # Header with cache button
        header_row = results_box.row()
        header_row.label(text="Results", icon='IMAGE_DATA')
        
        # Cache all button (if not already caching)
        if not state.caching_in_progress:
            header_row.operator("pexels.cache_images", text="", icon='IMPORT')
        
        # Check if we have valid items
        if not state.items:
            results_box.label(text="No images loaded")
            return
        
        # Image preview grid with larger scale for better visibility
        try:
            results_box.template_icon_view(
                state, 
                "selected_icon", 
                show_labels=False, 
                scale=10.0, 
                scale_popup=5.0
            )
        except Exception as e:
            logger.warning(f"Error drawing icon view: {e}")
            results_box.label(text="Error displaying images")
    
    def _draw_selected_image_details(self, layout, state):
        """Draw details and import options for selected image."""
        selected_item = state.get_selected_item()
        if not selected_item:
            return
        
        # Combined details and import section
        detail_box = layout.box()
        
        # Header with favorite button
        header_row = detail_box.row()
        header_row.label(text="Selected Image", icon='IMAGE_DATA')
        
        # Favorite toggle button
        if ENHANCED_CACHING_AVAILABLE:
            is_fav = is_favorite(selected_item.item_id)
            fav_icon = 'SOLO_ON' if is_fav else 'SOLO_OFF'
            fav_op = header_row.operator(
                "pexels.toggle_favorite",
                text="",
                icon=fav_icon,
                emboss=True
            )
            fav_op.item_id = selected_item.item_id
        
        # Image info
        info_col = detail_box.column(align=True)
        info_col.label(text=f"ID: {selected_item.item_id}")
        info_col.label(text=f"Size: {selected_item.width} × {selected_item.height}")
        
        if selected_item.photographer:
            info_col.label(text=f"By: {selected_item.photographer}")
        
        # Show favorite status
        if ENHANCED_CACHING_AVAILABLE and is_favorite(selected_item.item_id):
            info_col.label(text="In Favorites", icon='SOLO_ON')
        
        # Import buttons
        detail_box.separator()
        
        import_col = detail_box.column(align=True)
        import_col.scale_y = 1.2
        
        # Primary import button (as plane)
        plane_op = import_col.operator(
            "pexels.import_image",
            text="Import as Plane",
            icon='MESH_PLANE'
        )
        plane_op.as_plane = True
        
        # Secondary import button (image only)
        image_op = import_col.operator(
            "pexels.import_image",
            text="Import Image Only",
            icon='IMAGE_DATA'
        )
        image_op.as_plane = False
        
        # Preview overlay button
        import_col.separator()
        import_col.operator("pexels.overlay_widget", text="Preview Overlay", icon='RESTRICT_VIEW_OFF')
    
    def _draw_no_results_message(self, layout):
        """Draw no results found message."""
        no_results_box = layout.box()
        no_results_box.label(text="No images found", icon='INFO')
        
        help_col = no_results_box.column(align=True)
        help_col.label(text="Try different keywords")
        help_col.label(text="or check your spelling")
    
    def _draw_help_section(self, layout):
        """Draw help and tips section."""
        help_box = layout.box()
        help_box.label(text="Getting Started", icon='QUESTION')
        
        help_col = help_box.column(align=True)
        help_col.label(text="Enter keywords above")
        help_col.label(text="e.g. 'nature', 'city', 'abstract'")
        help_col.separator()
        help_col.label(text="All images are free to use")
        help_col.label(text="commercially with attribution")


class PEXELS_PT_Settings(bpy.types.Panel):
    """Settings sub-panel for advanced options."""
    
    bl_label = "Settings"
    bl_idname = "PEXELS_PT_settings"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Pexels"
    bl_parent_id = "PEXELS_PT_panel"
    bl_options = {'DEFAULT_CLOSED'}
    
    def draw(self, context):
        """Draw the settings panel."""
        layout = self.layout
        prefs = get_preferences(context)
        
        # Handle missing preferences
        if prefs is None:
            layout.label(text="Preferences not available", icon='ERROR')
            return
        
        # Quick Settings
        self._draw_quick_settings(layout, prefs)
        
        # Cache Management
        self._draw_cache_management(layout)
        
        # Network Status
        self._draw_network_status(layout)
        
        # API Status
        self._draw_api_status(layout, prefs)
    
    def _draw_api_status(self, layout, prefs):
        """Draw API key status."""
        status_box = layout.box()
        status_box.label(text="API Status", icon='KEYFRAME_HLT')
        
        if prefs.api_key:
            status_box.label(text="API Key: Configured", icon='CHECKMARK')
        else:
            status_box.label(text="API Key: Not Set", icon='ERROR')
            status_box.operator("pexels.open_preferences", text="Set API Key")
    
    def _draw_quick_settings(self, layout, prefs):
        """Draw quick settings."""
        settings_box = layout.box()
        settings_box.label(text="Search Settings", icon='PREFERENCES')
        
        settings_col = settings_box.column(align=True)
        settings_col.prop(prefs, "max_results", text="Results per Page")
        settings_col.prop(prefs, "cache_thumbnails")
        
        settings_box.separator()
        settings_box.label(text="Import Settings", icon='IMPORT')
        settings_box.prop(prefs, "default_plane_size", text="Plane Size")
    
    def _draw_cache_management(self, layout):
        """Draw cache management controls."""
        cache_box = layout.box()
        cache_box.label(text="Cache", icon='FILE_CACHE')
        
        # Show cache stats if available
        try:
            from .cache_manager import cache_manager
            stats = cache_manager.get_cache_stats()
            
            stats_col = cache_box.column(align=True)
            stats_col.label(text=f"Memory: {stats['memory_items']} items")
            stats_col.label(text=f"Disk: {stats['disk_size_mb']:.1f} MB")
            
            if stats['hit_rate_percent'] > 0:
                stats_col.label(text=f"Hit rate: {stats['hit_rate_percent']:.1f}%")
            
            # Show search cache and favorites count if available
            if 'search_cache_items' in stats:
                stats_col.label(text=f"Cached searches: {stats['search_cache_items']}")
            
            # Show favorites count
            if ENHANCED_CACHING_AVAILABLE:
                try:
                    from .favorites_manager import favorites_manager
                    fav_count = favorites_manager.get_count()
                    stats_col.label(text=f"Favorites: {fav_count}")
                except Exception:
                    pass
        except Exception:
            pass
        
        cache_box.separator()
        cache_box.operator("pexels.clear_cache", text="Clear Cache", icon='TRASH')
    
    def _draw_network_status(self, layout):
        """Draw network status."""
        network_box = layout.box()
        network_box.label(text="Network", icon='WORLD')
        
        try:
            from .network_manager import network_manager
            
            if network_manager.is_online():
                network_box.label(text="Status: Online", icon='CHECKMARK')
            else:
                network_box.label(text="Status: Offline", icon='ERROR')
                network_box.label(text=network_manager.get_status_message())
        except Exception:
            network_box.label(text="Status: Unknown")


class PEXELS_PT_CachingProgress(bpy.types.Panel):
    """Caching progress panel - only visible during caching operations."""
    
    bl_label = "Caching Progress"
    bl_idname = "PEXELS_PT_caching_progress"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Pexels"
    bl_parent_id = "PEXELS_PT_panel"
    bl_options = set()  # No options - always expanded when visible
    
    @classmethod
    def poll(cls, context):
        """Only show panel when caching is in progress."""
        state = get_state(context)
        if state is None:
            return False
        return state.caching_in_progress
    
    def draw(self, context):
        """Draw the caching progress panel."""
        layout = self.layout
        state = get_state(context)
        
        if state is None:
            return
        
        # Main progress box
        progress_box = layout.box()
        
        # Header
        progress_box.label(text="Caching Images...", icon='IMPORT')
        
        # Progress bar with percentage
        self._draw_progress_bar(progress_box, state)
        
        # Current file being processed
        self._draw_current_file(progress_box, state)
        
        # Items counter
        self._draw_items_counter(progress_box, state)
        
        # Speed and ETA in one row
        stats_row = progress_box.row()
        self._draw_speed_indicator(stats_row, state)
        self._draw_eta(stats_row, state)
        
        # Error message if any
        if state.caching_error_message:
            self._draw_error_message(progress_box, state)
        
        # Cancel button
        progress_box.separator()
        cancel_row = progress_box.row()
        cancel_row.scale_y = 1.2
        cancel_row.operator("pexels.cancel_caching", text="Cancel", icon='CANCEL')
    
    def _draw_progress_bar(self, layout, state):
        """Draw the visual progress bar."""
        # Visual progress bar using prop with slider
        progress_bar_row = layout.row()
        progress_bar_row.prop(
            state,
            "caching_progress",
            text=f"{state.caching_progress:.0f}%",
            slider=True
        )
    
    def _draw_current_file(self, layout, state):
        """Draw the current file being processed."""
        if state.caching_current_file:
            file_row = layout.row()
            truncated_name = truncate_filename(state.caching_current_file, max_length=30)
            file_row.label(text=truncated_name, icon='FILE_IMAGE')
    
    def _draw_items_counter(self, layout, state):
        """Draw the items processed counter."""
        items_row = layout.row()
        items_text = format_progress_items(state.caching_items_done, state.caching_items_total)
        items_row.label(text=items_text, icon='SEQUENCE')
    
    def _draw_speed_indicator(self, layout, state):
        """Draw the download speed indicator."""
        speed_text = format_speed(state.caching_speed_bytes)
        layout.label(text=speed_text)
    
    def _draw_eta(self, layout, state):
        """Draw the estimated time remaining."""
        if state.caching_eta_seconds > 0:
            eta_text = format_eta(state.caching_eta_seconds)
        else:
            eta_text = "..."
        layout.label(text=f"ETA: {eta_text}")
    
    def _draw_error_message(self, layout, state):
        """Draw error message if present."""
        error_box = layout.box()
        error_box.alert = True
        error_box.label(text="Error:", icon='ERROR')
        
        # Split long error messages
        error_msg = state.caching_error_message
        words = error_msg.split()
        line = ""
        for word in words:
            if len(line) + len(word) > 30:
                error_box.label(text=line)
                line = word
            else:
                line = f"{line} {word}".strip()
        if line:
            error_box.label(text=line)


class PEXELS_PT_Favorites(bpy.types.Panel):
    """Favorites panel for quick access to saved images."""
    
    bl_label = "Favorites"
    bl_idname = "PEXELS_PT_favorites"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Pexels"
    bl_parent_id = "PEXELS_PT_panel"
    bl_options = {'DEFAULT_CLOSED'}
    
    @classmethod
    def poll(cls, context):
        """Only show if enhanced caching is available."""
        return ENHANCED_CACHING_AVAILABLE
    
    def draw(self, context):
        """Draw the favorites panel."""
        layout = self.layout
        
        try:
            from .favorites_manager import favorites_manager
            
            favorites = favorites_manager.get_all_favorites()
            
            if not favorites:
                layout.label(text="No favorites yet", icon='INFO')
                layout.label(text="Click the star icon on")
                layout.label(text="any image to add it")
                return
            
            # Show favorites count
            layout.label(text=f"{len(favorites)} favorites", icon='SOLO_ON')
            
            # List favorites (show most recent first, limit to 10)
            recent_favorites = sorted(
                favorites,
                key=lambda f: f.added_at,
                reverse=True
            )[:10]
            
            for fav in recent_favorites:
                fav_row = layout.row(align=True)
                
                # Photographer name (truncated)
                name = fav.photographer[:15] + "..." if len(fav.photographer) > 15 else fav.photographer
                fav_row.label(text=name)
                
                # Import button
                import_op = fav_row.operator(
                    "pexels.import_favorite",
                    text="",
                    icon='IMPORT'
                )
                import_op.pexels_id = fav.pexels_id
                
                # Remove button
                remove_op = fav_row.operator(
                    "pexels.toggle_favorite",
                    text="",
                    icon='X'
                )
                remove_op.item_id = fav.pexels_id
            
            if len(favorites) > 10:
                layout.label(text=f"... and {len(favorites) - 10} more")
                
        except Exception as e:
            logger.warning(f"Error drawing favorites: {e}")
            layout.label(text="Error loading favorites")


class PEXELS_OT_ClearError(bpy.types.Operator):
    """Clear the last error message"""
    
    bl_idname = "pexels.clear_error"
    bl_label = "Clear Error"
    bl_description = "Dismiss the error message"
    bl_options = {'INTERNAL'}
    
    def execute(self, context):
        state = get_state(context)
        if state:
            state.last_error_message = ""
            state.operation_status = 'IDLE'
        return {'FINISHED'}


# UI classes for registration
ui_classes = (
    PEXELS_PT_Panel,
    PEXELS_PT_Settings,
    PEXELS_PT_CachingProgress,
    PEXELS_PT_Favorites,
    PEXELS_OT_ClearError,
)
