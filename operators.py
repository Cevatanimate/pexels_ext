# SPDX-License-Identifier: GPL-3.0-or-later
"""
Blender operators for Pexels image search and import functionality
"""

import bpy
from .api import search_images, download_image, PexelsAPIError, USER_AGENT
from .utils import load_image_from_url, create_plane_with_image, write_temp_file, preview_manager


class PEXELS_OT_Search(bpy.types.Operator):
    """Search for images on Pexels"""
    
    bl_idname = "pexels.search"
    bl_label = "Search Pexels"
    bl_description = "Search for images on Pexels using the entered keywords"
    bl_options = {'REGISTER', 'INTERNAL'}
    
    def execute(self, context):
        """Execute the search operation"""
        scene = context.scene
        state = scene.pexels_state
        prefs = context.preferences.addons[__package__].preferences
        
        # Validate inputs
        if not prefs.api_key:
            self.report({'ERROR'}, "Set Pexels API key in Add-on Preferences.")
            return {'CANCELLED'}
        
        if not state.query.strip():
            self.report({'WARNING'}, "Enter a search keyword.")
            return {'CANCELLED'}
        
        # Perform search
        return self._perform_search(context, state, prefs)
    
    def _perform_search(self, context, state, prefs):
        """Perform the actual search operation"""
        state.is_loading = True
        
        try:
            # Clear previous results
            state.clear_results()
            preview_manager.ensure_previews()
            
            # Search for images
            results = search_images(
                api_key=prefs.api_key,
                query=state.query,
                page=state.page,
                per_page=prefs.max_results
            )
            
            # Process results
            self._process_search_results(state, results, prefs.cache_thumbnails)
            
            # Set default selection
            if state.items:
                state.selected_icon = str(state.items[0].item_id)
            
            # Report success
            photos_count = len(state.items)
            total_count = state.total_results
            self.report({'INFO'}, f"Found {photos_count} images (Total: {total_count})")
            
            return {'FINISHED'}
            
        except PexelsAPIError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"Search failed: {e}")
            return {'CANCELLED'}
        finally:
            state.is_loading = False
    
    def _process_search_results(self, state, results, cache_thumbnails):
        """Process and store search results"""
        state.total_results = int(results.get("total_results", 0))
        photos = results.get("photos", []) or []
        
        for photo_data in photos:
            item = state.items.add()
            self._populate_item_data(item, photo_data)
            
            # Load thumbnail preview if caching enabled
            if cache_thumbnails and item.thumb_url:
                self._load_thumbnail_preview(item)
    
    def _populate_item_data(self, item, photo_data):
        """Populate PEXELS_Item with data from API response"""
        item.item_id = int(photo_data.get("id", 0))
        item.photographer = photo_data.get("photographer", "")
        item.width = int(photo_data.get("width", 0) or 0)
        item.height = int(photo_data.get("height", 0) or 0)
        
        # Extract image URLs
        src = photo_data.get("src", {}) or {}
        item.thumb_url = (
            src.get("medium") or 
            src.get("small") or 
            src.get("tiny") or ""
        )
        item.full_url = (
            src.get("large2x") or 
            src.get("original") or 
            src.get("large") or ""
        )
    
    def _load_thumbnail_preview(self, item):
        """Load thumbnail preview for an item"""
        try:
            thumb_data = download_image(item.thumb_url, headers={"User-Agent": USER_AGENT})
            thumb_path = write_temp_file(f"pexels_{item.item_id}_th.jpg", thumb_data)
            preview_manager.load_preview(str(item.item_id), thumb_path)
        except Exception:
            # Ignore thumbnail loading failures
            pass


class PEXELS_OT_Page(bpy.types.Operator):
    """Navigate between pages of search results"""
    
    bl_idname = "pexels.page"
    bl_label = "Change Page"
    bl_description = "Navigate to the previous or next page of search results"
    bl_options = {'INTERNAL'}
    
    direction: bpy.props.EnumProperty(
        items=[
            ('PREV', 'Previous', 'Previous page'),
            ('NEXT', 'Next', 'Next page')
        ],
        name="Direction",
        description="Navigation direction"
    )
    
    def execute(self, context):
        """Execute page navigation"""
        state = context.scene.pexels_state
        
        if self.direction == 'PREV' and state.page > 1:
            state.page -= 1
        elif self.direction == 'NEXT':
            state.page += 1
        
        # Trigger new search with updated page
        return bpy.ops.pexels.search('INVOKE_DEFAULT')


class PEXELS_OT_Import(bpy.types.Operator):
    """Import selected Pexels image into Blender"""
    
    bl_idname = "pexels.import_image"
    bl_label = "Import Selected Image"
    bl_description = "Import the selected image into Blender"
    bl_options = {'REGISTER', 'UNDO'}
    
    as_plane: bpy.props.BoolProperty(
        name="Import as Plane",
        description="Create a plane object with the image texture applied",
        default=True
    )
    
    plane_size: bpy.props.FloatProperty(
        name="Plane Size",
        description="Height of the created plane in Blender units",
        default=2.0,
        min=0.01,
        max=100.0
    )
    
    def execute(self, context):
        """Execute image import"""
        state = context.scene.pexels_state
        selected_item = state.get_selected_item()
        
        if not selected_item:
            self.report({'WARNING'}, "No image selected.")
            return {'CANCELLED'}
        
        if not selected_item.full_url:
            self.report({'WARNING'}, "No image URL available for selected item.")
            return {'CANCELLED'}
        
        try:
            return self._import_image(context, selected_item)
        except Exception as e:
            self.report({'ERROR'}, f"Import failed: {e}")
            return {'CANCELLED'}
    
    def _import_image(self, context, item):
        """Import the image into Blender"""
        # Load image from URL
        image = load_image_from_url(item.full_url)
        image.name = f"Pexels_{item.item_id}"
        
        # Create plane if requested
        if self.as_plane:
            plane_obj = create_plane_with_image(image, size=self.plane_size)
            if plane_obj:
                # Select and make active
                plane_obj.select_set(True)
                context.view_layer.objects.active = plane_obj
        
        # Report success
        photographer = item.photographer or "Unknown"
        self.report({'INFO'}, f"Imported: {photographer}'s image (ID: {item.item_id})")
        
        return {'FINISHED'}
    
    def invoke(self, context, event):
        """Invoke operator with current preferences"""
        prefs = context.preferences.addons[__package__].preferences
        self.plane_size = prefs.default_plane_size
        return self.execute(context)


class PEXELS_OT_ClearCache(bpy.types.Operator):
    """Clear cached thumbnails and temporary files"""
    
    bl_idname = "pexels.clear_cache"
    bl_label = "Clear Cache"
    bl_description = "Clear cached thumbnails and temporary files"
    bl_options = {'REGISTER'}
    
    def execute(self, context):
        """Execute cache clearing"""
        try:
            # Clear preview manager
            preview_manager.clear_previews()
            
            # Clear state
            state = context.scene.pexels_state
            state.clear_results()
            
            self.report({'INFO'}, "Cache cleared successfully")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to clear cache: {e}")
            return {'CANCELLED'}


class PEXELS_OT_OpenPreferences(bpy.types.Operator):
    """Open addon preferences"""
    
    bl_idname = "pexels.open_preferences"
    bl_label = "Open Preferences"
    bl_description = "Open the Pexels addon preferences"
    bl_options = {'REGISTER'}
    
    def execute(self, context):
        """Execute preferences opening"""
        bpy.ops.preferences.addon_show(module=__package__)
        return {'FINISHED'}


# Operator classes for registration
operator_classes = (
    PEXELS_OT_Search,
    PEXELS_OT_Page,
    PEXELS_OT_Import,
    PEXELS_OT_ClearCache,
    PEXELS_OT_OpenPreferences,
)
