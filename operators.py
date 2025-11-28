# SPDX-License-Identifier: GPL-3.0-or-later
"""
Blender operators for Pexels image search and import functionality.

Provides operators for searching, importing, and managing Pexels images
with background task support, progress tracking, and proper error handling.
"""

import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from typing import Optional, Set

from .api import (
    search_images,
    download_image,
    PexelsAPIError,
    PexelsAuthError,
    PexelsRateLimitError,
    PexelsNetworkError,
    PexelsCancellationError,
    USER_AGENT,
    check_online_access,
    get_online_access_disabled_message
)
from .network_manager import OnlineAccessDisabledError, network_manager
from .task_manager import task_manager, TaskPriority, TaskStatus
from .progress_tracker import progress_tracker, ProgressStatus
from .cache_manager import cache_manager
from .logger import logger
from .utils import (
    load_image_from_url,
    create_plane_with_image,
    write_temp_file,
    preview_manager,
    format_eta,
    format_speed,
    truncate_filename
)


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
    except Exception as e:
        logger.warning("Failed to get addon preferences", exception=e)
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
    except Exception as e:
        logger.warning("Failed to get addon state", exception=e)
        return None


class PEXELS_OT_Search(bpy.types.Operator):
    """Search for images on Pexels"""
    
    bl_idname = "pexels.search"
    bl_label = "Search Pexels"
    bl_description = "Search for images on Pexels using the entered keywords"
    bl_options = {'REGISTER', 'INTERNAL'}
    
    _task_id: str = ""
    
    def execute(self, context):
        """Execute the search operation"""
        state = get_state(context)
        prefs = get_preferences(context)
        
        # Validate state and preferences
        if state is None:
            self.report({'ERROR'}, "Addon state not available")
            return {'CANCELLED'}
        
        if prefs is None:
            self.report({'ERROR'}, "Addon preferences not available")
            return {'CANCELLED'}
        
        # Validate API key
        if not prefs.api_key:
            self.report({'ERROR'}, "Set Pexels API key in Add-on Preferences.")
            return {'CANCELLED'}
        
        # Validate query
        if not state.query or not state.query.strip():
            self.report({'WARNING'}, "Enter a search keyword.")
            return {'CANCELLED'}
        
        # Check online access
        if not check_online_access():
            self.report({'ERROR'}, get_online_access_disabled_message())
            return {'CANCELLED'}
        
        # Check network connectivity
        if not network_manager.is_online():
            self.report({'ERROR'}, "No network connectivity. Check your internet connection.")
            return {'CANCELLED'}
        
        logger.info("Starting search", query=state.query, page=state.page)
        
        # Clear previous results
        state.clear_results()
        state.is_loading = True
        preview_manager.ensure_previews()
        
        # Start progress tracking
        progress_tracker.start(total_items=100, initial_item="Searching Pexels...")
        
        # Submit background task
        self._task_id = task_manager.submit_task(
            task_func=self._background_search,
            priority=TaskPriority.HIGH,
            on_complete=lambda task: self._on_search_complete(context, task),
            on_error=lambda task, error: self._on_search_error(context, task, error),
            on_progress=lambda task: self._on_search_progress(context, task),
            kwargs={
                'api_key': prefs.api_key,
                'query': state.query,
                'page': state.page,
                'per_page': prefs.max_results,
                'cache_thumbnails': prefs.cache_thumbnails
            }
        )
        
        self.report({'INFO'}, "Search started...")
        return {'FINISHED'}
    
    @staticmethod
    def _background_search(
        api_key: str,
        query: str,
        page: int,
        per_page: int,
        cache_thumbnails: bool,
        cancellation_token=None,
        progress_callback=None
    ):
        """
        Background task for search operation.
        
        Args:
            api_key: Pexels API key
            query: Search query
            page: Page number
            per_page: Results per page
            cache_thumbnails: Whether to cache thumbnails
            cancellation_token: Event to signal cancellation
            progress_callback: Callback for progress updates
            
        Returns:
            Tuple of (results, headers, thumbnail_paths)
        """
        if progress_callback:
            progress_callback(0.1, "Searching Pexels...")
        
        # Perform search
        results, headers = search_images(
            api_key=api_key,
            query=query,
            page=page,
            per_page=per_page,
            cancellation_token=cancellation_token,
            progress_callback=lambda p, m: progress_callback(0.1 + p * 0.2, m) if progress_callback else None
        )
        
        # Check cancellation
        if cancellation_token and cancellation_token.is_set():
            raise InterruptedError("Search cancelled")
        
        photos = results.get("photos", []) or []
        total = len(photos)
        thumbnail_paths = {}
        
        if progress_callback:
            progress_callback(0.3, f"Found {total} images, loading thumbnails...")
        
        # Download thumbnails
        if cache_thumbnails and total > 0:
            for i, photo in enumerate(photos):
                # Check cancellation
                if cancellation_token and cancellation_token.is_set():
                    raise InterruptedError("Search cancelled")
                
                photo_id = photo.get("id")
                thumb_url = (
                    photo.get("src", {}).get("medium") or
                    photo.get("src", {}).get("small") or
                    photo.get("src", {}).get("tiny")
                )
                
                if thumb_url and photo_id:
                    try:
                        # Check cache first
                        cached_path = cache_manager.get_file_path(thumb_url, variant="thumb")
                        if cached_path:
                            thumbnail_paths[str(photo_id)] = cached_path
                            # Load preview from cached file
                            try:
                                preview_manager.load_preview(str(photo_id), cached_path)
                            except Exception as e:
                                logger.warning(f"Failed to load cached preview for {photo_id}", exception=e)
                        else:
                            # Download and cache
                            thumb_data = download_image(
                                thumb_url,
                                headers={"User-Agent": USER_AGENT},
                                cancellation_token=cancellation_token
                            )
                            
                            # Save to cache
                            cache_manager.put(
                                thumb_url,
                                thumb_data,
                                variant="thumb",
                                metadata={"photo_id": str(photo_id)}
                            )
                            
                            # Also write to temp for preview loading
                            temp_path = write_temp_file(f"pexels_{photo_id}_th.jpg", thumb_data)
                            thumbnail_paths[str(photo_id)] = temp_path
                            
                    except PexelsCancellationError:
                        raise InterruptedError("Search cancelled")
                    except Exception as e:
                        logger.warning(f"Failed to load thumbnail for {photo_id}", exception=e)
                
                if progress_callback:
                    progress = 0.3 + (0.7 * (i + 1) / total)
                    progress_callback(progress, f"Loading thumbnail {i + 1}/{total}")
        
        return results, headers, thumbnail_paths
    
    def _on_search_complete(self, context, task):
        """Handle search completion on main thread."""
        try:
            state = get_state(context)
            if state is None:
                logger.error("State not available in search completion handler")
                return
            
            results, headers, thumbnail_paths = task.result
            
            # Process results
            self._process_search_results(state, results, thumbnail_paths)
            
            # Update rate limits
            self._update_rate_limits(state, headers)
            
            # Set default selection
            if state.items:
                self._set_default_selection(state, context)
            
            state.is_loading = False
            progress_tracker.complete()
            
            # Report success
            photos_count = len(state.items)
            total_count = state.total_results
            logger.info("Search completed", photos_count=photos_count, total_count=total_count)
            
            # Force UI update
            self._redraw_ui(context)
            
        except Exception as e:
            logger.error("Error in search completion handler", exception=e)
            state = get_state(context)
            if state:
                state.is_loading = False
            progress_tracker.error(str(e))
    
    def _on_search_error(self, context, task, error):
        """Handle search error on main thread."""
        state = get_state(context)
        if state:
            state.is_loading = False
        
        progress_tracker.error(str(error))
        
        # Log error
        logger.error("Search failed", exception=error)
        
        # Show error message
        error_msg = str(error)
        if isinstance(error, OnlineAccessDisabledError):
            error_msg = get_online_access_disabled_message()
        elif isinstance(error, PexelsAuthError):
            error_msg = "Invalid API key. Check your Pexels API key in preferences."
        elif isinstance(error, PexelsRateLimitError):
            error_msg = "Rate limit exceeded. Please try again later."
        elif isinstance(error, PexelsNetworkError):
            error_msg = f"Network error: {error}"
        elif isinstance(error, (PexelsCancellationError, InterruptedError)):
            error_msg = "Search cancelled"
        
        # Schedule error report
        def report_error():
            self.report({'ERROR'}, error_msg)
            return None
        bpy.app.timers.register(report_error, first_interval=0.0)
        
        # Force UI update
        self._redraw_ui(context)
    
    def _on_search_progress(self, context, task):
        """Handle progress update on main thread."""
        # Update progress tracker
        progress_tracker.update(
            int(task.progress * 100),
            task.message
        )
        
        # Force UI update
        self._redraw_ui(context)
    
    def _process_search_results(self, state, results, thumbnail_paths):
        """Process and store search results."""
        state.total_results = int(results.get("total_results", 0))
        photos = results.get("photos", []) or []
        
        for photo_data in photos:
            item = state.items.add()
            self._populate_item_data(item, photo_data)
            
            # Load preview if thumbnail was downloaded
            photo_id = str(photo_data.get("id", ""))
            if photo_id in thumbnail_paths:
                try:
                    preview_manager.load_preview(photo_id, thumbnail_paths[photo_id])
                except Exception as e:
                    logger.warning(f"Failed to load preview for {photo_id}", exception=e)
    
    def _populate_item_data(self, item, photo_data):
        """Populate PEXELS_Item with data from API response."""
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
    
    def _set_default_selection(self, state, context):
        """Set default selection after search."""
        try:
            first_item_id = str(state.items[0].item_id)
            from .properties import pexels_enum_items
            enum_items = pexels_enum_items(state, context)
            valid_identifiers = {item[0] for item in enum_items}
            
            logger.debug(f"[DEBUG] _set_default_selection: first_item_id='{first_item_id}', enum_items count={len(enum_items)}")
            
            if first_item_id in valid_identifiers:
                state.selected_icon_storage = first_item_id
                logger.debug(f"[DEBUG] _set_default_selection: Set to first_item_id '{first_item_id}'")
            elif enum_items:
                state.selected_icon_storage = enum_items[0][0]
                logger.debug(f"[DEBUG] _set_default_selection: Set to first enum item '{enum_items[0][0]}'")
            else:
                state.selected_icon_storage = ""
                logger.debug("[DEBUG] _set_default_selection: No valid items, cleared storage")
        except Exception as e:
            logger.warning("Failed to set default selection", exception=e)
            state.selected_icon_storage = ""
    
    def _update_rate_limits(self, state, headers):
        """Update rate limit information from response headers."""
        try:
            limit_str = headers.get('X-Ratelimit-Limit')
            remaining_str = headers.get('X-Ratelimit-Remaining')
            reset_str = headers.get('X-Ratelimit-Reset')

            if limit_str:
                state.rate_limit = int(limit_str)
            if remaining_str:
                state.rate_remaining = int(remaining_str)
            if reset_str:
                state.rate_reset_timestamp = int(reset_str)
        except (ValueError, TypeError) as e:
            logger.warning("Failed to parse rate limit headers", exception=e)
    
    def _redraw_ui(self, context):
        """Force UI redraw."""
        try:
            if context and hasattr(context, 'screen') and context.screen:
                for area in context.screen.areas:
                    area.tag_redraw()
        except Exception:
            pass


class PEXELS_OT_Cancel(bpy.types.Operator):
    """Cancel current operation"""
    
    bl_idname = "pexels.cancel"
    bl_label = "Cancel"
    bl_description = "Cancel the current operation"
    bl_options = {'REGISTER', 'INTERNAL'}
    
    def execute(self, context):
        """Execute cancellation."""
        # Cancel all tasks
        cancelled_count = task_manager.cancel_all()
        
        # Update state
        state = get_state(context)
        if state:
            state.is_loading = False
        
        # Update progress tracker
        progress_tracker.cancel()
        
        logger.info("Operations cancelled", cancelled_count=cancelled_count)
        self.report({'INFO'}, f"Cancelled {cancelled_count} operation(s)")
        
        return {'FINISHED'}


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
        """Execute page navigation."""
        state = get_state(context)
        if state is None:
            self.report({'ERROR'}, "Addon state not available")
            return {'CANCELLED'}
        
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
    
    _task_id: str = ""
    
    def execute(self, context):
        """Execute image import."""
        state = get_state(context)
        if state is None:
            self.report({'ERROR'}, "Addon state not available")
            return {'CANCELLED'}
        
        selected_item = state.get_selected_item()
        
        if not selected_item:
            self.report({'WARNING'}, "No image selected.")
            return {'CANCELLED'}
        
        if not selected_item.full_url:
            self.report({'WARNING'}, "No image URL available for selected item.")
            return {'CANCELLED'}
        
        # Check online access
        if not check_online_access():
            self.report({'ERROR'}, get_online_access_disabled_message())
            return {'CANCELLED'}
        
        # Check network connectivity
        if not network_manager.is_online():
            self.report({'ERROR'}, "No network connectivity. Check your internet connection.")
            return {'CANCELLED'}
        
        logger.info("Starting image import", image_id=selected_item.item_id)
        
        # Start progress tracking
        progress_tracker.start(total_items=100, initial_item="Downloading image...")
        state.is_loading = True
        
        # Store import settings
        import_settings = {
            'url': selected_item.full_url,
            'item_id': selected_item.item_id,
            'photographer': selected_item.photographer,
            'as_plane': self.as_plane,
            'plane_size': self.plane_size
        }
        
        # Submit background task
        self._task_id = task_manager.submit_task(
            task_func=self._background_download,
            priority=TaskPriority.HIGH,
            on_complete=lambda task: self._on_download_complete(context, task, import_settings),
            on_error=lambda task, error: self._on_download_error(context, task, error),
            on_progress=lambda task: self._on_download_progress(context, task),
            kwargs={
                'url': selected_item.full_url,
                'item_id': selected_item.item_id
            }
        )
        
        self.report({'INFO'}, "Download started...")
        return {'FINISHED'}
    
    @staticmethod
    def _background_download(
        url: str,
        item_id: int,
        cancellation_token=None,
        progress_callback=None
    ):
        """
        Background task for image download.
        
        Args:
            url: Image URL
            item_id: Image ID
            cancellation_token: Event to signal cancellation
            progress_callback: Callback for progress updates
            
        Returns:
            Path to downloaded image file
        """
        if progress_callback:
            progress_callback(0.1, "Checking cache...")
        
        # Check cache first
        cached_path = cache_manager.get_file_path(url, variant="full")
        if cached_path:
            logger.info("Using cached image", image_id=item_id)
            if progress_callback:
                progress_callback(1.0, "Loaded from cache")
            return cached_path
        
        if progress_callback:
            progress_callback(0.2, "Downloading image...")
        
        # Download image
        image_data = download_image(
            url,
            headers={"User-Agent": USER_AGENT},
            cancellation_token=cancellation_token,
            progress_callback=lambda p, m: progress_callback(0.2 + p * 0.7, m) if progress_callback else None
        )
        
        if progress_callback:
            progress_callback(0.9, "Saving to cache...")
        
        # Save to cache
        cache_manager.put(
            url,
            image_data,
            variant="full",
            metadata={"image_id": str(item_id)}
        )
        
        # Get cached file path
        cached_path = cache_manager.get_file_path(url, variant="full")
        if cached_path:
            return cached_path
        
        # Fallback to temp file
        from .utils import extract_filename_from_url
        filename = extract_filename_from_url(url)
        temp_path = write_temp_file(filename, image_data)
        return temp_path
    
    def _on_download_complete(self, context, task, import_settings):
        """Handle download completion on main thread."""
        try:
            state = get_state(context)
            if state:
                state.is_loading = False
            
            image_path = task.result
            
            # Load image into Blender
            image = bpy.data.images.load(image_path, check_existing=False)
            image.name = f"Pexels_{import_settings['item_id']}"
            
            # Create plane if requested
            if import_settings['as_plane']:
                plane_obj = create_plane_with_image(image, size=import_settings['plane_size'])
                if plane_obj:
                    plane_obj.select_set(True)
                    context.view_layer.objects.active = plane_obj
            
            progress_tracker.complete()
            
            # Report success
            photographer = import_settings.get('photographer', 'Unknown')
            logger.info("Image imported successfully", image_id=import_settings['item_id'])
            
            def report_success():
                self.report({'INFO'}, f"Imported: {photographer}'s image (ID: {import_settings['item_id']})")
                return None
            bpy.app.timers.register(report_success, first_interval=0.0)
            
            # Force UI update
            self._redraw_ui(context)
            
        except Exception as e:
            logger.error("Error in download completion handler", exception=e)
            state = get_state(context)
            if state:
                state.is_loading = False
            progress_tracker.error(str(e))
            
            def report_error():
                self.report({'ERROR'}, f"Import failed: {e}")
                return None
            bpy.app.timers.register(report_error, first_interval=0.0)
    
    def _on_download_error(self, context, task, error):
        """Handle download error on main thread."""
        state = get_state(context)
        if state:
            state.is_loading = False
        
        progress_tracker.error(str(error))
        logger.error("Image download failed", exception=error)
        
        error_msg = str(error)
        if isinstance(error, OnlineAccessDisabledError):
            error_msg = get_online_access_disabled_message()
        elif isinstance(error, (PexelsCancellationError, InterruptedError)):
            error_msg = "Download cancelled"
        
        def report_error():
            self.report({'ERROR'}, error_msg)
            return None
        bpy.app.timers.register(report_error, first_interval=0.0)
        
        self._redraw_ui(context)
    
    def _on_download_progress(self, context, task):
        """Handle progress update on main thread."""
        progress_tracker.update(
            int(task.progress * 100),
            task.message
        )
        self._redraw_ui(context)
    
    def _redraw_ui(self, context):
        """Force UI redraw."""
        try:
            if context and hasattr(context, 'screen') and context.screen:
                for area in context.screen.areas:
                    area.tag_redraw()
        except Exception:
            pass
    
    def invoke(self, context, event):
        """Invoke operator with current preferences."""
        prefs = get_preferences(context)
        if prefs:
            self.plane_size = prefs.default_plane_size
        return self.execute(context)


class PEXELS_OT_ClearCache(bpy.types.Operator):
    """Clear cached thumbnails and temporary files"""
    
    bl_idname = "pexels.clear_cache"
    bl_label = "Clear Cache"
    bl_description = "Clear cached thumbnails and temporary files"
    bl_options = {'REGISTER'}
    
    def execute(self, context):
        """Execute cache clearing."""
        try:
            # Clear preview manager
            preview_manager.clear_previews()
            
            # Clear cache manager
            memory_cleared, disk_cleared = cache_manager.clear()
            
            # Clear state
            state = get_state(context)
            if state:
                state.clear_results()
            
            logger.info("Cache cleared", memory_items=memory_cleared, disk_items=disk_cleared)
            self.report({'INFO'}, f"Cache cleared: {memory_cleared} memory items, {disk_cleared} disk items")
            return {'FINISHED'}
            
        except Exception as e:
            logger.error("Failed to clear cache", exception=e)
            self.report({'ERROR'}, f"Failed to clear cache: {e}")
            return {'CANCELLED'}


class PEXELS_OT_OpenPreferences(bpy.types.Operator):
    """Open addon preferences"""
    
    bl_idname = "pexels.open_preferences"
    bl_label = "Open Preferences"
    bl_description = "Open the Pexels addon preferences"
    bl_options = {'REGISTER'}
    
    def execute(self, context):
        """Execute preferences opening."""
        bpy.ops.preferences.addon_show(module=__package__)
        return {'FINISHED'}


class PEXELS_UI_ImageWidget:
    """GPU-based image widget for overlay preview."""
    
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
        state = get_state(context)
        if not state:
            return None
        item = state.get_selected_item()
        if not item:
            return None
        url = item.thumb_url or item.full_url
        if not url:
            return None
        try:
            return load_image_from_url(url)
        except Exception as e:
            logger.warning("Failed to load image for overlay", exception=e)
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
        except Exception as e:
            logger.warning("Failed to remove draw handler", exception=e)
        
        try:
            if self._timer is not None:
                context.window_manager.event_timer_remove(self._timer)
                self._timer = None
        except Exception as e:
            logger.warning("Failed to remove timer", exception=e)
        
        try:
            if self._cursor_set:
                context.window.cursor_modal_restore()
                self._cursor_set = False
        except Exception:
            pass


class PEXELS_OT_CacheImages(bpy.types.Operator):
    """Cache all search result images for offline use"""
    
    bl_idname = "pexels.cache_images"
    bl_label = "Cache Images"
    bl_description = "Download and cache all images from current search results"
    bl_options = {'REGISTER', 'INTERNAL'}
    
    _task_id: str = ""
    _timer = None
    _start_time: float = 0.0
    _bytes_downloaded: float = 0.0
    _last_speed_update: float = 0.0
    
    def execute(self, context):
        """Execute the caching operation."""
        import time
        
        state = get_state(context)
        prefs = get_preferences(context)
        
        if state is None:
            self.report({'ERROR'}, "Addon state not available")
            return {'CANCELLED'}
        
        if prefs is None:
            self.report({'ERROR'}, "Addon preferences not available")
            return {'CANCELLED'}
        
        # Check if there are items to cache
        if not state.items:
            self.report({'WARNING'}, "No images to cache. Perform a search first.")
            return {'CANCELLED'}
        
        # Check if already caching
        if state.caching_in_progress:
            self.report({'WARNING'}, "Caching already in progress")
            return {'CANCELLED'}
        
        # Check online access
        if not check_online_access():
            self.report({'ERROR'}, get_online_access_disabled_message())
            return {'CANCELLED'}
        
        # Check network connectivity
        if not network_manager.is_online():
            self.report({'ERROR'}, "No network connectivity. Check your internet connection.")
            return {'CANCELLED'}
        
        # Collect URLs to cache
        urls_to_cache = []
        for item in state.items:
            if item.full_url:
                # Check if already cached
                cached_path = cache_manager.get_file_path(item.full_url, variant="full")
                if not cached_path:
                    urls_to_cache.append({
                        'url': item.full_url,
                        'item_id': item.item_id,
                        'filename': f"pexels_{item.item_id}.jpg"
                    })
        
        if not urls_to_cache:
            self.report({'INFO'}, "All images are already cached")
            return {'FINISHED'}
        
        logger.info("Starting batch image caching", total_images=len(urls_to_cache))
        
        # Initialize caching state
        state.caching_in_progress = True
        state.caching_progress = 0.0
        state.caching_current_file = ""
        state.caching_eta_seconds = 0
        state.caching_items_done = 0
        state.caching_items_total = len(urls_to_cache)
        state.caching_speed_bytes = 0.0
        state.caching_error_message = ""
        
        self._start_time = time.time()
        self._bytes_downloaded = 0.0
        self._last_speed_update = self._start_time
        
        # Submit background task
        self._task_id = task_manager.submit_task(
            task_func=self._background_cache,
            priority=TaskPriority.NORMAL,
            on_complete=lambda task: self._on_cache_complete(context, task),
            on_error=lambda task, error: self._on_cache_error(context, task, error),
            on_progress=lambda task: self._on_cache_progress(context, task),
            kwargs={
                'urls_to_cache': urls_to_cache
            }
        )
        
        # Start timer for UI updates
        self._timer = context.window_manager.event_timer_add(0.1, window=context.window)
        context.window_manager.modal_handler_add(self)
        
        self.report({'INFO'}, f"Caching {len(urls_to_cache)} images...")
        return {'RUNNING_MODAL'}
    
    def modal(self, context, event):
        """Handle modal events for progress updates."""
        state = get_state(context)
        
        if state is None or not state.caching_in_progress:
            self.cancel(context)
            return {'CANCELLED'}
        
        if event.type == 'TIMER':
            # Force UI redraw
            self._redraw_ui(context)
        
        return {'PASS_THROUGH'}
    
    def cancel(self, context):
        """Clean up when cancelled."""
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
    
    @staticmethod
    def _background_cache(
        urls_to_cache: list,
        cancellation_token=None,
        progress_callback=None
    ):
        """
        Background task for batch image caching.
        
        Args:
            urls_to_cache: List of dicts with url, item_id, filename
            cancellation_token: Event to signal cancellation
            progress_callback: Callback for progress updates
            
        Returns:
            Dict with cached_count and failed_count
        """
        import time as time_module
        
        cached_count = 0
        failed_count = 0
        total = len(urls_to_cache)
        start_time = time_module.time()
        total_bytes = 0
        
        for i, item_info in enumerate(urls_to_cache):
            # Check cancellation
            if cancellation_token and cancellation_token.is_set():
                raise InterruptedError("Caching cancelled")
            
            url = item_info['url']
            item_id = item_info['item_id']
            filename = item_info['filename']
            
            if progress_callback:
                progress = (i / total)
                elapsed = time_module.time() - start_time
                speed = total_bytes / elapsed if elapsed > 0 else 0
                
                # Calculate ETA
                if i > 0:
                    avg_time_per_item = elapsed / i
                    remaining_items = total - i
                    eta = avg_time_per_item * remaining_items
                else:
                    eta = 0
                
                progress_callback(
                    progress,
                    filename,
                    {
                        'completed': i,
                        'total': total,
                        'eta_seconds': int(eta),
                        'speed_bytes': speed,
                        'current_item': filename
                    }
                )
            
            try:
                # Download image
                from .api import download_image, USER_AGENT
                
                image_data = download_image(
                    url,
                    headers={"User-Agent": USER_AGENT},
                    cancellation_token=cancellation_token
                )
                
                total_bytes += len(image_data)
                
                # Save to cache
                cache_manager.put(
                    url,
                    image_data,
                    variant="full",
                    metadata={"image_id": str(item_id)}
                )
                
                cached_count += 1
                
            except PexelsCancellationError:
                raise InterruptedError("Caching cancelled")
            except Exception as e:
                logger.warning(f"Failed to cache image {item_id}", exception=e)
                failed_count += 1
        
        # Final progress update
        if progress_callback:
            progress_callback(1.0, "Complete", {
                'completed': total,
                'total': total,
                'eta_seconds': 0,
                'speed_bytes': 0,
                'current_item': ''
            })
        
        return {
            'cached_count': cached_count,
            'failed_count': failed_count,
            'total_bytes': total_bytes
        }
    
    def _on_cache_complete(self, context, task):
        """Handle caching completion on main thread."""
        state = get_state(context)
        if state:
            state.caching_in_progress = False
            state.caching_progress = 100.0
            state.caching_current_file = ""
            state.caching_eta_seconds = 0
        
        self.cancel(context)
        
        result = task.result
        cached = result.get('cached_count', 0)
        failed = result.get('failed_count', 0)
        
        logger.info("Batch caching completed", cached=cached, failed=failed)
        
        # Report result
        def report_result():
            if failed > 0:
                self.report({'WARNING'}, f"Cached {cached} images, {failed} failed")
            else:
                self.report({'INFO'}, f"Successfully cached {cached} images")
            return None
        bpy.app.timers.register(report_result, first_interval=0.0)
        
        self._redraw_ui(context)
    
    def _on_cache_error(self, context, task, error):
        """Handle caching error on main thread."""
        state = get_state(context)
        if state:
            state.caching_in_progress = False
            state.caching_error_message = str(error)
        
        self.cancel(context)
        
        logger.error("Batch caching failed", exception=error)
        
        error_msg = str(error)
        if isinstance(error, OnlineAccessDisabledError):
            error_msg = get_online_access_disabled_message()
        elif isinstance(error, (PexelsCancellationError, InterruptedError)):
            error_msg = "Caching cancelled"
        
        def report_error():
            self.report({'ERROR'}, error_msg)
            return None
        bpy.app.timers.register(report_error, first_interval=0.0)
        
        self._redraw_ui(context)
    
    def _on_cache_progress(self, context, task):
        """Handle progress update on main thread."""
        state = get_state(context)
        if state is None:
            return
        
        # Update state properties from task progress data
        state.caching_progress = task.progress * 100.0
        
        # Extract additional progress data if available
        if hasattr(task, 'progress_data') and task.progress_data:
            data = task.progress_data
            state.caching_current_file = data.get('current_item', '')
            state.caching_items_done = data.get('completed', 0)
            state.caching_items_total = data.get('total', 0)
            state.caching_eta_seconds = data.get('eta_seconds', 0)
            state.caching_speed_bytes = data.get('speed_bytes', 0.0)
        elif task.message:
            state.caching_current_file = task.message
        
        self._redraw_ui(context)
    
    def _redraw_ui(self, context):
        """Force UI redraw."""
        try:
            if context and hasattr(context, 'screen') and context.screen:
                for area in context.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()
        except Exception:
            pass


class PEXELS_OT_CancelCaching(bpy.types.Operator):
    """Cancel the current caching operation"""
    
    bl_idname = "pexels.cancel_caching"
    bl_label = "Cancel Caching"
    bl_description = "Cancel the current image caching operation"
    bl_options = {'REGISTER', 'INTERNAL'}
    
    def execute(self, context):
        """Execute cancellation."""
        state = get_state(context)
        
        # Cancel all tasks
        cancelled_count = task_manager.cancel_all()
        
        # Update state
        if state:
            state.caching_in_progress = False
            state.caching_error_message = "Cancelled by user"
        
        logger.info("Caching cancelled", cancelled_count=cancelled_count)
        self.report({'INFO'}, "Caching cancelled")
        
        return {'FINISHED'}


# Operator classes for registration
operator_classes = (
    PEXELS_OT_Search,
    PEXELS_OT_Cancel,
    PEXELS_OT_Page,
    PEXELS_OT_Import,
    PEXELS_OT_ClearCache,
    PEXELS_OT_OpenPreferences,
    PEXELS_OT_OverlayWidget,
    PEXELS_OT_CacheImages,
    PEXELS_OT_CancelCaching,
)
