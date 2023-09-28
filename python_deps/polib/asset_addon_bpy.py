#!/usr/bin/python3
# copyright (c) 2018- polygoniq xyz s.r.o.

import bpy
import bpy.utils.previews
import rna_prop_ui
import bmesh
import os
import os.path
import typing
import collections
import enum
import logging
logger = logging.getLogger(f"polygoniq.{__name__}")


if "linalg_bpy" not in locals():
    from . import linalg_bpy
    from . import utils_bpy
    from . import rigs_shared_bpy
else:
    import importlib
    linalg_bpy = importlib.reload(linalg_bpy)
    utils_bpy = importlib.reload(utils_bpy)
    rigs_shared_bpy = importlib.reload(rigs_shared_bpy)


CustomAttributeValueType = typing.Union[
    str,
    int,
    float,
    typing.Tuple[int, ...],
    typing.Tuple[float, ...],
    typing.List[int],
    typing.List[float],
]


class AssetAddon(enum.Enum):
    botaniq = 'botaniq'
    traffiq = 'traffiq'
    aquatiq = 'aquatiq'

    # The __eq__ and __hash__ methods need to be overriden for this enum so comparisons work as
    # expected when using importlib.reload() which registers the class second time and if some other
    # code wasn't reloaded (there are some instances of the non-reloaded enum left) then even the
    # seemingly same values compare to False.
    def __eq__(self, other):
        if type(self).__qualname__ != type(other).__qualname__:
            return False

        return (self.name, self.value) == (other.name, other.value)

    def __hash__(self):
        return hash((self.name, self.value))


# Maps asset addon names to blender Collection color_tags
ASSET_ADDON_COLLECTION_COLOR_MAP = {
    "botaniq": 'COLOR_04',  # green
    "traffiq": 'COLOR_02',  # orange
    "aquatiq": 'COLOR_05',  # blue
}


ASSET_ADDON_MODULE_NAMES = {
    AssetAddon.botaniq: [
        "botaniq_full",
        "botaniq_lite",
        "botaniq_starter",
        "botaniq_addon_only",
        "botaniq_addon"
    ],
    AssetAddon.traffiq: [
        "traffiq_full",
        "traffiq_lite",
        "traffiq_starter",
        "traffiq_addon_only",
        "traffiq_addon"
    ],
    AssetAddon.aquatiq: [
        "aquatiq_full",
        "aquatiq_addon_only",
        "aquatiq_addon"
    ]
}


def find_asset_addon_bpy_preferences(addon: AssetAddon) -> typing.Optional[bpy.types.AddonPreferences]:
    for module_name in ASSET_ADDON_MODULE_NAMES[addon]:
        if module_name not in bpy.context.preferences.addons:
            continue
        return bpy.context.preferences.addons[module_name].preferences

    return None


PARTICLE_SYSTEM_PREFIX = "pps_"
PREVIEW_NOT_FOUND = "No-Asset-Found"

# order matters, assets often have multiple seasons, color is set according to the first
# matched season
BOTANIQ_SEASONS_WITH_COLOR_CHANNEL = (
    ("summer", 1.0), ("spring", 0.75), ("winter", 0.5), ("autumn", 0.25)
)

BOTANIQ_ANIMATED_CATEGORIES = {
    "coniferous",
    "deciduous",
    "shrubs",
    "flowers",
    "grass",
    "ivy",
    "plants",
    "sapling",
    "tropical",
    "vine",
    "weed"
}


class CustomPropertyNames:
    # traffiq specific custom property names
    TQ_DIRT = "tq_dirt"
    TQ_SCRATCHES = "tq_scratches"
    TQ_BUMPS = "tq_bumps"
    TQ_PRIMARY_COLOR = "tq_primary_color"
    TQ_FLAKES_AMOUNT = "tq_flakes_amount"
    TQ_CLEARCOAT = "tq_clearcoat"
    TQ_LIGHTS = "tq_main_lights"
    # botaniq specific custom property names
    BQ_BRIGHTNESS = "bq_brightness"
    BQ_RANDOM_PER_BRANCH = "bq_random_per_branch"
    BQ_RANDOM_PER_LEAF = "bq_random_per_leaf"
    BQ_SEASON_OFFSET = "bq_season_offset"


def get_name_category_map(previews_paths: typing.Iterable[str]) -> typing.Dict[str, str]:
    ret = {}
    for previews_path in previews_paths:
        for path, _, files in os.walk(previews_path):
            for file in files:
                filename, ext = os.path.splitext(file)
                if ext not in {".png", ".jpg"}:
                    continue

                _, category = os.path.split(path)
                ret[filename] = category

    return ret


def list_categories(
    previews_paths: typing.Iterable[str],
    previews_gray_paths: typing.Optional[typing.Iterable[str]],
    filters: typing.Optional[typing.Iterable[typing.Callable]] = None
) -> typing.Iterable[str]:
    categories = set()
    for previews_path in previews_paths:
        if not os.path.isdir(previews_path):
            continue
        for category in os.listdir(previews_path):
            if not os.path.isdir(os.path.join(previews_path, category)):
                continue
            categories.add(category)

    if previews_gray_paths is not None:
        for previews_gray_path in previews_gray_paths:
            if not os.path.isdir(previews_gray_path):
                continue
            for category in os.listdir(previews_gray_path):
                if not os.path.isdir(os.path.join(previews_gray_path, category)):
                    continue
                categories.add(category)

    for name in sorted(categories):
        filtered = False
        if filters is not None:
            for filter_ in filters:
                if not filter_(name):
                    filtered = True
                    break

        if filtered:
            continue

        yield name


PreviewFilter = typing.Callable[[str], bool]


def expand_search_keywords(translator: typing.Dict[str, typing.Iterable[str]], keywords: typing.Iterable[str]) -> typing.Set[str]:
    ret = set()
    for keyword in keywords:
        keyword = keyword.lower()
        ret.add(keyword)
        ret.update(translator.get(keyword, []))
    return ret


def search_for_keywords(expanded_keywords: typing.Iterable[str], text: str) -> bool:
    """Returns true if at least one of the keywords is contained within given text

    Matching is case-insensitive.
    """
    text_lower = text.lower()
    for keyword in expanded_keywords:
        if keyword.lower() in text_lower:
            return True

    return False


def search_by_keywords_filter(preview_basename: str, search_keywords: typing.Iterable[str], name_formatter: typing.Callable[[str], str]) -> bool:
    if not search_keywords:
        return True

    nice_name = name_formatter(preview_basename)
    if not search_for_keywords(search_keywords, nice_name):
        # skipping because it was filtered out
        return False

    return True


def enum_property_set(datablock: bpy.types.bpy_struct, prop_name: str, value: int):
    """Default set function for enum properties"""
    datablock[prop_name] = value


def enum_property_get(
    datablock: bpy.types.bpy_struct,
    prop_name: str,
    items: typing.Iterable[bpy.types.EnumPropertyItem]
) -> int:
    """Default get function for enum properties that ensures validity of returned item"""
    assert len(items) > 0  # There should be one preview for not found state
    current_item = datablock.get(prop_name, 0)
    if current_item not in {i[4] for i in items}:
        return items[0][4]

    return current_item


def list_asset_previews(
        previews_paths: typing.Iterable[str],
        previews_gray_paths: typing.Optional[typing.Iterable[str]],
        category: str,
        name_formatter: typing.Callable[[str], str],
        filters: typing.Iterable[PreviewFilter]):
    if not hasattr(list_asset_previews, "pcoll"):
        list_asset_previews.pcoll = bpy.utils.previews.new()

    ret = {"enum_items": [], "pcoll": list_asset_previews.pcoll}

    def process_preview_file(previews_path: str, category: str, preview_filename: str, i: int, i_base: int = 0) -> None:
        if not preview_filename.endswith((".jpg", ".png")):
            return

        full_path = os.path.join(previews_path, category, preview_filename)
        if not os.path.exists(full_path):
            logger.warning(f"{full_path} not found! Skipping this asset in the browser!")
            return

        preview_basename, _ = os.path.splitext(preview_filename)

        filtered = False
        for filter_ in filters:
            if not filter_(preview_basename):
                # filtered out
                filtered = True
                break

        if filtered:
            return

        if preview_basename in ret["pcoll"]:
            image = ret["pcoll"][preview_basename]
        else:
            image = ret["pcoll"].load(preview_basename, full_path, 'IMAGE')

        nice_name = name_formatter(preview_basename)
        ret["enum_items"].append((preview_basename, nice_name,
                                  preview_basename, image.icon_id, i + i_base))

    previews_path_found = False
    i_base = 0
    for previews_path in previews_paths:
        path = os.path.join(previews_path, category)
        if not os.path.isdir(path):
            continue
        previews_path_found = True

        # TODO: fix sorting here
        preview_filenames = sorted(os.listdir(path))
        preview_count = 0
        for i, preview_filename in enumerate(preview_filenames):
            process_preview_file(previews_path, category, preview_filename, i, i_base)
            preview_count += 1
        i_base += preview_count

    if not previews_path_found:
        logger.warning(
            f"Category {category} not found in any of the preview paths: {previews_paths}!")

    if previews_gray_paths is not None:
        for previews_gray_path in previews_gray_paths:
            path_gray = os.path.join(
                previews_gray_path, category)
            if not os.path.isdir(path_gray):
                continue

            gray_preview_filenames = sorted(os.listdir(path_gray))
            preview_count = 0
            for i, preview_filename in enumerate(gray_preview_filenames):
                process_preview_file(previews_gray_path, category, preview_filename, i, i_base)
                preview_count += 1
            i_base += preview_count

    # Add at least one item, so we can represent that nothing was found
    if len(ret["enum_items"]) == 0:
        ret["enum_items"].append((PREVIEW_NOT_FOUND, "Nothing found", "Nothing Found", 'X', 0))
    return ret


def get_all_object_ancestors(obj: bpy.types.Object) -> typing.Iterable[bpy.types.Object]:
    """Returns given object's parent, the parent's parent, ...
    """

    current = obj.parent
    while current is not None:
        yield current
        current = current.parent


def filter_out_descendants_from_objects(
    objects: typing.Iterable[bpy.types.Object]
) -> typing.Set[bpy.types.Object]:
    """Given a list of objects (i.e. selected objects) this function will return only the
    roots. By roots we mean included objects that have no ancestor that is also contained
    in object.

    Example of use of this is when figuring out which objects to snap to ground. If you have
    a complicated selection of cars, their wheels, etc... you onlt want to snap the parent car
    body, not all objects.
    """

    all_objects = set(objects)

    ret = set()
    for obj in objects:
        ancestors = get_all_object_ancestors(obj)
        if len(all_objects.intersection(ancestors)) == 0:
            # this object has no ancestors that are also contained in objects
            ret.add(obj)

    return ret


def is_polygoniq_object(
    obj: bpy.types.Object,
    addon_name_filter: typing.Optional[typing.Callable[[str], bool]] = None,
    include_editable: bool = True,
    include_linked: bool = True
) -> bool:
    if include_editable and obj.instance_type == 'NONE' and obj.get("polygoniq_addon", None):
        # only non-'EMPTY' objects can be considered editable
        return addon_name_filter is None or addon_name_filter(obj.get("polygoniq_addon", None))

    elif include_linked and obj.instance_collection is not None:
        # the object is linked and the custom properties are in the linked collection
        # in most cases there will be exactly one linked object but we want to play it
        # safe and will check all of them. if any linked object is a polygoniq object
        # we assume the whole instance collection is
        for linked_obj in obj.instance_collection.objects:
            if is_polygoniq_object(linked_obj, addon_name_filter):
                return True

    return False


def find_polygoniq_root_objects(
    objects: typing.Iterable[bpy.types.Object],
    addon_name: typing.Optional[str] = None
) -> typing.Set[bpy.types.Object]:
    """Finds and returns polygoniq root objects in 'objects'.

    Returned objects are either root or their parent isn't polygoniq object.
    E. g. for 'objects' selected from hierarchy:
    Users_Empty -> Audi_R8 -> [Lights, Wheel1..N -> [Brakes]], this returns Audi_R8.
    """

    traversed_objects = set()
    root_objects = set()
    addon_name_filter = None if addon_name is None else lambda x: x == addon_name

    for obj in objects:
        if obj in traversed_objects:
            continue

        current_obj = obj
        while True:
            if current_obj in traversed_objects:
                break

            if current_obj.parent is None:
                if is_polygoniq_object(current_obj, addon_name_filter):
                    root_objects.add(current_obj)
                break

            if is_polygoniq_object(current_obj, addon_name_filter) and not is_polygoniq_object(current_obj.parent, addon_name_filter):
                root_objects.add(current_obj)
                break

            traversed_objects.add(current_obj)
            current_obj = current_obj.parent

    return root_objects


def get_polygoniq_objects(
    objects: typing.Iterable[bpy.types.Object],
    addon_name: typing.Optional[str] = None,
    include_editable: bool = True,
    include_linked: bool = True
) -> typing.Iterable[bpy.types.Object]:
    """Filters given objects and returns only those that contain the polygoniq_addon property
    """
    addon_name_filter = None if addon_name is None else lambda x: x == addon_name
    for obj in objects:
        if is_polygoniq_object(obj, addon_name_filter, include_editable, include_linked):
            yield obj


def get_addon_install_path(addon_name: str) -> typing.Optional[str]:
    addon = bpy.context.preferences.addons.get(addon_name, None)
    if addon is None:
        return None

    return getattr(addon.preferences, "install_path", None)


def get_addons_install_paths(addon_names: typing.Iterable[str], short_names: bool = False) -> typing.Dict[str, str]:
    install_paths = {}
    module_names = {module_name for asset_addon in ASSET_ADDON_MODULE_NAMES.values()
                    for module_name in asset_addon}
    for addon_name in addon_names:
        install_path = get_addon_install_path(addon_name)
        if install_path is None:
            continue
        if short_names:
            if addon_name in module_names:
                short_name, _ = addon_name.split("_", 1)
            else:
                # remove _addon and _addon_only even from asset packs
                if addon_name.endswith("_addon"):
                    short_name = addon_name[:-len("_addon")]
                elif addon_name.endswith("_addon_only"):
                    short_name = addon_name[:-len("_addon_only")]
                else:
                    short_name = addon_name
            install_paths[short_name] = install_path
        else:
            install_paths[addon_name] = install_path

    return install_paths


def get_installed_polygoniq_asset_addons(include_asset_packs: bool = False) -> typing.Dict[str, bpy.types.Addon]:
    polygoniq_addons = {}
    # We keep track of basenames to detect multiple installations of addons
    found_module_names = set()
    module_names = {module_name for asset_addon in ASSET_ADDON_MODULE_NAMES.values()
                    for module_name in asset_addon}

    # let's find asset addons first
    for name, addon in bpy.context.preferences.addons.items():
        if name in module_names:
            found_module_names.add(name)
            polygoniq_addons[name] = addon

    module_prefixes = tuple(
        f"{asset_addon.name}_" for asset_addon in ASSET_ADDON_MODULE_NAMES.keys())
    if include_asset_packs:
        for name, addon in bpy.context.preferences.addons.items():
            if name in found_module_names:
                continue
            if name.startswith(module_prefixes):
                found_module_names.add(name)
                polygoniq_addons[name] = addon

    return polygoniq_addons


class TiqAssetPart(enum.Enum):
    Body = 'Body'
    Lights = 'Lights'
    Wheel = 'Wheel'
    Brake = 'Brake'


def is_traffiq_asset_part(obj: bpy.types.Object, part: TiqAssetPart) -> bool:
    addon_name = obj.get("polygoniq_addon", "")
    if addon_name != "traffiq":
        return False

    obj_name = utils_bpy.remove_object_duplicate_suffix(obj.name)
    if part in {TiqAssetPart.Body, TiqAssetPart.Lights}:
        splitted_name = obj_name.rsplit("_", 1)
        if len(splitted_name) != 2:
            return False

        _, obj_part_name = splitted_name
        if obj_part_name != part.name:
            return False
        return True

    elif part in {TiqAssetPart.Wheel, TiqAssetPart.Brake}:
        splitted_name = obj_name.rsplit("_", 3)
        if len(splitted_name) != 4:
            return False

        _, obj_part_name, position, wheel_number = splitted_name
        if obj_part_name != part.name:
            return False
        if position not in {"FL", "FR", "BL", "BR", "F", "B"}:
            return False
        if not wheel_number.isdigit():
            return False
        return True

    return False


DecomposedCarType = typing.Tuple[bpy.types.Object, bpy.types.Object,
                                 bpy.types.Object, typing.List[bpy.types.Object], typing.List[bpy.types.Object]]


def get_root_object_of_asset(asset: bpy.types.Object) -> typing.Optional[bpy.types.Object]:
    """Returns the root linked object if given a linked asset (instanced collection empty).
    Returns the object itself if given an editable asset. In case there are multiple roots
    or no roots at all it returns None and logs a warning.
    """

    if asset.instance_type == 'COLLECTION':
        # we have to iterate through objects in the collection and return the one
        # that has no parent.

        root_obj = None
        for obj in asset.instance_collection.objects:
            if obj.parent is None:
                if root_obj is not None:
                    logger.warning(
                        f"Found multiple root objects in the given collection instance "
                        f"empty (name='{asset.name}')"
                    )
                    return None

                root_obj = obj

        if root_obj is None:
            logger.warning(
                f"Failed to find the root object of a given collection instance empty "
                f"(name='{asset.name}')"
            )

        return root_obj

    else:
        # given object is editable
        return asset


def get_entire_object_hierarchy(obj: bpy.types.Object) -> typing.Iterable[bpy.types.Object]:
    """List entire hierarchy of an instanced or editable object

    Returns object hierarchy (the object itself and all descendants) in case the object is
    editable. In case the object is instanced it looks through the instance_collection.objects
    and returns all descendants from there.

    Example: If you pass a traffiq car object it will return body, wheels and lights.
    """

    for child in obj.children:
        yield from get_entire_object_hierarchy(child)

    if obj.instance_type == 'COLLECTION':
        yield from obj.instance_collection.objects
    else:
        yield obj


def decompose_traffiq_vehicle(obj: bpy.types.Object) -> DecomposedCarType:
    if obj is None:
        return None, None, None, [], []

    root_object = get_root_object_of_asset(obj)
    body = None
    lights = None
    wheels = []
    brakes = []

    hierarchy_objects = get_entire_object_hierarchy(obj)
    for hierarchy_obj in hierarchy_objects:
        if is_traffiq_asset_part(hierarchy_obj, TiqAssetPart.Body):
            # there should be only one body
            assert body is None
            body = hierarchy_obj
        elif is_traffiq_asset_part(hierarchy_obj, TiqAssetPart.Lights):
            # there should be only one lights
            assert lights is None
            lights = hierarchy_obj
        elif is_traffiq_asset_part(hierarchy_obj, TiqAssetPart.Wheel):
            wheels.append(hierarchy_obj)
        elif is_traffiq_asset_part(hierarchy_obj, TiqAssetPart.Brake):
            brakes.append(hierarchy_obj)

    return root_object, body, lights, wheels, brakes


def find_traffiq_asset_parts(obj: bpy.types.Object, part: TiqAssetPart) -> typing.Iterable[bpy.types.Object]:
    """Find all asset parts of a specific type."""

    for hierarchy_obj in get_entire_object_hierarchy(obj):
        if is_traffiq_asset_part(hierarchy_obj, part):
            yield hierarchy_obj


def find_traffiq_lights_container(obj: bpy.types.Object) -> typing.Optional[bpy.types.Object]:
    """Finds whatever contains all the lights of given objects. This can be a empty with instance
    collection if the car is linked or an lights object if the car has been converted to editable.
    """
    return find_object_in_hierarchy(
        obj, lambda x, _: x.get(CustomPropertyNames.TQ_LIGHTS, None) is not None)


def create_instanced_object(collection_name: str) -> bpy.types.Object:
    """Creates empty and sets the instance collection to one with 'collection_name'.

    This is similar behaviour to bpy.ops.collection_instance_add(collection=collection_name),
    but it is faster, because it doesn't include bpy.ops overhead. Collection 'collection_name'
    has to exist in bpy.data.collections before call of this function.
    """

    assert collection_name in bpy.data.collections
    collection = bpy.data.collections[collection_name]
    instance_obj = bpy.data.objects.new(collection_name, None)
    instance_obj.instance_type = 'COLLECTION'
    instance_obj.instance_collection = collection
    # take object color from the first object in the collection
    # this is necessary for botaniq's seasons
    for obj in collection.all_objects:
        instance_obj.color = obj.color
        break
    return instance_obj


def copy_custom_prop(src: bpy.types.ID, dst: bpy.types.ID, prop_name: str) -> None:
    """Copies custom property 'prop_name' from 'src' to 'dst' while preserving its settings"""
    # Blender introduced new behaviour of custom properties post 3.0.0
    if bpy.app.version >= (3, 0, 0):
        # In order to copy the property with its configuration (min, max, subtype, etc)
        # we need to use following code. Code is taken from the "Copy Attributes" addon that's
        # shipped within Blender.

        # Create the property.
        dst[prop_name] = src[prop_name]
        # Copy the settings of the property.
        try:
            dst_prop_manager = dst.id_properties_ui(prop_name)
        except TypeError:
            # Python values like lists or dictionaries don't have any settings to copy.
            # They just consist of a value and nothing else.
            # Note: This also skips copying the properties that cannot be edited by
            # id_properties_ui
            return

        src_prop_manager = src.id_properties_ui(prop_name)
        assert src_prop_manager, f"Property '{prop_name}' not found in {src}"

        dst_prop_manager.update_from(src_prop_manager)
    else:
        # Don't ever copy _RNA_UI
        if prop_name == "_RNA_UI":
            return

        src_prop_ui = rna_prop_ui.rna_idprop_ui_prop_get(src, prop_name)
        dst[prop_name] = src[prop_name]
        dst_prop_ui = rna_prop_ui.rna_idprop_ui_prop_get(dst, prop_name)

        for k in src_prop_ui.keys():
            dst_prop_ui[k] = src_prop_ui[k]

    # Copy the Library Overridable flag, which is stored elsewhere, sometimes it's not possible
    # to copy the library override
    try:
        prop_rna_path = f'["{prop_name}"]'
        is_lib_overridable = src.is_property_overridable_library(prop_rna_path)
        dst.property_overridable_library_set(prop_rna_path, is_lib_overridable)
    except:
        pass


def copy_custom_props(
    src: bpy.types.ID,
    dst: bpy.types.ID,
    only_existing: bool = False,
    recursive: bool = False
) -> None:
    """Copies all custom properties from 'src' to 'dst'

    If 'only_existing' is True, then properties that don't exist on
    the 'dst' object are not created, only values of existing properties are
    updated.

    If 'recursive' is provided the property is copied to all children of 'dst' object
    """
    if recursive:
        for child in dst.children:
            copy_custom_props(src, child, only_existing, recursive)

    for prop_name in src.keys():
        if only_existing and prop_name not in dst:
            continue

        copy_custom_prop(src, dst, prop_name)


def generic_link_asset(
    context: bpy.types.Context,
    asset_name: str,
    blend_path: str,
    parent_collection: bpy.types.Collection,
) -> typing.Optional[bpy.types.Object]:
    """Links root collection from 'blend_path' to children of 'parent_collection'
    """

    root_collection_name = None
    with bpy.data.libraries.load(blend_path, link=True) as (data_from, data_to):
        # The root collection of the asset should have the same name as the asset name
        assert asset_name in data_from.collections
        data_to.collections = [asset_name]
        root_collection_name = data_to.collections[0]

    root_empty = None
    if root_collection_name is not None:
        root_empty = create_instanced_object(root_collection_name)
        root_empty.location = context.scene.cursor.location

    if root_empty is None:
        return None

    # Copy all children properties from the instanced objects to the instancer object
    for obj in root_empty.instance_collection.all_objects:
        if obj.library is None:
            continue

        copy_custom_props(obj, root_empty)

    collection_add_object(parent_collection, root_empty)

    return root_empty


def load_pps(
    container_object: bpy.types.Object,
    particle_system_blend: str,
    include_base_material: bool = False
) -> typing.List[typing.Tuple[bpy.types.Modifier, bpy.types.ParticleSystem, bpy.types.ParticleSettings]]:
    if not os.path.isfile(particle_system_blend):
        return []

    with bpy.data.libraries.load(particle_system_blend, link=False) as (data_from, data_to):
        data_to.particles = data_from.particles
        if include_base_material:
            for material in data_from.materials:
                # TODO: WIP unifying botaniq naming conventions: Add bq_ prefix for botaniq 7.0
                if material.startswith("Base_"):
                    data_to.materials = [material]
                    break

    assert len(data_to.particles) > 0
    particle_data = []
    for new_ps_settings in data_to.particles:
        modifier = container_object.modifiers.new(new_ps_settings.name, type='PARTICLE_SYSTEM')
        modifier.particle_system.settings = new_ps_settings
        particle_data.append((modifier, modifier.particle_system,
                              modifier.particle_system.settings))

        for obj in new_ps_settings.instance_collection.objects:
            obj.make_local()
            obj.location.z = container_object.location.z - 10

    if include_base_material:
        # Only one material was loaded and check_botaniq_particles hammer
        # assures its presence
        assert len(data_to.materials) == 1
        base_material = data_to.materials[0]
        container_object.active_material = base_material

    return particle_data


def get_area_based_particle_count(
    obj: bpy.types.Object,
    density: float,
    max_particle_count: int,
    include_weights: bool = False
) -> typing.Tuple[int, int]:
    mesh_area = calculate_mesh_area(obj, include_weights)
    particle_count = int(mesh_area * density)
    if particle_count > max_particle_count:
        return max_particle_count, particle_count - max_particle_count
    return particle_count, 0


def ensure_particle_naming_consistency(modifier: bpy.types.ParticleSystemModifier, particle_system: bpy.types.ParticleSystem) -> None:
    """
    Particle data gets duplicated and has the object duplicate suffix on copy, but modifiers and particle system names do not.
    This function ensures the same naming on the whole particle system -> modifier, data, particle system, instance_collection

    Using the name from instance collection is currently the best approach. Creating modifier creates particle data automatically,
    but we don't want to use those, we use the ones loaded from our blends (this gives them .001). Instance collections have the most
    correct duplicate suffix because we have almost full control over them (at least when we are creating them).
    """
    if modifier is None or particle_system is None:
        raise RuntimeError(
            "Cannot ensure naming consistency if modifier or particle_system is None!")

    ps_settings = particle_system.settings
    if ps_settings is None or ps_settings.instance_collection is None:
        raise RuntimeError(
            f"Cannot ensure naming consistency if particle_system ({particle_system.name}) has no settings or no instance_collection!")

    modifier.name = particle_system.name = ps_settings.name = ps_settings.instance_collection.name


def generic_spawn_pps(
    context: bpy.types.Context,
    asset_name: str,
    blend_path: str,
    target_object: bpy.types.Object
) -> typing.Optional[typing.List[typing.Tuple[bpy.types.Modifier, bpy.types.ParticleSystem, bpy.types.ParticleSettings]]]:
    particle_system_data = load_pps(
        target_object,
        blend_path,
        True  # TODO: Let people choose include_base_material?
    )
    if len(particle_system_data) == 0:
        logger.error(
            f"Scatter Assets: Cannot find particle system {asset_name}! "
            f"Path is invalid {blend_path}"
        )
        return None

    logger.info(f"Scattering {asset_name}")
    # If preserve_density is toggled we recalculate the density to respect the mesh size,
    # otherwise the default density of the preset from the blend sources is used.
    for modifier, particle_system, new_ps_settings in particle_system_data:
        # TODO: Let people choose preserve density and count
        # if props.preserve_density:
        particle_system.settings.count, overflow = get_area_based_particle_count(
            target_object, new_ps_settings.pps_density, 10000)  # props.max_particle_count)

        if overflow > 0:
            logger.warning(f"Particle count exceeded maximum by: {int(overflow)}")
        # else:
        #    particle_system.settings.count = self.count

    for modifier, particle_system, _ in particle_system_data:
        ensure_particle_naming_consistency(modifier, particle_system)
        # TODO: Let people choose display percentage
        particle_system.settings.display_percentage = 20  # props.display_percentage
        instance_collection = particle_system.settings.instance_collection
        assert instance_collection is not None
        for obj in instance_collection.all_objects:
            # TODO: Let people choose display type
            obj.display_type = 'TEXTURED'  # props.display_type

        # TODO: Let people link collection
        # if self.link_instance_collection:
        #     biq_coll = polib.asset_addon_bpy.collection_get(
        #         context, asset_helpers.PARTICLE_SYSTEMS_CATEGORY,
        #         parent=polib.asset_addon_bpy.collection_get(
        #             context, asset_helpers.BIQ_COLLECTION_NAME)
        #     )
        #     biq_coll.children.link(instance_collection)

    # area doesn't automatically redraw if the props dialog is overlaying the list
    # context.area is None in headless mode (e.g. while testing from Bazel)
    if context.area is not None:
        context.area.tag_redraw()
    return particle_system_data


def make_selection_linked(context: bpy.types.Context) -> typing.List[bpy.types.Object]:
    addon_install_paths = get_addons_install_paths(
        get_installed_polygoniq_asset_addons(include_asset_packs=True).keys(),
        short_names=True
    )
    previous_selection = [obj.name for obj in context.selected_objects]
    previous_active_object_name = context.active_object.name if context.active_object else None

    converted_objects = []
    for obj in find_polygoniq_root_objects(context.selected_objects):
        if obj.instance_type == 'COLLECTION':
            continue

        path_property = obj.get("polygoniq_addon_blend_path", None)
        if path_property is None:
            continue

        # Particle systems are skipped. After converting to editable
        # all instances of particle system are separate objects. It
        # is not easy to decide which object belonged to what preset.
        if path_property.startswith("blends/particles"):
            continue

        addon_property = obj.get("polygoniq_addon", None)
        if addon_property is None:
            continue

        install_path = addon_install_paths.get(addon_property, None)
        if install_path is None:
            logger.warning(
                f"Obj {obj.name} contains property: {addon_property} but addon is not installed!")
            continue

        asset_path = os.path.join(install_path, os.path.normpath(path_property))
        if not os.path.isfile(asset_path):
            logger.warning(
                f"Cannot link {obj.name} from {asset_path} because "
                "it doesn't exist, perhaps the asset isn't in this version anymore.")
            continue

        asset_name, _ = os.path.splitext(os.path.basename(path_property))

        instance_root = None
        old_model_matrix = obj.matrix_world.copy()
        old_collections = list(obj.users_collection)
        old_color = tuple(obj.color)
        old_parent = obj.parent

        # This way old object names won't interfere with the new ones
        hierarchy_objects = get_hierarchy(obj)
        for hierarchy_obj in hierarchy_objects:
            hierarchy_obj.name = utils_bpy.generate_unique_name(
                f"del_{hierarchy_obj.name}", bpy.data.objects)

        instance_root = generic_link_asset(
            context,
            asset_name,
            asset_path,
            old_collections[0],
        )
        if instance_root is not None:
            instance_root.color = old_color

        if instance_root is None:
            logger.error(f"Failed to link asset {obj} with "
                         f"{addon_property}, instance is None")
            continue

        instance_root.matrix_world = old_model_matrix
        instance_root.parent = old_parent

        for coll in old_collections:
            if instance_root.name not in coll.objects:
                coll.objects.link(instance_root)

        converted_objects.append(instance_root)

        bpy.data.batch_remove(hierarchy_objects)

    # Force Blender to evaluate view_layer data after programmatically removing/linking objects.
    # https://docs.blender.org/api/current/info_gotcha.html#no-updates-after-setting-values
    context.view_layer.update()

    for obj_name in previous_selection:
        obj = context.view_layer.objects.get(obj_name, None)
        # Linked version doesn't necessary contain the same objects
        # e. g. traffiq linked version doesn't contain wheels, brakes, ...
        if obj is not None:
            obj.select_set(True)

    if previous_active_object_name is not None and \
       previous_active_object_name in context.view_layer.objects:
        context.view_layer.objects.active = bpy.data.objects[previous_active_object_name]

    return converted_objects


def make_selection_editable(context: bpy.types.Context, delete_base_empty: bool, keep_selection: bool = True, keep_active: bool = True) -> typing.List[str]:
    def apply_botaniq_particle_system_modifiers(obj: bpy.types.Object):
        for child in obj.children:
            apply_botaniq_particle_system_modifiers(child)

        for modifier in obj.modifiers:
            if modifier.type != 'PARTICLE_SYSTEM' or not modifier.name.startswith(PARTICLE_SYSTEM_PREFIX):
                continue

            clear_selection(context)
            obj.select_set(True)
            bpy.ops.object.duplicates_make_real(use_base_parent=True, use_hierarchy=True)
            obj.select_set(False)

            # Remove collection with unused origin objects previously used for particle system
            if modifier.name in bpy.data.collections:
                collection = bpy.data.collections[modifier.name]
                particle_origins = [obj for obj in collection.objects if obj.users == 1]
                bpy.data.batch_remove(particle_origins)
                if len(collection.objects) == 0:
                    bpy.data.collections.remove(collection)

            obj.modifiers.remove(modifier)

    InstancedObjectInfo = typing.Tuple[bpy.types.Object, bpy.types.Collection,
                                       str, typing.Tuple[float, float, float, float]]

    def find_instanced_collection_objects(obj: bpy.types.Object, instanced_collection_objects: typing.Dict[str, InstancedObjectInfo]):
        for child in obj.children:
            find_instanced_collection_objects(child, instanced_collection_objects)

        if obj.instance_type == 'COLLECTION':
            if obj.name not in instanced_collection_objects:
                instanced_collection_objects[obj.name] = (
                    obj, obj.instance_collection, obj.parent.name if obj.parent else None, obj.color)

    def copy_polygoniq_custom_props_from_children(obj: bpy.types.Object) -> None:
        """Tries to copy Polygoniq custom properties from children to 'obj'.

        Tries to find child with all polygoniq custom properties
        if such a child exists, values of its properties are copied to 'obj'.
        """
        for child in obj.children:
            copyright = child.get("copyright", None)
            polygoniq_addon = child.get("polygoniq_addon", None)
            polygoniq_blend_path = child.get("polygoniq_addon_blend_path", None)
            if all(prop is not None for prop in [copyright, polygoniq_addon, polygoniq_blend_path]):
                obj["copyright"] = copyright
                obj["polygoniq_addon"] = polygoniq_addon
                obj["polygoniq_addon_blend_path"] = polygoniq_blend_path
                return

    def get_mesh_to_objects_map(obj: bpy.types.Object, result: typing.DefaultDict[str, typing.List[bpy.types.ID]]) -> None:
        for child in obj.children:
            get_mesh_to_objects_map(child, result)

        if obj.type == 'MESH' and obj.data is not None:
            original_mesh_name = utils_bpy.remove_object_duplicate_suffix(obj.data.name)
            result[original_mesh_name].append(obj)

    def get_material_to_slots_map(obj: bpy.types.Object, result: typing.DefaultDict[str, typing.List[bpy.types.ID]]) -> None:
        for child in obj.children:
            get_material_to_slots_map(child, result)

        if obj.type == 'MESH':
            for material_slot in obj.material_slots:
                if material_slot.material is None:
                    continue

                original_material_name = utils_bpy.remove_object_duplicate_suffix(
                    material_slot.material.name)
                result[original_material_name].append(material_slot)

    def get_armatures_to_objects_map(obj: bpy.types.Object, result: typing.DefaultDict[str, typing.List[bpy.types.ID]]) -> None:
        for child in obj.children:
            get_armatures_to_objects_map(child, result)

        if obj.type == 'ARMATURE' and obj.data is not None:
            original_armature_name = utils_bpy.remove_object_duplicate_suffix(obj.data.name)
            result[original_armature_name].append(obj)

    GetNameToUsersMapCallable = typing.Callable[[
        bpy.types.Object, typing.DefaultDict[str, typing.List[bpy.types.ID]]], None]

    def make_datablocks_unique_per_object(obj: bpy.types.Object, get_data_to_struct_map: GetNameToUsersMapCallable, datablock_name: str):
        datablocks_to_owner_structs: typing.DefaultDict[str, typing.List[bpy.types.ID]] = \
            collections.defaultdict(list)
        get_data_to_struct_map(obj, datablocks_to_owner_structs)

        for owner_structs in datablocks_to_owner_structs.values():
            if len(owner_structs) == 0:
                continue

            first_datablock = getattr(owner_structs[0], datablock_name)
            if first_datablock.library is None and first_datablock.users == len(owner_structs):
                continue

            # data block is linked from library or it is used outside of object 'obj' -> create copy
            datablock_duplicate = first_datablock.copy()
            for owner_struct in owner_structs:
                setattr(owner_struct, datablock_name, datablock_duplicate)

    selected_objects_names = [obj.name for obj in context.selected_objects]
    prev_active_object_name = context.active_object.name if context.active_object else None

    instanced_collection_objects: typing.Dict[str, InstancedObjectInfo] = {}
    for obj in context.selected_objects:
        find_instanced_collection_objects(obj, instanced_collection_objects)

    for obj_name in selected_objects_names:
        if obj_name in bpy.data.objects:
            apply_botaniq_particle_system_modifiers(bpy.data.objects[obj_name])

    # origin objects from particle systems were removed from scene
    selected_objects_names = [
        obj_name for obj_name in selected_objects_names if obj_name in bpy.data.objects]

    clear_selection(context)
    for instance_object, _, _, _ in instanced_collection_objects.values():
        # Operator duplicates_make_real converts each instance collection to empty (base parent) and its contents,
        # we change the name of the instance collection object (which becomes the empty) so it doesn't clash
        # with the naming of the actual objects (and doesn't increment duplicate suffix).
        # To keep track of what was converted and to not mess up names of objects
        # we use the '[0-9]+bp_' prefix for the base parent
        i = 0
        name = f"{i}bp_" + instance_object.name
        while name in bpy.data.objects:
            i += 1
            name = f"{i}bp_" + instance_object.name

        instance_object.name = name
        instance_object.select_set(True)
        bpy.ops.object.duplicates_make_real(use_base_parent=True, use_hierarchy=True)
        instance_object.select_set(False)

    for obj, instance_collection, parent_name, prev_color in instanced_collection_objects.values():
        assert obj is not None

        for child in obj.children:
            child.color = prev_color
            # Copy custom property values from each instanced obj to all children recursively
            # only if the property exists on the target object
            copy_custom_props(obj, child, only_existing=True, recursive=True)

        # reorder the hierarchy in following way (car example):
        # base_parent_CAR -> [CAR, base_parent_CAR_Lights, WHEEL1..N -> [CAR_Lights]] to CAR -> [CAR_Lights, WHEEL1..N]
        if parent_name is not None and parent_name in bpy.data.objects:
            parent = bpy.data.objects[parent_name]
            for child in obj.children:
                # after setting parent object here, child.parent_type is always set to 'OBJECT'
                child.parent = parent
                child_source_name = utils_bpy.remove_object_duplicate_suffix(child.name)
                if child_source_name in instance_collection.objects and \
                        instance_collection.objects[child_source_name].parent is not None:
                    # set parent_type from source blend, for example our _Lights need to have parent_type = 'BONE'
                    child.parent_type = instance_collection.objects[child_source_name].parent_type
                    child.matrix_local = instance_collection.objects[child_source_name].matrix_local
            bpy.data.objects.remove(obj)
            continue

        if delete_base_empty:
            if len(obj.children) > 1:
                # instanced collection contained multiple top-level objects, keep base empty as container
                splitted_name = obj.name.split("_", 1)
                if len(splitted_name) == 2:
                    obj.name = splitted_name[1]
                # empty parent newly created in duplicates_make_real does not have polygoniq custom properties
                copy_polygoniq_custom_props_from_children(obj)

            else:
                # remove the parent from children which were not reparented above
                # if they were reparented they are no longer in obj.children and we can
                # safely delete the base parent
                for child in obj.children:
                    child.parent = None
                    child.matrix_world = obj.matrix_world.copy()
                bpy.data.objects.remove(obj)

    selected_objects = []
    for obj_name in selected_objects_names:
        if obj_name not in bpy.data.objects:
            logger.error(f"Previously selected object: {obj_name} is no longer in bpy.data")
            continue

        obj = bpy.data.objects[obj_name]
        # Create copy of meshes shared with other objects or linked from library
        make_datablocks_unique_per_object(obj, get_mesh_to_objects_map, "data")
        # Create copy of materials shared with other objects or linked from library
        make_datablocks_unique_per_object(obj, get_material_to_slots_map, "material")
        # Create copy of armature data shared with other objects or linked from library
        make_datablocks_unique_per_object(obj, get_armatures_to_objects_map, "data")

        # Blender operator duplicates_make_real doesn't append animation data with drivers.
        # Thus we have to create those drivers dynamically based on bone names.
        if rigs_shared_bpy.is_object_rigged(obj):
            # set object as active to be able to go into POSE mode
            context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='POSE')
            driver_creator = rigs_shared_bpy.RigDrivers(obj)
            driver_creator.create_all_drivers()
            bpy.ops.object.mode_set(mode='OBJECT')

        if keep_selection:
            selected_objects.append(obj_name)
            obj.select_set(True)

    if keep_active and prev_active_object_name is not None:
        if prev_active_object_name in bpy.data.objects:
            context.view_layer.objects.active = bpy.data.objects[prev_active_object_name]

    return selected_objects


def calculate_mesh_area(obj: bpy.types.Object, include_weight: bool = False) -> float:
    mesh = obj.data
    try:
        if obj.mode == 'EDIT':
            bm = bmesh.from_edit_mesh(mesh)
        else:
            bm = bmesh.new()
            bm.from_mesh(mesh)

        bm.transform(obj.matrix_world)
        if include_weight:
            vg = obj.vertex_groups.active
            mesh_area = 0
            for face in bm.faces:
                f_area = face.calc_area()
                weighted_verts = 0
                weight = 0
                for v in face.verts:
                    # heavy approach, but we don't know whether i vertex is in the group :(
                    try:
                        weight += vg.weight(v.index)
                        weighted_verts += 1
                    except:
                        pass
                if weighted_verts > 0:
                    mesh_area += (weight / weighted_verts) * f_area
        else:
            mesh_area = sum(f.calc_area() for f in bm.faces)

    finally:
        bm.free()

    return mesh_area


HierarchyNameComparator = typing.Callable[[
    bpy.types.Object, typing.Optional[bpy.types.Object]], bool]


def find_object_in_hierarchy(
    root_obj: bpy.types.Object,
    name_comparator: HierarchyNameComparator,
) -> typing.Optional[bpy.types.Object]:
    # We don't use get_hierarchy function, because here we can return the desired
    # object before going through the whole hierarchy
    def search_hierarchy(parent_obj: bpy.types.Object) -> typing.Optional[bpy.types.Object]:
        if name_comparator(parent_obj, root_obj):
            return parent_obj

        for obj in parent_obj.children:
            candidate = search_hierarchy(obj)
            if candidate is not None:
                return candidate

        return None

    return search_hierarchy(root_obj)


def get_hierarchy(root):
    """Gathers children of 'root' recursively
    """

    assert hasattr(root, "children")
    ret = [root]
    for child in root.children:
        ret.extend(get_hierarchy(child))

    return ret


def collection_get(context: bpy.types.Context, name: str, parent:
                   typing.Optional[bpy.types.Collection] = None) -> bpy.types.Collection:
    scene_collections = get_hierarchy(context.scene.collection)
    for coll in scene_collections:
        if utils_bpy.remove_object_duplicate_suffix(coll.name) == name:
            return coll

    coll = bpy.data.collections.new(name)
    if parent is None:
        context.scene.collection.children.link(coll)
    else:
        parent.children.link(coll)

    if hasattr(coll, "color_tag"):  # coloring is only supported if this attribute is present
        coll_color = ASSET_ADDON_COLLECTION_COLOR_MAP.get(name, None)
        if coll_color is not None:
            coll.color_tag = coll_color
        elif parent is not None:  # color direct descendants by their parent color - e.g. botaniq/weed
            parent_name = utils_bpy.remove_object_duplicate_suffix(parent.name)
            parent_color = ASSET_ADDON_COLLECTION_COLOR_MAP.get(parent_name, None)
            if parent_color is not None:
                coll.color_tag = parent_color
    return coll


def collection_add_object(collection: bpy.types.Collection, obj: bpy.types.Object) -> None:
    """Unlinks 'obj' from all collections and links it into 'collection'
    """

    for coll in obj.users_collection:
        coll.objects.unlink(obj)

    collection.objects.link(obj)


def copy_object_hierarchy(root_obj: bpy.types.Object) -> bpy.types.Object:
    """Copies 'root_obj' and its hierarchy while preserving parenting, returns the root copy
    """

    def copy_hierarchy(obj: bpy.types.Object, parent: bpy.types.Object) -> None:
        obj_copy = obj.copy()
        obj_copy.parent = parent
        for child in obj.children:
            copy_hierarchy(child, obj_copy)

    root_obj_copy = root_obj.copy()
    for obj in root_obj.children:
        copy_hierarchy(obj, root_obj_copy)

    return root_obj_copy


def collection_link_hierarchy(collection: bpy.types.Collection, root_obj: bpy.types.Object) -> None:
    """Links 'root_obj' and its hierarachy to 'collection' and unlinks it from all other collections
    """

    for obj in get_hierarchy(root_obj):
        for coll in obj.users_collection:
            coll.objects.unlink(obj)
        collection.objects.link(obj)


def collection_unlink_hierarchy(collection: bpy.types.Collection, root_obj: bpy.types.Object) -> None:
    """Unlinks 'root_obj' and it's hierarchy from 'collection'
    """

    for obj in get_hierarchy(root_obj):
        collection.objects.unlink(obj)


def find_layer_collection(
        view_layer_root: bpy.types.LayerCollection,
        target: bpy.types.Collection) -> typing.Optional[bpy.types.LayerCollection]:
    """Finds corresponding LayerCollection from 'view_layer_coll' hierarchy
    which contains 'target' collection.
    """

    if view_layer_root.collection == target:
        return view_layer_root

    for layer_child in view_layer_root.children:
        found_layer_collection = find_layer_collection(layer_child, target)
        if found_layer_collection is not None:
            return found_layer_collection

    return None


def clear_selection(context: bpy.types.Context) -> None:
    for obj in context.selected_objects:
        obj.select_set(False)


def append_modifiers_from_library(
    modifier_container_name: str,
    library_path: str,
    target_objs: typing.Iterable[bpy.types.Object]
) -> None:
    """Add all modifiers from object with given name in given .blend library to 'target_objects'.

    It doesn't copy complex and readonly properties, e.g. properties that are driven by FCurve.
    """
    if modifier_container_name not in bpy.data.objects:
        with bpy.data.libraries.load(library_path) as (data_from, data_to):
            assert modifier_container_name in data_from.objects
            data_to.objects = [modifier_container_name]

    assert modifier_container_name in bpy.data.objects
    modifier_container = bpy.data.objects[modifier_container_name]

    for obj in target_objs:
        for src_modifier in modifier_container.modifiers:
            assert src_modifier.name not in obj.modifiers
            dest_modifier = obj.modifiers.new(src_modifier.name, src_modifier.type)

            # collect names of writable properties
            properties = [p.identifier for p in src_modifier.bl_rna.properties if not p.is_readonly]

            # copy those properties
            for prop in properties:
                setattr(dest_modifier, prop, getattr(src_modifier, prop))


def update_custom_prop(
    context: bpy.types.Context,
    objs: typing.Iterable[bpy.types.Object],
    prop_name: str,
    value: CustomAttributeValueType,
    update_tag_refresh: typing.Set[str] = {'OBJECT'}
) -> None:
    """Update custom properties of given objects and force 3D view to redraw

    When we set values of custom properties from code, affected objects don't get updated in 3D View
    automatically. We need to call obj.update_tag() and then refresh 3D view areas manually.

    'update_tag_refresh' set of enums {'OBJECT', 'DATA', 'TIME'}, updating DATA is really slow
    as it forces Blender to recompute the whole mesh, we should use 'OBJECT' wherever it's enough.
    """
    for obj in objs:
        if prop_name in obj:
            obj[prop_name] = value
            obj.update_tag(refresh=update_tag_refresh)

    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


def generic_spawn_scene(
    context: bpy.types.Context,
    asset_name: str,
    blend_path: str
) -> typing.Optional[bpy.types.Scene]:
    existing_scene = bpy.data.scenes.get(asset_name, None)
    if existing_scene is not None:
        context.window.scene = existing_scene
        return existing_scene

    with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
        assert len(data_from.scenes) > 0
        data_to.scenes = data_from.scenes

    context.window.scene = data_to.scenes[0]
    return existing_scene
