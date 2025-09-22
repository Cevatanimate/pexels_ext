# SPDX-License-Identifier: GPL-3.0-or-later
"""
Blender property groups and data structures
"""

import bpy
from .utils import preview_manager


class PEXELS_Item(bpy.types.PropertyGroup):
    """Property group for storing individual Pexels image data"""
    
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


def pexels_enum_items(self, context):
    """
    EnumProperty items callback for template_icon_view
    
    Returns:
        list: List of enum items for image selection
    """
    items = []
    state = context.scene.pexels_state
    
    for i, item in enumerate(state.items):
        image_id = str(item.item_id)
        icon_id = preview_manager.get_preview_icon(image_id)
        
        if icon_id:
            # Format: (identifier, name, description, icon, number)
            items.append((
                image_id,
                f"{item.item_id}",
                item.photographer or "Unknown photographer",
                icon_id,
                i
            ))
    
    return items


class PEXELS_State(bpy.types.PropertyGroup):
    """Main state property group for the Pexels addon"""

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
    
    # Search results collection
    items: bpy.props.CollectionProperty(
        type=PEXELS_Item,
        name="Search Results",
        description="Collection of found images"
    )
    
    # Selected preview (Pexels ID as string)
    selected_icon: bpy.props.EnumProperty(
        name="Selected Image",
        description="Currently selected image from search results",
        items=pexels_enum_items
    )
    
    def clear_results(self):
        """Clear all search results and reset state"""
        self.items.clear()
        self.total_results = 0
        preview_manager.clear_previews()
    
    def get_selected_item(self):
        """
        Get the currently selected PEXELS_Item
        
        Returns:
            PEXELS_Item or None: Selected item or None if no selection
        """
        if not self.selected_icon:
            return None
        
        try:
            selected_id = int(self.selected_icon)
            return next((item for item in self.items if item.item_id == selected_id), None)
        except ValueError:
            return None


class PEXELS_AddonPrefs(bpy.types.AddonPreferences):
    """Addon preferences for API configuration and settings"""
    
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
        """Draw the preferences panel"""
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
        """Draw API configuration section"""
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
        """Draw search settings section"""
        settings_box = layout.box()
        settings_box.label(text="🔍 Search Settings", icon='VIEWZOOM')
        
        settings_col = settings_box.column(align=True)
        settings_col.prop(self, "max_results")
        settings_col.prop(self, "cache_thumbnails")
    
    def _draw_import_section(self, layout):
        """Draw import settings section"""
        import_box = layout.box()
        import_box.label(text="⬇ Import Settings", icon='IMPORT')
        import_box.prop(self, "default_plane_size")
    
    def _draw_usage_section(self, layout):
        """Draw usage instructions section"""
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
