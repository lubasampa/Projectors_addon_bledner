import logging
import math
import os
import json
import uuid

from enum import Enum
import bpy
from bpy.app.handlers import persistent
from bpy.types import AddonPreferences, Operator, PropertyGroup
from mathutils import Euler, Matrix, Vector

from .helper import (ADDON_ID, auto_offset,
                     get_projectors, get_projector, random_color)

logging.basicConfig(
    format='[Projectors Addon]: %(name)s - %(levelname)s - %(message)s')
log = logging.getLogger(name=__file__)

PROJECTOR_SPOT_TAG = ADDON_ID.format('spot')
PROJECTOR_BODY_TAG = ADDON_ID.format('body')
PROJECTOR_CONE_TAG = ADDON_ID.format('projection_cone')
PROJECTOR_INSTANCE_TAG = ADDON_ID.format('instance_id')
PROJECTOR_ARRAY_SOURCE_TAG = ADDON_ID.format('array_source')
PROJECTOR_ARRAY_SOURCE_ID_TAG = ADDON_ID.format('array_source_id')
PROJECTOR_ARRAY_LINKED_TAG = ADDON_ID.format('array_linked')
PROJECTOR_ARRAY_STATE_TAG = ADDON_ID.format('array_source_state')
PROJECTOR_ARRAY_CONTROLLER_TAG = ADDON_ID.format('array_controller')
PROJECTOR_ARRAY_INDEX_TAG = ADDON_ID.format('array_index')
PROJECTOR_ARRAY_SETTINGS_TAG = ADDON_ID.format('array_settings')
MODELS_STORE_FILENAME = 'projector_saved_models.json'
_PROJECTOR_DUPLICATE_HANDLER_RUNNING = False
_PROJECTOR_DUPLICATE_REFRESH_PENDING = set()
_PROJECTOR_DUPLICATE_REFRESH_SCHEDULED = False
_PROJECTOR_ARRAY_SYNC_SCHEDULED = False


def _get_models_store_path():
    config_dir = bpy.utils.user_resource('CONFIG', path='projector_addon', create=True)
    if config_dir:
        return os.path.join(config_dir, MODELS_STORE_FILENAME)
    return os.path.join(os.path.expanduser('~'), MODELS_STORE_FILENAME)


def _as_float_vector(value, default):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return default
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError):
        return default


def _clear_projector_models(prefs):
    for idx in range(len(prefs.projector_models) - 1, -1, -1):
        prefs.projector_models.remove(idx)


def _serialize_models_from_preferences(prefs):
    models = []
    for preset in prefs.projector_models:
        models.append({
            'manufacturer': preset.manufacturer,
            'model_name': preset.model_name,
            'body_type': preset.body_type,
            'body_dimensions': list(preset.body_dimensions),
            'body_offset': list(preset.body_offset),
            'body_rotation': list(preset.body_rotation),
            'projector_location': list(preset.projector_location),
            'projector_rotation': list(preset.projector_rotation),
            'projector_scale': list(preset.projector_scale),
            'emitter_offset': list(preset.emitter_offset),
            'emitter_rotation': list(preset.emitter_rotation),
            'power': float(preset.power),
            'throw_ratio': float(preset.throw_ratio),
            'h_shift': float(preset.h_shift),
            'v_shift': float(preset.v_shift),
            'resolution': preset.resolution,
            'use_custom_texture_res': bool(preset.use_custom_texture_res),
            'projected_texture': preset.projected_texture,
            'projected_color': list(preset.projected_color),
            'show_pixel_grid': bool(preset.show_pixel_grid),
            'projection_cone_enabled': bool(preset.projection_cone_enabled),
            'projection_cone_length': float(preset.projection_cone_length),
            'body_mesh_vertices_json': preset.body_mesh_vertices_json,
            'body_mesh_faces_json': preset.body_mesh_faces_json,
            'body_mesh_material_indices_json': preset.body_mesh_material_indices_json,
            'body_materials_json': preset.body_materials_json,
        })
    return models


def _write_models_store(prefs=None):
    prefs = prefs or get_addon_preferences()
    if prefs is None:
        return False

    path = _get_models_store_path()
    payload = {
        'version': 1,
        'models': _serialize_models_from_preferences(prefs),
    }
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2)
        return True
    except OSError:
        log.exception('Failed to write projector model store: %s', path)
        return False


def _read_models_store():
    path = _get_models_store_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        log.exception('Failed to read projector model store: %s', path)
        return None

    if isinstance(payload, dict):
        models = payload.get('models', [])
    elif isinstance(payload, list):
        models = payload
    else:
        models = []
    return models if isinstance(models, list) else []


def _models_from_payload(payload):
    if isinstance(payload, dict):
        models = payload.get('models', [])
    elif isinstance(payload, list):
        models = payload
    else:
        models = []
    return models if isinstance(models, list) else []


def _populate_preferences_from_model_data(prefs, stored_models):
    _clear_projector_models(prefs)
    for data in stored_models:
        if not isinstance(data, dict):
            continue
        manufacturer = str(data.get('manufacturer', '')).strip()
        model_name = str(data.get('model_name', '')).strip()
        if not manufacturer or not model_name:
            continue

        preset = prefs.projector_models.add()
        preset.manufacturer = manufacturer
        preset.model_name = model_name
        preset.body_type = data.get('body_type', 'DEFAULT_BOX')
        preset.body_dimensions = _as_float_vector(data.get('body_dimensions'), (0.35, 0.12, 0.22))
        preset.body_offset = _as_float_vector(data.get('body_offset'), (0.0, 0.0, 0.12))
        preset.body_rotation = _as_float_vector(data.get('body_rotation'), (0.0, 0.0, 0.0))
        preset.projector_location = _as_float_vector(data.get('projector_location'), (0.0, 0.0, 0.0))
        preset.projector_rotation = _as_float_vector(data.get('projector_rotation'), (0.0, 0.0, 0.0))
        preset.projector_scale = _as_float_vector(data.get('projector_scale'), (1.0, 1.0, 1.0))
        preset.emitter_offset = _as_float_vector(data.get('emitter_offset'), (0.0, 0.0, 0.0))
        preset.emitter_rotation = _as_float_vector(data.get('emitter_rotation'), (0.0, 0.0, 0.0))
        try:
            preset.power = float(data.get('power', 1000.0))
            preset.throw_ratio = float(data.get('throw_ratio', 0.8))
            preset.h_shift = float(data.get('h_shift', 0.0))
            preset.v_shift = float(data.get('v_shift', 0.0))
            preset.resolution = str(data.get('resolution', '1920x1080'))
            preset.use_custom_texture_res = bool(data.get('use_custom_texture_res', True))
            preset.projected_texture = str(data.get('projected_texture', Textures.CHECKER.value))
            preset.projected_color = _as_float_vector(data.get('projected_color'), (1.0, 1.0, 1.0))
            preset.show_pixel_grid = bool(data.get('show_pixel_grid', False))
            preset.projection_cone_enabled = bool(data.get('projection_cone_enabled', False))
            preset.projection_cone_length = float(data.get('projection_cone_length', 3.0))
        except (TypeError, ValueError):
            preset.power = 1000.0
            preset.throw_ratio = 0.8
            preset.h_shift = 0.0
            preset.v_shift = 0.0
            preset.resolution = '1920x1080'
            preset.use_custom_texture_res = True
            preset.projected_texture = Textures.CHECKER.value
            preset.projected_color = (1.0, 1.0, 1.0)
            preset.show_pixel_grid = False
            preset.projection_cone_enabled = False
            preset.projection_cone_length = 3.0
        preset.body_mesh_vertices_json = str(data.get('body_mesh_vertices_json', ''))
        preset.body_mesh_faces_json = str(data.get('body_mesh_faces_json', ''))
        preset.body_mesh_material_indices_json = str(data.get('body_mesh_material_indices_json', ''))
        preset.body_materials_json = str(data.get('body_materials_json', ''))
    return True


def _load_models_store_into_preferences(prefs=None):
    prefs = prefs or get_addon_preferences()
    if prefs is None:
        return False

    stored_models = _read_models_store()
    if stored_models is None:
        # Migration path: if only Blender preferences contain models, bootstrap JSON storage.
        if len(prefs.projector_models) > 0:
            _write_models_store(prefs)
            return True
        return False

    return _populate_preferences_from_model_data(prefs, stored_models)


def _safe_register_class(cls):
    try:
        bpy.utils.register_class(cls)
    except ValueError as exc:
        # Happens on script reload when Blender still holds previous class registration.
        if 'already registered as a subclass' not in str(exc):
            raise
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
        bpy.utils.register_class(cls)


def _safe_unregister_class(cls):
    try:
        bpy.utils.unregister_class(cls)
    except RuntimeError as exc:
        # Happens when class was not registered in this session/order.
        if 'missing bl_rna attribute from' not in str(exc):
            raise


def get_projector_spot(projector):
    if projector is None:
        return None
    for child in projector.children:
        if child.get(PROJECTOR_SPOT_TAG, False):
            return child
    return None


def get_projector_body(projector):
    if projector is None:
        return None
    for child in projector.children:
        if child.get(PROJECTOR_BODY_TAG, False):
            return child
    return None


def get_projector_cone(projector):
    if projector is None:
        return None
    # Cone is parented to the spot light (grandchild of projector), so scan recursively.
    stack = list(projector.children)
    while stack:
        child = stack.pop()
        if child.get(PROJECTOR_CONE_TAG, False):
            return child
        stack.extend(child.children)
    return None


def _new_projector_instance_id():
    return uuid.uuid4().hex


def _make_node_groups_local(node_tree):
    if node_tree is None:
        return
    for node in node_tree.nodes:
        if getattr(node, 'type', None) == 'GROUP' and getattr(node, 'node_tree', None) is not None:
            if node.node_tree.users > 1:
                node.node_tree = node.node_tree.copy()


def _make_material_slots_local(obj):
    if obj is None or not hasattr(obj, 'material_slots'):
        return
    for slot in obj.material_slots:
        if slot.material is not None and slot.material.users > 1:
            slot.material = slot.material.copy()


def _make_projector_datablocks_local(projector):
    if projector is None:
        return

    if projector.data is not None and projector.data.users > 1:
        projector.data = projector.data.copy()

    spot = get_projector_spot(projector)
    if spot is not None:
        if spot.data is not None and spot.data.users > 1:
            spot.data = spot.data.copy()
        _make_node_groups_local(spot.data.node_tree if spot.data else None)

    body = get_projector_body(projector)
    if body is not None:
        if body.data is not None and body.data.users > 1:
            body.data = body.data.copy()
        _make_material_slots_local(body)

    cone = get_projector_cone(projector)
    if cone is not None:
        if cone.data is not None and cone.data.users > 1:
            cone.data = cone.data.copy()
        _make_material_slots_local(cone)


def _create_spot_for_projector(projector):
    light_data = bpy.data.lights.new('Projector.Spot', type='SPOT')
    spot = bpy.data.objects.new('Projector.Spot', light_data)
    spot.scale = (.01, .01, .01)
    spot.data.spot_size = math.pi - 0.001
    spot.data.spot_blend = 0
    spot.data.shadow_soft_size = 0.0
    spot.hide_select = True
    spot[PROJECTOR_SPOT_TAG] = True
    spot.data.cycles.use_multiple_importance_sampling = False
    add_projector_node_tree_to_spot(spot)
    spot.parent = projector
    spot.matrix_parent_inverse.identity()
    target_collection = projector.users_collection[0] if projector.users_collection else bpy.context.scene.collection
    target_collection.objects.link(spot)
    return spot


def _ensure_projector_hierarchy(projector):
    if get_projector_spot(projector) is None:
        _create_spot_for_projector(projector)
        _apply_throw_ratio_to_projector(projector, projector.proj_settings)
        _apply_body(projector, projector.proj_settings)
        _apply_emitter_transform(projector, projector.proj_settings)
        _apply_projection_cone(projector, projector.proj_settings)


def _refresh_duplicated_projector_cones():
    global _PROJECTOR_DUPLICATE_HANDLER_RUNNING
    global _PROJECTOR_DUPLICATE_REFRESH_SCHEDULED

    pending_names = list(_PROJECTOR_DUPLICATE_REFRESH_PENDING)
    _PROJECTOR_DUPLICATE_REFRESH_PENDING.clear()
    _PROJECTOR_DUPLICATE_REFRESH_SCHEDULED = False

    _PROJECTOR_DUPLICATE_HANDLER_RUNNING = True
    try:
        for name in pending_names:
            projector = bpy.data.objects.get(name)
            if projector is None or not hasattr(projector, 'proj_settings'):
                continue
            _refresh_projector_derived_state(projector)
    finally:
        _PROJECTOR_DUPLICATE_HANDLER_RUNNING = False

    return None


def _queue_projector_cone_refresh(projector):
    global _PROJECTOR_DUPLICATE_REFRESH_SCHEDULED

    if projector is None:
        return

    _PROJECTOR_DUPLICATE_REFRESH_PENDING.add(projector.name)
    if not _PROJECTOR_DUPLICATE_REFRESH_SCHEDULED:
        _PROJECTOR_DUPLICATE_REFRESH_SCHEDULED = True
        bpy.app.timers.register(_refresh_duplicated_projector_cones, first_interval=0.1)


@persistent
def _ensure_duplicated_projectors_are_independent(scene, depsgraph=None):
    global _PROJECTOR_DUPLICATE_HANDLER_RUNNING
    if _PROJECTOR_DUPLICATE_HANDLER_RUNNING:
        return

    _PROJECTOR_DUPLICATE_HANDLER_RUNNING = True
    try:
        _queue_linked_projector_array_sync()
        used_ids = set()
        projectors = list(_iter_projector_objects(scene))
        instance_counts = {}
        for projector in projectors:
            instance_id = projector.get(PROJECTOR_INSTANCE_TAG)
            if instance_id:
                instance_counts[instance_id] = instance_counts.get(instance_id, 0) + 1

        for projector in projectors:
            _ensure_projector_hierarchy(projector)
            instance_id = projector.get(PROJECTOR_INSTANCE_TAG)
            is_new_instance = not instance_id or instance_id in used_ids
            has_duplicated_id = instance_id and instance_counts.get(instance_id, 0) > 1
            if is_new_instance:
                projector[PROJECTOR_INSTANCE_TAG] = _new_projector_instance_id()
                _make_projector_datablocks_local(projector)
                _queue_projector_cone_refresh(projector)
            else:
                _make_projector_datablocks_local(projector)
                if has_duplicated_id:
                    _queue_projector_cone_refresh(projector)
            used_ids.add(projector[PROJECTOR_INSTANCE_TAG])
    finally:
        _PROJECTOR_DUPLICATE_HANDLER_RUNNING = False


def _remove_all_projector_cones(projector):
    if projector is None:
        return
    stack = list(projector.children)
    to_remove = []
    while stack:
        child = stack.pop()
        if child.get(PROJECTOR_CONE_TAG, False):
            to_remove.append(child)
        stack.extend(child.children)

    for cone in to_remove:
        old_mesh = cone.data
        bpy.data.objects.remove(cone, do_unlink=True)
        if old_mesh and old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh, do_unlink=True)


def get_addon_preferences(context=None):
    addon_name = __package__
    prefs_owner = None
    if context is not None and getattr(context, 'preferences', None) is not None:
        prefs_owner = context.preferences
    elif getattr(bpy.context, 'preferences', None) is not None:
        prefs_owner = bpy.context.preferences

    if prefs_owner is None:
        return None
    if addon_name in prefs_owner.addons:
        return prefs_owner.addons[addon_name].preferences
    return None


class Textures(Enum):
    CHECKER = 'checker_texture'
    COLOR_GRID = 'color_grid_texture'
    CUSTOM_TEXTURE = 'custom_texture'


RESOLUTIONS = [
    # 16:10 aspect ratio
    ('1280x800', 'WXGA (1280x800) 16:10', '', 1),
    ('1440x900', 'WXGA+ (1440x900) 16:10', '', 2),
    ('1920x1200', 'WUXGA (1920x1200) 16:10', '', 3),
    # 16:9 aspect ratio
    ('1280x720', '720p (1280x720) 16:9', '', 4),
    ('1920x1080', '1080p (1920x1080) 16:9', '', 5),
    ('3840x2160', '4K Ultra HD (3840x2160) 16:9', '', 6),
    # 4:3 aspect ratio
    ('800x600', 'SVGA (800x600) 4:3', '', 7),
    ('1024x768', 'XGA (1024x768) 4:3', '', 8),
    ('1400x1050', 'SXGA+ (1400x1050) 4:3', '', 9),
    ('1600x1200', 'UXGA (1600x1200) 4:3', '', 10),
    # 17:9 aspect ratio
    ('4096x2160', 'Native 4K (4096x2160) 17:9', '', 11),
    # 1:1 aspect ratio
    ('1000x1000', 'Square (1000x1000) 1:1', '', 12)
]

PROJECTED_OUTPUTS = [(Textures.CHECKER.value, 'Checker', '', 1),
                     (Textures.COLOR_GRID.value, 'Color Grid', '', 2),
                     (Textures.CUSTOM_TEXTURE.value, 'Custom Texture', '', 3)]

BODY_TYPES = [
    ('NONE', 'No Body', 'Create projector without a 3D body', 1),
    ('DEFAULT_BOX', 'Default Body', 'Create a configurable box body', 2),
    ('SELECTED_OBJECT', 'Duplicate Active Object', 'Duplicate the active mesh object as projector body', 3),
]


def _saved_model_items(self, context):
    items = [('NONE', 'None', 'No saved model', 0)]
    prefs = get_addon_preferences(context)
    if not prefs:
        return items
    for idx, item in enumerate(prefs.projector_models):
        label = f'{item.manufacturer} - {item.model_name}'
        items.append((str(idx), label, 'Saved projector model preset', idx + 1))
    return items


def _model_preset_items(self, context):
    return _saved_model_items(self, context)


class ProjectorModelPreset(PropertyGroup):
    manufacturer: bpy.props.StringProperty(name='Manufacturer')
    model_name: bpy.props.StringProperty(name='Model')
    body_type: bpy.props.EnumProperty(name='Body Type', items=BODY_TYPES, default='DEFAULT_BOX')
    body_dimensions: bpy.props.FloatVectorProperty(name='Body Dimensions', size=3, default=(0.35, 0.12, 0.22), min=0.01, subtype='XYZ')
    body_offset: bpy.props.FloatVectorProperty(name='Body Offset', size=3, default=(0.0, 0.0, 0.12), subtype='TRANSLATION')
    body_rotation: bpy.props.FloatVectorProperty(name='Body Rotation', size=3, default=(0.0, 0.0, 0.0), subtype='EULER', unit='ROTATION')
    projector_location: bpy.props.FloatVectorProperty(name='Projector Location', size=3, default=(0.0, 0.0, 0.0), subtype='TRANSLATION')
    projector_rotation: bpy.props.FloatVectorProperty(name='Projector Rotation', size=3, default=(0.0, 0.0, 0.0), subtype='EULER', unit='ROTATION')
    projector_scale: bpy.props.FloatVectorProperty(name='Projector Scale', size=3, default=(1.0, 1.0, 1.0), subtype='XYZ')
    emitter_offset: bpy.props.FloatVectorProperty(name='Emitter Offset', size=3, default=(0.0, 0.0, 0.0), subtype='TRANSLATION')
    emitter_rotation: bpy.props.FloatVectorProperty(name='Emitter Rotation', size=3, default=(0.0, 0.0, 0.0), subtype='EULER', unit='ROTATION')
    power: bpy.props.FloatProperty(name='Power', default=1000.0, min=0.0, soft_max=999999.0)
    throw_ratio: bpy.props.FloatProperty(name='Throw Ratio', default=0.8, min=0.1, soft_max=3.0)
    h_shift: bpy.props.FloatProperty(name='Horizontal Shift', default=0.0, soft_min=-20.0, soft_max=20.0)
    v_shift: bpy.props.FloatProperty(name='Vertical Shift', default=0.0, soft_min=-20.0, soft_max=20.0)
    resolution: bpy.props.EnumProperty(name='Resolution', items=RESOLUTIONS, default='1920x1080')
    use_custom_texture_res: bpy.props.BoolProperty(name='Use Texture Resolution', default=True)
    projected_texture: bpy.props.EnumProperty(name='Projected Texture', items=PROJECTED_OUTPUTS, default=Textures.CHECKER.value)
    projected_color: bpy.props.FloatVectorProperty(name='Projected Color', size=3, default=(1.0, 1.0, 1.0), subtype='COLOR')
    show_pixel_grid: bpy.props.BoolProperty(name='Show Pixel Grid', default=False)
    projection_cone_enabled: bpy.props.BoolProperty(name='Projection Cone', default=False)
    projection_cone_length: bpy.props.FloatProperty(name='Cone Length (m)', default=0.0, min=0.0)
    body_mesh_vertices_json: bpy.props.StringProperty(name='Body Mesh Vertices', default='')
    body_mesh_faces_json: bpy.props.StringProperty(name='Body Mesh Faces', default='')
    body_mesh_material_indices_json: bpy.props.StringProperty(name='Body Mesh Material Indices', default='')
    body_materials_json: bpy.props.StringProperty(name='Body Materials', default='')


class PROJECTOR_AP_preferences(AddonPreferences):
    bl_idname = __package__

    projector_models: bpy.props.CollectionProperty(type=ProjectorModelPreset)

    def draw(self, context):
        layout = self.layout
        layout.label(text='Saved Projector Models')
        if not self.projector_models:
            layout.label(text='No saved models yet.')
        for item in self.projector_models:
            layout.label(text=f'{item.manufacturer} - {item.model_name}')


class PROJECTOR_OT_change_color_randomly(Operator):
    """ Randomly change the color of the projected checker texture."""
    bl_idname = 'projector.change_color'
    bl_label = 'Change color of projection checker texture'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(get_projectors(context, only_selected=True)) == 1

    def execute(self, context):
        projectors = get_projectors(context, only_selected=True)
        new_color = random_color(alpha=True)
        for projector in projectors:
            projector.proj_settings['projected_color'] = new_color[:-1]
            update_checker_color(projector.proj_settings, context)
        return {'FINISHED'}


def create_projector_textures():
    """ This function checks if the needed images exist and if not creates them. """
    name_template = '_proj.tex.{}'
    for res in RESOLUTIONS:
        img_name = name_template.format(res[0])
        w, h = res[0].split('x')
        if not bpy.data.images.get(img_name):
            log.debug(f'Create projection texture: {res}')
            bpy.ops.image.new(name=img_name,
                              width=int(w),
                              height=int(h),
                              color=(0.0, 0.0, 0.0, 1.0),
                              alpha=True,
                              generated_type='COLOR_GRID',
                              float=False)

        bpy.data.images[img_name].use_fake_user = True


def add_projector_node_tree_to_spot(spot):
    """
    This function turns a spot light into a projector.
    This is achieved through a texture on the spot light and some basic math.
    """

    spot.data.use_nodes = True
    root_tree = spot.data.node_tree
    root_tree.nodes.clear()

    node_group = bpy.data.node_groups.new('_Projector', 'ShaderNodeTree')

    # Create output sockets for the node group.
    if(bpy.app.version >= (4, 0)):
        node_group.interface.new_socket('texture vector',  in_out="OUTPUT", socket_type='NodeSocketVector')
        node_group.interface.new_socket('color', in_out="OUTPUT", socket_type='NodeSocketColor')
    else:
        output = node_group.outputs
        output.new('NodeSocketVector', 'texture vector')
        output.new('NodeSocketColor', 'color')

    # # Inside Group Node #
    # #####################

    # Hold important nodes inside a group node.
    group = spot.data.node_tree.nodes.new('ShaderNodeGroup')
    group.node_tree = node_group
    group.label = "!! Don't touch !!"

    nodes = group.node_tree.nodes
    tree = group.node_tree

    auto_pos = auto_offset()

    tex = nodes.new('ShaderNodeTexCoord')
    tex.location = auto_pos(200)

    geo = nodes.new('ShaderNodeNewGeometry')
    geo.location = auto_pos(0, -300)
    vec_transform = nodes.new('ShaderNodeVectorTransform')
    vec_transform.location = auto_pos(200)
    vec_transform.vector_type = 'NORMAL'

    map_1 = nodes.new('ShaderNodeMapping')
    map_1.vector_type = 'TEXTURE'
    # Flip the image horizontally and vertically to display it the intended way.
    if bpy.app.version < (2, 81):
        map_1.scale[0] = -1
        map_1.scale[1] = -1
    else:
        map_1.inputs[3].default_value[0] = -1
        map_1.inputs[3].default_value[1] = -1
    map_1.location = auto_pos(200)

    sep = nodes.new('ShaderNodeSeparateXYZ')
    sep.location = auto_pos(350)

    div_1 = nodes.new('ShaderNodeMath')
    div_1.operation = 'DIVIDE'
    div_1.name = ADDON_ID + 'div_01'
    div_1.location = auto_pos(200)

    div_2 = nodes.new('ShaderNodeMath')
    div_2.operation = 'DIVIDE'
    div_2.name = ADDON_ID + 'div_02'
    div_2.location = auto_pos(y=-200)

    com = nodes.new('ShaderNodeCombineXYZ')
    com.inputs['Z'].default_value = 1.0
    com.location = auto_pos(200)

    map_2 = nodes.new('ShaderNodeMapping')
    map_2.location = auto_pos(200)
    map_2.vector_type = 'TEXTURE'

    add = nodes.new('ShaderNodeMixRGB')
    add.blend_type = 'ADD'
    add.inputs[0].default_value = 1
    add.location = auto_pos(350)

    # Texture
    # a) Image
    img = nodes.new('ShaderNodeTexImage')
    img.extension = 'CLIP'
    img.location = auto_pos(200)

    # b) Generated checker texture.
    checker_tex = nodes.new('ShaderNodeTexChecker')
    # checker_tex.inputs['Color2'].default_value = random_color(alpha=True)
    checker_tex.inputs[3].default_value = 8
    checker_tex.inputs[1].default_value = (1, 1, 1, 1)
    checker_tex.location = auto_pos(y=-300)

    mix_rgb = nodes.new('ShaderNodeMixRGB')
    mix_rgb.name = 'Mix.001'
    mix_rgb.inputs[1].default_value = (0, 0, 0, 0)
    mix_rgb.location = auto_pos(200, y=-300)

    group_output_node = node_group.nodes.new('NodeGroupOutput')
    group_output_node.location = auto_pos(200)

    # # Root Nodes #
    # ##############
    auto_pos_root = auto_offset()
    # Image Texture
    user_texture = root_tree.nodes.new('ShaderNodeTexImage')
    user_texture.extension = 'CLIP'
    user_texture.label = 'Add your Image Texture or Movie here'
    user_texture.location = auto_pos_root(200, y=200)
    # Emission
    emission = root_tree.nodes.new('ShaderNodeEmission')
    emission.inputs['Strength'].default_value = 1
    emission.location = auto_pos_root(300)
    # Material Output
    output = root_tree.nodes.new('ShaderNodeOutputLight')
    output.location = auto_pos_root(200)

    # # LINK NODES #
    # ##############

    # Link inside group node
    if(bpy.app.version >= (4, 0)):
        tree.links.new(geo.outputs['Incoming'], vec_transform.inputs['Vector'])
        tree.links.new(vec_transform.outputs['Vector'], map_1.inputs['Vector'])
    else:
        tree.links.new(tex.outputs['Normal'], map_1.inputs['Vector'])
    tree.links.new(map_1.outputs['Vector'], sep.inputs['Vector'])

    tree.links.new(sep.outputs[0], div_1.inputs[0])  # X -> value0
    tree.links.new(sep.outputs[2], div_1.inputs[1])  # Z -> value1
    tree.links.new(sep.outputs[1], div_2.inputs[0])  # Y -> value0
    tree.links.new(sep.outputs[2], div_2.inputs[1])  # Z -> value1

    tree.links.new(div_1.outputs[0], com.inputs[0])
    tree.links.new(div_2.outputs[0], com.inputs[1])

    tree.links.new(com.outputs['Vector'], map_2.inputs['Vector'])

    # Textures
    # a) generated texture
    tree.links.new(map_2.outputs['Vector'], add.inputs['Color1'])
    tree.links.new(add.outputs['Color'], img.inputs['Vector'])
    tree.links.new(add.outputs['Color'], group_output_node.inputs[0])
    # b) checker texture
    tree.links.new(add.outputs['Color'], checker_tex.inputs['Vector'])
    tree.links.new(img.outputs['Alpha'], mix_rgb.inputs[0])
    tree.links.new(checker_tex.outputs['Color'], mix_rgb.inputs[2])

    # Link in root
    root_tree.links.new(group.outputs['texture vector'], user_texture.inputs['Vector'])
    root_tree.links.new(group.outputs['color'], emission.inputs['Color'])
    root_tree.links.new(emission.outputs['Emission'], output.inputs['Surface'])

    # Pixel Grid Setup
    pixel_grid_group = create_pixel_grid_node_group()
    pixel_grid_node = spot.data.node_tree.nodes.new('ShaderNodeGroup')
    pixel_grid_node.node_tree = pixel_grid_group
    pixel_grid_node.label = "Pixel Grid"
    pixel_grid_node.name = 'pixel_grid'
    loc = root_tree.nodes['Emission'].location
    pixel_grid_node.location = (loc[0], loc[1] - 150)

    root_tree.links.new(group.outputs[0], pixel_grid_node.inputs[1])
    root_tree.links.new(emission.outputs[0], pixel_grid_node.inputs[0])


def _create_box_mesh(mesh_name, dimensions):
    sx = max(dimensions[0], 0.01) * 0.5
    sy = max(dimensions[1], 0.01) * 0.5
    sz = max(dimensions[2], 0.01) * 0.5
    verts = [
        (-sx, -sy, -sz), (sx, -sy, -sz), (sx, sy, -sz), (-sx, sy, -sz),
        (-sx, -sy, sz), (sx, -sy, sz), (sx, sy, sz), (-sx, sy, sz),
    ]
    faces = [
        (0, 1, 2, 3),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (2, 3, 7, 6),
        (1, 2, 6, 5),
        (3, 0, 4, 7),
    ]
    mesh = bpy.data.meshes.new(mesh_name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    return mesh


def _get_or_create_body_material():
    mat_name = '_Projector.BodyMaterial'
    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        mat = bpy.data.materials.new(mat_name)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get('Principled BSDF')
        if bsdf is not None:
            bsdf.inputs['Base Color'].default_value = (0.17, 0.17, 0.19, 1.0)
            bsdf.inputs['Roughness'].default_value = 0.55
    return mat


def _ensure_default_body(projector):
    body = get_projector_body(projector)
    if body and body.type == 'MESH':
        return body
    if body:
        bpy.data.objects.remove(body, do_unlink=True)

    settings = projector.proj_settings
    mesh = _create_box_mesh('_Projector.BodyMesh', settings.body_dimensions)
    body = bpy.data.objects.new('Projector.Body', mesh)
    body[PROJECTOR_BODY_TAG] = True
    body.parent = projector
    body.matrix_parent_inverse.identity()
    body.hide_render = False
    body.hide_viewport = False
    body.display_type = 'SOLID'
    body.scale = (1.0, 1.0, 1.0)
    target_collection = projector.users_collection[0] if projector.users_collection else bpy.context.scene.collection
    target_collection.objects.link(body)
    mat = _get_or_create_body_material()
    if not body.data.materials:
        body.data.materials.append(mat)
    else:
        body.data.materials[0] = mat
    return body


def _set_body_from_object(source_obj, projector):
    if source_obj is None or source_obj.type != 'MESH':
        raise RuntimeError('Active object must be a mesh to duplicate as projector body.')

    body = source_obj.copy()
    if source_obj.data:
        body.data = source_obj.data.copy()
    body.name = f'{source_obj.name}.ProjectorBody'
    body[PROJECTOR_BODY_TAG] = True
    body.parent = projector
    body.matrix_parent_inverse.identity()
    body.location = projector.proj_settings.body_offset
    target_collection = projector.users_collection[0] if projector.users_collection else bpy.context.scene.collection
    target_collection.objects.link(body)
    return body


def _serialize_material(mat):
    if mat is None:
        return None

    data = {
        'name': mat.name,
        'diffuse_color': [float(value) for value in mat.diffuse_color],
        'use_nodes': bool(mat.use_nodes),
        'blend_method': getattr(mat, 'blend_method', 'OPAQUE'),
    }
    if mat.use_nodes and mat.node_tree is not None:
        bsdf = mat.node_tree.nodes.get('Principled BSDF')
        if bsdf is not None:
            for prop_name, input_name in (
                ('base_color', 'Base Color'),
                ('roughness', 'Roughness'),
                ('metallic', 'Metallic'),
                ('alpha', 'Alpha'),
            ):
                socket = bsdf.inputs.get(input_name)
                if socket is None:
                    continue
                value = socket.default_value
                if hasattr(value, '__iter__'):
                    data[prop_name] = [float(item) for item in value]
                else:
                    data[prop_name] = float(value)
    return data


def _create_material_from_data(data):
    if not isinstance(data, dict):
        return _get_or_create_body_material()

    mat_name = data.get('name') or 'Saved Body Material'
    source_mat = bpy.data.materials.get(mat_name)
    if source_mat is not None:
        return source_mat.copy()

    mat = bpy.data.materials.new(f'{mat_name}.ProjectorCopy')
    diffuse_color = data.get('diffuse_color', (0.17, 0.17, 0.19, 1.0))
    try:
        mat.diffuse_color = tuple(diffuse_color)
    except (TypeError, ValueError):
        mat.diffuse_color = (0.17, 0.17, 0.19, 1.0)

    mat.use_nodes = bool(data.get('use_nodes', True))
    if mat.use_nodes and mat.node_tree is not None:
        bsdf = mat.node_tree.nodes.get('Principled BSDF')
        if bsdf is not None:
            if 'base_color' in data and bsdf.inputs.get('Base Color') is not None:
                bsdf.inputs['Base Color'].default_value = tuple(data['base_color'])
            if 'roughness' in data and bsdf.inputs.get('Roughness') is not None:
                bsdf.inputs['Roughness'].default_value = float(data['roughness'])
            if 'metallic' in data and bsdf.inputs.get('Metallic') is not None:
                bsdf.inputs['Metallic'].default_value = float(data['metallic'])
            if 'alpha' in data and bsdf.inputs.get('Alpha') is not None:
                bsdf.inputs['Alpha'].default_value = float(data['alpha'])

    if hasattr(mat, 'blend_method'):
        mat.blend_method = data.get('blend_method', 'OPAQUE')
    return mat


def _serialize_body_materials(obj):
    if obj is None or obj.type != 'MESH' or obj.data is None:
        return ''
    materials = [_serialize_material(slot.material) for slot in obj.material_slots if slot.material is not None]
    return json.dumps(materials) if materials else ''


def _apply_body_materials(obj, materials_json):
    if obj is None or obj.type != 'MESH' or obj.data is None:
        return
    obj.data.materials.clear()
    materials = []
    if materials_json:
        try:
            materials = json.loads(materials_json)
        except json.JSONDecodeError:
            materials = []
    if not materials:
        obj.data.materials.append(_get_or_create_body_material())
        return
    for material_data in materials:
        obj.data.materials.append(_create_material_from_data(material_data))


def _serialize_mesh_data(obj):
    if obj is None or obj.type != 'MESH' or obj.data is None:
        return '', '', ''
    mesh = obj.data
    vertices = [[float(v.co.x), float(v.co.y), float(v.co.z)] for v in mesh.vertices]
    faces = [list(p.vertices) for p in mesh.polygons if len(p.vertices) >= 3]
    material_indices = [int(p.material_index) for p in mesh.polygons if len(p.vertices) >= 3]
    if not vertices or not faces:
        return '', '', ''
    return json.dumps(vertices), json.dumps(faces), json.dumps(material_indices)


def _create_body_from_mesh_data(projector, vertices_json, faces_json, material_indices_json='', materials_json=''):
    if not vertices_json or not faces_json:
        return None
    try:
        vertices = json.loads(vertices_json)
        faces = json.loads(faces_json)
    except Exception:
        return None
    if not vertices or not faces:
        return None

    mesh = bpy.data.meshes.new('_Projector.BodyMesh.Template')
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    material_indices = []
    if material_indices_json:
        try:
            material_indices = json.loads(material_indices_json)
        except json.JSONDecodeError:
            material_indices = []
    for poly, material_index in zip(mesh.polygons, material_indices):
        try:
            poly.material_index = int(material_index)
        except (TypeError, ValueError):
            poly.material_index = 0

    body = bpy.data.objects.new('Projector.Body', mesh)
    body[PROJECTOR_BODY_TAG] = True
    body.parent = projector
    body.matrix_parent_inverse.identity()
    body.hide_render = False
    body.hide_viewport = False
    body.display_type = 'SOLID'
    target_collection = projector.users_collection[0] if projector.users_collection else bpy.context.scene.collection
    target_collection.objects.link(body)
    _apply_body_materials(body, materials_json)
    return body


def _apply_body(projector, proj_settings):
    if projector is None:
        return

    body = get_projector_body(projector)
    body_type = proj_settings.get('body_type', 'DEFAULT_BOX')

    if body_type == 'NONE':
        if body:
            bpy.data.objects.remove(body, do_unlink=True)
        return

    if body_type == 'DEFAULT_BOX':
        body = _ensure_default_body(projector)
        mesh = _create_box_mesh('_Projector.BodyMesh', proj_settings.body_dimensions)
        old_mesh = body.data
        body.data = mesh
        if old_mesh and old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh, do_unlink=True)
        mat = _get_or_create_body_material()
        if not body.data.materials:
            body.data.materials.append(mat)
        else:
            body.data.materials[0] = mat
    elif body_type == 'SELECTED_OBJECT':
        # Keep the currently assigned custom body if available, otherwise fallback.
        if body is None:
            body = _ensure_default_body(projector)

    if body:
        body.location = Vector(proj_settings.body_offset)
        body.rotation_euler = Euler(proj_settings.body_rotation, 'XYZ')
        body.hide_render = False
        body.hide_viewport = False


def update_body(proj_settings, context):
    _apply_body(get_projector(context), proj_settings)


def _apply_emitter_transform(projector, proj_settings):
    spot = get_projector_spot(projector)
    if spot is None:
        return

    spot.location = Vector(proj_settings.emitter_offset)
    spot.rotation_euler = Euler(proj_settings.emitter_rotation, 'XYZ')


def update_emitter_transform(proj_settings, context):
    projector = get_projector(context)
    _apply_emitter_transform(projector, proj_settings)
    _apply_projection_cone(projector, proj_settings)


def _create_projection_cone_mesh(name, width, height, shift_x, shift_y, length):
    half_w = max(width * 0.5, 0.01)
    half_h = max(height * 0.5, 0.01)
    length = max(length, 0.2)
    verts = [
        (0.0, 0.0, 0.0),
        (-half_w + shift_x, -half_h + shift_y, -length),
        (half_w + shift_x, -half_h + shift_y, -length),
        (half_w + shift_x, half_h + shift_y, -length),
        (-half_w + shift_x, half_h + shift_y, -length),
    ]
    faces = [(0, 1, 2), (0, 2, 3), (0, 3, 4), (0, 4, 1), (4, 3, 2, 1)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    return mesh


def _meters_to_scene_units(value_m, scene=None):
    scene = scene or bpy.context.scene
    scale = 1.0
    if scene is not None and scene.unit_settings is not None:
        scale = scene.unit_settings.scale_length if scene.unit_settings.scale_length > 0 else 1.0
    return value_m / scale


def _get_or_create_cone_material():
    mat = bpy.data.materials.get('_Projector.ConeMaterial')
    if mat is None:
        mat = bpy.data.materials.new('_Projector.ConeMaterial')
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out = nodes.new('ShaderNodeOutputMaterial')
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Base Color'].default_value = (0.45, 0.72, 1.0, 1.0)
    bsdf.inputs['Alpha'].default_value = 0.25
    bsdf.inputs['Roughness'].default_value = 0.35
    links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])

    mat.blend_method = 'BLEND'
    if hasattr(mat, 'shadow_method'):
        mat.shadow_method = 'NONE'
    return mat


def _set_spot_enabled(projector, enabled):
    spot = get_projector_spot(projector)
    if spot is None:
        return
    spot.data.energy = projector.proj_settings.power if enabled else 0.0


def _apply_projection_cone(projector, proj_settings):
    if projector is None:
        return

    cone = get_projector_cone(projector)
    if not proj_settings.projection_cone_enabled:
        _remove_all_projector_cones(projector)
        _set_spot_enabled(projector, True)
        return

    res_w, res_h = _get_resolution_for_projector(projector, proj_settings)
    aspect = max(res_w / max(res_h, 1.0), 0.01)
    throw_ratio = max(proj_settings.throw_ratio, 0.1)
    length_m = max(proj_settings.projection_cone_length, 0.0)
    if length_m <= 0.0:
        _remove_all_projector_cones(projector)
        _set_spot_enabled(projector, False)
        return
    length = _meters_to_scene_units(length_m)
    width = length / throw_ratio
    height = width / aspect
    shift_x = (proj_settings.h_shift / 100.0) * width
    shift_y = (proj_settings.v_shift / 100.0) * height
    mesh = _create_projection_cone_mesh(
        '_Projector.ConeMesh',
        width=width,
        height=height,
        shift_x=shift_x,
        shift_y=shift_y,
        length=length,
    )

    spot = get_projector_spot(projector)
    if spot is None:
        return

    if cone is None:
        cone = bpy.data.objects.new('Projector.Cone', mesh)
        cone[PROJECTOR_CONE_TAG] = True
        cone.parent = spot
        cone.matrix_parent_inverse.identity()
        target_collection = projector.users_collection[0] if projector.users_collection else bpy.context.scene.collection
        target_collection.objects.link(cone)
    else:
        # Clean up any duplicated old cones and keep a single active one.
        _remove_all_projector_cones(projector)
        cone = bpy.data.objects.new('Projector.Cone', mesh)
        cone[PROJECTOR_CONE_TAG] = True
        cone.parent = spot
        cone.matrix_parent_inverse.identity()
        target_collection = projector.users_collection[0] if projector.users_collection else bpy.context.scene.collection
        target_collection.objects.link(cone)

    cone.location = (0.0, 0.0, 0.0)
    cone.rotation_euler = Euler((0.0, 0.0, 0.0), 'XYZ')
    cone.hide_render = False
    cone.hide_viewport = False
    cone.hide_select = True
    cone.display_type = 'TEXTURED'
    mat = _get_or_create_cone_material()
    if not cone.data.materials:
        cone.data.materials.append(mat)
    else:
        cone.data.materials[0] = mat
    _set_spot_enabled(projector, False)


def update_projection_cone(proj_settings, context):
    _apply_projection_cone(get_projector(context), proj_settings)

def _get_resolution_for_projector(projector, proj_settings):
    if proj_settings.use_custom_texture_res and proj_settings.projected_texture == Textures.CUSTOM_TEXTURE.value:
        spot = get_projector_spot(projector)
        if spot is None:
            return 300.0, 300.0
        root_tree = spot.data.node_tree
        image_node = root_tree.nodes.get('Image Texture')
        if image_node and image_node.image:
            return float(image_node.image.size[0]), float(image_node.image.size[1])
        return 300.0, 300.0

    try:
        w, h = proj_settings.resolution.split('x')
        return float(w), float(h)
    except Exception:
        return 1920.0, 1080.0


def get_resolution(proj_settings, context):
    """ Find out what resolution is currently used and return it.
    Resolution from the dropdown or the resolution from the custom texture.
    """
    return _get_resolution_for_projector(get_projector(context), proj_settings)


def _apply_lens_shift_to_projector(projector, proj_settings):
    if projector is None:
        return
    h_shift = proj_settings.get('h_shift', 0.0) / 100
    v_shift = proj_settings.get('v_shift', 0.0) / 100
    throw_ratio = proj_settings.get('throw_ratio')

    w, h = _get_resolution_for_projector(projector, proj_settings)
    inverted_aspect_ratio = h/w

    cam = projector
    cam.data.shift_x = h_shift
    cam.data.shift_y = v_shift * inverted_aspect_ratio

    spot = get_projector_spot(projector)
    if spot is None:
        return
    nodes = spot.data.node_tree.nodes['Group'].node_tree.nodes
    if bpy.app.version < (2, 81):
        nodes['Mapping.001'].translation[0] = h_shift / throw_ratio
        nodes['Mapping.001'].translation[1] = v_shift / throw_ratio * inverted_aspect_ratio
    else:
        nodes['Mapping.001'].inputs[1].default_value[0] = h_shift / throw_ratio
        nodes['Mapping.001'].inputs[1].default_value[1] = v_shift / throw_ratio * inverted_aspect_ratio


def _apply_throw_ratio_to_projector(projector, proj_settings):
    if projector is None:
        return
    throw_ratio = proj_settings.get('throw_ratio')
    distance = 1
    alpha = math.atan((distance/throw_ratio)*.5) * 2
    projector.data.lens_unit = 'FOV'
    projector.data.angle = alpha
    projector.data.sensor_width = 10
    projector.data.display_size = 1

    w, h = _get_resolution_for_projector(projector, proj_settings)
    aspect_ratio = w/h
    inverted_aspect_ratio = 1/aspect_ratio

    _apply_projected_texture_to_projector(projector, proj_settings)

    spot = get_projector_spot(projector)
    if spot is None:
        return
    nodes = spot.data.node_tree.nodes['Group'].node_tree.nodes
    if bpy.app.version < (2, 81):
        nodes['Mapping.001'].scale[0] = 1 / throw_ratio
        nodes['Mapping.001'].scale[1] = 1 / throw_ratio * inverted_aspect_ratio
    else:
        nodes['Mapping.001'].inputs[3].default_value[0] = 1 / throw_ratio
        nodes['Mapping.001'].inputs[3].default_value[1] = 1 / \
            throw_ratio * inverted_aspect_ratio

    _apply_lens_shift_to_projector(projector, proj_settings)
    _apply_projection_cone(projector, proj_settings)


def _apply_pixel_grid_to_projector(projector, proj_settings):
    spot = get_projector_spot(projector)
    if spot is None:
        return
    root_tree = spot.data.node_tree
    nodes = root_tree.nodes
    pixel_grid_nodes = nodes['pixel_grid'].node_tree.nodes
    width, height = _get_resolution_for_projector(projector, proj_settings)
    pixel_grid_nodes['_width'].outputs[0].default_value = width
    pixel_grid_nodes['_height'].outputs[0].default_value = height
    if proj_settings.show_pixel_grid:
        root_tree.links.new(nodes['pixel_grid'].outputs[0], nodes['Light Output'].inputs[0])
    else:
        root_tree.links.new(nodes['Emission'].outputs[0], nodes['Light Output'].inputs[0])


def _apply_checker_color_to_projector(projector, proj_settings):
    spot = get_projector_spot(projector)
    if spot is None:
        return
    nodes = spot.data.node_tree.nodes['Group'].node_tree.nodes
    c = proj_settings.projected_color
    nodes['Checker Texture'].inputs['Color2'].default_value = [c.r, c.g, c.b, 1]


def _apply_power_to_projector(projector, proj_settings):
    spot = get_projector_spot(projector)
    if spot is None:
        return
    if proj_settings.projection_cone_enabled:
        spot.data.energy = 0.0
    else:
        spot.data.energy = proj_settings["power"]


def _apply_resolution_to_projector(projector, proj_settings):
    spot = get_projector_spot(projector)
    if spot is None:
        return
    nodes = spot.data.node_tree.nodes['Group'].node_tree.nodes
    nodes['Image Texture'].image = bpy.data.images[f'_proj.tex.{proj_settings.resolution}']
    _apply_throw_ratio_to_projector(projector, proj_settings)
    _apply_pixel_grid_to_projector(projector, proj_settings)
    _apply_projection_cone(projector, proj_settings)


def _refresh_projector_derived_state(projector):
    if projector is None or not hasattr(projector, 'proj_settings'):
        return

    proj_settings = projector.proj_settings
    _ensure_projector_hierarchy(projector)
    _make_projector_datablocks_local(projector)
    _apply_emitter_transform(projector, proj_settings)
    _apply_resolution_to_projector(projector, proj_settings)
    _apply_projected_texture_to_projector(projector, proj_settings)
    _apply_checker_color_to_projector(projector, proj_settings)
    _apply_power_to_projector(projector, proj_settings)
    _apply_body(projector, proj_settings)
    _apply_projection_cone(projector, proj_settings)


def update_throw_ratio(proj_settings, context):
    """
    Adjust some settings on a camera to achieve a throw ratio
    """
    projector = get_projector(context)
    _apply_throw_ratio_to_projector(projector, proj_settings)

    


def update_lens_shift(proj_settings, context):
    """
    Apply the shift to the camera and texture.
    """
    projector = get_projector(context)
    _apply_lens_shift_to_projector(projector, proj_settings)
    _apply_projection_cone(projector, proj_settings)


def update_resolution(proj_settings, context):
    projector = get_projector(context)
    _apply_resolution_to_projector(projector, proj_settings)


def update_checker_color(proj_settings, context):
    # Update checker texture color
    projector = get_projector(context)
    _apply_checker_color_to_projector(projector, proj_settings)


def update_power(proj_settings, context):
    projector = get_projector(context)
    _apply_power_to_projector(projector, proj_settings)


def update_pixel_grid(proj_settings, context):
    """ Update the pixel grid. Meaning, make it visible by linking the right node and updating the resolution. """
    _apply_pixel_grid_to_projector(get_projector(context), proj_settings)

    
def create_pixel_grid_node_group():
    node_group = bpy.data.node_groups.new(
        '_Projectors-Addon_PixelGrid', 'ShaderNodeTree')

    # Create input/output sockets for the node group.
    if(bpy.app.version >= (4, 0)):
        node_group.interface.new_socket('Shader', socket_type='NodeSocketShader')
        node_group.interface.new_socket('Vector', socket_type='NodeSocketVector')

        node_group.interface.new_socket('Shader', in_out='OUTPUT', socket_type='NodeSocketShader')
    else:
        inputs = node_group.inputs
        inputs.new('NodeSocketShader', 'Shader')
        inputs.new('NodeSocketVector', 'Vector')

        outputs = node_group.outputs
        outputs.new('NodeSocketShader', 'Shader')

    nodes = node_group.nodes

    auto_pos = auto_offset()

    group_input = nodes.new('NodeGroupInput')
    group_input.location = auto_pos(200)

    sepXYZ = nodes.new('ShaderNodeSeparateXYZ')
    sepXYZ.location = auto_pos(200)

    in_width = nodes.new('ShaderNodeValue')
    in_width.name = '_width'
    in_width.label = 'Width'
    in_width.location = auto_pos(100)

    in_height = nodes.new('ShaderNodeValue')
    in_height.name = '_height'
    in_height.label = 'Height'
    in_height.location = auto_pos(y=-200)

    mul1 = nodes.new('ShaderNodeMath')
    mul1.operation = 'MULTIPLY'
    mul1.location = auto_pos(100)

    mul2 = nodes.new('ShaderNodeMath')
    mul2.operation = 'MULTIPLY'
    mul2.location = auto_pos(y=-200)

    mod1 = nodes.new('ShaderNodeMath')
    mod1.operation = 'MODULO'
    mod1.inputs[1].default_value = 1
    mod1.location = auto_pos(100)

    mod2 = nodes.new('ShaderNodeMath')
    mod2.operation = 'MODULO'
    mod2.inputs[1].default_value = 1
    mod2.location = auto_pos(y=-200)

    col_ramp1 = nodes.new('ShaderNodeValToRGB')
    col_ramp1.color_ramp.elements[1].position = 0.025
    col_ramp1.color_ramp.interpolation = 'CONSTANT'
    col_ramp1.location = auto_pos(100)

    col_ramp2 = nodes.new('ShaderNodeValToRGB')
    col_ramp2.color_ramp.elements[1].position = 0.025
    col_ramp2.color_ramp.interpolation = 'CONSTANT'
    col_ramp2.location = auto_pos(y=-200)

    mix_rgb = nodes.new('ShaderNodeMixRGB')
    mix_rgb.use_clamp = True
    mix_rgb.blend_type = 'MULTIPLY'
    mix_rgb.inputs[0].default_value = 1
    mix_rgb.location = auto_pos(200)
    
    transparent = nodes.new('ShaderNodeBsdfTransparent')
    transparent.location = auto_pos(y=-200)

    mix_shader = nodes.new('ShaderNodeMixShader')
    mix_shader.location = auto_pos(100)

    group_output = nodes.new('NodeGroupOutput')
    group_output.location = auto_pos(100)
    
    # Link Nodes
    links = node_group.links

    links.new(group_input.outputs[0], mix_shader.inputs[2])
    links.new(group_input.outputs[1], sepXYZ.inputs[0])

    links.new(in_width.outputs[0], mul1.inputs[1])
    links.new(in_height.outputs[0], mul2.inputs[1])

    links.new(sepXYZ.outputs[0], mul1.inputs[0])
    links.new(sepXYZ.outputs[1], mul2.inputs[0])

    links.new(mul1.outputs[0], mod1.inputs[0])
    links.new(mul2.outputs[0], mod2.inputs[0])

    links.new(mod1.outputs[0], col_ramp1.inputs[0])
    links.new(mod2.outputs[0], col_ramp2.inputs[0])

    links.new(col_ramp1.outputs[0], mix_rgb.inputs[1])
    links.new(col_ramp2.outputs[0], mix_rgb.inputs[2])

    links.new(mix_rgb.outputs[0], mix_shader.inputs[0])
    links.new(transparent.outputs[0], mix_shader.inputs[1])

    links.new(mix_shader.outputs[0], group_output.inputs[0])

    return node_group
    

def create_projector(context):
    """
    Create a new projector composed out of a camera (parent obj) and a spotlight (child not intended for user interaction).
    The camera is the object intended for the user to manipulate and custom properties are stored there.
    The spotlight with a custom nodetree is responsible for actual projection of the texture.
    """
    create_projector_textures()
    log.debug('Creating projector.')

    # Create a camera and a spotlight
    # ### Spot Light ###
    bpy.ops.object.light_add(type='SPOT', location=(0, 0, 0))
    spot = context.object
    spot.name = 'Projector.Spot'
    spot.scale = (.01, .01, .01)
    spot.data.spot_size = math.pi - 0.001
    spot.data.spot_blend = 0
    spot.data.shadow_soft_size = 0.0
    spot.hide_select = True
    spot[PROJECTOR_SPOT_TAG] = True
    spot.data.cycles.use_multiple_importance_sampling = False
    add_projector_node_tree_to_spot(spot)

    # ### Camera ###
    bpy.ops.object.camera_add(enter_editmode=False,
                              location=(0, 0, 0),
                              rotation=(0, 0, 0))
    cam = context.object
    cam.name = 'Projector'
    cam[PROJECTOR_INSTANCE_TAG] = _new_projector_instance_id()

    # Parent light to cam.
    spot.parent = cam

    # Move newly create projector (cam and spotlight) to 3D-Cursor position.
    cam.location = context.scene.cursor.location
    cam.rotation_euler = context.scene.cursor.rotation_euler
    return cam


def init_projector(proj_settings, context):
    # # Add custom properties to store projector settings on the camera obj..
    proj_settings.throw_ratio = 0.8
    proj_settings.power = 1000.0
    proj_settings.projected_texture = Textures.CHECKER.value
    proj_settings.h_shift = 0.0
    proj_settings.v_shift = 0.0
    proj_settings.projected_color = random_color()
    proj_settings.resolution = '1920x1080'
    proj_settings.use_custom_texture_res = True
    proj_settings.body_type = 'DEFAULT_BOX'
    proj_settings.body_dimensions = (0.35, 0.12, 0.22)
    proj_settings.body_offset = (0.0, 0.0, 0.12)
    proj_settings.body_rotation = (0.0, 0.0, 0.0)
    proj_settings.emitter_offset = (0.0, 0.0, 0.0)
    proj_settings.emitter_rotation = (0.0, 0.0, 0.0)
    proj_settings.projection_cone_enabled = False
    proj_settings.projection_cone_length = 3.0

    # Init Projector
    update_throw_ratio(proj_settings, context)
    update_projected_texture(proj_settings, context)
    update_resolution(proj_settings, context)
    update_checker_color(proj_settings, context)
    update_lens_shift(proj_settings, context)
    update_power(proj_settings, context)
    update_pixel_grid(proj_settings, context)
    update_emitter_transform(proj_settings, context)
    update_body(proj_settings, context)
    update_projection_cone(proj_settings, context)


def _apply_model_to_projector(projector, model_data):
    settings = projector.proj_settings
    projector.location = Vector(model_data.get('projector_location', tuple(projector.location)))
    projector.rotation_euler = Euler(model_data.get('projector_rotation', tuple(projector.rotation_euler)), 'XYZ')
    projector.scale = Vector(model_data.get('projector_scale', tuple(projector.scale)))
    settings.throw_ratio = model_data['throw_ratio']
    settings.power = model_data['power']
    settings.h_shift = model_data['h_shift']
    settings.v_shift = model_data['v_shift']
    resolution = model_data.get('resolution', settings.resolution)
    if any(item[0] == resolution for item in RESOLUTIONS):
        settings.resolution = resolution
    settings.use_custom_texture_res = model_data.get('use_custom_texture_res', settings.use_custom_texture_res)
    projected_texture = model_data.get('projected_texture', settings.projected_texture)
    if projected_texture in {item[0] for item in PROJECTED_OUTPUTS}:
        settings.projected_texture = projected_texture
    settings.projected_color = model_data.get('projected_color', tuple(settings.projected_color))
    settings.show_pixel_grid = model_data.get('show_pixel_grid', settings.show_pixel_grid)
    settings.projection_cone_enabled = model_data.get('projection_cone_enabled', False)
    settings.projection_cone_length = model_data.get('projection_cone_length', 3.0)
    settings.body_type = model_data['body_type']
    settings.body_dimensions = model_data['body_dimensions']
    settings.body_offset = model_data['body_offset']
    settings.body_rotation = model_data.get('body_rotation', (0.0, 0.0, 0.0))
    settings.emitter_offset = model_data['emitter_offset']
    settings.emitter_rotation = model_data['emitter_rotation']


def _model_data_from_preset(preset):
    return {
        'body_type': preset.body_type,
        'body_dimensions': tuple(preset.body_dimensions),
        'body_offset': tuple(preset.body_offset),
        'body_rotation': tuple(preset.body_rotation),
        'projector_location': tuple(preset.projector_location),
        'projector_rotation': tuple(preset.projector_rotation),
        'projector_scale': tuple(preset.projector_scale),
        'emitter_offset': tuple(preset.emitter_offset),
        'emitter_rotation': tuple(preset.emitter_rotation),
        'power': preset.power,
        'throw_ratio': preset.throw_ratio,
        'h_shift': preset.h_shift,
        'v_shift': preset.v_shift,
        'resolution': preset.resolution,
        'use_custom_texture_res': preset.use_custom_texture_res,
        'projected_texture': preset.projected_texture,
        'projected_color': tuple(preset.projected_color),
        'show_pixel_grid': preset.show_pixel_grid,
        'projection_cone_enabled': preset.projection_cone_enabled,
        'projection_cone_length': preset.projection_cone_length,
        'body_mesh_vertices_json': preset.body_mesh_vertices_json,
        'body_mesh_faces_json': preset.body_mesh_faces_json,
        'body_mesh_material_indices_json': preset.body_mesh_material_indices_json,
        'body_materials_json': preset.body_materials_json,
    }


def _store_model_preset_from_data(manufacturer, model_name, model_data):
    prefs = get_addon_preferences()
    if prefs is None:
        return False

    manufacturer = manufacturer.strip()
    model_name = model_name.strip()
    if not manufacturer or not model_name:
        return False

    # Overwrite existing same name.
    existing_idx = -1
    for idx, item in enumerate(prefs.projector_models):
        if item.manufacturer == manufacturer and item.model_name == model_name:
            existing_idx = idx
            break

    if existing_idx >= 0:
        preset = prefs.projector_models[existing_idx]
    else:
        preset = prefs.projector_models.add()

    preset.manufacturer = manufacturer
    preset.model_name = model_name
    preset.body_type = model_data['body_type']
    preset.body_dimensions = model_data['body_dimensions']
    preset.body_offset = model_data['body_offset']
    preset.body_rotation = model_data.get('body_rotation', (0.0, 0.0, 0.0))
    preset.projector_location = model_data.get('projector_location', (0.0, 0.0, 0.0))
    preset.projector_rotation = model_data.get('projector_rotation', (0.0, 0.0, 0.0))
    preset.projector_scale = model_data.get('projector_scale', (1.0, 1.0, 1.0))
    preset.emitter_offset = model_data['emitter_offset']
    preset.emitter_rotation = model_data['emitter_rotation']
    preset.power = model_data['power']
    preset.throw_ratio = model_data['throw_ratio']
    preset.h_shift = model_data['h_shift']
    preset.v_shift = model_data['v_shift']
    preset.resolution = model_data.get('resolution', '1920x1080')
    preset.use_custom_texture_res = model_data.get('use_custom_texture_res', True)
    preset.projected_texture = model_data.get('projected_texture', Textures.CHECKER.value)
    preset.projected_color = model_data.get('projected_color', (1.0, 1.0, 1.0))
    preset.show_pixel_grid = model_data.get('show_pixel_grid', False)
    preset.projection_cone_enabled = model_data.get('projection_cone_enabled', False)
    preset.projection_cone_length = model_data.get('projection_cone_length', 3.0)
    preset.body_mesh_vertices_json = model_data.get('body_mesh_vertices_json', '')
    preset.body_mesh_faces_json = model_data.get('body_mesh_faces_json', '')
    preset.body_mesh_material_indices_json = model_data.get('body_mesh_material_indices_json', '')
    preset.body_materials_json = model_data.get('body_materials_json', '')
    _write_models_store(prefs)
    return True


class PROJECTOR_OT_create_projector(Operator):
    """Create Projector"""
    bl_idname = 'projector.create'
    bl_label = 'Create a new Projector'
    bl_options = {'REGISTER', 'UNDO'}

    body_type: bpy.props.EnumProperty(name='Body', items=BODY_TYPES, default='DEFAULT_BOX')
    body_x: bpy.props.FloatProperty(name='Length', default=0.35, min=0.01, subtype='DISTANCE')
    body_y: bpy.props.FloatProperty(name='Depth', default=0.12, min=0.01, subtype='DISTANCE')
    body_z: bpy.props.FloatProperty(name='Height', default=0.22, min=0.01, subtype='DISTANCE')
    body_offset: bpy.props.FloatVectorProperty(name='Body Offset', size=3, default=(0.0, 0.0, 0.12), subtype='TRANSLATION')
    body_rotation: bpy.props.FloatVectorProperty(name='Body Rotation', size=3, default=(0.0, 0.0, 0.0), subtype='EULER', unit='ROTATION')
    emitter_offset: bpy.props.FloatVectorProperty(name='Emitter Offset', size=3, default=(0.0, 0.0, 0.0), subtype='TRANSLATION')
    emitter_rotation: bpy.props.FloatVectorProperty(name='Emitter Rotation', size=3, default=(0.0, 0.0, 0.0), subtype='EULER', unit='ROTATION')

    power: bpy.props.FloatProperty(name='Power', default=1000.0, min=0.0, soft_max=999999.0)
    throw_ratio: bpy.props.FloatProperty(name='Throw Ratio', default=0.8, min=0.1, soft_max=3.0)
    h_shift: bpy.props.FloatProperty(name='Horizontal Shift', default=0.0, soft_min=-20.0, soft_max=20.0, subtype='PERCENTAGE')
    v_shift: bpy.props.FloatProperty(name='Vertical Shift', default=0.0, soft_min=-20.0, soft_max=20.0, subtype='PERCENTAGE')
    projection_cone_enabled: bpy.props.BoolProperty(name='Show Projection Cone', default=False)
    projection_cone_length: bpy.props.FloatProperty(name='Cone Length (m)', default=0.0, min=0.0)

    use_saved_model: bpy.props.BoolProperty(name='Use Saved Model', default=False)
    saved_model: bpy.props.EnumProperty(name='Saved Model', items=_model_preset_items)

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(self, 'use_saved_model')
        if self.use_saved_model:
            # Keep selected model in WM as fallback for stale operator instances during reload.
            context.window_manager['projector_saved_model_pending'] = self.saved_model
            row_model = layout.row(align=True)
            row_model.prop(self, 'saved_model', text='Saved Model')
            op_del = row_model.operator('projector.delete_saved_model', text='', icon='X')
            if hasattr(op_del, 'skip_dialog'):
                op_del.skip_dialog = True
            if hasattr(op_del, 'saved_model'):
                op_del.saved_model = self.saved_model

        box = layout.box()
        box.label(text='Body')
        box.prop(self, 'body_type')
        if self.body_type == 'DEFAULT_BOX':
            row = box.row(align=True)
            row.prop(self, 'body_x')
            row.prop(self, 'body_y')
            row.prop(self, 'body_z')
        box.prop(self, 'body_offset')
        box.prop(self, 'body_rotation')

        beam = layout.box()
        beam.label(text='Projection Cone')
        beam.prop(self, 'projection_cone_enabled')
        if getattr(self, 'projection_cone_enabled', False):
            beam.prop(self, 'projection_cone_length')

        proj = layout.box()
        proj.label(text='Projector Settings')
        proj.prop(self, 'power')
        proj.prop(self, 'throw_ratio')
        proj.prop(self, 'h_shift')
        proj.prop(self, 'v_shift')

    def execute(self, context):
        source_body_obj = context.view_layer.objects.active
        projector = create_projector(context)
        init_projector(projector.proj_settings, context)

        model_data = None
        if self.use_saved_model and self.saved_model != 'NONE':
            prefs = get_addon_preferences()
            if prefs is not None:
                try:
                    preset = prefs.projector_models[int(self.saved_model)]
                    model_data = _model_data_from_preset(preset)
                except (ValueError, IndexError):
                    pass

        if model_data is None:
            model_data = {
                'body_type': self.body_type,
                'body_dimensions': (self.body_x, self.body_y, self.body_z),
                'body_offset': tuple(self.body_offset),
                'body_rotation': tuple(self.body_rotation),
                'projector_location': tuple(projector.location),
                'projector_rotation': tuple(projector.rotation_euler),
                'projector_scale': tuple(projector.scale),
                'emitter_offset': tuple(self.emitter_offset),
                'emitter_rotation': tuple(self.emitter_rotation),
                'power': self.power,
                'throw_ratio': self.throw_ratio,
                'h_shift': self.h_shift,
                'v_shift': self.v_shift,
                'resolution': '1920x1080',
                'use_custom_texture_res': True,
                'projected_texture': Textures.CHECKER.value,
                'projected_color': random_color(),
                'show_pixel_grid': False,
                'projection_cone_enabled': getattr(self, 'projection_cone_enabled', False),
                'projection_cone_length': getattr(self, 'projection_cone_length', 3.0),
                'body_mesh_vertices_json': '',
                'body_mesh_faces_json': '',
                'body_mesh_material_indices_json': '',
                'body_materials_json': '',
            }

        _apply_model_to_projector(projector, model_data)

        if model_data.get('body_mesh_vertices_json'):
            existing_body = get_projector_body(projector)
            if existing_body is not None:
                old_mesh = existing_body.data
                bpy.data.objects.remove(existing_body, do_unlink=True)
                if old_mesh and old_mesh.users == 0:
                    bpy.data.meshes.remove(old_mesh, do_unlink=True)
            restored = _create_body_from_mesh_data(
                projector,
                model_data.get('body_mesh_vertices_json', ''),
                model_data.get('body_mesh_faces_json', ''),
                model_data.get('body_mesh_material_indices_json', ''),
                model_data.get('body_materials_json', ''),
            )
            if restored is not None:
                restored.location = Vector(model_data['body_offset'])
                restored.rotation_euler = Euler(model_data.get('body_rotation', (0.0, 0.0, 0.0)), 'XYZ')
                projector.proj_settings.body_type = 'SELECTED_OBJECT'
            else:
                _apply_body(projector, projector.proj_settings)
        elif model_data['body_type'] == 'SELECTED_OBJECT':
            try:
                existing_body = get_projector_body(projector)
                if existing_body is not None:
                    old_mesh = existing_body.data
                    bpy.data.objects.remove(existing_body, do_unlink=True)
                    if old_mesh and old_mesh.users == 0:
                        bpy.data.meshes.remove(old_mesh, do_unlink=True)
                body = _set_body_from_object(source_body_obj, projector)
                body.location = Vector(model_data['body_offset'])
            except RuntimeError as exc:
                self.report({'WARNING'}, f'{exc} Using default body instead.')
                projector.proj_settings.body_type = 'DEFAULT_BOX'
                _apply_body(projector, projector.proj_settings)
        else:
            _apply_body(projector, projector.proj_settings)

        _apply_emitter_transform(projector, projector.proj_settings)
        _apply_projection_cone(projector, projector.proj_settings)
        if projector.proj_settings.body_type == 'DEFAULT_BOX' and get_projector_body(projector) is None:
            _ensure_default_body(projector)
            _apply_body(projector, projector.proj_settings)
        return {'FINISHED'}


def _model_data_from_settings(settings):
    return {
        'body_type': settings.body_type,
        'body_dimensions': tuple(settings.body_dimensions),
        'body_offset': tuple(settings.body_offset),
        'body_rotation': tuple(settings.body_rotation),
        'emitter_offset': tuple(settings.emitter_offset),
        'emitter_rotation': tuple(settings.emitter_rotation),
        'power': settings.power,
        'throw_ratio': settings.throw_ratio,
        'h_shift': settings.h_shift,
        'v_shift': settings.v_shift,
        'resolution': settings.resolution,
        'use_custom_texture_res': settings.use_custom_texture_res,
        'projected_texture': settings.projected_texture,
        'projected_color': tuple(settings.projected_color),
        'show_pixel_grid': settings.show_pixel_grid,
        'projection_cone_enabled': settings.projection_cone_enabled,
        'projection_cone_length': settings.projection_cone_length,
        'body_mesh_vertices_json': '',
        'body_mesh_faces_json': '',
        'body_mesh_material_indices_json': '',
        'body_materials_json': '',
    }


def _model_data_from_projector(projector):
    settings = projector.proj_settings
    data = _model_data_from_settings(settings)
    data['projector_location'] = tuple(projector.location)
    data['projector_rotation'] = tuple(projector.rotation_euler)
    data['projector_scale'] = tuple(projector.scale)
    body = get_projector_body(projector)
    if body is None:
        return data

    data['body_offset'] = tuple(body.location)
    data['body_rotation'] = tuple(body.rotation_euler)

    # Persist the current configured body geometry, not only defaults.
    if body.type == 'MESH':
        dims = body.dimensions
        data['body_dimensions'] = (
            max(float(dims.x), 0.01),
            max(float(dims.y), 0.01),
            max(float(dims.z), 0.01),
        )
        vertices_json, faces_json, material_indices_json = _serialize_mesh_data(body)
        data['body_mesh_vertices_json'] = vertices_json
        data['body_mesh_faces_json'] = faces_json
        data['body_mesh_material_indices_json'] = material_indices_json
        data['body_materials_json'] = _serialize_body_materials(body)

    return data


def _model_settings_signature(model_data):
    settings_data = dict(model_data)
    for key in ('projector_location', 'projector_rotation', 'projector_scale'):
        settings_data.pop(key, None)
    return json.dumps(settings_data, sort_keys=True, ensure_ascii=True)


def _array_settings_signature(settings):
    return json.dumps(settings, sort_keys=True, ensure_ascii=True)


def _array_settings_from_source(source):
    raw_settings = source.get(PROJECTOR_ARRAY_SETTINGS_TAG, '')
    if not raw_settings:
        return None
    try:
        settings = json.loads(raw_settings)
    except (TypeError, json.JSONDecodeError):
        return None
    return settings if isinstance(settings, dict) else None


def _array_total_count(settings):
    if settings.get('mode') == 'GRID':
        return max(int(settings.get('columns', 1)), 1) * max(int(settings.get('rows', 1)), 1)
    return max(int(settings.get('count', 2)), 2)


def _iter_projector_objects(scene=None):
    objects = bpy.data.objects if scene is None else scene.objects
    for obj in list(objects):
        if obj.type == 'CAMERA' and obj.name.startswith('Projector') and hasattr(obj, 'proj_settings'):
            yield obj


def _find_projector_by_instance_id(scene, instance_id):
    if not instance_id:
        return None
    for obj in _iter_projector_objects(scene):
        if obj.type == 'CAMERA' and obj.get(PROJECTOR_INSTANCE_TAG, '') == instance_id:
            return obj
    return None


def _array_source_for_projector(scene, projector):
    source_id = projector.get(PROJECTOR_ARRAY_SOURCE_ID_TAG, '')
    source = _find_projector_by_instance_id(scene, source_id)
    if source is not None:
        return source

    source_name = projector.get(PROJECTOR_ARRAY_SOURCE_TAG, '')
    source = bpy.data.objects.get(source_name)
    if source is not None and source.type == 'CAMERA':
        return source
    return None


def _array_controller_source_from_context(context):
    projector = get_projector(context)
    if projector is None:
        return None
    if projector.get(PROJECTOR_ARRAY_CONTROLLER_TAG, False):
        return projector
    if projector.get(PROJECTOR_ARRAY_LINKED_TAG, False):
        return _array_source_for_projector(context.scene, projector)
    return None


def _linked_array_children(scene, source):
    source_id = source.get(PROJECTOR_INSTANCE_TAG, '')
    children = []
    for obj in scene.objects:
        if obj == source or not obj.get(PROJECTOR_ARRAY_LINKED_TAG, False):
            continue
        if obj.get(PROJECTOR_ARRAY_SOURCE_ID_TAG, '') == source_id:
            children.append(obj)
        elif obj.get(PROJECTOR_ARRAY_SOURCE_TAG, '') == source.name:
            children.append(obj)
    return sorted(children, key=lambda child: int(child.get(PROJECTOR_ARRAY_INDEX_TAG, 0)))


def _array_transform_for_index(source, settings, index):
    base_location = Vector(source.location)
    base_rotation = source.rotation_euler.copy()
    base_scale = Vector(source.scale)
    mode = settings.get('mode', 'LINEAR')

    if mode == 'GRID':
        columns = max(int(settings.get('columns', 1)), 1)
        column = index % columns
        row = index // columns
        column_offset = Vector(settings.get('offset', (1.0, 0.0, 0.0)))
        row_offset = Vector(settings.get('row_offset', (0.0, 1.0, 0.0)))
        local_offset = (column_offset * column) + (row_offset * row)
        return base_location + local_offset, base_rotation, base_scale

    if mode == 'RADIAL':
        total = _array_total_count(settings)
        arc = float(settings.get('radial_arc', math.tau))
        start = float(settings.get('radial_start_angle', 0.0))
        is_full_circle = abs(abs(arc) - math.tau) < 0.0001
        step = arc / total if is_full_circle else arc / max(total - 1, 1)
        radius = _meters_to_scene_units(float(settings.get('radial_radius', 2.0)))
        source_offset = Vector((
            math.cos(start) * radius,
            math.sin(start) * radius,
            0.0,
        ))
        center = base_location - source_offset
        angle = start + (step * index)
        local_offset = Vector((
            math.cos(angle) * radius,
            math.sin(angle) * radius,
            0.0,
        ))
        rotation = base_rotation.copy()
        if bool(settings.get('rotate_radial_projectors', True)):
            rotation = (Matrix.Rotation(step * index, 3, 'Z') @ base_rotation.to_matrix()).to_euler('XYZ')
        return center + local_offset, rotation, base_scale

    offset = Vector(settings.get('offset', (1.0, 0.0, 0.0)))
    return base_location + (offset * index), base_rotation, base_scale


def _apply_source_state_to_array_child(source_data, source_signature, projector, location, rotation, scale):
    model_data = dict(source_data)
    model_data['projector_location'] = tuple(location)
    model_data['projector_rotation'] = tuple(rotation)
    model_data['projector_scale'] = tuple(scale)
    _apply_model_to_projector(projector, model_data)
    _restore_body_from_model_data(projector, model_data)
    projector.location = Vector(location)
    projector.rotation_euler = Euler(rotation, 'XYZ')
    projector.scale = Vector(scale)
    _refresh_projector_derived_state(projector)
    projector[PROJECTOR_ARRAY_STATE_TAG] = source_signature


def _configure_array_child(projector, source, index, source_signature):
    projector[PROJECTOR_ARRAY_LINKED_TAG] = True
    projector[PROJECTOR_ARRAY_SOURCE_TAG] = source.name
    projector[PROJECTOR_ARRAY_SOURCE_ID_TAG] = source.get(PROJECTOR_INSTANCE_TAG, '')
    projector[PROJECTOR_ARRAY_INDEX_TAG] = int(index)
    projector[PROJECTOR_ARRAY_STATE_TAG] = source_signature


def _settings_from_array_operator(operator):
    return {
        'mode': operator.array_mode,
        'count': int(operator.count),
        'columns': int(operator.columns),
        'rows': int(operator.rows),
        'offset': list(operator.offset),
        'row_offset': list(operator.row_offset),
        'radial_radius': float(operator.radial_radius),
        'radial_arc': float(operator.radial_arc),
        'radial_start_angle': float(operator.radial_start_angle),
        'rotate_radial_projectors': bool(operator.rotate_radial_projectors),
    }


def _apply_array_settings_to_operator(operator, settings):
    operator.array_mode = settings.get('mode', operator.array_mode)
    operator.count = int(settings.get('count', operator.count))
    operator.columns = int(settings.get('columns', operator.columns))
    operator.rows = int(settings.get('rows', operator.rows))
    operator.offset = settings.get('offset', tuple(operator.offset))
    operator.row_offset = settings.get('row_offset', tuple(operator.row_offset))
    operator.radial_radius = float(settings.get('radial_radius', operator.radial_radius))
    operator.radial_arc = float(settings.get('radial_arc', operator.radial_arc))
    operator.radial_start_angle = float(settings.get('radial_start_angle', operator.radial_start_angle))
    operator.rotate_radial_projectors = bool(
        settings.get('rotate_radial_projectors', operator.rotate_radial_projectors))


def _remove_projector_hierarchy(projector):
    stack = list(projector.children)
    descendants = []
    while stack:
        child = stack.pop()
        descendants.append(child)
        stack.extend(child.children)
    for child in descendants:
        bpy.data.objects.remove(child, do_unlink=True)
    bpy.data.objects.remove(projector, do_unlink=True)


def _rebuild_projector_array(context, source, settings, operator=None):
    model_data = _model_data_from_projector(source)
    source_signature = _model_settings_signature(model_data)
    total = _array_total_count(settings)
    existing_children = {
        int(child.get(PROJECTOR_ARRAY_INDEX_TAG, 0)): child
        for child in _linked_array_children(context.scene, source)
        if int(child.get(PROJECTOR_ARRAY_INDEX_TAG, 0)) > 0
    }
    created_count = 0

    source[PROJECTOR_ARRAY_CONTROLLER_TAG] = True
    source[PROJECTOR_ARRAY_SETTINGS_TAG] = _array_settings_signature(settings)

    for index in range(1, total):
        location, rotation, scale = _array_transform_for_index(source, settings, index)
        projector = existing_children.pop(index, None)
        if projector is None:
            copy_data = dict(model_data)
            copy_data['projector_location'] = tuple(location)
            copy_data['projector_rotation'] = tuple(rotation)
            copy_data['projector_scale'] = tuple(scale)
            projector = _create_projector_from_model_data(context, copy_data)
            projector.name = f'{source.name}.Array'
            projector[PROJECTOR_INSTANCE_TAG] = _new_projector_instance_id()
            created_count += 1
        _configure_array_child(projector, source, index, source_signature)
        _apply_source_state_to_array_child(model_data, source_signature, projector, location, rotation, scale)

    removed_count = 0
    for projector in existing_children.values():
        _remove_projector_hierarchy(projector)
        removed_count += 1

    if operator is not None:
        operator.report({'INFO'}, f'Array updated. Created {created_count}, removed {removed_count}.')

    return created_count, removed_count


def _sync_linked_projector_arrays(scene=None):
    source_states = {}
    for projector in _iter_projector_objects(scene):
        if not projector.get(PROJECTOR_ARRAY_LINKED_TAG, False):
            continue

        source = _array_source_for_projector(scene, projector)
        if source is None or source == projector or not hasattr(source, 'proj_settings'):
            continue

        source_name = source.name
        if source_name not in source_states:
            source_data = _model_data_from_projector(source)
            source_states[source_name] = (
                source_data,
                _model_settings_signature(source_data),
                _array_settings_from_source(source),
            )

        source_data, source_signature, settings = source_states[source_name]
        if settings is not None and PROJECTOR_ARRAY_INDEX_TAG in projector:
            target_location, target_rotation, target_scale = _array_transform_for_index(
                source, settings, int(projector.get(PROJECTOR_ARRAY_INDEX_TAG, 0)))
        else:
            target_location = tuple(projector.location)
            target_rotation = tuple(projector.rotation_euler)
            target_scale = tuple(projector.scale)

        has_state_change = projector.get(PROJECTOR_ARRAY_STATE_TAG, '') != source_signature
        has_transform_change = (
            tuple(projector.location) != tuple(target_location)
            or tuple(projector.rotation_euler) != tuple(target_rotation)
            or tuple(projector.scale) != tuple(target_scale)
        )
        if has_state_change:
            _apply_source_state_to_array_child(
                source_data, source_signature, projector, target_location, target_rotation, target_scale)
        elif has_transform_change:
            projector.location = Vector(target_location)
            projector.rotation_euler = Euler(target_rotation, 'XYZ')
            projector.scale = Vector(target_scale)


def _sync_linked_projector_arrays_deferred():
    global _PROJECTOR_DUPLICATE_HANDLER_RUNNING
    global _PROJECTOR_ARRAY_SYNC_SCHEDULED

    _PROJECTOR_ARRAY_SYNC_SCHEDULED = False
    _PROJECTOR_DUPLICATE_HANDLER_RUNNING = True
    try:
        _sync_linked_projector_arrays()
    finally:
        _PROJECTOR_DUPLICATE_HANDLER_RUNNING = False

    return None


def _queue_linked_projector_array_sync():
    global _PROJECTOR_ARRAY_SYNC_SCHEDULED

    if not _PROJECTOR_ARRAY_SYNC_SCHEDULED:
        _PROJECTOR_ARRAY_SYNC_SCHEDULED = True
        bpy.app.timers.register(_sync_linked_projector_arrays_deferred, first_interval=0.05)


class PROJECTOR_OT_apply_saved_model(Operator):
    bl_idname = 'projector.apply_saved_model'
    bl_label = 'Apply Saved Model'
    bl_options = {'REGISTER', 'UNDO'}
    saved_model: bpy.props.EnumProperty(name='Saved Model', items=_saved_model_items, default='NONE')

    @classmethod
    def poll(cls, context):
        return get_projector(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, 'saved_model')

    def execute(self, context):
        projector = get_projector(context)
        if projector is None:
            return {'CANCELLED'}

        model_key = getattr(self, 'saved_model', 'NONE')
        if model_key == 'NONE':
            self.report({'WARNING'}, 'Select a saved model first.')
            return {'CANCELLED'}

        prefs = get_addon_preferences()
        if prefs is None:
            return {'CANCELLED'}

        try:
            preset = prefs.projector_models[int(model_key)]
        except (ValueError, IndexError):
            self.report({'ERROR'}, 'Saved model not found.')
            return {'CANCELLED'}

        model_data = _model_data_from_preset(preset)
        _apply_model_to_projector(projector, model_data)
        if model_data.get('body_mesh_vertices_json'):
            existing_body = get_projector_body(projector)
            if existing_body is not None:
                old_mesh = existing_body.data
                bpy.data.objects.remove(existing_body, do_unlink=True)
                if old_mesh and old_mesh.users == 0:
                    bpy.data.meshes.remove(old_mesh, do_unlink=True)
            restored = _create_body_from_mesh_data(
                projector,
                model_data.get('body_mesh_vertices_json', ''),
                model_data.get('body_mesh_faces_json', ''),
                model_data.get('body_mesh_material_indices_json', ''),
                model_data.get('body_materials_json', ''),
            )
            if restored is not None:
                restored.location = Vector(model_data['body_offset'])
                restored.rotation_euler = Euler(model_data.get('body_rotation', (0.0, 0.0, 0.0)), 'XYZ')
                projector.proj_settings.body_type = 'SELECTED_OBJECT'
            else:
                _apply_body(projector, projector.proj_settings)
        else:
            _apply_body(projector, projector.proj_settings)
        _apply_emitter_transform(projector, projector.proj_settings)
        _apply_projection_cone(projector, projector.proj_settings)
        self.report({'INFO'}, f'Applied model: {preset.manufacturer} - {preset.model_name}')
        return {'FINISHED'}


class PROJECTOR_OT_save_model_from_selected(Operator):
    bl_idname = 'projector.save_model_from_selected'
    bl_label = 'Save Current as Model'
    bl_options = {'REGISTER', 'UNDO'}

    manufacturer: bpy.props.StringProperty(name='Manufacturer', default='')
    model_name: bpy.props.StringProperty(name='Model', default='')

    @classmethod
    def poll(cls, context):
        return get_projector(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, 'manufacturer')
        layout.prop(self, 'model_name')

    def execute(self, context):
        projector = get_projector(context)
        if projector is None:
            return {'CANCELLED'}
        model_data = _model_data_from_projector(projector)
        if _store_model_preset_from_data(self.manufacturer, self.model_name, model_data):
            self.report({'INFO'}, f'Saved model {self.manufacturer} - {self.model_name}')
            return {'FINISHED'}
        self.report({'WARNING'}, 'Model not saved. Fill manufacturer and model name.')
        return {'CANCELLED'}


class PROJECTOR_OT_create_projector_array(Operator):
    bl_idname = 'projector.create_array'
    bl_label = 'Create Projector Array'
    bl_options = {'REGISTER', 'UNDO'}

    array_mode: bpy.props.EnumProperty(
        name='Mode',
        items=[
            ('LINEAR', 'Linear', 'Create a line of projectors'),
            ('GRID', 'Grid', 'Create rows and columns of projectors'),
            ('RADIAL', 'Radial', 'Create projectors around an arc or circle'),
        ],
        default='LINEAR')
    count: bpy.props.IntProperty(name='Count', default=3, min=2)
    columns: bpy.props.IntProperty(name='Columns', default=3, min=1)
    rows: bpy.props.IntProperty(name='Rows', default=2, min=1)
    offset: bpy.props.FloatVectorProperty(
        name='Offset',
        size=3,
        default=(1.0, 0.0, 0.0),
        subtype='TRANSLATION')
    row_offset: bpy.props.FloatVectorProperty(
        name='Row Offset',
        size=3,
        default=(0.0, 1.0, 0.0),
        subtype='TRANSLATION')
    radial_radius: bpy.props.FloatProperty(
        name='Radius',
        default=2.0,
        min=0.0,
        subtype='DISTANCE',
        unit='LENGTH')
    radial_arc: bpy.props.FloatProperty(
        name='Arc',
        default=math.tau,
        min=-math.tau,
        max=math.tau,
        subtype='ANGLE',
        unit='ROTATION')
    radial_start_angle: bpy.props.FloatProperty(
        name='Start Angle',
        default=0.0,
        subtype='ANGLE',
        unit='ROTATION')
    rotate_radial_projectors: bpy.props.BoolProperty(name='Rotate Along Arc', default=True)
    keep_settings_linked: bpy.props.BoolProperty(name='Keep Settings Linked', default=True)

    @classmethod
    def poll(cls, context):
        return get_projector(context) is not None and context.mode == 'OBJECT'

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, 'array_mode')

        if self.array_mode == 'LINEAR':
            layout.prop(self, 'count')
            layout.prop(self, 'offset')
        elif self.array_mode == 'GRID':
            layout.prop(self, 'columns')
            layout.prop(self, 'rows')
            layout.prop(self, 'offset', text='Column Offset')
            layout.prop(self, 'row_offset')
        else:
            layout.prop(self, 'count')
            layout.prop(self, 'radial_radius')
            layout.prop(self, 'radial_arc')
            layout.prop(self, 'radial_start_angle')
            layout.prop(self, 'rotate_radial_projectors')

        layout.prop(self, 'keep_settings_linked')

    def _array_transforms(self, source):
        base_location = Vector(source.location)
        base_rotation = source.rotation_euler.copy()
        base_scale = Vector(source.scale)
        rotation_matrix = base_rotation.to_matrix()

        if self.array_mode == 'LINEAR':
            offset = Vector(self.offset)
            for index in range(1, self.count):
                yield (
                    base_location + rotation_matrix @ (offset * index),
                    base_rotation,
                    base_scale,
                )
        elif self.array_mode == 'GRID':
            column_offset = Vector(self.offset)
            row_offset = Vector(self.row_offset)
            for row in range(self.rows):
                for column in range(self.columns):
                    if row == 0 and column == 0:
                        continue
                    local_offset = (column_offset * column) + (row_offset * row)
                    yield (
                        base_location + rotation_matrix @ local_offset,
                        base_rotation,
                        base_scale,
                    )
        else:
            total = max(self.count, 2)
            arc = self.radial_arc
            start = self.radial_start_angle
            is_full_circle = abs(abs(arc) - math.tau) < 0.0001
            step = arc / total if is_full_circle else arc / max(total - 1, 1)
            radius = _meters_to_scene_units(self.radial_radius)
            source_offset = Vector((
                math.cos(start) * radius,
                math.sin(start) * radius,
                0.0,
            ))
            center = base_location - (rotation_matrix @ source_offset)
            for index in range(1, total):
                angle = start + (step * index)
                local_offset = Vector((
                    math.cos(angle) * radius,
                    math.sin(angle) * radius,
                    0.0,
                ))
                rotation = base_rotation.copy()
                if self.rotate_radial_projectors:
                    rotation = (Matrix.Rotation(step * index, 3, 'Z') @ base_rotation.to_matrix()).to_euler('XYZ')
                yield (
                    center + rotation_matrix @ local_offset,
                    rotation,
                    base_scale,
                )

    def execute(self, context):
        source = get_projector(context)
        if source is None:
            return {'CANCELLED'}

        settings = _settings_from_array_operator(self)
        if self.keep_settings_linked:
            _rebuild_projector_array(context, source, settings)
            created = _linked_array_children(context.scene, source)
            bpy.ops.object.select_all(action='DESELECT')
            source.select_set(True)
            for projector in created:
                projector.select_set(True)
            context.view_layer.objects.active = source
            self.report({'INFO'}, f'Created {len(created)} linked array projectors.')
            return {'FINISHED'}

        model_data = _model_data_from_projector(source)
        created = []

        for index in range(1, _array_total_count(settings)):
            location, rotation, scale = _array_transform_for_index(source, settings, index)
            copy_data = dict(model_data)
            copy_data['projector_location'] = tuple(location)
            copy_data['projector_rotation'] = tuple(rotation)
            copy_data['projector_scale'] = tuple(scale)
            projector = _create_projector_from_model_data(context, copy_data)
            projector.name = f'{source.name}.Array'
            projector[PROJECTOR_INSTANCE_TAG] = _new_projector_instance_id()
            _refresh_projector_derived_state(projector)
            created.append(projector)

        if not created:
            self.report({'WARNING'}, 'No projectors were created.')
            return {'CANCELLED'}

        bpy.ops.object.select_all(action='DESELECT')
        source.select_set(True)
        for projector in created:
            projector.select_set(True)
        context.view_layer.objects.active = source

        self.report({'INFO'}, f'Created {len(created)} array projectors.')
        return {'FINISHED'}


class PROJECTOR_OT_edit_projector_array(Operator):
    bl_idname = 'projector.edit_array'
    bl_label = 'Edit Projector Array'
    bl_options = {'REGISTER', 'UNDO'}

    array_mode: bpy.props.EnumProperty(
        name='Mode',
        items=[
            ('LINEAR', 'Linear', 'Create a line of projectors'),
            ('GRID', 'Grid', 'Create rows and columns of projectors'),
            ('RADIAL', 'Radial', 'Create projectors around an arc or circle'),
        ],
        default='LINEAR')
    count: bpy.props.IntProperty(name='Count', default=3, min=2)
    columns: bpy.props.IntProperty(name='Columns', default=3, min=1)
    rows: bpy.props.IntProperty(name='Rows', default=2, min=1)
    offset: bpy.props.FloatVectorProperty(
        name='Offset',
        size=3,
        default=(1.0, 0.0, 0.0),
        subtype='TRANSLATION')
    row_offset: bpy.props.FloatVectorProperty(
        name='Row Offset',
        size=3,
        default=(0.0, 1.0, 0.0),
        subtype='TRANSLATION')
    radial_radius: bpy.props.FloatProperty(
        name='Radius',
        default=2.0,
        min=0.0,
        subtype='DISTANCE',
        unit='LENGTH')
    radial_arc: bpy.props.FloatProperty(
        name='Arc',
        default=math.tau,
        min=-math.tau,
        max=math.tau,
        subtype='ANGLE',
        unit='ROTATION')
    radial_start_angle: bpy.props.FloatProperty(
        name='Start Angle',
        default=0.0,
        subtype='ANGLE',
        unit='ROTATION')
    rotate_radial_projectors: bpy.props.BoolProperty(name='Rotate Along Arc', default=True)

    @classmethod
    def poll(cls, context):
        return _array_controller_source_from_context(context) is not None and context.mode == 'OBJECT'

    def invoke(self, context, event):
        source = _array_controller_source_from_context(context)
        if source is None:
            return {'CANCELLED'}
        settings = _array_settings_from_source(source)
        if settings is not None:
            _apply_array_settings_to_operator(self, settings)
        self.keep_settings_linked = True
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, 'array_mode')

        if self.array_mode == 'LINEAR':
            layout.prop(self, 'count')
            layout.prop(self, 'offset')
        elif self.array_mode == 'GRID':
            layout.prop(self, 'columns')
            layout.prop(self, 'rows')
            layout.prop(self, 'offset', text='Column Offset')
            layout.prop(self, 'row_offset')
        else:
            layout.prop(self, 'count')
            layout.prop(self, 'radial_radius')
            layout.prop(self, 'radial_arc')
            layout.prop(self, 'radial_start_angle')
            layout.prop(self, 'rotate_radial_projectors')

    def execute(self, context):
        source = _array_controller_source_from_context(context)
        if source is None:
            return {'CANCELLED'}
        settings = _settings_from_array_operator(self)
        _rebuild_projector_array(context, source, settings, self)
        bpy.ops.object.select_all(action='DESELECT')
        source.select_set(True)
        for projector in _linked_array_children(context.scene, source):
            projector.select_set(True)
        context.view_layer.objects.active = source
        return {'FINISHED'}


class PROJECTOR_OT_make_array_independent(Operator):
    bl_idname = 'projector.make_array_independent'
    bl_label = 'Make Array Independent'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(
            projector.get(PROJECTOR_ARRAY_LINKED_TAG, False)
            or projector.get(PROJECTOR_ARRAY_CONTROLLER_TAG, False)
            for projector in get_projectors(context, only_selected=True)
        )

    def execute(self, context):
        count = 0
        keys = (
            PROJECTOR_ARRAY_LINKED_TAG,
            PROJECTOR_ARRAY_SOURCE_TAG,
            PROJECTOR_ARRAY_SOURCE_ID_TAG,
            PROJECTOR_ARRAY_STATE_TAG,
            PROJECTOR_ARRAY_CONTROLLER_TAG,
            PROJECTOR_ARRAY_INDEX_TAG,
            PROJECTOR_ARRAY_SETTINGS_TAG,
        )
        for projector in get_projectors(context, only_selected=True):
            if projector.get(PROJECTOR_ARRAY_CONTROLLER_TAG, False):
                for child in _linked_array_children(context.scene, projector):
                    for key in keys:
                        if key in child:
                            del child[key]
                    count += 1
                for key in keys:
                    if key in projector:
                        del projector[key]
                continue

            if not projector.get(PROJECTOR_ARRAY_LINKED_TAG, False):
                continue
            for key in keys:
                if key in projector:
                    del projector[key]
            count += 1

        if count == 0:
            self.report({'WARNING'}, 'Select linked array projectors first.')
            return {'CANCELLED'}

        self.report({'INFO'}, f'Made {count} array projectors independent.')
        return {'FINISHED'}


def _restore_body_from_model_data(projector, model_data, source_body_obj=None, operator=None):
    if model_data.get('body_mesh_vertices_json'):
        existing_body = get_projector_body(projector)
        if existing_body is not None:
            old_mesh = existing_body.data
            bpy.data.objects.remove(existing_body, do_unlink=True)
            if old_mesh and old_mesh.users == 0:
                bpy.data.meshes.remove(old_mesh, do_unlink=True)
        restored = _create_body_from_mesh_data(
            projector,
            model_data.get('body_mesh_vertices_json', ''),
            model_data.get('body_mesh_faces_json', ''),
            model_data.get('body_mesh_material_indices_json', ''),
            model_data.get('body_materials_json', ''),
        )
        if restored is not None:
            restored.location = Vector(model_data['body_offset'])
            restored.rotation_euler = Euler(model_data.get('body_rotation', (0.0, 0.0, 0.0)), 'XYZ')
            projector.proj_settings.body_type = 'SELECTED_OBJECT'
        else:
            _apply_body(projector, projector.proj_settings)
    elif model_data['body_type'] == 'SELECTED_OBJECT' and source_body_obj is not None:
        try:
            existing_body = get_projector_body(projector)
            if existing_body is not None:
                old_mesh = existing_body.data
                bpy.data.objects.remove(existing_body, do_unlink=True)
                if old_mesh and old_mesh.users == 0:
                    bpy.data.meshes.remove(old_mesh, do_unlink=True)
            body = _set_body_from_object(source_body_obj, projector)
            body.location = Vector(model_data['body_offset'])
        except RuntimeError as exc:
            if operator is not None:
                operator.report({'WARNING'}, f'{exc} Using default body instead.')
            projector.proj_settings.body_type = 'DEFAULT_BOX'
            _apply_body(projector, projector.proj_settings)
    else:
        _apply_body(projector, projector.proj_settings)

    _apply_emitter_transform(projector, projector.proj_settings)
    _apply_projection_cone(projector, projector.proj_settings)


def _create_projector_from_model_data(context, model_data):
    projector = create_projector(context)
    init_projector(projector.proj_settings, context)
    _apply_model_to_projector(projector, model_data)
    _restore_body_from_model_data(projector, model_data)
    return projector


class PROJECTOR_OT_reload_saved_models(Operator):
    bl_idname = 'projector.reload_saved_models'
    bl_label = 'Reload Saved Models'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if _load_models_store_into_preferences():
            prefs = get_addon_preferences()
            count = len(prefs.projector_models) if prefs is not None else 0
            self.report({'INFO'}, f'Reloaded {count} saved models.')
            return {'FINISHED'}

        self.report({'WARNING'}, 'No saved model store found.')
        return {'CANCELLED'}


class PROJECTOR_OT_export_saved_models(Operator):
    bl_idname = 'projector.export_saved_models'
    bl_label = 'Export Saved Library'
    bl_options = {'REGISTER'}

    filepath: bpy.props.StringProperty(
        name='File Path',
        default='projector_saved_models.json',
        subtype='FILE_PATH')

    @classmethod
    def poll(cls, context):
        prefs = get_addon_preferences()
        return prefs is not None and len(prefs.projector_models) > 0

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        prefs = get_addon_preferences()
        if prefs is None:
            return {'CANCELLED'}

        filepath = self.filepath
        if not filepath:
            self.report({'WARNING'}, 'Choose a JSON file path.')
            return {'CANCELLED'}
        if not filepath.lower().endswith('.json'):
            filepath = f'{filepath}.json'

        payload = {
            'version': 1,
            'models': _serialize_models_from_preferences(prefs),
        }
        try:
            output_dir = os.path.dirname(filepath)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as handle:
                json.dump(payload, handle, ensure_ascii=True, indent=2)
        except OSError:
            log.exception('Failed to export projector model library: %s', filepath)
            self.report({'ERROR'}, 'Failed to export saved projector library.')
            return {'CANCELLED'}

        self.report({'INFO'}, f'Exported {len(payload["models"])} saved models.')
        return {'FINISHED'}


class PROJECTOR_OT_import_saved_models(Operator):
    bl_idname = 'projector.import_saved_models'
    bl_label = 'Import Saved Library'
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(
        name='File Path',
        subtype='FILE_PATH')

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        prefs = get_addon_preferences()
        if prefs is None:
            return {'CANCELLED'}
        if not self.filepath:
            self.report({'WARNING'}, 'Choose a saved projector JSON file.')
            return {'CANCELLED'}

        try:
            with open(self.filepath, 'r', encoding='utf-8') as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            log.exception('Failed to import projector model library: %s', self.filepath)
            self.report({'ERROR'}, 'Failed to import saved projector library.')
            return {'CANCELLED'}

        stored_models = _models_from_payload(payload)
        if not stored_models:
            self.report({'WARNING'}, 'No saved projector models found in this file.')
            return {'CANCELLED'}

        _populate_preferences_from_model_data(prefs, stored_models)
        _write_models_store(prefs)
        self.report({'INFO'}, f'Imported {len(prefs.projector_models)} saved models.')
        return {'FINISHED'}


class PROJECTOR_OT_delete_saved_model(Operator):
    bl_idname = 'projector.delete_saved_model'
    bl_label = 'Delete Saved Model'
    bl_options = {'REGISTER', 'UNDO'}
    saved_model: bpy.props.EnumProperty(name='Saved Model', items=_saved_model_items, default='NONE')
    skip_dialog: bpy.props.BoolProperty(name='Skip Dialog', default=False)

    @classmethod
    def poll(cls, context):
        prefs = get_addon_preferences()
        return prefs is not None and len(prefs.projector_models) > 0

    def invoke(self, context, event):
        if getattr(self, 'skip_dialog', False):
            return self.execute(context)
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, 'saved_model')

    def execute(self, context):
        model_key = getattr(self, 'saved_model', None)
        if not model_key or model_key == 'NONE':
            model_key = context.window_manager.get('projector_saved_model_pending', 'NONE')
        if model_key == 'NONE':
            self.report({'WARNING'}, 'Select a saved model to delete.')
            return {'CANCELLED'}

        prefs = get_addon_preferences()
        if prefs is None:
            return {'CANCELLED'}

        try:
            idx = int(model_key)
            label = f'{prefs.projector_models[idx].manufacturer} - {prefs.projector_models[idx].model_name}'
            prefs.projector_models.remove(idx)
            _write_models_store(prefs)
            context.window_manager['projector_saved_model_pending'] = 'NONE'
            self.report({'INFO'}, f'Deleted model: {label}')
            return {'FINISHED'}
        except (ValueError, IndexError):
            self.report({'ERROR'}, 'Saved model not found.')
            return {'CANCELLED'}


class PROJECTOR_OT_export_projection_cone(Operator):
    bl_idname = 'projector.export_projection_cone'
    bl_label = 'Export Cone Copy'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return get_projector(context) is not None

    def execute(self, context):
        projector = get_projector(context)
        if projector is None:
            return {'CANCELLED'}

        cone = get_projector_cone(projector)
        if cone is None:
            self.report({'ERROR'}, 'No projection cone found. Enable Show Projection Cone first.')
            return {'CANCELLED'}

        coll_name = 'Projector Cone Copies'
        target_collection = bpy.data.collections.get(coll_name)
        if target_collection is None:
            target_collection = bpy.data.collections.new(coll_name)
            context.scene.collection.children.link(target_collection)

        exported = _export_independent_cone_copy(cone, f'{projector.name}.ConeCopy', target_collection)
        if exported is None:
            self.report({'ERROR'}, 'Failed to create cone copy.')
            return {'CANCELLED'}
        self.report({'INFO'}, f'Cone copy created in collection "{coll_name}".')
        return {'FINISHED'}


def _export_independent_cone_copy(cone, name, target_collection):
    if cone is None or cone.data is None:
        return None

    mesh_copy = cone.data.copy()
    # Bake final world transform into geometry so the copy has no dependency on parent chain.
    mesh_copy.transform(cone.matrix_world)

    obj = bpy.data.objects.new(name, mesh_copy)
    obj.parent = None
    obj.matrix_world.identity()
    if PROJECTOR_CONE_TAG in obj:
        del obj[PROJECTOR_CONE_TAG]
    target_collection.objects.link(obj)
    return obj


def _create_random_cone_copy_material(name):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out = nodes.new('ShaderNodeOutputMaterial')
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    color = random_color(alpha=True)
    color[3] = 0.25
    mat.diffuse_color = color
    bsdf.inputs['Base Color'].default_value = color
    bsdf.inputs['Alpha'].default_value = 0.25
    bsdf.inputs['Roughness'].default_value = 0.35
    links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])

    mat.blend_method = 'BLEND'
    if hasattr(mat, 'shadow_method'):
        mat.shadow_method = 'NONE'
    return mat


class PROJECTOR_OT_export_all_projection_cones(Operator):
    bl_idname = 'projector.export_all_projection_cones'
    bl_label = 'Export All Cone Copies'
    bl_options = {'REGISTER', 'UNDO'}

    randomize_colors: bpy.props.BoolProperty(
        name='Randomize Colors',
        description='Give each copied cone its own random transparent material',
        default=False)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, 'randomize_colors')

    def execute(self, context):
        projectors = get_projectors(context, only_selected=False)
        if not projectors:
            self.report({'ERROR'}, 'No projectors found in scene.')
            return {'CANCELLED'}

        coll_name = 'Projector Cone Copies'
        target_collection = bpy.data.collections.get(coll_name)
        if target_collection is None:
            target_collection = bpy.data.collections.new(coll_name)
            context.scene.collection.children.link(target_collection)

        count = 0
        for projector in projectors:
            cone = get_projector_cone(projector)
            if cone is None:
                continue
            name = f'{projector.name}.ConeCopy'
            exported = _export_independent_cone_copy(cone, name, target_collection)
            if exported is not None:
                if self.randomize_colors:
                    mat = _create_random_cone_copy_material(f'{exported.name}.RandomMaterial')
                    if exported.data.materials:
                        exported.data.materials[0] = mat
                    else:
                        exported.data.materials.append(mat)
                count += 1

        if count == 0:
            self.report({'WARNING'}, 'No active projection cones found.')
            return {'CANCELLED'}

        self.report({'INFO'}, f'Created {count} independent cone copies in "{coll_name}".')
        return {'FINISHED'}


def _apply_projected_texture_to_projector(projector, proj_settings):
    if projector is None:
        return
    spot = get_projector_spot(projector)
    if spot is None:
        return
    root_tree = spot.data.node_tree
    group_tree = root_tree.nodes['Group'].node_tree
    group_output_node = group_tree.nodes['Group Output']
    group_node = root_tree.nodes['Group']
    emission_node = root_tree.nodes['Emission']

    # Switch between the three possible cases by relinking some nodes.
    case = proj_settings.projected_texture
    if case == Textures.CHECKER.value:
        mix_node = group_tree.nodes['Mix.001']
        group_tree.links.new(
            mix_node.outputs['Color'], group_output_node.inputs[1])
        root_tree.links.new(group_node.outputs[1], emission_node.inputs[0])
    elif case == Textures.COLOR_GRID.value:
        img_node = group_tree.nodes['Image Texture']
        group_tree.links.new(img_node.outputs[0], group_output_node.inputs[1])
        root_tree.links.new(group_node.outputs[1], emission_node.inputs[0])
    elif case == Textures.CUSTOM_TEXTURE.value:
        custom_tex_node = root_tree.nodes['Image Texture']
        root_tree.links.new(
            custom_tex_node.outputs[0], emission_node.inputs[0])


def update_projected_texture(proj_settings, context):
    """ Update the projected output source. """
    _apply_projected_texture_to_projector(get_projector(context), proj_settings)


class PROJECTOR_OT_delete_projector(Operator):
    """Delete Projector"""
    bl_idname = 'projector.delete'
    bl_label = 'Delete Projector'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(get_projectors(context, only_selected=True))

    def execute(self, context):
        selected_projectors = get_projectors(context, only_selected=True)
        for projector in selected_projectors:
            # Remove whole hierarchy (children, grandchildren, etc.) first.
            stack = list(projector.children)
            descendants = []
            while stack:
                child = stack.pop()
                descendants.append(child)
                stack.extend(child.children)

            # Remove deepest objects first to avoid orphaned hierarchy leftovers.
            for obj in reversed(descendants):
                if obj.name in bpy.data.objects:
                    bpy.data.objects.remove(obj, do_unlink=True)

            if projector.name in bpy.data.objects:
                bpy.data.objects.remove(projector, do_unlink=True)
        return {'FINISHED'}


class ProjectorSettings(bpy.types.PropertyGroup):
    throw_ratio: bpy.props.FloatProperty(
        name="Throw Ratio",
        soft_min=0.4, soft_max=3,
        update=update_throw_ratio,
        subtype='FACTOR')
    power: bpy.props.FloatProperty(
        name="Projector Power",
        soft_min=0, soft_max=999999,
        update=update_power,
        unit='POWER')
    resolution: bpy.props.EnumProperty(
        items=RESOLUTIONS,
        default='1920x1080',
        description="Select a Resolution for your Projector",
        update=update_resolution)
    use_custom_texture_res: bpy.props.BoolProperty(
        name="Let Image Define Projector Resolution",
        default=True,
        description="Use the resolution from the image as the projector resolution. Warning: After selecting a new image toggle this checkbox to update",
        update=update_throw_ratio)
    h_shift: bpy.props.FloatProperty(
        name="Horizontal Shift",
        description="Horizontal Lens Shift",
        soft_min=-20, soft_max=20,
        update=update_lens_shift,
        subtype='PERCENTAGE')
    v_shift: bpy.props.FloatProperty(
        name="Vertical Shift",
        description="Vertical Lens Shift",
        soft_min=-20, soft_max=20,
        update=update_lens_shift,
        subtype='PERCENTAGE')
    projected_color: bpy.props.FloatVectorProperty(
        subtype='COLOR',
        update=update_checker_color)
    projected_texture: bpy.props.EnumProperty(
        items=PROJECTED_OUTPUTS,
        default=Textures.CHECKER.value,
        description="What do you to project?",
        update=update_throw_ratio)
    show_pixel_grid: bpy.props.BoolProperty(
        name="Show Pixel Grid",
        description="When checked the image is divided into a pixel grid with the dimensions of the image resolution.",
        default=False,
        update=update_pixel_grid)
    body_type: bpy.props.EnumProperty(
        name='Body Type',
        items=BODY_TYPES,
        default='DEFAULT_BOX',
        update=update_body)
    body_dimensions: bpy.props.FloatVectorProperty(
        name='Body Dimensions',
        size=3,
        default=(0.35, 0.12, 0.22),
        min=0.01,
        subtype='XYZ',
        update=update_body)
    body_offset: bpy.props.FloatVectorProperty(
        name='Body Offset',
        size=3,
        default=(0.0, 0.0, 0.12),
        subtype='TRANSLATION',
        update=update_body)
    body_rotation: bpy.props.FloatVectorProperty(
        name='Body Rotation',
        size=3,
        default=(0.0, 0.0, 0.0),
        subtype='EULER',
        unit='ROTATION',
        update=update_body)
    emitter_offset: bpy.props.FloatVectorProperty(
        name='Emitter Offset',
        size=3,
        default=(0.0, 0.0, 0.0),
        subtype='TRANSLATION',
        update=update_emitter_transform)
    emitter_rotation: bpy.props.FloatVectorProperty(
        name='Emitter Rotation',
        size=3,
        default=(0.0, 0.0, 0.0),
        subtype='EULER',
        unit='ROTATION',
        update=update_emitter_transform)
    projection_cone_enabled: bpy.props.BoolProperty(
        name='Show Projection Cone',
        default=False,
        update=update_projection_cone)
    projection_cone_length: bpy.props.FloatProperty(
        name='Cone Length',
        default=3.0,
        min=0.2,
        subtype='DISTANCE',
        unit='LENGTH',
        update=update_projection_cone)


def register():
    _safe_register_class(ProjectorModelPreset)
    _safe_register_class(PROJECTOR_AP_preferences)
    _safe_register_class(ProjectorSettings)
    _safe_register_class(PROJECTOR_OT_create_projector)
    _safe_register_class(PROJECTOR_OT_apply_saved_model)
    _safe_register_class(PROJECTOR_OT_save_model_from_selected)
    _safe_register_class(PROJECTOR_OT_create_projector_array)
    _safe_register_class(PROJECTOR_OT_edit_projector_array)
    _safe_register_class(PROJECTOR_OT_make_array_independent)
    _safe_register_class(PROJECTOR_OT_reload_saved_models)
    _safe_register_class(PROJECTOR_OT_export_saved_models)
    _safe_register_class(PROJECTOR_OT_import_saved_models)
    _safe_register_class(PROJECTOR_OT_delete_saved_model)
    _safe_register_class(PROJECTOR_OT_export_projection_cone)
    _safe_register_class(PROJECTOR_OT_export_all_projection_cones)
    _safe_register_class(PROJECTOR_OT_delete_projector)
    _safe_register_class(PROJECTOR_OT_change_color_randomly)
    _load_models_store_into_preferences()
    bpy.types.Object.proj_settings = bpy.props.PointerProperty(
        type=ProjectorSettings)
    if _ensure_duplicated_projectors_are_independent not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_ensure_duplicated_projectors_are_independent)


def unregister():
    if _ensure_duplicated_projectors_are_independent in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_ensure_duplicated_projectors_are_independent)
    if hasattr(bpy.types.Object, 'proj_settings'):
        del bpy.types.Object.proj_settings
    _safe_unregister_class(PROJECTOR_OT_change_color_randomly)
    _safe_unregister_class(PROJECTOR_OT_delete_projector)
    _safe_unregister_class(PROJECTOR_OT_delete_saved_model)
    _safe_unregister_class(PROJECTOR_OT_import_saved_models)
    _safe_unregister_class(PROJECTOR_OT_export_saved_models)
    _safe_unregister_class(PROJECTOR_OT_reload_saved_models)
    _safe_unregister_class(PROJECTOR_OT_make_array_independent)
    _safe_unregister_class(PROJECTOR_OT_edit_projector_array)
    _safe_unregister_class(PROJECTOR_OT_create_projector_array)
    _safe_unregister_class(PROJECTOR_OT_save_model_from_selected)
    _safe_unregister_class(PROJECTOR_OT_export_all_projection_cones)
    _safe_unregister_class(PROJECTOR_OT_export_projection_cone)
    _safe_unregister_class(PROJECTOR_OT_apply_saved_model)
    _safe_unregister_class(PROJECTOR_OT_create_projector)
    _safe_unregister_class(ProjectorSettings)
    _safe_unregister_class(PROJECTOR_AP_preferences)
    _safe_unregister_class(ProjectorModelPreset)
