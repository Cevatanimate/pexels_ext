# SPDX-License-Identifier: GPL-3.0-or-later
"""
Blender operators for Pexels image search and import functionality
"""

import bpy
from .api import search_images, download_image, PexelsAPIError, USER_AGENT
from .utils import load_image_from_url, create_plane_with_image, write_temp_file, preview_manager
import gpu
from gpu_extras.batch import batch_for_shader


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
            results, response_headers = search_images(
                api_key=prefs.api_key,
                query=state.query,
                page=state.page,
                per_page=prefs.max_results
            )

            # Process results
            self._process_search_results(state, results, prefs.cache_thumbnails)

            # Store rate limit information
            self._update_rate_limits(state, response_headers)

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

    def _update_rate_limits(self, state, headers):
        """Update rate limit information from response headers"""
        try:
            # Extract rate limit headers
            limit_str = headers.get('X-Ratelimit-Limit')
            remaining_str = headers.get('X-Ratelimit-Remaining')
            reset_str = headers.get('X-Ratelimit-Reset')

            # Update state properties if headers are present
            if limit_str:
                state.rate_limit = int(limit_str)
            if remaining_str:
                state.rate_remaining = int(remaining_str)
            if reset_str:
                state.rate_reset_timestamp = int(reset_str)
        except (ValueError, TypeError):
            # Ignore invalid header values
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


class PEXELS_UI_ImageWidget:
    def __init__(self, x, y, width, height, image):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.image = image
        self._bg_color = (0.08, 0.08, 0.08, 0.85)
        self._batch_bg = None
        self._shader_bg = None
        # Interaction
        self._resize_margin = 8.0
        self._min_width = 120.0
        self._min_height = 90.0
        self._hover_edges = {"left": False, "right": False, "top": False, "bottom": False}
        self._hover_inside = False
        self._is_dragging = False
        self._drag_mode = None

    def _build_bg(self, area_h):
        y_flip = area_h - self.y
        verts = (
            (self.x, self.y),
            (self.x + self.width, self.y),
            (self.x + self.width, self.y + self.height),
            (self.x, self.y + self.height),
        )
        indices = ((0, 1, 2), (0, 2, 3))
        shader_name = "UNIFORM_COLOR" if bpy.app.version >= (4, 0, 0) else "2D_UNIFORM_COLOR"
        self._shader_bg = gpu.shader.from_builtin(shader_name)
        self._batch_bg = batch_for_shader(self._shader_bg, "TRIS", {"pos": verts}, indices=indices)

    def contains_point(self, px, py):
        return (self.x <= px <= self.x + self.width) and (self.y <= py <= self.y + self.height)

    def hit_test_edges(self, px, py):
        # Returns dict of which edges are hovered: left, right, top, bottom
        m = self._resize_margin
        within_x = self.x <= px <= self.x + self.width
        within_y = self.y <= py <= self.y + self.height
        left = abs(px - self.x) <= m and within_y
        right = abs(px - (self.x + self.width)) <= m and within_y
        bottom = abs(py - self.y) <= m and within_x
        top = abs(py - (self.y + self.height)) <= m and within_x
        return {"left": left, "right": right, "top": top, "bottom": bottom}

    def clamp_size(self):
        # Ensure widget size doesn't go below minimums
        if self.width < self._min_width:
            self.width = self._min_width
        if self.height < self._min_height:
            self.height = self._min_height

    def update(self, context):
        self._build_bg(context.area.height)

    def draw(self, context):
        if self._batch_bg is None:
            self.update(context)

        # Draw background panel
        gpu.state.blend_set('ALPHA_PREMULT')
        self._shader_bg.bind()
        self._shader_bg.uniform_float("color", self._bg_color)
        self._batch_bg.draw(self._shader_bg)
        gpu.state.blend_set('NONE')

        # Draw image aspect-fit inside widget rect
        if self.image and self.image.size[0] and self.image.size[1]:
            iw = float(self.image.size[0])
            ih = float(self.image.size[1])
            if iw <= 0.0 or ih <= 0.0:
                return
            scale = min(self.width / iw, self.height / ih)
            dw = iw * scale
            dh = ih * scale
            x0 = self.x + (self.width - dw) * 0.5
            y0 = self.y + (self.height - dh) * 0.5

            shader = gpu.shader.from_builtin('IMAGE')
            tex = gpu.texture.from_image(self.image)
            positions = ((x0, y0), (x0 + dw, y0), (x0 + dw, y0 + dh), (x0, y0 + dh))
            uvs = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
            batch = batch_for_shader(shader, 'TRI_FAN', {"pos": positions, "texCoord": uvs})
            gpu.state.blend_set('ALPHA_PREMULT')
            shader.bind()
            shader.uniform_sampler('image', tex)
            batch.draw(shader)
            gpu.state.blend_set('NONE')

        # Draw hover/drag outline
        outline_color = (0.4, 0.4, 0.4, 0.9)
        if self._is_dragging:
            outline_color = (1.0, 0.6, 0.1, 1.0)
        elif self._hover_inside or any(self._hover_edges.values()):
            outline_color = (0.2, 0.8, 1.0, 1.0)

        shader_name = "UNIFORM_COLOR" if bpy.app.version >= (4, 0, 0) else "2D_UNIFORM_COLOR"
        line_shader = gpu.shader.from_builtin(shader_name)
        line_shader.bind()
        line_shader.uniform_float("color", outline_color)
        p0 = (self.x, self.y)
        p1 = (self.x + self.width, self.y)
        p2 = (self.x + self.width, self.y + self.height)
        p3 = (self.x, self.y + self.height)
        positions = (p0, p1, p2, p3, p0)
        line_batch = batch_for_shader(line_shader, 'LINE_STRIP', {"pos": positions})
        gpu.state.line_width_set(2.0)
        line_batch.draw(line_shader)


class PEXELS_OT_OverlayWidget(bpy.types.Operator):
    """Floating aspect-correct preview overlay (widget-based)"""
    bl_idname = "pexels.overlay_widget"
    bl_label = "Preview Overlay"
    bl_description = "Show the selected image in a floating overlay"
    bl_options = {'REGISTER', 'INTERNAL'}

    _handle = None
    _timer = None
    _widget = None
    _image = None
    _is_dragging = False
    _drag_mode = None  # 'move' or 'resize'
    _resize_edges = None  # dict with left/right/top/bottom bools
    _drag_start_mouse = None  # (x, y)
    _start_rect = None  # (x, y, w, h)
    _cursor_set = False

    @staticmethod
    def _draw(self_ref, context):
        if self_ref and self_ref._widget:
            self_ref._widget.draw(context)

    def _load_selected_image(self, context):
        state = context.scene.pexels_state
        item = state.get_selected_item()
        if not item:
            return None
        url = item.thumb_url or item.full_url
        if not url:
            return None
        try:
            return load_image_from_url(url)
        except Exception:
            return None

    def invoke(self, context, event):
        self._image = self._load_selected_image(context)
        if not self._image:
            self.report({'WARNING'}, "No image to preview")
            return {'CANCELLED'}

        region = context.region
        panel_margin = 16.0
        w = max(200.0, min(float(region.width) - 2.0 * panel_margin, 600.0))
        h = max(150.0, min(float(region.height) * 0.6, 400.0))
        self._widget = PEXELS_UI_ImageWidget(panel_margin, panel_margin, w, h, self._image)
        self._widget.update(context)
        self._is_dragging = False
        self._drag_mode = None
        self._resize_edges = {"left": False, "right": False, "top": False, "bottom": False}
        self._drag_start_mouse = (event.mouse_region_x, event.mouse_region_y)
        self._start_rect = (self._widget.x, self._widget.y, self._widget.width, self._widget.height)
        self._cursor_set = False

        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            PEXELS_OT_OverlayWidget._draw, (self, context), 'WINDOW', 'POST_PIXEL'
        )
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.05, window=context.window)
        wm.modal_handler_add(self)
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'}:
            self.cancel(context)
            return {'CANCELLED'}

        # Start drag on left press
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS' and self._widget:
            mx, my = event.mouse_region_x, event.mouse_region_y
            edges = self._widget.hit_test_edges(mx, my)
            if any(edges.values()):
                self._is_dragging = True
                self._drag_mode = 'resize'
                self._resize_edges = edges
                self._drag_start_mouse = (mx, my)
                self._start_rect = (self._widget.x, self._widget.y, self._widget.width, self._widget.height)
                self._widget._is_dragging = True
                self._widget._drag_mode = 'resize'
                return {'RUNNING_MODAL'}
            elif self._widget.contains_point(mx, my):
                self._is_dragging = True
                self._drag_mode = 'move'
                self._drag_start_mouse = (mx, my)
                self._start_rect = (self._widget.x, self._widget.y, self._widget.width, self._widget.height)
                self._widget._is_dragging = True
                self._widget._drag_mode = 'move'
                return {'RUNNING_MODAL'}

        # End drag on left release
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE' and self._is_dragging:
            self._is_dragging = False
            self._drag_mode = None
            if self._widget:
                self._widget._is_dragging = False
                self._widget._drag_mode = None
            # restore hover state after drag end
            mx, my = event.mouse_region_x, event.mouse_region_y
            if self._widget:
                edges = self._widget.hit_test_edges(mx, my)
                self._widget._hover_edges = edges
                self._widget._hover_inside = self._widget.contains_point(mx, my) and not any(edges.values())
            return {'RUNNING_MODAL'}

        # Handle mouse move while dragging
        if event.type == 'MOUSEMOVE' and self._widget:
            if self._is_dragging and self._drag_mode:
                mx, my = event.mouse_region_x, event.mouse_region_y
                sx, sy = self._drag_start_mouse
                dx, dy = mx - sx, my - sy
                x0, y0, w0, h0 = self._start_rect

                # Image aspect for uniform scaling
                aspect = 1.0
                if self._image and self._image.size[0] and self._image.size[1]:
                    iw = float(self._image.size[0])
                    ih = float(self._image.size[1])
                    if iw > 0.0 and ih > 0.0:
                        aspect = iw / ih

                if self._drag_mode == 'move':
                    self._widget.x = x0 + dx
                    self._widget.y = y0 + dy
                elif self._drag_mode == 'resize':
                    # Keep opposite edge anchored and enforce aspect ratio
                    cx0 = x0 + w0 * 0.5
                    cy0 = y0 + h0 * 0.5

                    if self._resize_edges.get('left'):
                        x1 = x0 + w0
                        new_x = x0 + dx
                        new_w = max(self._widget._min_width, x1 - new_x)
                        new_h = max(self._widget._min_height, new_w / aspect)
                        new_w = max(self._widget._min_width, new_h * aspect)
                        self._widget.width = new_w
                        self._widget.height = new_h
                        self._widget.x = x1 - new_w
                        self._widget.y = cy0 - new_h * 0.5
                    if self._resize_edges.get('right'):
                        new_w = max(self._widget._min_width, w0 + dx)
                        new_h = max(self._widget._min_height, new_w / aspect)
                        new_w = max(self._widget._min_width, new_h * aspect)
                        self._widget.width = new_w
                        self._widget.height = new_h
                        self._widget.x = x0
                        self._widget.y = cy0 - new_h * 0.5

                    if self._resize_edges.get('bottom'):
                        y1 = y0 + h0
                        new_y = y0 + dy
                        new_h = max(self._widget._min_height, y1 - new_y)
                        new_w = max(self._widget._min_width, new_h * aspect)
                        new_h = max(self._widget._min_height, new_w / aspect)
                        self._widget.height = new_h
                        self._widget.width = new_w
                        self._widget.y = y1 - new_h
                        self._widget.x = cx0 - new_w * 0.5
                    if self._resize_edges.get('top'):
                        new_h = max(self._widget._min_height, h0 + dy)
                        new_w = max(self._widget._min_width, new_h * aspect)
                        new_h = max(self._widget._min_height, new_w / aspect)
                        self._widget.height = new_h
                        self._widget.width = new_w
                        self._widget.y = y0
                        self._widget.x = cx0 - new_w * 0.5

                self._widget.clamp_size()
                self._widget.update(context)

            # Always redraw on mouse move for hover feedback
            if not self._is_dragging:
                mx, my = event.mouse_region_x, event.mouse_region_y
                edges = self._widget.hit_test_edges(mx, my)
                self._widget._hover_edges = edges
                self._widget._hover_inside = self._widget.contains_point(mx, my) and not any(edges.values())

                # Set mouse cursor to indicate action
                try:
                    if any(edges.values()):
                        horizontal = edges.get('left') or edges.get('right')
                        vertical = edges.get('top') or edges.get('bottom')
                        if horizontal and vertical:
                            context.window.cursor_modal_set('SCROLL_XY')
                        elif horizontal:
                            context.window.cursor_modal_set('SCROLL_X')
                        else:
                            context.window.cursor_modal_set('SCROLL_Y')
                        self._cursor_set = True
                    elif self._widget._hover_inside:
                        context.window.cursor_modal_set('HAND')
                        self._cursor_set = True
                    else:
                        if self._cursor_set:
                            context.window.cursor_modal_restore()
                            self._cursor_set = False
                except Exception:
                    pass

            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
            return {'RUNNING_MODAL'}

        if event.type == 'TIMER':
            if self._widget:
                self._widget.update(context)
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
            return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}

    def cancel(self, context):
        try:
            if self._handle is not None:
                bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
                self._handle = None
        except Exception:
            pass
        try:
            if self._timer is not None:
                context.window_manager.event_timer_remove(self._timer)
                self._timer = None
        except Exception:
            pass
        try:
            if self._cursor_set:
                context.window.cursor_modal_restore()
                self._cursor_set = False
        except Exception:
            pass

# Operator classes for registration
operator_classes = (
    PEXELS_OT_Search,
    PEXELS_OT_Page,
    PEXELS_OT_Import,
    PEXELS_OT_ClearCache,
    PEXELS_OT_OpenPreferences,
    PEXELS_OT_OverlayWidget,
)
