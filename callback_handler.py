# SPDX-License-Identifier: GPL-3.0-or-later
"""
Centralized Callback Handler for Pexels Extension.

Provides static callback handlers for async operations that don't depend on
operator instances. This solves the StructRNA removal error that occurs when
operator instances are garbage collected while async callbacks are still pending.

The key insight is that Blender operators are transient - they're destroyed after
execute() returns. By using static methods and passing context data as dictionaries,
we avoid capturing 'self' references that become invalid.
"""

import bpy
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass, field

from . import logger


@dataclass
class CallbackContext:
    """
    Context data for async callbacks.
    
    This replaces capturing 'self' in lambda closures. All data needed
    for callback execution is stored here as plain Python objects.
    
    Attributes:
        operation_type: Type of operation ('search', 'import', 'cache')
        query: Search query (for search operations)
        page: Page number (for search operations)
        per_page: Results per page (for search operations)
        item_id: Image ID (for import operations)
        photographer: Photographer name (for import operations)
        import_settings: Import settings dict (for import operations)
        extra_data: Additional operation-specific data
    """
    operation_type: str
    query: str = ""
    page: int = 1
    per_page: int = 50
    item_id: int = 0
    photographer: str = ""
    import_settings: Dict[str, Any] = field(default_factory=dict)
    extra_data: Dict[str, Any] = field(default_factory=dict)


def _is_context_valid() -> bool:
    """
    Check if Blender context is still valid for callback execution.
    
    Returns:
        True if context is valid and safe to use
    """
    try:
        # Check if we have a valid context
        if bpy.context is None:
            return False
        
        # Check if scene exists
        if not hasattr(bpy.context, 'scene') or bpy.context.scene is None:
            return False
        
        # Check if our state property exists
        if not hasattr(bpy.context.scene, 'pexels_state'):
            return False
        
        return True
    except (ReferenceError, AttributeError, RuntimeError):
        return False


def _get_state():
    """
    Safely get addon state from current context.
    
    Returns:
        PEXELS_State or None if not available
    """
    try:
        if not _is_context_valid():
            return None
        return bpy.context.scene.pexels_state
    except (ReferenceError, AttributeError, RuntimeError):
        return None


def _get_preferences():
    """
    Safely get addon preferences.
    
    Returns:
        Addon preferences or None if not available
    """
    try:
        if bpy.context is None:
            return None
        if not hasattr(bpy.context, 'preferences'):
            return None
        if bpy.context.preferences is None:
            return None
        
        # Get package name for preferences lookup
        package = __package__
        if package not in bpy.context.preferences.addons:
            return None
        
        return bpy.context.preferences.addons[package].preferences
    except (ReferenceError, AttributeError, RuntimeError):
        return None


def _redraw_ui():
    """Force UI redraw across all areas."""
    try:
        if bpy.context and hasattr(bpy.context, 'screen') and bpy.context.screen:
            for area in bpy.context.screen.areas:
                area.tag_redraw()
    except (ReferenceError, AttributeError, RuntimeError):
        pass


def _show_message(message: str, message_type: str = 'INFO'):
    """
    Show a message to the user via Blender's reporting system.
    
    Args:
        message: Message text
        message_type: 'INFO', 'WARNING', or 'ERROR'
    """
    def _report():
        try:
            # Use window_manager to show message
            if bpy.context and bpy.context.window_manager:
                # Store message in state for UI display
                state = _get_state()
                if state:
                    state.last_error_message = message if message_type == 'ERROR' else ""
                    state.loading_message = message
        except Exception:
            pass
        return None
    
    try:
        bpy.app.timers.register(_report, first_interval=0.0)
    except Exception:
        pass


class SearchCallbackHandler:
    """
    Static callback handlers for search operations.
    
    All methods are static and use CallbackContext instead of operator instances.
    """
    
    @staticmethod
    def on_complete(ctx: CallbackContext, task) -> None:
        """
        Handle search completion on main thread.
        
        Args:
            ctx: Callback context with operation data
            task: Completed task with results
        """
        try:
            state = _get_state()
            if state is None:
                logger.error("State not available in search completion handler")
                return
            
            results, headers, thumbnail_paths = task.result
            
            # Process results
            SearchCallbackHandler._process_search_results(state, results, thumbnail_paths)
            
            # Update rate limits
            SearchCallbackHandler._update_rate_limits(state, headers)
            
            # Cache search results for future use
            SearchCallbackHandler._cache_results(ctx, state, results)
            
            # Set default selection
            if state.items:
                SearchCallbackHandler._set_default_selection(state)
            
            # Update state
            state.is_loading = False
            state.operation_status = 'IDLE'
            state.last_error_message = ""
            
            # Update progress tracker
            from .progress_tracker import progress_tracker
            progress_tracker.complete()
            
            # Report success
            photos_count = len(state.items)
            total_count = state.total_results
            logger.info("Search completed", photos_count=photos_count, total_count=total_count)
            
            # Force UI update
            _redraw_ui()
            
        except Exception as e:
            logger.error("Error in search completion handler", exception=e)
            state = _get_state()
            if state:
                state.is_loading = False
                state.operation_status = 'ERROR'
                state.last_error_message = str(e)
            
            from .progress_tracker import progress_tracker
            progress_tracker.error(str(e))
    
    @staticmethod
    def on_error(ctx: CallbackContext, task, error: Exception) -> None:
        """
        Handle search error on main thread.
        
        Args:
            ctx: Callback context with operation data
            task: Failed task
            error: Exception that occurred
        """
        state = _get_state()
        if state:
            state.is_loading = False
            state.operation_status = 'ERROR'
        
        from .progress_tracker import progress_tracker
        progress_tracker.error(str(error))
        
        # Log error
        logger.error("Search failed", exception=error)
        
        # Determine user-friendly error message
        error_msg = SearchCallbackHandler._get_error_message(error)
        
        if state:
            state.last_error_message = error_msg
        
        _show_message(error_msg, 'ERROR')
        _redraw_ui()
    
    @staticmethod
    def on_progress(ctx: CallbackContext, task) -> None:
        """
        Handle progress update on main thread.
        
        Args:
            ctx: Callback context with operation data
            task: Task with progress info
        """
        state = _get_state()
        if state:
            state.loading_progress = task.progress * 100.0
            state.loading_message = task.message
        
        from .progress_tracker import progress_tracker
        progress_tracker.update(
            int(task.progress * 100),
            task.message
        )
        
        _redraw_ui()
    
    @staticmethod
    def _process_search_results(state, results: Dict, thumbnail_paths: Dict) -> None:
        """Process and store search results."""
        state.total_results = int(results.get("total_results", 0))
        photos = results.get("photos", []) or []
        
        from .utils import get_preview_manager
        
        for photo_data in photos:
            item = state.items.add()
            SearchCallbackHandler._populate_item_data(item, photo_data)
            
            # Load preview if thumbnail was downloaded
            photo_id = str(photo_data.get("id", ""))
            if photo_id in thumbnail_paths:
                try:
                    get_preview_manager().load_preview(photo_id, thumbnail_paths[photo_id])
                except Exception as e:
                    logger.warning(f"Failed to load preview for {photo_id}", exception=e)
    
    @staticmethod
    def _populate_item_data(item, photo_data: Dict) -> None:
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
    
    @staticmethod
    def _set_default_selection(state) -> None:
        """Set default selection after search."""
        try:
            first_item_id = str(state.items[0].item_id)
            from .properties import pexels_enum_items
            enum_items = pexels_enum_items(state, bpy.context)
            valid_identifiers = {item[0] for item in enum_items}
            
            if first_item_id in valid_identifiers:
                state.selected_icon_storage = first_item_id
            elif enum_items:
                state.selected_icon_storage = enum_items[0][0]
            else:
                state.selected_icon_storage = ""
        except Exception as e:
            logger.warning("Failed to set default selection", exception=e)
            state.selected_icon_storage = ""
    
    @staticmethod
    def _update_rate_limits(state, headers: Dict) -> None:
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
    
    @staticmethod
    def _cache_results(ctx: CallbackContext, state, results: Dict) -> None:
        """Cache search results for future use."""
        try:
            from .cache_manager import get_cache_manager
            from .history_manager import get_history_manager
            
            photos = results.get("photos", []) or []
            total_results = results.get("total_results", 0)
            
            cached_result = get_cache_manager().cache_search_result(
                query=ctx.query,
                page=ctx.page,
                per_page=ctx.per_page,
                photos=photos,
                total_results=total_results
            )
            
            # Record in search history
            if cached_result:
                get_history_manager().record_search(
                    query=ctx.query,
                    result_count=total_results,
                    page=ctx.page,
                    per_page=ctx.per_page,
                    cached_result_id=cached_result.id
                )
        except Exception as e:
            logger.warning(f"Failed to cache search results: {e}")
    
    @staticmethod
    def _get_error_message(error: Exception) -> str:
        """Get user-friendly error message."""
        from .api import PexelsAuthError, PexelsRateLimitError, PexelsNetworkError, PexelsCancellationError
        from .network_manager import OnlineAccessDisabledError
        from .api import get_online_access_disabled_message
        
        if isinstance(error, OnlineAccessDisabledError):
            return get_online_access_disabled_message()
        elif isinstance(error, PexelsAuthError):
            return "Invalid API key. Check your Pexels API key in preferences."
        elif isinstance(error, PexelsRateLimitError):
            return "Rate limit exceeded. Please try again later."
        elif isinstance(error, PexelsNetworkError):
            return f"Network error: {error}"
        elif isinstance(error, (PexelsCancellationError, InterruptedError)):
            return "Search cancelled"
        else:
            return str(error)


class ImportCallbackHandler:
    """
    Static callback handlers for import operations.
    """
    
    @staticmethod
    def on_complete(ctx: CallbackContext, task) -> None:
        """
        Handle download completion on main thread.
        
        Args:
            ctx: Callback context with import settings
            task: Completed task with image path
        """
        try:
            state = _get_state()
            if state:
                state.is_loading = False
                state.operation_status = 'IDLE'
            
            image_path = task.result
            import_settings = ctx.import_settings
            
            # Load image into Blender
            image = bpy.data.images.load(image_path, check_existing=False)
            image.name = f"Pexels_{ctx.item_id}"
            
            # Create plane if requested
            if import_settings.get('as_plane', True):
                from .utils import create_plane_with_image
                plane_obj = create_plane_with_image(image, size=import_settings.get('plane_size', 2.0))
                if plane_obj:
                    plane_obj.select_set(True)
                    if bpy.context.view_layer:
                        bpy.context.view_layer.objects.active = plane_obj
            
            from .progress_tracker import progress_tracker
            progress_tracker.complete()
            
            # Report success
            logger.info("Image imported successfully", image_id=ctx.item_id)
            _show_message(f"Imported: {ctx.photographer}'s image (ID: {ctx.item_id})", 'INFO')
            _redraw_ui()
            
        except Exception as e:
            logger.error("Error in download completion handler", exception=e)
            state = _get_state()
            if state:
                state.is_loading = False
                state.operation_status = 'ERROR'
                state.last_error_message = str(e)
            
            from .progress_tracker import progress_tracker
            progress_tracker.error(str(e))
            _show_message(f"Import failed: {e}", 'ERROR')
    
    @staticmethod
    def on_error(ctx: CallbackContext, task, error: Exception) -> None:
        """
        Handle download error on main thread.
        
        Args:
            ctx: Callback context
            task: Failed task
            error: Exception that occurred
        """
        state = _get_state()
        if state:
            state.is_loading = False
            state.operation_status = 'ERROR'
        
        from .progress_tracker import progress_tracker
        progress_tracker.error(str(error))
        logger.error("Image download failed", exception=error)
        
        # Get user-friendly error message
        error_msg = ImportCallbackHandler._get_error_message(error)
        
        if state:
            state.last_error_message = error_msg
        
        _show_message(error_msg, 'ERROR')
        _redraw_ui()
    
    @staticmethod
    def on_progress(ctx: CallbackContext, task) -> None:
        """
        Handle progress update on main thread.
        
        Args:
            ctx: Callback context
            task: Task with progress info
        """
        state = _get_state()
        if state:
            state.loading_progress = task.progress * 100.0
            state.loading_message = task.message
        
        from .progress_tracker import progress_tracker
        progress_tracker.update(
            int(task.progress * 100),
            task.message
        )
        _redraw_ui()
    
    @staticmethod
    def _get_error_message(error: Exception) -> str:
        """Get user-friendly error message."""
        from .api import PexelsCancellationError
        from .network_manager import OnlineAccessDisabledError
        from .api import get_online_access_disabled_message
        
        if isinstance(error, OnlineAccessDisabledError):
            return get_online_access_disabled_message()
        elif isinstance(error, (PexelsCancellationError, InterruptedError)):
            return "Download cancelled"
        else:
            return str(error)


class CacheCallbackHandler:
    """
    Static callback handlers for caching operations.
    """
    
    @staticmethod
    def on_complete(ctx: CallbackContext, task) -> None:
        """
        Handle caching completion on main thread.
        
        Args:
            ctx: Callback context
            task: Completed task with results
        """
        state = _get_state()
        if state:
            state.caching_in_progress = False
            state.caching_progress = 100.0
            state.caching_current_file = ""
            state.caching_eta_seconds = 0
            state.operation_status = 'IDLE'
        
        result = task.result
        cached = result.get('cached_count', 0)
        failed = result.get('failed_count', 0)
        
        logger.info("Batch caching completed", cached=cached, failed=failed)
        
        if failed > 0:
            _show_message(f"Cached {cached} images, {failed} failed", 'WARNING')
        else:
            _show_message(f"Successfully cached {cached} images", 'INFO')
        
        _redraw_ui()
    
    @staticmethod
    def on_error(ctx: CallbackContext, task, error: Exception) -> None:
        """
        Handle caching error on main thread.
        
        Args:
            ctx: Callback context
            task: Failed task
            error: Exception that occurred
        """
        state = _get_state()
        if state:
            state.caching_in_progress = False
            state.caching_error_message = str(error)
            state.operation_status = 'ERROR'
        
        logger.error("Batch caching failed", exception=error)
        
        error_msg = CacheCallbackHandler._get_error_message(error)
        _show_message(error_msg, 'ERROR')
        _redraw_ui()
    
    @staticmethod
    def on_progress(ctx: CallbackContext, task) -> None:
        """
        Handle progress update on main thread.
        
        Args:
            ctx: Callback context
            task: Task with progress info
        """
        state = _get_state()
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
        
        _redraw_ui()
    
    @staticmethod
    def _get_error_message(error: Exception) -> str:
        """Get user-friendly error message."""
        from .api import PexelsCancellationError
        from .network_manager import OnlineAccessDisabledError
        from .api import get_online_access_disabled_message
        
        if isinstance(error, OnlineAccessDisabledError):
            return get_online_access_disabled_message()
        elif isinstance(error, (PexelsCancellationError, InterruptedError)):
            return "Caching cancelled"
        else:
            return str(error)


def create_search_context(query: str, page: int, per_page: int) -> CallbackContext:
    """
    Create callback context for search operation.
    
    Args:
        query: Search query
        page: Page number
        per_page: Results per page
        
    Returns:
        CallbackContext configured for search
    """
    return CallbackContext(
        operation_type='search',
        query=query,
        page=page,
        per_page=per_page
    )


def create_import_context(
    item_id: int,
    photographer: str,
    url: str,
    as_plane: bool = True,
    plane_size: float = 2.0
) -> CallbackContext:
    """
    Create callback context for import operation.
    
    Args:
        item_id: Pexels image ID
        photographer: Photographer name
        url: Image URL
        as_plane: Whether to import as plane
        plane_size: Size of plane
        
    Returns:
        CallbackContext configured for import
    """
    return CallbackContext(
        operation_type='import',
        item_id=item_id,
        photographer=photographer,
        import_settings={
            'url': url,
            'as_plane': as_plane,
            'plane_size': plane_size
        }
    )


def create_cache_context(urls_count: int) -> CallbackContext:
    """
    Create callback context for caching operation.
    
    Args:
        urls_count: Number of URLs to cache
        
    Returns:
        CallbackContext configured for caching
    """
    return CallbackContext(
        operation_type='cache',
        extra_data={'urls_count': urls_count}
    )