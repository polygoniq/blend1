# copyright (c) 2018- polygoniq xyz s.r.o.

import bpy
import typing
import itertools

if "utils_bpy" not in locals():
    from . import utils_bpy
else:
    import importlib
    utils_bpy = importlib.reload(utils_bpy)


def find_nodes_in_tree(
    node_tree: bpy.types.NodeTree,
    filter_: typing.Optional[typing.Callable[[bpy.types.Node], bool]] = None,
    local_only: bool = False,
) -> typing.Set[bpy.types.Node]:
    """Returns a set of nodes from a given node tree that comply with the filter"""
    ret = set()
    for node in node_tree.nodes:
        if getattr(node, "node_tree", None) is not None:
            if node.node_tree.library is None or not local_only:
                ret.update(find_nodes_in_tree(
                    node.node_tree, filter_, local_only))

        if filter_ is not None and not filter_(node):
            continue

        ret.add(node)

    return ret


def get_top_level_material_nodes_with_name(
    obj: bpy.types.Object,
    node_names: typing.Set[str],
) -> typing.Iterable[bpy.types.Node]:
    """Searches for top level nodes or node groups = not nodes nested in other node groups.

    Raise exception if 'obj' is instanced collection. If linked object links materials from another
    blend then Blender API doesn't allow us easily access these materials. We would be able only
    to access materials that are local inside blend of linked object. This could be confusing
    behavior of this function, so this function doesn't search for any nodes in linked objects.
    """
    assert obj.instance_collection != 'COLLECTION'

    for material_slot in obj.material_slots:
        if material_slot.material is None:
            continue
        if material_slot.material.node_tree is None:
            continue  # material is not using nodes or the node_tree is invalid
        for node in material_slot.material.node_tree.nodes:
            if node.type == 'GROUP':
                if utils_bpy.remove_object_duplicate_suffix(node.node_tree.name) in node_names:
                    yield node
            else:
                if utils_bpy.remove_object_duplicate_suffix(node.name) in node_names:
                    yield node


def find_nodes_by_bl_idname(
    nodes: typing.Iterable[bpy.types.Node],
    bl_idname: str,
    recursive: bool = False
) -> typing.Iterable[bpy.types.Node]:
    for node in nodes:
        if node.bl_idname == bl_idname:
            yield node
        if recursive and node.node_tree is not None:
            yield from find_nodes_by_bl_idname(node.node_tree.nodes, bl_idname)


def find_nodes_by_name(node_tree: bpy.types.NodeTree, name: str) -> typing.Set[bpy.types.Node]:
    """Returns set of nodes from 'node_tree' which name without duplicate suffix is 'name'"""
    nodes = find_nodes_in_tree(
        node_tree,
        lambda x: utils_bpy.remove_object_duplicate_suffix(x.name) == name
    )
    return nodes


def find_nodegroups_by_name(
    node_tree: bpy.types.NodeTree,
    name: str,
    use_node_tree_name: bool = True
) -> typing.Set[bpy.types.NodeGroup]:
    """Returns set of node groups from 'node_tree' which name without duplicate suffix is 'name'

    Nodegroups have node.label, node.name and node.node_tree.name, if node.label is empty,
    Blender UI, displays node_tree.name in nodegroup header. That's why node.name is often not
    renamed to anything reasonable. So most of the times we want to search nodegroups by
    node_tree.name.
    """
    def nodegroup_filter(node: bpy.types.Node) -> bool:
        if node.type != 'GROUP':
            return False
        name_for_comparing = node.node_tree.name if use_node_tree_name else node.name
        return utils_bpy.remove_object_duplicate_suffix(name_for_comparing) == name

    nodes = find_nodes_in_tree(
        node_tree,
        nodegroup_filter
    )
    return nodes


def find_incoming_nodes(node: bpy.types.Node) -> typing.Set[bpy.types.Node]:
    """Finds and returns all nodes connecting to 'node'"""
    ret: typing.Set[bpy.types.Node] = set()
    for input_ in node.inputs:
        for link in input_.links:
            ret.add(link.from_node)

    return ret


def find_link_connected_to(
    links: typing.Iterable[bpy.types.NodeLink],
    to_node: bpy.types.Node,
    to_socket_name: str
) -> typing.Optional[bpy.types.NodeLink]:
    """Find the link connected to given target node (to_node) to given socket name (to_socket_name)

    There can be at most 1 such link. In Blender it is not allowed to connect more than one link
    to a socket. It is allowed to connect multiple links *from* one socket, but not *to* one socket.
    """

    ret: typing.List[bpy.types.NodeLink] = []
    for link in links:
        if to_node != link.to_node:
            continue
        if to_socket_name != link.to_socket.name:
            continue

        ret.append(link)

    if len(ret) > 1:
        raise RuntimeError(
            "Found multiple nodes connected to given node and socket. This is not valid!")
    elif len(ret) == 0:
        return None
    return ret[0]


def find_links_connected_from(
    links: typing.Iterable[bpy.types.NodeLink],
    from_node: bpy.types.Node,
    from_socket_name: str
) -> typing.Iterable[bpy.types.NodeLink]:
    """Find links connected from given node (from_node) from given socket name (from_socket_name)

    There can be any number of such links.
    """
    for link in links:
        if from_node != link.from_node:
            continue
        if from_socket_name != link.from_socket.name:
            continue

        yield link


def is_node_socket_connected_to(
    links: typing.Iterable[bpy.types.NodeLink],
    from_node: bpy.types.Node,
    from_socket_name: str,
    to_nodes: typing.List[bpy.types.Node],
    to_socket_name: typing.Optional[str],
    recursive: bool = True
) -> bool:
    for link in find_links_connected_from(links, from_node, from_socket_name):
        if link.to_node in to_nodes and \
                (to_socket_name is None or to_socket_name == link.to_socket.name):
            return True
        if recursive and is_node_socket_connected_to(
            links,
            link.to_node,
            link.to_socket.name,
            to_nodes,
            to_socket_name,
            True
        ):
            return True

    return False


def get_node_input_socket(node: bpy.types.Node, socket_name: str) -> typing.Optional[bpy.types.NodeSocket]:
    ret = None
    for input_ in node.inputs:
        if input_.name != socket_name:
            continue
        if ret is not None:
            raise RuntimeError("Multiple matches!")
        ret = input_

    return ret


def get_node_output_socket(node: bpy.types.Node, socket_name: str) -> typing.Optional[bpy.types.NodeSocket]:
    ret = None
    for output in node.outputs:
        if output.name != socket_name:
            continue
        if ret is not None:
            raise RuntimeError("Multiple matches!")
        ret = output

    return ret


def unlink_displacement(material: bpy.types.Material) -> None:
    if material.node_tree is None:
        # it's not using nodes or the node_tree is invalid
        return

    material_output_nodes = find_nodes_by_bl_idname(
        material.node_tree.nodes, "ShaderNodeOutputMaterial")

    for material_output_node in material_output_nodes:
        displacement_link = find_link_connected_to(
            material.node_tree.links, material_output_node, "Displacement"
        )

        if displacement_link is not None:
            material.node_tree.links.remove(displacement_link)


def link_displacement(material: bpy.types.Material) -> None:
    if material.node_tree is None:
        # it's not using nodes or the node_tree is invalid
        return

    displacement_nodegroups = find_nodes_in_tree(
        material.node_tree,
        lambda x: x.bl_idname == "ShaderNodeGroup" and x.node_tree.name.startswith(
            "mq_Displacement")
    )

    if len(displacement_nodegroups) == 0:
        raise RuntimeError(
            f"Tried to link materialiq displacement in {material.name} which is does not have the "
            f"mq_Displacement node, is it a materialiq material?")
    if len(displacement_nodegroups) > 1:
        raise RuntimeError(
            f"Multiple mq_Displacement nodes found in {material.name}, this is likely an asset "
            f"issue with the material itself."
        )
    displacement_nodegroup = displacement_nodegroups.pop()

    material_output_nodes = find_nodes_by_bl_idname(
        material.node_tree.nodes, "ShaderNodeOutputMaterial")

    for material_output_node in material_output_nodes:
        material.node_tree.links.new(
            displacement_nodegroup.outputs["Displacement"],
            material_output_node.inputs["Displacement"]
        )


def find_nodegroup_users(
    nodegroup_name: str,
) -> typing.Iterable[typing.Tuple[bpy.types.Object, typing.Iterable[bpy.types.Object]]]:
    """Returns iterable of (obj, user_objs) that use nodegroup with name 'nodegroup_name'

    In case of instanced object this checks the instanced collection and the nested
    objects in order to find the mesh object that can be potentional user of 'nodegroup_name'.
    In this case this returns the original instanced object and list of non-empty objects that are
    instanced.

    In case of editable objects this returns the object itself and list with the object in it.
    """
    def find_origin_objects(instancer_obj: bpy.types.Object) -> typing.Iterable[bpy.types.Object]:
        if instancer_obj.type != 'EMPTY':
            return [instancer_obj]

        objects = {instancer_obj}
        while len(objects) > 0:
            obj = objects.pop()
            if obj.type == 'EMPTY' and obj.instance_type == 'COLLECTION' \
               and obj.instance_collection is not None:
                objects.update(obj.instance_collection.all_objects)
            else:
                yield obj

    # Firstly gather all the materials that use the nodegroup with given name
    materials_using_nodegroup = set()
    for material in bpy.data.materials:
        if material.node_tree is None:
            continue

        nodes = find_nodes_in_tree(
            material.node_tree,
            lambda x: isinstance(x, bpy.types.ShaderNodeGroup) and
            x.node_tree.name == nodegroup_name)

        if len(nodes) > 0:
            materials_using_nodegroup.add(material)

    if len(materials_using_nodegroup) == 0:
        return []

    # Go through all objects and yield ones that have one of the found materials
    for obj in bpy.data.objects:
        # We skip objects with library here as they will be gathered by 'find_origin_objects'
        if obj.library is not None:
            continue

        # In case of instanced collection we find the actual instanced objects and gather all
        # used materials.
        if obj.type == 'EMPTY' and obj.instance_type == 'COLLECTION' \
           and obj.instance_collection is not None:
            instance_materials = set()
            instanced_objs = set(itertools.chain(find_origin_objects(obj)))
            for instanced_obj in instanced_objs:
                instance_materials.update({
                    slot.material for slot in instanced_obj.material_slots
                    if slot.material is not None
                })

            if len(instance_materials.intersection(materials_using_nodegroup)) > 0:
                yield obj, instanced_objs

        else:
            if not hasattr(obj, "material_slots"):
                continue

            obj_materials = {
                slot.material for slot in obj.material_slots if slot.material is not None}

            if len(obj_materials & materials_using_nodegroup) > 0:
                yield obj, [obj]
