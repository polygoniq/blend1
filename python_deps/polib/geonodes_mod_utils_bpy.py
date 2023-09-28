# copyright (c) 2018- polygoniq xyz s.r.o.
# Functionalities to work with geometry nodes modifiers
import bpy
import typing


# Mapping of input.identifier to (input.name, input.value)
NodeGroupInputs = typing.Dict[str, typing.Tuple[str, typing.Any]]


class NodesModifierInput:
    """Mapping of one node group and its inputs"""

    def __init__(self, modifier: bpy.types.NodesModifier) -> None:
        assert modifier.node_group is not None
        self.inputs: NodeGroupInputs = {}
        self.node_group = modifier.node_group
        for input_ in modifier.node_group.inputs:
            if input_.identifier in modifier:
                self.inputs[input_.identifier] = (input_.name, modifier[input_.identifier])


def get_modifiers_inputs_map(
    modifiers: typing.Iterable[bpy.types.Modifier]
) -> typing.Dict[str, NodesModifierInput]:
    """Returns mapping of geometry nodes modifiers to their respective inputs"""
    ret: typing.Dict[str, NodesModifierInput] = {}
    for mod in modifiers:
        if mod.type != 'NODES':
            continue

        mod = typing.cast(bpy.types.NodesModifier, mod)
        if mod.node_group is None:
            continue

        ret[mod.name] = NodesModifierInput(mod)

    return ret


class NodesModifierInputsNameView:
    """View of Geometry Nodes modifier that allows changing inputs by input name"""

    def __init__(self, mod: bpy.types.Modifier):
        assert mod.type == 'NODES'
        self.mod = mod
        self.name_to_identifier_map = {}
        for input_ in mod.node_group.inputs:
            # Is the input exposed in the modifier -> modifiers["RG_"]
            if input_.identifier in mod:
                self.name_to_identifier_map[input_.name] = input_.identifier

    def set_input_value(self, input_name: str, value: typing.Any) -> None:
        identifier = self.name_to_identifier_map.get(input_name)
        self.mod[identifier] = value

    def set_obj_input_value(self, input_name: str, obj_name: str) -> None:
        identifier = self.name_to_identifier_map.get(input_name)
        # Object reference has to be set directly from bpy.data.objects
        self.mod[identifier] = bpy.data.objects[obj_name]

    def set_material_input_value(self, input_name: str, mat_name: str) -> None:
        identifier = self.name_to_identifier_map.get(input_name)
        # Materials reference has to be set directly from bpy.data.materials
        self.mod[identifier] = bpy.data.materials[mat_name]

    def set_collection_input_value(self, input_name: str, collection_name: str) -> None:
        identifier = self.name_to_identifier_map.get(input_name)
        # Collections reference has to be set directly from bpy.data.collections
        self.mod[identifier] = bpy.data.collections[collection_name]

    def set_array_input_value(self, input_name: str, value: typing.List[typing.Any]) -> None:
        identifier = self.name_to_identifier_map.get(input_name)
        for i, v in enumerate(value):
            self.mod[identifier][i] = v

    def get_input_value(self, input_name: str) -> typing.Any:
        identifier = self.name_to_identifier_map.get(input_name)
        return self.mod[identifier]

    def __contains__(self, input_name: str) -> bool:
        return input_name in self.name_to_identifier_map
