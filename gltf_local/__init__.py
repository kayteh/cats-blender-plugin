import json, os, struct

import bpy
from bpy.props import StringProperty, BoolProperty, FloatProperty, EnumProperty
from bpy_extras.io_utils import ImportHelper
from mathutils import Euler
import importlib

if "gltf_local" not in locals():
    import gltf_local.animation
    import gltf_local.buffer
    import gltf_local.camera
    import gltf_local.material
    import gltf_local.mesh
    import gltf_local.scene
    import gltf_local.node_groups
    import gltf_local.light
else:
    importlib.reload(gltf_local.animation)
    importlib.reload(gltf_local.buffer)
    importlib.reload(gltf_local.camera)
    importlib.reload(gltf_local.material)
    importlib.reload(gltf_local.mesh)
    importlib.reload(gltf_local.scene)
    importlib.reload(gltf_local.node_groups)
    importlib.reload(gltf_local.light)

bl_info = {
    'name': 'glTF 2.0 Importer',
    'author': 'Kristian Sons (ksons), scurest, kayteh',
    'blender': (2, 79, 0),
    'version': (0, 3, 0),
    'location': 'File > Import > glTF JSON (.gltf/.glb/.vrm)',
    'description': 'Importer for the glTF 2.0 file format. Okano fork for VRM.',
    'warning': '',
    'wiki_url': 'https://github.com/ksons/gltf-blender-importer/blob/master/README.md',
    'tracker_url': 'https://github.com/ksons/gltf-blender-importer/issues',
    'category': 'Import-Export'
}


# Supported glTF version
GLTF_VERSION = (2, 0)

# Supported extensions
EXTENSIONS = set((
    'KHR_lights_punctual', # tentative until stabilized
    'KHR_materials_pbrSpecularGlossiness',
    'KHR_materials_unlit',
    'KHR_texture_transform',
    'MSFT_texture_dds',
    'VRM'
))


def trip(x): return (x, x, x)

class ImportGLTF(bpy.types.Operator, ImportHelper):
    bl_idname = 'import_scene.gltf'
    bl_label = 'Import glTF'

    filename_ext = '.gltf'
    filter_glob = StringProperty(
        default='*.gltf;*.glb;*.vrm',
        options={'HIDDEN'},
    )

    import_under_current_scene = BoolProperty(
        name='Import contents under current scene',
        description=
            'When enabled, all the objects will be placed in the current '
            'scene and no scenes will be created.\n'
            'When disabled, scenes will be created to match the ones in the '
            'glTF file. Any object not in a scene will not be visible.',
        default=True,
    )
    smooth_polys = BoolProperty(
        name='Enable polygon smoothing',
        description=
            'Enable smoothing for all polygons in imported meshes. Suggest '
            'disabling for low-res models.',
        default=True,
    )
    bone_rotation_mode = EnumProperty(
        items=[
            ('NONE', 'Don\'t change', ''),
            ('AUTO', 'Choose for me', ''),
            ('MANUAL', 'Choose manually', ''),
        ],
        name='Axis',
        description=
            'Adjusts which local axis bones should point along. The axis they '
            'points along is always +Y. This option lets you rotate them so another '
            'axis becomes +Y.',
        default='AUTO',
    )
    bone_rotation_axis = EnumProperty(
        items=[
            trip('+X'),
            trip('-X'),
            trip('-Y'),
            trip('+Z'),
            trip('-Z'),
        ],
        name='+Y to',
        description=
            'If bones point the wrong way with the default value, enable '
            '"Display > Axes" for the Armature and look in Edit mode. '
            'You\'ll see that bones point along the local +Y axis. Decide '
            'which local axis they should point along and put it here.',
        default='+Z',
    )
    import_animations = BoolProperty(
        name='Import Animations (EXPERIMENTAL)',
        description='',
        default=False,
    )
    framerate = FloatProperty(
        name='Frames/second',
        description=
            'Used for animation. The Blender frame corresponding to the glTF '
            'time t is computed as framerate * t.',
        default=60.0,
    )

    def execute(self, context):
        self.caches = {}

        self.load_config()
        self.load()
        self.check_version()
        self.check_required_extensions()
        self.config_vrm()

        material.compute_materials_using_color0(self)
        scene.create_scenes(self)
        if self.import_animations:
            animation.add_animations(self)

        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout

        layout.prop(self, 'import_under_current_scene')

        col = layout.box().column()
        col.label('Mesh:', icon='MESH_DATA')
        col.prop(self, 'smooth_polys')

        col = layout.box().column()
        col.label('Bones:', icon='BONE_DATA')
        col.label('(Tweak if bones point wrong)')
        col.prop(self, 'bone_rotation_mode')
        if self.as_keywords()['bone_rotation_mode'] == 'MANUAL':
            col.prop(self, 'bone_rotation_axis')

        col = layout.box().column()
        col.label('Animation:', icon='OUTLINER_DATA_POSE')
        col.prop(self, 'import_animations')
        col.prop(self, 'framerate')


    def get(self, kind, id):
        cache = self.caches.setdefault(kind, {})
        if id in cache:
            return cache[id]
        else:
            result = CREATE_FNS[kind](self, id)
            if type(result) == dict and result.get('do_not_cache_me', False):
                # Callee is requesting we not cache it
                return result['result']
            else:
                cache[id] = result
                return result

    def load(self):
        filename = self.filepath

        # Remember this for resolving relative paths
        self.base_path = os.path.dirname(filename)

        with open(filename, 'rb') as f:
            contents = f.read()

        # Use magic number to detect GLB files.
        is_glb = contents[:4] == b'glTF'
        if is_glb:
            self.parse_glb(contents)
        else:
            self.gltf = json.loads(contents.decode('utf-8'))
            self.glb_buffer = None

    def parse_glb(self, contents):
        contents = memoryview(contents)

        # Parse the header
        header = struct.unpack_from('<4sII', contents)
        glb_version = header[1]
        if glb_version != 2:
            raise Exception('GLB: version not supported: %d' % glb_version)

        def parse_chunk(offset):
            header = struct.unpack_from('<I4s', contents, offset=offset)
            data_len = header[0]
            ty = header[1]
            data = contents[offset + 8: offset + 8 + data_len]
            next_offset = offset + 8 + data_len
            return {
                'type': ty,
                'data': data,
                'next_offset': next_offset,
            }

        offset = 12  # end of header

        # The first chunk must be JSON
        json_chunk = parse_chunk(offset)
        if json_chunk['type'] != b'JSON':
            raise Exception('GLB: JSON chunk must be first')
        self.gltf = json.loads(
            json_chunk['data'].tobytes().decode('utf-8'),  # Need to decode for < 2.79.4 which comes with Python 3.5
            encoding='utf-8'
        )

        self.glb_buffer = None

        offset = json_chunk['next_offset']
        while offset < len(contents):
            chunk = parse_chunk(offset)

            # Ignore unknown chunks
            if chunk['type'] != b'BIN\0':
                offset = chunk['next_offset']
                continue

            if chunk['type'] == b'JSON':
                raise Exception('GLB: Too many JSON chunks, should be 1')

            if self.glb_buffer != None:
                raise Exception('GLB: Too many BIN chunks, should be 0 or 1')

            self.glb_buffer = chunk['data']

            offset = chunk['next_offset']

    def check_version(self):
        def parse_version(s):
            """Parse a string like '1.1' to a tuple (1,1)."""
            try:
                version = tuple(int(x) for x in s.split('.'))
                if len(version) >= 2: return version
            except Exception:
                pass
            raise Exception('unknown version format: %s' % s)

        asset = self.gltf['asset']

        if 'minVersion' in asset:
            min_version = parse_version(asset['minVersion'])
            supported = GLTF_VERSION >= min_version
            if not supported:
                raise Exception('unsupported minimum version: %s' % min_version)
        else:
            version = parse_version(asset['version'])
            # Check only major version; we should be backwards- and forwards-compatible
            supported = version[0] == GLTF_VERSION[0]
            if not supported:
                raise Exception('unsupported version: %s' % version)

    def check_required_extensions(self):
        for ext in self.gltf.get('extensionsRequired', []):
            if ext not in EXTENSIONS:
                raise Exception('unsupported extension was required: %s' % ext)


    def load_config(self):
        """Load user-supplied options into instance vars."""
        keywords = self.as_keywords()
        self.import_under_current_scene = keywords['import_under_current_scene']
        self.smooth_polys = keywords['smooth_polys']
        self.import_animations = keywords['import_animations']
        self.framerate = keywords['framerate']
        self.bone_rotation_mode = keywords['bone_rotation_mode']
        self.bone_rotation_axis = keywords['bone_rotation_axis']
    
    def config_vrm(self):
        """Map VRM-specific data into instance vars."""
        if 'VRM' in self.gltf['extensions']:
            self.vrm = True
        else:
            self.vrm = False


CREATE_FNS = {
    'buffer': gltf_local.buffer.create_buffer,
    'buffer_view': gltf_local.buffer.create_buffer_view,
    'accessor': gltf_local.buffer.create_accessor,
    'image': gltf_local.material.create_image,
    'material': gltf_local.material.create_material,
    'node_group': gltf_local.node_groups.create_group,
    'mesh': gltf_local.mesh.create_mesh,
    'camera': gltf_local.camera.create_camera,
    'light': gltf_local.light.create_light,
}

# Add to a menu
def menu_func_import(self, context):
    self.layout.operator(ImportGLTF.bl_idname, text='glTF JSON (.gltf/.glb)')


def register():
    bpy.utils.register_module(__name__)

    bpy.types.INFO_MT_file_import.append(menu_func_import)


def unregister():
    bpy.utils.unregister_module(__name__)

    bpy.types.INFO_MT_file_import.remove(menu_func_import)


if __name__ == '__main__':
    register()
