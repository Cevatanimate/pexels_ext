# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
import os
import io
import json
import tempfile
import urllib.request
import urllib.parse
from mathutils import Vector
import bpy.utils.previews

# -------------------- Consts --------------------
PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
USER_AGENT = "Blender/{major}.{minor} PexelsImageSearch/1.0".format(
    major=bpy.app.version[0], minor=bpy.app.version[1]
)

# Global previews collection
_previews = None  # type: bpy.utils.previews.ImagePreviewCollection

# -------------------- Networking --------------------
def _http_get(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()

def _http_json(url, headers=None, q=None, timeout=30):
    if q:
        url = url + "?" + urllib.parse.urlencode(q)
    data = _http_get(url, headers=headers, timeout=timeout)
    return json.loads(data.decode("utf-8"))

# -------------------- Temp / Image helpers --------------------
def _ensure_tmp_dir():
    tmp = os.path.join(tempfile.gettempdir(), "pexels_import")
    os.makedirs(tmp, exist_ok=True)
    return tmp

def _write_temp_bytes(name, data: bytes):
    path = os.path.join(_ensure_tmp_dir(), name)
    with open(path, "wb") as f:
        f.write(data)
    return path

def _load_image_from_url(url: str):
    data = _http_get(url, headers={"User-Agent": USER_AGENT})
    # extract filename from url or fallback
    filename = os.path.basename(urllib.parse.urlparse(url).path) or "pexels.jpg"
    path = _write_temp_bytes(filename, data)
    return bpy.data.images.load(path, check_existing=False)

def _ensure_material_for_image(img: bpy.types.Image):
    mat = bpy.data.materials.new(name=f"Mat_{img.name}")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.interpolation = 'Smart'
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    mat.blend_method = 'CLIP'
    return mat

def _add_plane_with_image(img: bpy.types.Image, fit=2.0):
    # Try Images as Planes first
    try:
        if "io_import_images_as_planes" in bpy.context.preferences.addons:
            bpy.ops.import_image.to_plane(
                files=[{"name": os.path.basename(img.filepath)}],
                directory=os.path.dirname(img.filepath),
                relative=False
            )
            return bpy.context.active_object
    except Exception:
        pass

    # Fallback: create plane and UV map
    w = img.size[0] or 1
    h = img.size[1] or 1
    aspect = w / h
    sx, sy = fit * aspect, fit

    mesh = bpy.data.meshes.new(f"Plane_{img.name}")
    verts = [(-sx, -sy, 0), (sx, -sy, 0), (sx, sy, 0), (-sx, sy, 0)]
    faces = [(0, 1, 2, 3)]
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    # UVs
    mesh.uv_layers.new(name="UVMap")
    uv = mesh.uv_layers.active.data
    uv[0].uv = Vector((0, 0))
    uv[1].uv = Vector((1, 0))
    uv[2].uv = Vector((1, 1))
    uv[3].uv = Vector((0, 1))

    ob = bpy.data.objects.new(f"Plane_{img.name}", mesh)
    bpy.context.scene.collection.objects.link(ob)

    mat = _ensure_material_for_image(img)
    if ob.data.materials:
        ob.data.materials[0] = mat
    else:
        ob.data.materials.append(mat)
    return ob

# -------------------- Previews helpers --------------------
def ensure_previews():
    global _previews
    if _previews is None:
        _previews = bpy.utils.previews.new()

def clear_previews():
    global _previews
    if _previews is not None:
        # remove and recreate for a clean state
        bpy.utils.previews.remove(_previews)
        _previews = None

# -------------------- Preferences --------------------
class PEXELS_AddonPrefs(bpy.types.AddonPreferences):
    bl_idname = __name__

    api_key: bpy.props.StringProperty(
        name="Pexels API Key",
        description="Get your free API key at https://www.pexels.com/api/new/",
        subtype='PASSWORD',
    )
    max_results: bpy.props.IntProperty(
        name="Results per page", 
        description="Number of images to fetch per search (1-80)",
        default=50, 
        min=1, 
        max=80
    )

    def draw(self, ctx):
        layout = self.layout
        
        main_col = layout.column()
        
        # API Key section
        key_box = main_col.box()
        key_box.label(text="🔑 API Configuration", icon='KEYFRAME_HLT')
        key_box.prop(self, "api_key")
        
        if not self.api_key:
            warning_row = key_box.row()
            warning_row.alert = True
            warning_row.label(text="⚠ API key required to search images", icon='ERROR')
        
        info_col = key_box.column(align=True)
        info_col.label(text="Get your free API key at:")
        info_col.label(text="https://www.pexels.com/api/new/")
        
        # Settings section
        settings_box = main_col.box()
        settings_box.label(text="⚙ Search Settings", icon='PREFERENCES')
        settings_box.prop(self, "max_results")
        
        # Usage info
        usage_box = main_col.box()
        usage_box.label(text="📖 How to Use", icon='QUESTION')
        usage_col = usage_box.column(align=True)
        usage_col.label(text="1. Set your API key above")
        usage_col.label(text="2. Open 3D View > N-Panel > Pexels tab")
        usage_col.label(text="3. Search and import high-quality images")
        usage_col.label(text="4. All images are free to use commercially")

# -------------------- Data Model --------------------
class PEXELS_Item(bpy.types.PropertyGroup):
    item_id: bpy.props.IntProperty()
    thumb_url: bpy.props.StringProperty()
    full_url: bpy.props.StringProperty()
    photographer: bpy.props.StringProperty()
    width: bpy.props.IntProperty()
    height: bpy.props.IntProperty()

def pexels_enum_items(self, context):
    """EnumProperty items callback for template_icon_view."""
    items = []
    if _previews is None:
        return items
    st = context.scene.pexels_state
    for i, it in enumerate(st.items):
        key = str(it.item_id)
        if key in _previews:
            icon_id = _previews[key].icon_id
            # (identifier, name, description, icon, number)
            items.append((key, f"{it.item_id}", it.photographer or "", icon_id, i))
    return items

class PEXELS_State(bpy.types.PropertyGroup):
    query: bpy.props.StringProperty(
        name="Search", 
        default="",
        description="Enter keywords to search for images (e.g., 'nature', 'architecture', 'abstract')"
    )
    page: bpy.props.IntProperty(default=1, min=1)
    total_results: bpy.props.IntProperty(default=0)
    is_loading: bpy.props.BoolProperty(default=False)

    # Search results
    items: bpy.props.CollectionProperty(type=PEXELS_Item)

    # Selected preview key (Pexels id as string)
    selected_icon: bpy.props.EnumProperty(
        name="Results",
        items=pexels_enum_items
    )

# -------------------- Operators --------------------
class PEXELS_OT_Search(bpy.types.Operator):
    bl_idname = "pexels.search"
    bl_label = "Search Pexels"
    bl_description = "Search for images on Pexels using the entered keywords"
    bl_options = {'REGISTER', 'INTERNAL'}

    def execute(self, ctx):
        scn = ctx.scene
        st = scn.pexels_state
        prefs = ctx.preferences.addons[__name__].preferences

        if not prefs.api_key:
            self.report({'ERROR'}, "Set Pexels API key in Add-on Preferences.")
            return {'CANCELLED'}
        if not st.query.strip():
            self.report({'WARNING'}, "Enter a search keyword.")
            return {'CANCELLED'}

        st.is_loading = True
        try:
            # reset state
            st.items.clear()
            st.total_results = 0
            clear_previews()
            ensure_previews()

            headers = {
                "Authorization": prefs.api_key,
                "User-Agent": USER_AGENT,
            }
            q = {
                "query": st.query,
                "page": st.page,
                "per_page": prefs.max_results
            }
            data = _http_json(PEXELS_SEARCH_URL, headers=headers, q=q)

            st.total_results = int(data.get("total_results", 0))
            photos = data.get("photos", []) or []

            for p in photos:
                it = st.items.add()
                it.item_id = int(p.get("id", 0))
                src = p.get("src", {}) or {}
                it.thumb_url = src.get("medium") or src.get("small") or src.get("tiny") or ""
                it.full_url = src.get("large2x") or src.get("original") or src.get("large") or ""
                it.photographer = p.get("photographer", "")
                it.width = int(p.get("width", 0) or 0)
                it.height = int(p.get("height", 0) or 0)

                if it.thumb_url:
                    try:
                        thumb_bytes = _http_get(it.thumb_url, headers={"User-Agent": USER_AGENT})
                        thumb_path = _write_temp_bytes(f"pexels_{it.item_id}_th.jpg", thumb_bytes)
                        _previews.load(str(it.item_id), thumb_path, 'IMAGE')
                    except Exception:
                        # ignore thumb failures
                        pass

            # default selection
            st.selected_icon = str(st.items[0].item_id) if len(st.items) else ""
            self.report({'INFO'}, f"Found {len(photos)} images (Total: {st.total_results})")
        except Exception as e:
            self.report({'ERROR'}, f"Search failed: {e}")
            return {'CANCELLED'}
        finally:
            st.is_loading = False

        return {'FINISHED'}

class PEXELS_OT_Page(bpy.types.Operator):
    bl_idname = "pexels.page"
    bl_label = "Change Page"
    bl_description = "Navigate to the previous or next page of search results"
    bl_options = {'INTERNAL'}

    dir: bpy.props.EnumProperty(
        items=[('PREV', 'Prev', 'Previous page'), ('NEXT', 'Next', 'Next page')],
        name="Direction"
    )

    def execute(self, ctx):
        st = ctx.scene.pexels_state
        if self.dir == 'PREV' and st.page > 1:
            st.page -= 1
        elif self.dir == 'NEXT':
            st.page += 1
        return bpy.ops.pexels.search('INVOKE_DEFAULT')

class PEXELS_OT_Import(bpy.types.Operator):
    bl_idname = "pexels.import_image"
    bl_label = "Import Selected Image"
    bl_description = "Import the selected image into Blender"
    bl_options = {'REGISTER', 'UNDO'}

    as_plane: bpy.props.BoolProperty(
        name="Add as Plane", 
        description="Create a plane object with the image texture applied",
        default=True
    )
    fit_size: bpy.props.FloatProperty(
        name="Plane Height", 
        description="Height of the created plane in Blender units",
        default=2.0, 
        min=0.01, 
        max=100.0
    )

    def execute(self, ctx):
        st = ctx.scene.pexels_state
        if not st.selected_icon:
            self.report({'WARNING'}, "No image selected.")
            return {'CANCELLED'}
        try:
            sel_id = int(st.selected_icon)
        except ValueError:
            self.report({'WARNING'}, "Invalid selection.")
            return {'CANCELLED'}

        it = next((x for x in st.items if x.item_id == sel_id), None)
        if not it or not it.full_url:
            self.report({'WARNING'}, "No image URL for selection.")
            return {'CANCELLED'}

        try:
            img = _load_image_from_url(it.full_url)
            img.name = f"Pexels_{it.item_id}"
            if self.as_plane:
                ob = _add_plane_with_image(img, fit=self.fit_size)
                if ob:
                    ob.select_set(True)
                    ctx.view_layer.objects.active = ob
            self.report({'INFO'}, f"Imported: {it.photographer}'s image (ID: {it.item_id})")
        except Exception as e:
            self.report({'ERROR'}, f"Import failed: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}

# -------------------- UI Panel --------------------
class PEXELS_PT_Panel(bpy.types.Panel):
    bl_label = "Pexels Image Search"
    bl_idname = "PEXELS_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Pexels"

    def draw(self, ctx):
        layout = self.layout
        st = ctx.scene.pexels_state
        prefs = ctx.preferences.addons[__name__].preferences

        # Check if API key is set
        if not prefs.api_key:
            box = layout.box()
            box.label(text="⚠ API Key Required", icon='ERROR')
            box.label(text="Set your Pexels API key in")
            box.label(text="Add-on Preferences first")
            box.operator("preferences.addon_show", text="Open Preferences", icon='PREFERENCES').module = __name__
            return

        # Search section
        search_box = layout.box()
        search_box.label(text="🔍 Search Images", icon='VIEWZOOM')
        
        col = search_box.column(align=True)
        col.prop(st, "query", text="Keywords")
        
        row = col.row(align=True)
        row.operator("pexels.search", text="Search", icon='VIEWZOOM')
        
        # Results info and pagination
        if st.total_results > 0:
            info_row = search_box.row(align=True)
            info_row.label(text=f"📊 Results: {len(st.items)} / {st.total_results}")
            
            # Pagination controls
            nav_row = search_box.row(align=True)
            nav_row.label(text=f"Page {st.page}")
            
            if st.page > 1:
                prev_op = nav_row.operator("pexels.page", text="← Prev", icon='TRIA_LEFT')
                prev_op.dir = 'PREV'
            else:
                nav_row.label(text="")  # Empty space for alignment
            
            next_op = nav_row.operator("pexels.page", text="Next →", icon='TRIA_RIGHT')
            next_op.dir = 'NEXT'
            
            # Settings row
            settings_row = search_box.row(align=True)
            settings_row.prop(prefs, "max_results", text="Per Page")

        # Loading indicator
        if st.is_loading:
            loading_box = layout.box()
            loading_box.label(text="🔄 Loading images...", icon='FILE_REFRESH')
            return

        # Results section
        if len(st.items) > 0:
            results_box = layout.box()
            results_box.label(text="📷 Image Gallery", icon='IMAGE_DATA')
            
            # Image preview grid with larger scale for better visibility
            results_box.template_icon_view(st, "selected_icon", show_labels=False, scale=7.0, scale_popup=10.0)

            # Selected image details and import options
            if st.selected_icon:
                try:
                    sid = int(st.selected_icon)
                except ValueError:
                    sid = None
                it = next((x for x in st.items if x.item_id == sid), None)
                if it:
                    detail_box = layout.box()
                    detail_box.label(text="📋 Image Details", icon='INFO')
                    
                    info_col = detail_box.column(align=True)
                    info_col.label(text=f"ID: {it.item_id}")
                    info_col.label(text=f"Size: {it.width} × {it.height} pixels")
                    if it.photographer:
                        info_col.label(text=f"📸 Photo by: {it.photographer}")
                    
                    # Import options
                    import_box = layout.box()
                    import_box.label(text="⬇ Import Options", icon='IMPORT')
                    
                    # Primary import button (as plane)
                    import_box.operator("pexels.import_image", text="Import as Plane", icon='MESH_PLANE')
                    
                    # Secondary import button (image only)
                    image_op = import_box.operator("pexels.import_image", text="Import Image Only", icon='IMAGE_DATA')
                    image_op.as_plane = False
        
        elif st.query and not st.is_loading:
            # No results found
            no_results_box = layout.box()
            no_results_box.label(text="😔 No images found", icon='ERROR')
            no_results_box.label(text="Try different keywords")
        
        # Help section
        if not st.items and not st.query:
            help_box = layout.box()
            help_box.label(text="💡 Tips:", icon='QUESTION')
            help_col = help_box.column(align=True)
            help_col.label(text="• Enter keywords like 'nature'")
            help_col.label(text="• Use specific terms for better results")
            help_col.label(text="• All images are free to use")

# -------------------- Registration --------------------
classes = (
    PEXELS_AddonPrefs,
    PEXELS_Item,
    PEXELS_State,
    PEXELS_OT_Search,
    PEXELS_OT_Page,
    PEXELS_OT_Import,
    PEXELS_PT_Panel,
)

def register():
    ensure_previews()
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.pexels_state = bpy.props.PointerProperty(type=PEXELS_State)

def unregister():
    del bpy.types.Scene.pexels_state
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    clear_previews()

if __name__ == "__main__":
    register()
