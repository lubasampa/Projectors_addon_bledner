from .helper import get_projectors
from .projector import RESOLUTIONS, Textures, get_projector_spot

import bpy
from bpy.types import Panel, PropertyGroup, UIList, Operator


class PROJECTOR_PT_projector_settings(Panel):
    bl_idname = 'OBJECT_PT_projector_n_panel'
    bl_label = 'Projector'
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Projector"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        row = layout.row(align=True)
        row.operator('projector.create',
                     icon='ADD', text="New")
        row.operator('projector.delete',
                     text='Remove', icon='REMOVE')

        if context.scene.render.engine == 'BLENDER_EEVEE':
            box = layout.box()
            box.label(text='Image Projection only works in Cycles.', icon='ERROR')
            box.operator('projector.switch_to_cycles')

        selected_projectors = get_projectors(context, only_selected=True)
        if len(selected_projectors) == 1:
            projector = selected_projectors[0]
            proj_settings = projector.proj_settings

            layout.separator()

            layout.label(text='Projector Settings:')
            box = layout.box()
            box.prop(proj_settings, 'throw_ratio')
            box.prop(proj_settings, 'power', text='Power')
            res_row = box.row()
            res_row.prop(proj_settings, 'resolution',
                         text='Resolution', icon='PRESET')
            if proj_settings.projected_texture == Textures.CUSTOM_TEXTURE.value and proj_settings.use_custom_texture_res:
                res_row.active = False
                res_row.enabled = False
            else:
                res_row.active = True
                res_row.enabled = True
            # Lens Shift
            col = box.column(align=True)
            col.prop(proj_settings,
                     'h_shift', text='Horizontal Shift')
            col.prop(proj_settings, 'v_shift', text='Vertical Shift')
            layout.prop(proj_settings,
                        'projected_texture', text='Project')
            # Pixel Grid
            box.prop(proj_settings, 'show_pixel_grid')

            layout.separator()
            layout.label(text='Projector Body:')
            body_box = layout.box()
            body_box.prop(proj_settings, 'body_type', text='Body')
            if proj_settings.body_type == 'DEFAULT_BOX':
                row = body_box.row(align=True)
                row.prop(proj_settings, 'body_dimensions', text='Size')
            body_box.prop(proj_settings, 'body_offset')
            body_box.prop(proj_settings, 'body_rotation')
            body_box.prop(proj_settings, 'projection_cone_enabled')
            if proj_settings.projection_cone_enabled:
                body_box.prop(proj_settings, 'projection_cone_length')
            row_cone = body_box.row(align=True)
            row_cone.operator('projector.export_projection_cone', text='Copy This Cone')
            row_cone.operator('projector.export_all_projection_cones', text='Copy All Cones')

            # Custom Texture
            if proj_settings.projected_texture == Textures.CUSTOM_TEXTURE.value:
                box = layout.box()
                box.prop(proj_settings, 'use_custom_texture_res')
                projector = get_projectors(context, only_selected=True)[0]
                spot = get_projector_spot(projector)
                if spot:
                    node = spot.data.node_tree.nodes['Image Texture']
                    box.template_image(node, 'image', node.image_user, compact=False)

            layout.separator()
            layout.label(text='Projector Array:')
            array_box = layout.box()
            row_array = array_box.row(align=True)
            row_array.operator('projector.create_array', text='Create Array')
            row_array.operator('projector.edit_array', text='Edit Array')
            array_box.operator('projector.make_array_independent', text='Make Independent')

        layout.separator()
        layout.label(text='Saved Models:')
        model_box = layout.box()
        model_box.operator('projector.save_model_from_selected', text='Save Current')
        row_library = model_box.row(align=True)
        row_library.operator('projector.export_saved_models', text='Export Library')
        row_library.operator('projector.import_saved_models', text='Import Library')
        model_box.operator('projector.reload_saved_models', text='Refresh Saved List')


class PROJECTOR_PT_projected_color(Panel):
    bl_label = "Projected Color"
    bl_parent_id = "OBJECT_PT_projector_n_panel"
    bl_option = {'DEFAULT_CLOSED'}
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    @classmethod
    def poll(self, context):
        """ Only show if projected texture is set to  'checker'."""
        projector = context.object
        return bool(get_projectors(context, only_selected=True)) and projector.proj_settings.projected_texture == Textures.CHECKER.value

    def draw(self, context):
        projector = context.object
        layout = self.layout
        layout.use_property_decorate = False
        col = layout.column()
        col.use_property_split = True
        col.prop(projector.proj_settings, 'projected_color', text='Color')
        col.operator('projector.change_color',
                     icon='MODIFIER_ON', text='Random Color')


def append_to_add_menu(self, context):
    self.layout.operator('projector.create',
                         text='Projector', icon='CAMERA_DATA')


def register():
    bpy.utils.register_class(PROJECTOR_PT_projector_settings)
    bpy.utils.register_class(PROJECTOR_PT_projected_color)
    # Register create  in the blender add menu.
    bpy.types.VIEW3D_MT_light_add.append(append_to_add_menu)


def unregister():
    # Register create in the blender add menu.
    bpy.types.VIEW3D_MT_light_add.remove(append_to_add_menu)
    bpy.utils.unregister_class(PROJECTOR_PT_projected_color)
    bpy.utils.unregister_class(PROJECTOR_PT_projector_settings)
