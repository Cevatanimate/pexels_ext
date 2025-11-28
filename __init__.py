# SPDX-License-Identifier: GPL-3.0-or-later
"""
Pexels Image Search - Blender Extension

Search, preview, and import high-quality images from Pexels.
Features background task processing, caching, progress tracking,
favorites management, and comprehensive cache browsing.

IMPORTANT FIX (v1.1.0):
This version includes a comprehensive fix for the StructRNA error:
"TaskManager Callback error: StructRNA of type PEXELS_OT_Search has been removed"

The error occurred because:
1. Blender operators are transient - destroyed after execute() returns
2. Async callbacks captured 'self' (operator instance) in lambda closures
3. When callbacks fired, the operator was already destroyed

The fix implements:
1. Static callback handlers in callback_handler.py
2. CallbackContext dataclass to pass operation data without capturing 'self'
3. Safe callback scheduling with context validation in task_manager.py
4. Proper error handling and user feedback in UI
"""

import bpy

# Import modular components
from .properties import property_classes, PEXELS_State
from .operators import operator_classes
from .ui import ui_classes
from .utils import preview_manager, cleanup_all_temp_files, cleanup_old_temp_files

# Import managers for initialization
from .task_manager import task_manager
from .cache_manager import cache_manager
from .network_manager import network_manager
from .progress_tracker import progress_tracker
from .logger import logger, LogLevel

# Import callback handler module (critical for StructRNA fix)
from . import callback_handler

# Import new cache system components
from .database_manager import database_manager
from .favorites_manager import favorites_manager
from .history_manager import history_manager
from . import ui_cache_browser

# Collect all classes for registration
all_classes = property_classes + operator_classes + ui_classes


def _initialize_managers():
    """Initialize all manager instances."""
    try:
        # Initialize preview manager
        preview_manager.ensure_previews()
        logger.debug("Preview manager initialized")
        
        # Cache manager initializes itself on first access
        # Just verify it's accessible
        cache_dir = cache_manager.get_cache_directory()
        logger.debug(f"Cache manager initialized, directory: {cache_dir}")
        
        # Database manager initializes itself on first access
        db_path = database_manager.get_database_path()
        logger.debug(f"Database manager initialized, path: {db_path}")
        
        # Favorites manager initializes itself on first access
        fav_count = favorites_manager.get_count()
        logger.debug(f"Favorites manager initialized, {fav_count} favorites")
        
        # History manager initializes itself on first access
        history_count = history_manager.get_count()
        logger.debug(f"History manager initialized, {history_count} entries")
        
        # Network manager initializes itself on first access
        # Just verify it's accessible
        online_status = network_manager.is_online_access_enabled()
        logger.debug(f"Network manager initialized, online access enabled: {online_status}")
        
        # Task manager initializes itself on first access
        # Just verify it's running
        is_running = task_manager.is_running()
        logger.debug(f"Task manager initialized, running: {is_running}")
        
        # Progress tracker is ready to use
        logger.debug("Progress tracker initialized")
        
        # Clean up old temp files from previous sessions
        cleanup_old_temp_files(max_age_hours=24.0)
        
        # Run cache cleanup if auto-cleanup is enabled
        try:
            policy = cache_manager.get_retention_policy()
            if policy.auto_cleanup_enabled:
                cache_manager.full_cleanup()
                history_manager.cleanup_old(policy.history_retention_days)
                logger.debug("Auto-cleanup completed")
        except Exception as e:
            logger.warning(f"Auto-cleanup failed: {e}")
        
        logger.info("All managers initialized successfully")
        
    except Exception as e:
        logger.error(f"Error initializing managers: {e}", exception=e)
        raise


def _shutdown_managers():
    """Shutdown all manager instances and cleanup resources."""
    try:
        # Cancel all pending tasks
        try:
            cancelled = task_manager.cancel_all()
            if cancelled > 0:
                logger.info(f"Cancelled {cancelled} pending tasks")
        except Exception as e:
            logger.warning(f"Error cancelling tasks: {e}")
        
        # Shutdown task manager
        try:
            task_manager.shutdown(wait=True, timeout=2.0)
            logger.debug("Task manager shutdown")
        except Exception as e:
            logger.warning(f"Error shutting down task manager: {e}")
        
        # Reset progress tracker
        try:
            progress_tracker.reset()
            progress_tracker.clear_callbacks()
            logger.debug("Progress tracker reset")
        except Exception as e:
            logger.warning(f"Error resetting progress tracker: {e}")
        
        # Clear preview manager
        try:
            preview_manager.clear_previews()
            logger.debug("Preview manager cleared")
        except Exception as e:
            logger.warning(f"Error clearing preview manager: {e}")
        
        # Clean up temp files
        try:
            cleaned = cleanup_all_temp_files()
            if cleaned > 0:
                logger.debug(f"Cleaned up {cleaned} temp files")
        except Exception as e:
            logger.warning(f"Error cleaning temp files: {e}")
        
        # Close database connection
        try:
            database_manager.close()
            logger.debug("Database manager closed")
        except Exception as e:
            logger.warning(f"Error closing database: {e}")
        
        # Note: We don't clear the cache manager on unregister
        # to preserve cached data for next session
        
        # Shutdown logger last
        try:
            logger.info("Pexels extension shutdown complete")
            logger.shutdown()
        except Exception:
            pass
        
    except Exception as e:
        print(f"Pexels Image Search: Error during shutdown - {e}")


def register():
    """Register all addon classes and properties."""
    try:
        # Initialize managers first
        _initialize_managers()
        
        # Register all classes
        for cls in all_classes:
            bpy.utils.register_class(cls)
        
        # Register cache browser UI
        ui_cache_browser.register()
        
        # Add state property to scene
        bpy.types.Scene.pexels_state = bpy.props.PointerProperty(type=PEXELS_State)
        
        logger.info("Pexels Image Search: Registration successful")
        print("Pexels Image Search: Registration successful")
        
    except Exception as e:
        logger.error(f"Registration failed: {e}", exception=e)
        print(f"Pexels Image Search: Registration failed - {e}")
        raise


def unregister():
    """Unregister all addon classes and cleanup."""
    try:
        # Remove scene property
        if hasattr(bpy.types.Scene, "pexels_state"):
            del bpy.types.Scene.pexels_state
        
        # Unregister cache browser UI first
        try:
            ui_cache_browser.unregister()
        except Exception as e:
            logger.warning(f"Error unregistering cache browser: {e}")
        
        # Unregister all classes in reverse order
        for cls in reversed(all_classes):
            try:
                bpy.utils.unregister_class(cls)
            except RuntimeError:
                pass  # Class may already be unregistered
        
        # Shutdown managers
        _shutdown_managers()
        
        print("Pexels Image Search: Unregistration successful")
        
    except Exception as e:
        print(f"Pexels Image Search: Unregistration failed - {e}")
        # Don't raise on unregister to avoid blocking Blender shutdown


if __name__ == "__main__":
    register()
