# SPDX-License-Identifier: GPL-3.0-or-later
"""
Utility functions for file handling, image processing, and Blender operations.

Provides thread-safe utilities for temporary file management, image loading,
plane creation, and preview collection management with proper resource cleanup.
"""

import os
import tempfile
import urllib.parse
import threading
import time
import atexit
from typing import Optional, Set, Dict
from contextlib import contextmanager

from mathutils import Vector
import bpy
import bpy.utils.previews

from .logger import logger


# Thread lock for temp file operations
_temp_file_lock = threading.Lock()

# Track temp files for cleanup
_temp_files: Set[str] = set()
_temp_files_lock = threading.Lock()

# Temp directory path
_temp_dir: Optional[str] = None


def get_temp_directory() -> str:
    """
    Get or create the temporary directory for image caching.
    
    Thread-safe implementation.
    
    Returns:
        Path to temporary directory
    """
    global _temp_dir
    
    with _temp_file_lock:
        if _temp_dir is None or not os.path.exists(_temp_dir):
            _temp_dir = os.path.join(tempfile.gettempdir(), "pexels_import")
            os.makedirs(_temp_dir, exist_ok=True)
        return _temp_dir


def ensure_temp_directory() -> str:
    """
    Create and return temporary directory for image caching.
    
    Alias for get_temp_directory() for backward compatibility.
    
    Returns:
        Path to temporary directory
    """
    return get_temp_directory()


def write_temp_file(filename: str, data: bytes) -> str:
    """
    Write bytes data to temporary file with tracking for cleanup.
    
    Thread-safe implementation with proper error handling.
    
    Args:
        filename: Filename for the temporary file
        data: Data to write
    
    Returns:
        Path to the created temporary file
        
    Raises:
        IOError: If file cannot be written
    """
    temp_dir = get_temp_directory()
    
    # Sanitize filename
    safe_filename = "".join(c for c in filename if c.isalnum() or c in '._-')
    if not safe_filename:
        safe_filename = f"pexels_{int(time.time())}.tmp"
    
    file_path = os.path.join(temp_dir, safe_filename)
    
    with _temp_file_lock:
        try:
            with open(file_path, "wb") as f:
                f.write(data)
            
            # Track file for cleanup
            with _temp_files_lock:
                _temp_files.add(file_path)
            
            logger.debug(f"Wrote temp file: {file_path}", size_bytes=len(data))
            return file_path
            
        except IOError as e:
            logger.error(f"Failed to write temp file: {file_path}", exception=e)
            raise


def cleanup_temp_file(file_path: str) -> bool:
    """
    Remove a specific temporary file.
    
    Args:
        file_path: Path to file to remove
        
    Returns:
        True if file was removed
    """
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            
            with _temp_files_lock:
                _temp_files.discard(file_path)
            
            logger.debug(f"Cleaned up temp file: {file_path}")
            return True
    except OSError as e:
        logger.warning(f"Failed to cleanup temp file: {file_path}", exception=e)
    
    return False


def cleanup_all_temp_files() -> int:
    """
    Remove all tracked temporary files.
    
    Returns:
        Number of files removed
    """
    removed_count = 0
    
    with _temp_files_lock:
        files_to_remove = list(_temp_files)
    
    for file_path in files_to_remove:
        if cleanup_temp_file(file_path):
            removed_count += 1
    
    logger.info(f"Cleaned up {removed_count} temp files")
    return removed_count


def cleanup_old_temp_files(max_age_hours: float = 24.0) -> int:
    """
    Remove temporary files older than max_age_hours.
    
    Args:
        max_age_hours: Maximum age in hours
        
    Returns:
        Number of files removed
    """
    removed_count = 0
    temp_dir = get_temp_directory()
    max_age_seconds = max_age_hours * 3600
    current_time = time.time()
    
    try:
        for filename in os.listdir(temp_dir):
            file_path = os.path.join(temp_dir, filename)
            
            try:
                if os.path.isfile(file_path):
                    file_age = current_time - os.path.getmtime(file_path)
                    if file_age > max_age_seconds:
                        os.remove(file_path)
                        removed_count += 1
                        
                        with _temp_files_lock:
                            _temp_files.discard(file_path)
            except OSError:
                pass
    except OSError as e:
        logger.warning(f"Error cleaning old temp files", exception=e)
    
    if removed_count > 0:
        logger.info(f"Cleaned up {removed_count} old temp files")
    
    return removed_count


def extract_filename_from_url(url: str, fallback: str = "pexels.jpg") -> str:
    """
    Extract filename from URL or return fallback.
    
    Args:
        url: URL to extract filename from
        fallback: Fallback filename if extraction fails
    
    Returns:
        Extracted or fallback filename
    """
    try:
        parsed = urllib.parse.urlparse(url)
        filename = os.path.basename(parsed.path)
        
        # Remove query parameters from filename
        if '?' in filename:
            filename = filename.split('?')[0]
        
        return filename if filename else fallback
    except Exception:
        return fallback


def load_image_from_url(url: str, use_cache: bool = True) -> bpy.types.Image:
    """
    Download and load image from URL into Blender.
    
    Uses CacheManager for caching when available.
    
    Args:
        url: Image URL to download
        use_cache: Whether to use caching
    
    Returns:
        Loaded Blender image
    
    Raises:
        Exception: If download or loading fails
    """
    from .api import download_image, USER_AGENT
    
    # Try to use cache manager
    if use_cache:
        try:
            from .cache_manager import cache_manager
            
            # Check cache first
            cached_path = cache_manager.get_file_path(url, variant="full")
            if cached_path and os.path.exists(cached_path):
                logger.debug(f"Loading image from cache: {cached_path}")
                return bpy.data.images.load(cached_path, check_existing=False)
        except ImportError:
            pass
    
    # Download image
    image_data = download_image(url, headers={"User-Agent": USER_AGENT})
    
    # Try to cache the image
    if use_cache:
        try:
            from .cache_manager import cache_manager
            cache_manager.put(url, image_data, variant="full")
            
            # Load from cache path
            cached_path = cache_manager.get_file_path(url, variant="full")
            if cached_path and os.path.exists(cached_path):
                return bpy.data.images.load(cached_path, check_existing=False)
        except ImportError:
            pass
    
    # Fallback to temp file
    filename = extract_filename_from_url(url)
    temp_path = write_temp_file(filename, image_data)
    return bpy.data.images.load(temp_path, check_existing=False)


def create_material_for_image(image: bpy.types.Image) -> bpy.types.Material:
    """
    Create a material with the given image texture.
    
    Args:
        image: Blender image to create material for
    
    Returns:
        Created material with image texture
    """
    material = bpy.data.materials.new(name=f"Mat_{image.name}")
    material.use_nodes = True
    
    # Clear existing nodes
    node_tree = material.node_tree
    for node in list(node_tree.nodes):
        node_tree.nodes.remove(node)
    
    # Create shader nodes
    output_node = node_tree.nodes.new("ShaderNodeOutputMaterial")
    bsdf_node = node_tree.nodes.new("ShaderNodeBsdfPrincipled")
    texture_node = node_tree.nodes.new("ShaderNodeTexImage")
    
    # Configure texture node
    texture_node.image = image
    texture_node.interpolation = 'Smart'
    
    # Link nodes
    node_tree.links.new(bsdf_node.outputs["BSDF"], output_node.inputs["Surface"])
    node_tree.links.new(texture_node.outputs["Color"], bsdf_node.inputs["Base Color"])
    node_tree.links.new(texture_node.outputs["Alpha"], bsdf_node.inputs["Alpha"])
    
    # Set material properties
    material.blend_method = 'CLIP'
    
    return material


def create_plane_with_image(image: bpy.types.Image, size: float = 2.0) -> Optional[bpy.types.Object]:
    """
    Create a plane object with the given image as texture.
    
    Args:
        image: Blender image to apply to plane
        size: Height of the plane in Blender units
    
    Returns:
        Created plane object with image texture, or None on failure
    """
    # Try using Images as Planes addon if available
    result = try_import_with_images_as_planes(image)
    if result:
        return bpy.context.active_object
    
    # Fallback: Create plane manually
    return create_plane_manual(image, size)


def try_import_with_images_as_planes(image: bpy.types.Image) -> bool:
    """
    Try to use the Images as Planes addon for importing.
    
    Args:
        image: Image to import
    
    Returns:
        True if successful, False otherwise
    """
    try:
        if "io_import_images_as_planes" in bpy.context.preferences.addons:
            bpy.ops.import_image.to_plane(
                files=[{"name": os.path.basename(image.filepath)}],
                directory=os.path.dirname(image.filepath),
                relative=False
            )
            return True
    except Exception as e:
        logger.debug(f"Images as Planes import failed: {e}")
    return False


def create_plane_manual(image: bpy.types.Image, size: float = 2.0) -> Optional[bpy.types.Object]:
    """
    Manually create a plane with image texture.
    
    Args:
        image: Image to apply to plane
        size: Height of the plane
    
    Returns:
        Created plane object, or None on failure
    """
    try:
        # Calculate aspect ratio with safe defaults
        width = image.size[0] if image.size[0] > 0 else 1
        height = image.size[1] if image.size[1] > 0 else 1
        aspect_ratio = width / height
        
        # Calculate plane dimensions
        plane_width = size * aspect_ratio
        plane_height = size
        
        # Create mesh
        mesh = bpy.data.meshes.new(f"Plane_{image.name}")
        vertices = [
            (-plane_width, -plane_height, 0),
            (plane_width, -plane_height, 0),
            (plane_width, plane_height, 0),
            (-plane_width, plane_height, 0)
        ]
        faces = [(0, 1, 2, 3)]
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        
        # Create UV mapping
        create_uv_mapping(mesh)
        
        # Create object and add to scene
        obj = bpy.data.objects.new(f"Plane_{image.name}", mesh)
        bpy.context.scene.collection.objects.link(obj)
        
        # Apply material
        material = create_material_for_image(image)
        if obj.data.materials:
            obj.data.materials[0] = material
        else:
            obj.data.materials.append(material)
        
        return obj
        
    except Exception as e:
        logger.error(f"Failed to create plane: {e}", exception=e)
        return None


def create_uv_mapping(mesh: bpy.types.Mesh) -> None:
    """
    Create UV mapping for a plane mesh.
    
    Args:
        mesh: Mesh to create UV mapping for
    """
    mesh.uv_layers.new(name="UVMap")
    uv_layer = mesh.uv_layers.active.data
    
    # Set UV coordinates for plane
    uv_coordinates = [
        Vector((0, 0)),  # Bottom-left
        Vector((1, 0)),  # Bottom-right
        Vector((1, 1)),  # Top-right
        Vector((0, 1))   # Top-left
    ]
    
    for i, coord in enumerate(uv_coordinates):
        uv_layer[i].uv = coord


class PreviewManager:
    """
    Thread-safe manager for Blender preview collections.
    
    Handles preview loading, caching, and cleanup with proper
    resource management to prevent memory leaks.
    """
    
    def __init__(self):
        self._previews: Optional[bpy.utils.previews.ImagePreviewCollection] = None
        self._lock = threading.RLock()
        self._loaded_ids: Set[str] = set()
    
    def ensure_previews(self) -> None:
        """Ensure preview collection exists. Thread-safe."""
        with self._lock:
            if self._previews is None:
                self._previews = bpy.utils.previews.new()
                logger.debug("Preview collection created")
    
    def clear_previews(self) -> None:
        """Clear and remove preview collection. Thread-safe."""
        with self._lock:
            if self._previews is not None:
                try:
                    bpy.utils.previews.remove(self._previews)
                except Exception as e:
                    logger.warning(f"Error removing preview collection: {e}")
                finally:
                    self._previews = None
                    self._loaded_ids.clear()
                    logger.debug("Preview collection cleared")
    
    def load_preview(self, image_id: str, image_path: str) -> bool:
        """
        Load image preview. Thread-safe.
        
        Args:
            image_id: Unique identifier for the image
            image_path: Path to the image file
            
        Returns:
            True if preview was loaded successfully
        """
        with self._lock:
            if self._previews is None:
                self.ensure_previews()
            
            if self._previews is None:
                return False
            
            try:
                # Check if already loaded
                if image_id in self._loaded_ids:
                    return True
                
                # Verify file exists
                if not os.path.exists(image_path):
                    logger.warning(f"Preview image not found: {image_path}")
                    return False
                
                self._previews.load(image_id, image_path, 'IMAGE')
                self._loaded_ids.add(image_id)
                logger.debug(f"Loaded preview: {image_id}")
                return True
                
            except Exception as e:
                logger.warning(f"Failed to load preview {image_id}: {e}")
                return False
    
    def get_preview_icon(self, image_id: str) -> int:
        """
        Get preview icon ID. Thread-safe.

        Args:
            image_id: Image identifier

        Returns:
            Icon ID or 0 if not found
        """
        with self._lock:
            if self._previews is None:
                return 0
            
            if image_id not in self._previews:
                return 0
            
            try:
                icon_id = self._previews[image_id].icon_id
                # Ensure icon_id is never None - return 0 if None or not an integer
                if icon_id is None:
                    return 0
                return int(icon_id)
            except (TypeError, ValueError, KeyError):
                return 0
    
    def has_preview(self, image_id: str) -> bool:
        """
        Check if preview exists. Thread-safe.
        
        Args:
            image_id: Image identifier
        
        Returns:
            True if preview exists
        """
        with self._lock:
            return (
                self._previews is not None and 
                image_id in self._previews and
                image_id in self._loaded_ids
            )
    
    def remove_preview(self, image_id: str) -> bool:
        """
        Remove a specific preview. Thread-safe.
        
        Args:
            image_id: Image identifier
            
        Returns:
            True if preview was removed
        """
        with self._lock:
            if self._previews is None:
                return False
            
            if image_id in self._loaded_ids:
                self._loaded_ids.discard(image_id)
                # Note: Blender's preview collection doesn't support removing individual items
                # We just track that it's no longer valid
                return True
            
            return False
    
    def get_loaded_count(self) -> int:
        """
        Get number of loaded previews. Thread-safe.
        
        Returns:
            Number of loaded previews
        """
        with self._lock:
            return len(self._loaded_ids)


# Global preview manager instance
preview_manager = PreviewManager()


# ============================================================================
# Formatting Helper Functions
# ============================================================================

def format_eta(seconds: int) -> str:
    """
    Format seconds as human-readable time.
    
    Args:
        seconds: Time in seconds
        
    Returns:
        Formatted time string (e.g., '2m 30s', '1h 15m', '45s')
    """
    if seconds <= 0:
        return "Almost done..."
    
    if seconds < 60:
        return f"{int(seconds)}s remaining"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        secs = int(seconds % 60)
        if secs > 0:
            return f"{minutes}m {secs}s remaining"
        return f"{minutes}m remaining"
    else:
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        if minutes > 0:
            return f"{hours}h {minutes}m remaining"
        return f"{hours}h remaining"


def format_speed(bytes_per_sec: float) -> str:
    """
    Format download speed as human-readable string.
    
    Args:
        bytes_per_sec: Speed in bytes per second
        
    Returns:
        Formatted speed string (e.g., '1.5 MB/s', '256 KB/s', '512 B/s')
    """
    if bytes_per_sec <= 0:
        return "0 B/s"
    
    # Define units
    units = [
        (1024 ** 3, "GB/s"),
        (1024 ** 2, "MB/s"),
        (1024, "KB/s"),
        (1, "B/s")
    ]
    
    for threshold, unit in units:
        if bytes_per_sec >= threshold:
            value = bytes_per_sec / threshold
            if value >= 100:
                return f"{int(value)} {unit}"
            elif value >= 10:
                return f"{value:.1f} {unit}"
            else:
                return f"{value:.2f} {unit}"
    
    return f"{int(bytes_per_sec)} B/s"


def truncate_filename(filename: str, max_length: int = 30) -> str:
    """
    Truncate long filenames with ellipsis in the middle.
    
    Args:
        filename: Filename to truncate
        max_length: Maximum length of the result
        
    Returns:
        Truncated filename with ellipsis if needed
    """
    if not filename:
        return ""
    
    if len(filename) <= max_length:
        return filename
    
    if max_length < 10:
        # Too short for meaningful truncation
        return filename[:max_length]
    
    # Keep extension visible
    ext_start = filename.rfind('.')
    if ext_start > 0 and len(filename) - ext_start <= 6:
        # Has a reasonable extension
        ext = filename[ext_start:]
        name = filename[:ext_start]
        
        # Calculate how much of the name we can keep
        available = max_length - len(ext) - 3  # 3 for "..."
        if available > 0:
            half = available // 2
            return f"{name[:half]}...{name[-half:]}{ext}" if half > 0 else f"...{ext}"
    
    # No extension or very long extension - simple truncation
    half = (max_length - 3) // 2
    return f"{filename[:half]}...{filename[-half:]}"


def format_file_size(size_bytes: int) -> str:
    """
    Format file size as human-readable string.
    
    Args:
        size_bytes: Size in bytes
        
    Returns:
        Formatted size string (e.g., '1.5 MB', '256 KB', '512 B')
    """
    if size_bytes <= 0:
        return "0 B"
    
    units = [
        (1024 ** 3, "GB"),
        (1024 ** 2, "MB"),
        (1024, "KB"),
        (1, "B")
    ]
    
    for threshold, unit in units:
        if size_bytes >= threshold:
            value = size_bytes / threshold
            if value >= 100:
                return f"{int(value)} {unit}"
            elif value >= 10:
                return f"{value:.1f} {unit}"
            else:
                return f"{value:.2f} {unit}"
    
    return f"{int(size_bytes)} B"


def format_progress_items(done: int, total: int) -> str:
    """
    Format progress as 'X of Y items' string.
    
    Args:
        done: Number of completed items
        total: Total number of items
        
    Returns:
        Formatted progress string (e.g., '45 of 100 images')
    """
    if total <= 0:
        return "0 items"
    
    return f"{done} of {total} images"


# Register cleanup on exit
def _cleanup_on_exit():
    """Cleanup function called on exit."""
    try:
        cleanup_all_temp_files()
    except Exception:
        pass


atexit.register(_cleanup_on_exit)
