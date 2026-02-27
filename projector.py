import logging
import math
import os

from enum import Enum
import bpy
from bpy.types import AddonPreferences, Operator, PropertyGroup
from mathutils import Euler, Vector

from .helper import (ADDON_ID, auto_offset,
                     get_projectors, get_projector, random_color)

logging.basicConfig(
    format='[Projectors Addon]: %(name)s - %(levelname)s - %(message)s')
log = logging.getLogger(name=__file__)

PROJECTOR_SPOT_TAG = ADDON_ID.format('spot')
PROJECTOR_BODY_TAG = ADDON_ID.format('body')


def _safe_register_class(cls):
    try:
        bpy.utils.register_class(cls)
    except ValueError as exc:
        # Happens on script reload when Blender still holds previous class registration.
        if 'already registered as a subclass' not in str(exc):
            raise


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
    body_offset: bpy.props.FloatVectorProperty(name='Body Offset', size=3, default=(0.0, -0.06, 0.0), subtype='TRANSLATION')
    emitter_offset: bpy.props.FloatVectorProperty(name='Emitter Offset', size=3, default=(0.0, 0.0, 0.0), subtype='TRANSLATION')
    emitter_rotation: bpy.props.FloatVectorProperty(name='Emitter Rotation', size=3, default=(0.0, 0.0, 0.0), subtype='EULER', unit='ROTATION')
    power: bpy.props.FloatProperty(name='Power', default=1000.0, min=0.0, soft_max=999999.0)
    throw_ratio: bpy.props.FloatProperty(name='Throw Ratio', default=0.8, min=0.1, soft_max=3.0)
    h_shift: bpy.props.FloatProperty(name='Horizontal Shift', default=0.0, soft_min=-20.0, soft_max=20.0)
    v_shift: bpy.props.FloatProperty(name='Vertical Shift', default=0.0, soft_min=-20.0, soft_max=20.0)


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
        body.rotation_euler = Euler((0.0, 0.0, 0.0), 'XYZ')
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

def get_resolution(proj_settings, context):
    """ Find out what resolution is currently used and return it.
    Resolution from the dropdown or the resolution from the custom texture.
    """
    if proj_settings.use_custom_texture_res and proj_settings.projected_texture == Textures.CUSTOM_TEXTURE.value:
        projector = get_projector(context)
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


def update_throw_ratio(proj_settings, context):
    """
    Adjust some settings on a camera to achieve a throw ratio
    """
    projector = get_projector(context)
    if projector is None:
        return
    # Update properties of the camera.
    throw_ratio = proj_settings.get('throw_ratio')
    distance = 1
    alpha = math.atan((distance/throw_ratio)*.5) * 2
    projector.data.lens_unit = 'FOV'
    projector.data.angle = alpha
    projector.data.sensor_width = 10
    projector.data.display_size = 1

    # Adjust Texture to fit new camera ###
    w, h = get_resolution(proj_settings, context)
    aspect_ratio = w/h
    inverted_aspect_ratio = 1/aspect_ratio

    # Projected Texture
    update_projected_texture(proj_settings, context)

    # Update spotlight properties.
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

    # Update lens shift because it depends on the throw ratio.
    update_lens_shift(proj_settings, context)

    


def update_lens_shift(proj_settings, context):
    """
    Apply the shift to the camera and texture.
    """
    projector = get_projector(context)
    if projector is None:
        return
    h_shift = proj_settings.get('h_shift', 0.0) / 100
    v_shift = proj_settings.get('v_shift', 0.0) / 100
    throw_ratio = proj_settings.get('throw_ratio')

    w, h = get_resolution(proj_settings, context)
    inverted_aspect_ratio = h/w

    # Update the properties of the camera.
    cam = projector
    cam.data.shift_x = h_shift
    cam.data.shift_y = v_shift * inverted_aspect_ratio

    # Update spotlight node setup.
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


def update_resolution(proj_settings, context):
    projector = get_projector(context)
    spot = get_projector_spot(projector)
    if spot is None:
        return
    nodes = spot.data.node_tree.nodes['Group'].node_tree.nodes
    # Change resolution image texture
    nodes['Image Texture'].image = bpy.data.images[f'_proj.tex.{proj_settings.resolution}']
    update_throw_ratio(proj_settings, context)
    update_pixel_grid(proj_settings, context)


def update_checker_color(proj_settings, context):
    # Update checker texture color
    projector = get_projector(context)
    spot = get_projector_spot(projector)
    if spot is None:
        return
    nodes = spot.data.node_tree.nodes['Group'].node_tree.nodes
    c = proj_settings.projected_color
    nodes['Checker Texture'].inputs['Color2'].default_value = [c.r, c.g, c.b, 1]


def update_power(proj_settings, context):
    # Update spotlight power
    spot = get_projector_spot(get_projector(context))
    if spot is None:
        return
    spot.data.energy = proj_settings["power"]


def update_pixel_grid(proj_settings, context):
    """ Update the pixel grid. Meaning, make it visible by linking the right node and updating the resolution. """
    spot = get_projector_spot(get_projector(context))
    if spot is None:
        return
    root_tree = spot.data.node_tree
    nodes = root_tree.nodes
    pixel_grid_nodes = nodes['pixel_grid'].node_tree.nodes
    width, height = get_resolution(proj_settings, context)
    pixel_grid_nodes['_width'].outputs[0].default_value = width
    pixel_grid_nodes['_height'].outputs[0].default_value = height
    if proj_settings.show_pixel_grid:
        root_tree.links.new(nodes['pixel_grid'].outputs[0], nodes['Light Output'].inputs[0])
    else:
        root_tree.links.new(nodes['Emission'].outputs[0], nodes['Light Output'].inputs[0])

    
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

    # Parent light to cam.
    spot.parent = cam

    # Move newly create projector (cam and spotlight) to 3D-Cursor position.
    cam.location = context.scene.cursor.location
    cam.rotation_euler = context.scene.cursor.rotation_euler
    return cam


def init_projector(proj_settings, context):
    # # Add custom properties to store projector settings on the camera obj.
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
    proj_settings.body_offset = (0.0, -0.06, 0.0)
    proj_settings.emitter_offset = (0.0, 0.0, 0.0)
    proj_settings.emitter_rotation = (0.0, 0.0, 0.0)

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


def _apply_model_to_projector(projector, model_data):
    settings = projector.proj_settings
    settings.throw_ratio = model_data['throw_ratio']
    settings.power = model_data['power']
    settings.h_shift = model_data['h_shift']
    settings.v_shift = model_data['v_shift']
    settings.body_type = model_data['body_type']
    settings.body_dimensions = model_data['body_dimensions']
    settings.body_offset = model_data['body_offset']
    settings.emitter_offset = model_data['emitter_offset']
    settings.emitter_rotation = model_data['emitter_rotation']


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
    preset.emitter_offset = model_data['emitter_offset']
    preset.emitter_rotation = model_data['emitter_rotation']
    preset.power = model_data['power']
    preset.throw_ratio = model_data['throw_ratio']
    preset.h_shift = model_data['h_shift']
    preset.v_shift = model_data['v_shift']
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
    body_offset: bpy.props.FloatVectorProperty(name='Body Offset', size=3, default=(0.0, -0.06, 0.0), subtype='TRANSLATION')
    emitter_offset: bpy.props.FloatVectorProperty(name='Emitter Offset', size=3, default=(0.0, 0.0, 0.0), subtype='TRANSLATION')
    emitter_rotation: bpy.props.FloatVectorProperty(name='Emitter Rotation', size=3, default=(0.0, 0.0, 0.0), subtype='EULER', unit='ROTATION')

    power: bpy.props.FloatProperty(name='Power', default=1000.0, min=0.0, soft_max=999999.0)
    throw_ratio: bpy.props.FloatProperty(name='Throw Ratio', default=0.8, min=0.1, soft_max=3.0)
    h_shift: bpy.props.FloatProperty(name='Horizontal Shift', default=0.0, soft_min=-20.0, soft_max=20.0, subtype='PERCENTAGE')
    v_shift: bpy.props.FloatProperty(name='Vertical Shift', default=0.0, soft_min=-20.0, soft_max=20.0, subtype='PERCENTAGE')

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
            layout.prop(self, 'saved_model')

        box = layout.box()
        box.label(text='Body')
        box.prop(self, 'body_type')
        if self.body_type == 'DEFAULT_BOX':
            row = box.row(align=True)
            row.prop(self, 'body_x')
            row.prop(self, 'body_y')
            row.prop(self, 'body_z')
        box.prop(self, 'body_offset')

        beam = layout.box()
        beam.label(text='Beam Origin and Direction')
        beam.prop(self, 'emitter_offset')
        beam.prop(self, 'emitter_rotation')

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
                    model_data = {
                        'body_type': preset.body_type,
                        'body_dimensions': tuple(preset.body_dimensions),
                        'body_offset': tuple(preset.body_offset),
                        'emitter_offset': tuple(preset.emitter_offset),
                        'emitter_rotation': tuple(preset.emitter_rotation),
                        'power': preset.power,
                        'throw_ratio': preset.throw_ratio,
                        'h_shift': preset.h_shift,
                        'v_shift': preset.v_shift,
                    }
                except (ValueError, IndexError):
                    pass

        if model_data is None:
            model_data = {
                'body_type': self.body_type,
                'body_dimensions': (self.body_x, self.body_y, self.body_z),
                'body_offset': tuple(self.body_offset),
                'emitter_offset': tuple(self.emitter_offset),
                'emitter_rotation': tuple(self.emitter_rotation),
                'power': self.power,
                'throw_ratio': self.throw_ratio,
                'h_shift': self.h_shift,
                'v_shift': self.v_shift,
            }

        _apply_model_to_projector(projector, model_data)

        if model_data['body_type'] == 'SELECTED_OBJECT':
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
        if projector.proj_settings.body_type == 'DEFAULT_BOX' and get_projector_body(projector) is None:
            _ensure_default_body(projector)
            _apply_body(projector, projector.proj_settings)
        return {'FINISHED'}


def _model_data_from_settings(settings):
    return {
        'body_type': settings.body_type,
        'body_dimensions': tuple(settings.body_dimensions),
        'body_offset': tuple(settings.body_offset),
        'emitter_offset': tuple(settings.emitter_offset),
        'emitter_rotation': tuple(settings.emitter_rotation),
        'power': settings.power,
        'throw_ratio': settings.throw_ratio,
        'h_shift': settings.h_shift,
        'v_shift': settings.v_shift,
    }


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

        model_key = self.saved_model
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

        model_data = {
            'body_type': preset.body_type,
            'body_dimensions': tuple(preset.body_dimensions),
            'body_offset': tuple(preset.body_offset),
            'emitter_offset': tuple(preset.emitter_offset),
            'emitter_rotation': tuple(preset.emitter_rotation),
            'power': preset.power,
            'throw_ratio': preset.throw_ratio,
            'h_shift': preset.h_shift,
            'v_shift': preset.v_shift,
        }
        _apply_model_to_projector(projector, model_data)
        _apply_body(projector, projector.proj_settings)
        _apply_emitter_transform(projector, projector.proj_settings)
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
        model_data = _model_data_from_settings(projector.proj_settings)
        if _store_model_preset_from_data(self.manufacturer, self.model_name, model_data):
            self.report({'INFO'}, f'Saved model {self.manufacturer} - {self.model_name}')
            return {'FINISHED'}
        self.report({'WARNING'}, 'Model not saved. Fill manufacturer and model name.')
        return {'CANCELLED'}


class PROJECTOR_OT_delete_saved_model(Operator):
    bl_idname = 'projector.delete_saved_model'
    bl_label = 'Delete Saved Model'
    bl_options = {'REGISTER', 'UNDO'}
    saved_model: bpy.props.EnumProperty(name='Saved Model', items=_saved_model_items, default='NONE')

    @classmethod
    def poll(cls, context):
        prefs = get_addon_preferences()
        return prefs is not None and len(prefs.projector_models) > 0

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, 'saved_model')

    def execute(self, context):
        model_key = self.saved_model
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
            self.report({'INFO'}, f'Deleted model: {label}')
            return {'FINISHED'}
        except (ValueError, IndexError):
            self.report({'ERROR'}, 'Saved model not found.')
            return {'CANCELLED'}


def update_projected_texture(proj_settings, context):
    """ Update the projected output source. """
    projector = get_projector(context)
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
            for child in projector.children:
                bpy.data.objects.remove(child, do_unlink=True)
            else:
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
        default=(0.0, -0.06, 0.0),
        subtype='TRANSLATION',
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


def register():
    _safe_register_class(ProjectorModelPreset)
    _safe_register_class(PROJECTOR_AP_preferences)
    _safe_register_class(ProjectorSettings)
    _safe_register_class(PROJECTOR_OT_create_projector)
    _safe_register_class(PROJECTOR_OT_apply_saved_model)
    _safe_register_class(PROJECTOR_OT_save_model_from_selected)
    _safe_register_class(PROJECTOR_OT_delete_saved_model)
    _safe_register_class(PROJECTOR_OT_delete_projector)
    _safe_register_class(PROJECTOR_OT_change_color_randomly)
    bpy.types.Object.proj_settings = bpy.props.PointerProperty(
        type=ProjectorSettings)


def unregister():
    if hasattr(bpy.types.Object, 'proj_settings'):
        del bpy.types.Object.proj_settings
    _safe_unregister_class(PROJECTOR_OT_change_color_randomly)
    _safe_unregister_class(PROJECTOR_OT_delete_projector)
    _safe_unregister_class(PROJECTOR_OT_delete_saved_model)
    _safe_unregister_class(PROJECTOR_OT_save_model_from_selected)
    _safe_unregister_class(PROJECTOR_OT_apply_saved_model)
    _safe_unregister_class(PROJECTOR_OT_create_projector)
    _safe_unregister_class(ProjectorSettings)
    _safe_unregister_class(PROJECTOR_AP_preferences)
    _safe_unregister_class(ProjectorModelPreset)
