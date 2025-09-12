# SPDX-License-Identifier: GPL-3.0-or-later
"""
User interface panels and components for the Pexels addon
"""

import bpy


class PEXELS_PT_Panel(bpy.types.Panel):
    """Main Pexels panel in the 3D View N-Panel"""
    
    bl_label = "Pexels Image Search"
    bl_idname = "PEXELS_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Pexels"
    
    def draw(self, context):
        """Draw the main panel"""
        layout = self.layout
        state = context.scene.pexels_state
        prefs = context.preferences.addons[__package__].preferences
        
        # Check if API key is configured
        if not prefs.api_key:
            self._draw_api_key_warning(layout)
            return
        
        # Draw main interface sections
        self._draw_search_section(layout, state, prefs)
        
        if state.is_loading:
            self._draw_loading_indicator(layout)
            return
        
        if state.items:
            self._draw_results_section(layout, state)
            self._draw_selected_image_details(layout, state)
        elif state.query:
            self._draw_no_results_message(layout)
        else:
            self._draw_help_section(layout)
    
    def _draw_api_key_warning(self, layout):
        """Draw API key requirement warning"""
        warning_box = layout.box()
        warning_box.label(text="⚠ API Key Required", icon='ERROR')
        
        info_col = warning_box.column(align=True)
        info_col.label(text="Set your Pexels API key in")
        info_col.label(text="Add-on Preferences first")
        
        warning_box.operator("pexels.open_preferences", text="Open Preferences", icon='PREFERENCES')
    
    def _draw_search_section(self, layout, state, prefs):
        """Draw search interface section"""
        search_box = layout.box()
        search_box.label(text="🔍 Search Images", icon='VIEWZOOM')
        
        # Search input and button
        search_col = search_box.column(align=True)
        search_col.prop(state, "query", text="Keywords")
        search_col.operator("pexels.search", text="Search", icon='VIEWZOOM')
        
        # Results info and pagination
        if state.total_results > 0:
            self._draw_results_info(search_box, state)
            self._draw_pagination_controls(search_box, state)
            self._draw_settings_controls(search_box, prefs)
    
    def _draw_results_info(self, layout, state):
        """Draw results information"""
        info_row = layout.row(align=True)
        results_text = f"📊 Results: {len(state.items)} / {state.total_results}"
        info_row.label(text=results_text)
    
    def _draw_pagination_controls(self, layout, state):
        """Draw pagination navigation controls"""
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
        """Draw quick settings controls"""
        settings_row = layout.row(align=True)
        settings_row.prop(prefs, "max_results", text="Per Page")
        settings_row.operator("pexels.clear_cache", text="", icon='FILE_REFRESH')
    
    def _draw_loading_indicator(self, layout):
        """Draw loading indicator"""
        loading_box = layout.box()
        loading_box.label(text="🔄 Loading images...", icon='FILE_REFRESH')
    
    def _draw_results_section(self, layout, state):
        """Draw image results gallery"""
        results_box = layout.box()
        results_box.label(text="📷 Image Gallery", icon='IMAGE_DATA')
        
        # Image preview grid with larger scale for better visibility
        results_box.template_icon_view(
            state, 
            "selected_icon", 
            show_labels=False, 
            scale=10.0, 
            scale_popup=5.0
        )
    
    def _draw_selected_image_details(self, layout, state):
        """Draw details and import options for selected image"""
        selected_item = state.get_selected_item()
        if not selected_item:
            return
        
        # Image details section
        self._draw_image_details(layout, selected_item)
        
        # Import options section
        self._draw_import_options(layout, selected_item)

        # Overlay preview launcher
        overlay_row = layout.row(align=True)
        overlay_row.operator("pexels.overlay_widget", text="Preview Overlay", icon='IMAGE_DATA')
    
    def _draw_image_details(self, layout, item):
        """Draw selected image details"""
        detail_box = layout.box()
        detail_box.label(text="📋 Image Details", icon='INFO')
        
        info_col = detail_box.column(align=True)
        info_col.label(text=f"ID: {item.item_id}")
        info_col.label(text=f"Size: {item.width} × {item.height} pixels")
        
        if item.photographer:
            info_col.label(text=f"📸 Photo by: {item.photographer}")
    
    def _draw_import_options(self, layout, item):
        """Draw import options for selected image"""
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
        """Draw no results found message"""
        no_results_box = layout.box()
        no_results_box.label(text="😔 No images found", icon='ERROR')
        no_results_box.label(text="Try different keywords")
    
    def _draw_help_section(self, layout):
        """Draw help and tips section"""
        help_box = layout.box()
        help_box.label(text="💡 Tips:", icon='QUESTION')
        
        help_col = help_box.column(align=True)
        help_col.label(text="• Enter keywords like 'nature'")
        help_col.label(text="• Use specific terms for better results")
        help_col.label(text="• All images are free to use")
        help_col.label(text="• Try different search terms")


class PEXELS_PT_Settings(bpy.types.Panel):
    """Settings sub-panel for advanced options"""
    
    bl_label = "Settings"
    bl_idname = "PEXELS_PT_settings"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Pexels"
    bl_parent_id = "PEXELS_PT_panel"
    bl_options = {'DEFAULT_CLOSED'}
    
    def draw(self, context):
        """Draw the settings panel"""
        layout = self.layout
        prefs = context.preferences.addons[__package__].preferences
        
        # API Status
        self._draw_api_status(layout, prefs)
        
        # Quick Settings
        self._draw_quick_settings(layout, prefs)
        
        # Cache Management
        self._draw_cache_management(layout)
    
    def _draw_api_status(self, layout, prefs):
        """Draw API key status"""
        status_box = layout.box()
        
        if prefs.api_key:
            status_box.label(text="✅ API Key Configured", icon='CHECKMARK')
        else:
            status_box.label(text="❌ No API Key", icon='CANCEL')
            status_box.operator("pexels.open_preferences", text="Set API Key")
    
    def _draw_quick_settings(self, layout, prefs):
        """Draw quick settings"""
        settings_box = layout.box()
        settings_box.label(text="⚙ Quick Settings", icon='PREFERENCES')
        
        settings_col = settings_box.column(align=True)
        settings_col.prop(prefs, "max_results")
        settings_col.prop(prefs, "cache_thumbnails")
        settings_col.prop(prefs, "default_plane_size")
    
    def _draw_cache_management(self, layout):
        """Draw cache management controls"""
        cache_box = layout.box()
        cache_box.label(text="🗂 Cache Management", icon='FILE_CACHE')
        
        cache_box.operator("pexels.clear_cache", text="Clear Cache", icon='TRASH')
        cache_box.label(text="Clears downloaded thumbnails", icon='INFO')


# UI classes for registration
ui_classes = (
    PEXELS_PT_Panel,
    PEXELS_PT_Settings,
)
