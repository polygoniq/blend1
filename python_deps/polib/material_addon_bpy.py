# copyright (c) 2018- polygoniq xyz s.r.o.

import bpy
import os
import typing
from . import node_utils_bpy
from . import material_utils_bpy
import logging
logger = logging.getLogger(f"polygoniq.{__name__}")

TEXTURE_EXTENSIONS = {".png", ".jpg"}


def generate_filepath(texture_path: str, basename: str, max_size: str, ext: str) -> str:
    if basename.startswith("mq_") and basename.split("_")[-1].isdigit():
        name_without_resolution = basename.rsplit("_", 1)[0]

    return os.path.join(texture_path, f"{name_without_resolution}_{max_size}{ext}")


def is_materialiq_texture(image: bpy.types.Image) -> bool:
    basename, _ = os.path.splitext(os.path.basename(image.filepath))
    if basename.startswith("mq_") and basename.split("_")[-1].isdigit():
        return True

    return False


def change_texture_size(max_size: int, image: bpy.types.Image):
    if not is_materialiq_texture(image):
        return

    basename, ext = os.path.splitext(os.path.basename(image.filepath))
    if ext not in TEXTURE_EXTENSIONS:
        return

    logger.debug(f"Changing {image.name} to {max_size}...")

    new_path = None
    found = False
    parent_dir = os.path.dirname(image.filepath)
    for ext in TEXTURE_EXTENSIONS:
        new_path = generate_filepath(parent_dir, basename, str(max_size), ext)
        new_abs_path = bpy.path.abspath(new_path)
        # We getsize() to check that the file is not empty. Because of compress_textures, there could
        # exist different file formats of the same texture, and all except one of them would be empty.
        if os.path.exists(new_abs_path) and os.path.getsize(new_abs_path) > 0:
            found = True
            break

    if not found:
        logger.warning(f"Can't find {image.name} in size {max_size}, skipping...")
        return

    image.filepath = new_path
    image.name = os.path.basename(new_path)


def change_texture_sizes(max_size: int, only_textures: typing.Optional[set] = None):
    logger.debug(f"mq: changing textures to {max_size}...")

    if only_textures is not None:
        for image in only_textures:
            change_texture_size(max_size, bpy.data.images[image])
    else:
        for image in bpy.data.images:
            change_texture_size(max_size, image)


def get_used_textures_in_node(node: bpy.types.Node) -> typing.Set[str]:
    ret = set()

    if hasattr(node, "node_tree"):
        for child_node in node.node_tree.nodes:
            ret.update(get_used_textures_in_node(child_node))

    if hasattr(node, "image"):
        if node.image:
            ret.add(node.image.name)

    return ret


def get_used_textures(material: bpy.types.Material) -> typing.Set[str]:
    if material is None:
        return set()

    if not material.use_nodes:
        logger.warning(
            f"Can't get used textures from material '{material.name}' that is not using "
            f"the node system!")
        return set()

    assert material.node_tree is not None, "use_nodes is True, yet node_tree is None"
    ret = set()
    for node in material.node_tree.nodes:
        ret.update(get_used_textures_in_node(node))

    return ret


def spawn_material(
    context: bpy.types.Context,
    asset_name: str,
    blend_path: str,
) -> typing.Optional[bpy.types.Material]:
    """Loads the first material from given blend_path into current file and
    assigns it to all selected objects.
    """

    # TODO: This should be replaced by materialiq templated spawn system that is coming in future
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
