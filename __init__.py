# SPDX-License-Identifier: GPL-3.0-or-later
"""
Pexels Image Search - Blender Extension
Search, preview, and import high-quality images from Pexels
"""

import bpy

# Import modular components
from .properties import property_classes, PEXELS_State
from .operators import operator_classes
from .ui import ui_classes
from .utils import preview_manager

# Collect all classes for registration
all_classes = property_classes + operator_classes + ui_classes


def register():
    """Register all addon classes and properties"""
    try:
        # Initialize preview manager
        preview_manager.ensure_previews()
        
        # Register all classes
        for cls in all_classes:
            bpy.utils.register_class(cls)
        
        # Add state property to scene
        bpy.types.Scene.pexels_state = bpy.props.PointerProperty(type=PEXELS_State)
        
        print("Pexels Image Search: Registration successful")
    except Exception as e:
        print(f"Pexels Image Search: Registration failed - {e}")
        raise


def unregister():
    """Unregister all addon classes and cleanup"""
    try:
        # Remove scene property
        if hasattr(bpy.types.Scene, "pexels_state"):
            del bpy.types.Scene.pexels_state
        
        # Unregister all classes in reverse order
        for cls in reversed(all_classes):
            try:
                bpy.utils.unregister_class(cls)
            except RuntimeError:
                pass  # Class may already be unregistered
        
        # Clean up preview manager
        preview_manager.clear_previews()
        
        print("Pexels Image Search: Unregistration successful")
    except Exception as e:
        print(f"Pexels Image Search: Unregistration failed - {e}")
        # Don't raise on unregister to avoid blocking Blender shutdown


if __name__ == "__main__":
    register()
