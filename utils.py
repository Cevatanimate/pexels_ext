# SPDX-License-Identifier: GPL-3.0-or-later
"""
Utility functions for file handling, image processing, and Blender operations
"""

import os
import tempfile
import urllib.parse
from mathutils import Vector
import bpy
import bpy.utils.previews
from .api import download_image, USER_AGENT


def ensure_temp_directory():
    """Create and return temporary directory for image caching"""
    temp_dir = os.path.join(tempfile.gettempdir(), "pexels_import")
    os.makedirs(temp_dir, exist_ok=True)
    return temp_dir


def write_temp_file(filename, data: bytes):
    """
    Write bytes data to temporary file
    
    Args:
        filename (str): Filename for the temporary file
        data (bytes): Data to write
    
    Returns:
        str: Path to the created temporary file
    """
    file_path = os.path.join(ensure_temp_directory(), filename)
    with open(file_path, "wb") as f:
        f.write(data)
    return file_path


def extract_filename_from_url(url: str, fallback="pexels.jpg"):
    """
    Extract filename from URL or return fallback
    
    Args:
        url (str): URL to extract filename from
        fallback (str): Fallback filename if extraction fails
    
    Returns:
        str: Extracted or fallback filename
    """
    try:
        parsed = urllib.parse.urlparse(url)
        filename = os.path.basename(parsed.path)
        return filename if filename else fallback
    except Exception:
        return fallback


def load_image_from_url(url: str):
    """
    Download and load image from URL into Blender
    
    Args:
        url (str): Image URL to download
    
    Returns:
        bpy.types.Image: Loaded Blender image
    
    Raises:
        Exception: If download or loading fails
    """
    image_data = download_image(url, headers={"User-Agent": USER_AGENT})
    filename = extract_filename_from_url(url)
    temp_path = write_temp_file(filename, image_data)
    return bpy.data.images.load(temp_path, check_existing=False)


def create_material_for_image(image: bpy.types.Image):
    """
    Create a material with the given image texture
    
    Args:
        image (bpy.types.Image): Blender image to create material for
    
    Returns:
        bpy.types.Material: Created material with image texture
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


def create_plane_with_image(image: bpy.types.Image, size=2.0):
    """
    Create a plane object with the given image as texture
    
    Args:
        image (bpy.types.Image): Blender image to apply to plane
        size (float): Height of the plane in Blender units
    
    Returns:
        bpy.types.Object: Created plane object with image texture
    """
    # Try using Images as Planes addon if available
    if try_import_with_images_as_planes(image):
        return bpy.context.active_object
    
    # Fallback: Create plane manually
    return create_plane_manual(image, size)


def try_import_with_images_as_planes(image: bpy.types.Image):
    """
    Try to use the Images as Planes addon for importing
    
    Args:
        image (bpy.types.Image): Image to import
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        if "io_import_images_as_planes" in bpy.context.preferences.addons:
            bpy.ops.import_image.to_plane(
                files=[{"name": os.path.basename(image.filepath)}],
                directory=os.path.dirname(image.filepath),
                relative=False
            )
            return True
    except Exception:
        pass
    return False


def create_plane_manual(image: bpy.types.Image, size=2.0):
    """
    Manually create a plane with image texture
    
    Args:
        image (bpy.types.Image): Image to apply to plane
        size (float): Height of the plane
    
    Returns:
        bpy.types.Object: Created plane object
    """
    # Calculate aspect ratio
    width = image.size[0] or 1
    height = image.size[1] or 1
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


def create_uv_mapping(mesh):
    """
    Create UV mapping for a plane mesh
    
    Args:
        mesh (bpy.types.Mesh): Mesh to create UV mapping for
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
    """Manager for Blender preview collections"""
    
    def __init__(self):
        self._previews = None
    
    def ensure_previews(self):
        """Ensure preview collection exists"""
        if self._previews is None:
            self._previews = bpy.utils.previews.new()
    
    def clear_previews(self):
        """Clear and remove preview collection"""
        if self._previews is not None:
            bpy.utils.previews.remove(self._previews)
            self._previews = None
    
    def load_preview(self, image_id: str, image_path: str):
        """
        Load image preview
        
        Args:
            image_id (str): Unique identifier for the image
            image_path (str): Path to the image file
        """
        if self._previews is not None:
            self._previews.load(image_id, image_path, 'IMAGE')
    
    def get_preview_icon(self, image_id: str):
        """
        Get preview icon ID
        
        Args:
            image_id (str): Image identifier
        
        Returns:
            int: Icon ID or 0 if not found
        """
        if self._previews is not None and image_id in self._previews:
            return self._previews[image_id].icon_id
        return 0
    
    def has_preview(self, image_id: str):
        """
        Check if preview exists
        
        Args:
            image_id (str): Image identifier
        
        Returns:
            bool: True if preview exists
        """
        return self._previews is not None and image_id in self._previews


# Global preview manager instance
preview_manager = PreviewManager()
