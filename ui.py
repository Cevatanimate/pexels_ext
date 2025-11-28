# SPDX-License-Identifier: GPL-3.0-or-later
"""
User interface panels and components for the Pexels addon.

Provides panels for searching, browsing, and importing images from Pexels
with proper null checks, error state display, and progress indicators.
"""

import bpy

from .progress_tracker import progress_tracker, ProgressStatus
from .logger import logger
from .utils import format_eta, format_speed, truncate_filename, format_progress_items


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
        
        # Draw main interface sections
        self._draw_search_section(layout, state, prefs)
        
        # Draw progress/loading indicator
        if state.is_loading:
            self._draw_progress_indicator(layout)
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
    
    def _draw_error_state(self, layout, message: str):
        """Draw error state message."""
        error_box = layout.box()
        error_box.alert = True
        error_box.label(text="❌ Error", icon='ERROR')
        
        # Split long messages into multiple lines
        words = message.split()
        line = ""
        for word in words:
            if len(line) + len(word) > 40:
                error_box.label(text=line)
                line = word
            else:
                line = f"{line} {word}".strip()
        if line:
            error_box.label(text=line)
    
    def _draw_api_key_warning(self, layout):
        """Draw API key requirement warning."""
        warning_box = layout.box()
        warning_box.label(text="⚠ API Key Required", icon='ERROR')
        
        info_col = warning_box.column(align=True)
        info_col.label(text="Set your Pexels API key in")
        info_col.label(text="Add-on Preferences first")
        
        warning_box.operator("pexels.open_preferences", text="Open Preferences", icon='PREFERENCES')
    
    def _draw_search_section(self, layout, state, prefs):
        """Draw search interface section."""
        search_box = layout.box()
        search_box.label(text="🔍 Search Images", icon='VIEWZOOM')
        
        # Search input and button
        search_col = search_box.column(align=True)
        search_col.prop(state, "query", text="Keywords")
        
        # Search and cancel buttons
        row = search_col.row(align=True)
        if state.is_loading:
            row.operator("pexels.cancel", text="Cancel", icon='CANCEL')
        else:
            row.operator("pexels.search", text="Search", icon='VIEWZOOM')

        # Overlay preview launcher
        overlay_row = layout.row(align=True)
        overlay_row.operator("pexels.overlay_widget", text="Preview Overlay", icon='IMAGE_DATA')
        
        # Results info and pagination
        if state.total_results > 0:
            self._draw_results_info(search_box, state)
            self._draw_pagination_controls(search_box, state)
            self._draw_settings_controls(search_box, prefs)

        # Rate limit indicator
        self._draw_rate_limit_indicator(search_box, state)
    
    def _draw_results_info(self, layout, state):
        """Draw results information."""
        info_row = layout.row(align=True)
        results_text = f"📊 Results: {len(state.items)} / {state.total_results}"
        info_row.label(text=results_text)
    
    def _draw_pagination_controls(self, layout, state):
        """Draw pagination navigation controls."""
        nav_row = layout.row(align=True)
        nav_row.label(text=f"Page {state.page}")
        
        # Previous page button (only show if not on first page)
        if state.page > 1:
            prev_op = nav_row.operator("pexels.page", text="← Prev", icon='TRIA_LEFT')
            prev_op.direction = 'PREV'
        else:
            nav_row.label(text="")  # Empty space for alignment
        
        # Next page button
        next_op = nav_row.operator("pexels.page", text="Next →", icon='TRIA_RIGHT')
        next_op.direction = 'NEXT'
    
    def _draw_settings_controls(self, layout, prefs):
        """Draw quick settings controls."""
        settings_row = layout.row(align=True)
        settings_row.prop(prefs, "max_results", text="Per Page")
        settings_row.operator("pexels.clear_cache", text="", icon='FILE_REFRESH')

    def _draw_rate_limit_indicator(self, layout, state):
        """Draw rate limit status indicator."""
        # Only show if we have rate limit data
        if state.rate_limit <= 0:
            return

        rate_row = layout.row(align=True)

        # Calculate usage percentage
        usage_percent = ((state.rate_limit - state.rate_remaining) / state.rate_limit) * 100

        # Choose icon and color based on remaining requests
        if state.rate_remaining == 0:
            icon = 'ERROR'
            status_text = "Rate limit exceeded"
        elif usage_percent >= 90:
            icon = 'CANCEL'
            status_text = f"⚠ {state.rate_remaining} requests left"
        elif usage_percent >= 75:
            icon = 'INFO'
            status_text = f"📊 {state.rate_remaining} requests left"
        else:
            icon = 'NONE'
            status_text = f"✅ {state.rate_remaining}/{state.rate_limit} requests"

        rate_row.label(text=status_text, icon=icon)
    
    def _draw_progress_indicator(self, layout):
        """Draw progress indicator with cancel button."""
        progress_box = layout.box()
        
        # Get progress state
        progress_state = progress_tracker.get_progress()
        
        # Status icon and message
        if progress_state.status == ProgressStatus.ACTIVE:
            progress_box.label(text="🔄 Loading...", icon='FILE_REFRESH')
        elif progress_state.status == ProgressStatus.ERROR:
            progress_box.label(text="❌ Error", icon='ERROR')
        elif progress_state.status == ProgressStatus.CANCELLED:
            progress_box.label(text="⏹ Cancelled", icon='CANCEL')
        else:
            progress_box.label(text="🔄 Processing...", icon='FILE_REFRESH')
        
        # Current item
        if progress_state.current_item:
            progress_box.label(text=progress_state.current_item)
        
        # Progress bar
        if progress_state.total_items > 0:
            progress_row = progress_box.row()
            progress_row.prop(
                bpy.context.scene.pexels_state,
                "loading_progress",
                text=f"{progress_state.percentage:.0f}%"
            )
            
            # Update the property value
            try:
                bpy.context.scene.pexels_state.loading_progress = progress_state.percentage
            except Exception:
                pass
        
        # ETA and stats
        stats_row = progress_box.row()
        stats_row.label(text=f"ETA: {progress_tracker.format_eta()}")
        if progress_state.total_items > 0:
            stats_row.label(text=f"{progress_state.completed_items}/{progress_state.total_items}")
        
        # Cancel button
        progress_box.operator("pexels.cancel", text="Cancel", icon='CANCEL')
    
    def _draw_results_section(self, layout, state):
        """Draw image results gallery."""
        results_box = layout.box()
        results_box.label(text="📷 Image Gallery", icon='IMAGE_DATA')
        
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
        
        # Image details section
        self._draw_image_details(layout, selected_item)
        
        # Import options section
        self._draw_import_options(layout, selected_item)
    
    def _draw_image_details(self, layout, item):
        """Draw selected image details."""
        detail_box = layout.box()
        detail_box.label(text="📋 Image Details", icon='INFO')
        
        info_col = detail_box.column(align=True)
        info_col.label(text=f"ID: {item.item_id}")
        info_col.label(text=f"Size: {item.width} × {item.height} pixels")
        
        if item.photographer:
            info_col.label(text=f"📸 Photo by: {item.photographer}")
    
    def _draw_import_options(self, layout, item):
        """Draw import options for selected image."""
        import_box = layout.box()
        import_box.label(text="⬇ Import Options", icon='IMPORT')
        
        # Primary import button (as plane)
        plane_op = import_box.operator(
            "pexels.import_image", 
            text="Import as Plane", 
            icon='MESH_PLANE'
        )
        plane_op.as_plane = True
        
        # Secondary import button (image only)
        image_op = import_box.operator(
            "pexels.import_image", 
            text="Import Image Only", 
            icon='IMAGE_DATA'
        )
        image_op.as_plane = False
    
    def _draw_no_results_message(self, layout):
        """Draw no results found message."""
        no_results_box = layout.box()
        no_results_box.label(text="😔 No images found", icon='ERROR')
        no_results_box.label(text="Try different keywords")
    
    def _draw_help_section(self, layout):
        """Draw help and tips section."""
        help_box = layout.box()
        help_box.label(text="💡 Tips:", icon='QUESTION')
        
        help_col = help_box.column(align=True)
        help_col.label(text="• Enter keywords like 'nature'")
        help_col.label(text="• Use specific terms for better results")
        help_col.label(text="• All images are free to use")
        help_col.label(text="• Try different search terms")


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
        
        # API Status
        self._draw_api_status(layout, prefs)
        
        # Quick Settings
        self._draw_quick_settings(layout, prefs)
        
        # Cache Management
        self._draw_cache_management(layout)
        
        # Network Status
        self._draw_network_status(layout)
    
    def _draw_api_status(self, layout, prefs):
        """Draw API key status."""
        status_box = layout.box()
        
        if prefs.api_key:
            status_box.label(text="✅ API Key Configured", icon='NONE')
        else:
            status_box.label(text="❌ No API Key", icon='NONE')
            status_box.operator("pexels.open_preferences", text="Set API Key")
    
    def _draw_quick_settings(self, layout, prefs):
        """Draw quick settings."""
        settings_box = layout.box()
        settings_box.label(text="⚙ Quick Settings", icon='PREFERENCES')
        
        settings_col = settings_box.column(align=True)
        settings_col.prop(prefs, "max_results")
        settings_col.prop(prefs, "cache_thumbnails")
        settings_col.prop(prefs, "default_plane_size")
    
    def _draw_cache_management(self, layout):
        """Draw cache management controls."""
        cache_box = layout.box()
        cache_box.label(text="🗂 Cache Management", icon='FILE_CACHE')
        
        # Show cache stats if available
        try:
            from .cache_manager import cache_manager
            stats = cache_manager.get_cache_stats()
            
            stats_col = cache_box.column(align=True)
            stats_col.label(text=f"Memory: {stats['memory_items']} items")
            stats_col.label(text=f"Disk: {stats['disk_size_mb']:.1f} MB")
            stats_col.label(text=f"Hit rate: {stats['hit_rate_percent']:.1f}%")
        except Exception:
            pass
        
        cache_box.operator("pexels.clear_cache", text="Clear Cache", icon='TRASH')
        cache_box.label(text="Clears downloaded thumbnails", icon='INFO')
    
    def _draw_network_status(self, layout):
        """Draw network status."""
        network_box = layout.box()
        network_box.label(text="🌐 Network Status", icon='WORLD')
        
        try:
            from .network_manager import network_manager
            status_msg = network_manager.get_status_message()
            
            if network_manager.is_online():
                network_box.label(text=f"✅ {status_msg}")
            else:
                network_box.label(text=f"❌ {status_msg}")
        except Exception:
            network_box.label(text="Status unknown")


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
        
        # Progress bar with percentage
        self._draw_progress_bar(progress_box, state)
        
        # Current file being processed
        self._draw_current_file(progress_box, state)
        
        # Items counter
        self._draw_items_counter(progress_box, state)
        
        # Speed indicator
        self._draw_speed_indicator(progress_box, state)
        
        # ETA display
        self._draw_eta(progress_box, state)
        
        # Error message if any
        if state.caching_error_message:
            self._draw_error_message(progress_box, state)
        
        # Cancel button
        layout.separator()
        cancel_row = layout.row()
        cancel_row.scale_y = 1.2
        cancel_row.operator("pexels.cancel_caching", text="Cancel Caching", icon='CANCEL')
    
    def _draw_progress_bar(self, layout, state):
        """Draw the visual progress bar."""
        # Progress percentage header
        progress_row = layout.row()
        progress_row.label(text=f"Progress: {state.caching_progress:.1f}%")
        
        # Visual progress bar using prop with slider
        progress_bar_row = layout.row()
        progress_bar_row.prop(
            state,
            "caching_progress",
            text="",
            slider=True
        )
    
    def _draw_current_file(self, layout, state):
        """Draw the current file being processed."""
        if state.caching_current_file:
            file_row = layout.row()
            truncated_name = truncate_filename(state.caching_current_file, max_length=35)
            file_row.label(text=f"Current: {truncated_name}", icon='FILE_IMAGE')
    
    def _draw_items_counter(self, layout, state):
        """Draw the items processed counter."""
        items_row = layout.row()
        items_text = format_progress_items(state.caching_items_done, state.caching_items_total)
        items_row.label(text=f"Progress: {items_text}", icon='SEQUENCE')
    
    def _draw_speed_indicator(self, layout, state):
        """Draw the download speed indicator."""
        speed_row = layout.row()
        speed_text = format_speed(state.caching_speed_bytes)
        speed_row.label(text=f"Speed: {speed_text}", icon='SORTTIME')
    
    def _draw_eta(self, layout, state):
        """Draw the estimated time remaining."""
        eta_row = layout.row()
        if state.caching_eta_seconds > 0:
            eta_text = format_eta(state.caching_eta_seconds)
        else:
            eta_text = "Calculating..."
        eta_row.label(text=f"ETA: {eta_text}", icon='TIME')
    
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
            if len(line) + len(word) > 35:
                error_box.label(text=line)
                line = word
            else:
                line = f"{line} {word}".strip()
        if line:
            error_box.label(text=line)


# UI classes for registration
ui_classes = (
    PEXELS_PT_Panel,
    PEXELS_PT_Settings,
    PEXELS_PT_CachingProgress,
)
