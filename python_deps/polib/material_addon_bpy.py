# copyright (c) 2018- polygoniq xyz s.r.o.

import bpy
import typing
from . import node_utils_bpy
from . import material_utils_bpy


def spawn_material(
    context: bpy.types.Context,
    asset_name: str,
    blend_path: str,
) -> typing.Optional[bpy.types.Material]:
    """Loads the first material from given blend_path into current file and
    assigns it to all selected objects.
    """

    # TODO: This should be replaced by materialiq5 templated spawn system that is coming in future
    # We use two approaches to load material:
    # 1. Materials are present in the blend_path -> load first one
    # 2. Material is not available in data_from -> Material can be linked in the source file so it
    #    isn't available through the load API. We take the first mesh in the data and load the
    #    material from there.
    #
    # We use those two approaches because the materials can be linked from the library in the
    # material sources directly if artists want to use the materials in assets too (simplifies
    # linking and changes a lot).

    using_transfer_mesh = False
    with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
        if len(data_from.materials) > 0:
            assert len(data_from.materials) > 0
            data_to.materials = [data_from.materials[0]]
        else:
            if asset_name in data_from.meshes:
                data_to.meshes = [asset_name]
                using_transfer_mesh = True

    material = None
    if using_transfer_mesh:
        transfer_mesh: bpy.types.Mesh = data_to.meshes[0]
        assert len(transfer_mesh.materials) > 0
        material = transfer_mesh.materials[0]
        bpy.data.meshes.remove(transfer_mesh)
    else:
        material = data_to.materials[0]

    # This can happen if mesh or material was not found
    if material is None:
        return None

    # For optimization purposes we unlink the displacement part of node tree, that way the images
    # are not evaluated by the shader until user specifically asks for displacement.
    node_utils_bpy.unlink_displacement(material)

    for obj in context.selected_objects:
        if not material_utils_bpy.can_have_materials_assigned(obj):
            continue

        if len(obj.material_slots) < 1:
            obj.data.materials.append(material)
        else:
            obj.material_slots[obj.active_material_index].material = material

    return material


def spawn_world(
    context: bpy.types.Context,
    asset_name: str,
    blend_path: str,
) -> typing.Optional[bpy.types.World]:
    """Loads first world from given blend_path and sets it as active in current scene"""
    with bpy.data.libraries.load(blend_path) as (data_from, data_to):
        assert len(data_from.worlds) > 0
        data_to.worlds = [data_from.worlds[0]]

    world = data_to.worlds[0]
    context.scene.world = world
    return world
