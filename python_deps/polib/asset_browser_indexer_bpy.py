#!/usr/bin/python3
# copyright (c) 2018- polygoniq xyz s.r.o.

import bpy
import os
import sys
import glob
import argparse
import uuid
import typing
import pathlib
import polib

import logging
logger = logging.getLogger(f"polygoniq.{__name__}")


def gather_custom_property_values(
    property_name: str,
    datablocks: typing.Iterable[bpy.types.ID]
) -> typing.Iterable[str]:
    for datablock in datablocks:
        if datablock.get(property_name, None) is not None:
            yield str(datablock.get(property_name))


def index_asset_source(
    blends_path: str,
    previews_path: str,
    extra_tags: typing.List[str],
    catalog_paths_to_uuid: typing.Dict[str, str]
) -> None:
    input_blends = sorted(glob.glob(os.path.join(blends_path, "**/*.blend"), recursive=True))
    if len(input_blends) == 0:
        logger.critical(f"'{blends_path}' is a directory but contains no blends!")
        sys.exit(1)

    for i, input_blend in enumerate(input_blends):
        message = \
            f"{i}/{len(input_blends)}: processing " \
            f"{os.path.relpath(input_blend, blends_path)}..."
        logger.info(message)

        if os.path.isdir(input_blend):
            continue

        if polib.asset_addon.is_library_blend(input_blend):
            continue

        basename = os.path.basename(input_blend)
        basename_without_ext, _ = os.path.splitext(basename)
        rel_blend_path = os.path.relpath(os.path.dirname(input_blend), blends_path)
        browser_category = rel_blend_path.replace("\\", "/")
        # This cannot happen currently as all assets are at least in one category folder
        if browser_category == ".":
            browser_category = "general"
        rel_blend_path_obj = pathlib.Path(rel_blend_path)

        bpy.ops.wm.open_mainfile(filepath=input_blend)

        def fill_asset_data(
            main_datablock: bpy.types.ID,
            datablocks: typing.Iterable[bpy.types.ID]
        ) -> None:
            # Create catalog (= Asset Browser category) from our folder structure
            # if this is the first asset from the category
            if browser_category not in catalog_paths_to_uuid:
                catalog_paths_to_uuid[browser_category] = str(uuid.uuid4())

            asset_data = main_datablock.asset_data
            # Assign this asset into catalog which corresponds to its category
            asset_data.catalog_id = catalog_paths_to_uuid[browser_category]
            asset_data.tags.new(browser_category, skip_if_exists=True)
            for tag in extra_tags:
                asset_data.tags.new(tag, skip_if_exists=True)

            copyrights = set(gather_custom_property_values(
                "copyright", datablocks))
            if len(copyrights) > 0:
                asset_data.author = ", ".join(copyrights)

            try:
                bpy.ops.ed.lib_id_load_custom_preview(
                    {"id": main_datablock},
                    filepath=os.path.join(
                        previews_path,
                        os.path.relpath(os.path.dirname(input_blend), blends_path),
                        f"{basename_without_ext}.png"
                    )
                )
            except RuntimeError:
                logger.exception(
                    f"Something went wrong when trying to load preview for {input_blend}")
                # generating preview only works when blender is run in foreground mode, in
                # background mode it crashes
                # bpy.ops.ed.lib_id_generate_preview(
                #    {"id": datablock}
                # )

        if basename.startswith("pps_"):
            # Particle blends are stripped of unnecessary data, but to spawn it via asset browser
            # we have to present it somehow as an object.
            # We create a plane, add the particle systems and the base material
            # and tag the plane as a asset.
            bpy.ops.mesh.primitive_plane_add()
            plane = bpy.data.objects["Plane"]
            plane.name = basename_without_ext
            plane.data.name = basename_without_ext
            instanced_objs = []
            for particle_system in bpy.data.particles:
                mod: bpy.types.ParticleSystemModifier = plane.modifiers.new(
                    particle_system.name, 'PARTICLE_SYSTEM')
                mod.particle_system.settings = particle_system
                instance_collection = mod.particle_system.settings.instance_collection
                if instance_collection is not None:
                    instanced_objs.extend(instance_collection.objects)

            for material in bpy.data.materials:
                # TODO: Add addon prefix to material name
                if material.name.startswith("Base_"):
                    plane.data.materials.append(material)
                    break
            plane.asset_mark()
            fill_asset_data(plane, [plane] + instanced_objs)

        elif "materials" in rel_blend_path_obj.parts:
            assert len(bpy.data.materials) == 1
            mat = bpy.data.materials[0]
            mat.asset_mark()
            fill_asset_data(mat, [mat])

        elif "worlds" in rel_blend_path_obj.parts:
            assert len(bpy.data.worlds) == 1
            world = bpy.data.worlds[0]
            world.asset_mark()
            fill_asset_data(world, [world])

        # we prefer marking objects as assets, because the spawning and snapping GUI is better
        # for objects. we mark collections as assets only when there is more than one object
        elif len(bpy.data.objects) == 1:
            obj = bpy.data.objects[0]
            obj.asset_mark()
            fill_asset_data(obj, [obj])

        else:
            collection = bpy.data.collections.get(basename_without_ext)
            if collection is not None:
                collection.asset_mark()
                fill_asset_data(collection, collection.all_objects)
            else:
                logger.error(
                    f"Expected {bpy.data.filepath} to contain collection named "
                    f"{basename_without_ext} but no such collection was found. Not sure what to "
                    f"mark as the asset in this blend. Skipping...")

        bpy.ops.wm.save_as_mainfile(
            filepath=bpy.data.filepath,
            compress=True,
        )


def main():
    argv = sys.argv
    if "--" not in argv:
        argv = []
    else:
        argv = argv[argv.index("--") + 1:]

    parser = argparse.ArgumentParser(
        description="Create an Asset Catalog Definition file and fill "
                    "in asset data to index them to the catalog for the specified addon.")
    parser.add_argument(
        "--addon_name",
        type=str,
        help="Which addon are we indexing.",
    )
    parser.add_argument(
        "--extra_tags",
        type=str,
        help="Additional tags to add to each asset. Comma-separated.",
    )
    parser.add_argument(
        "INPUT_DIRS",
        type=str,
        nargs="+",
        help="Directories to index from. Always `blends_dir` followed by `previews_dir` per entry."
    )
    args = parser.parse_args(argv)

    if len(args.INPUT_DIRS) % 2 != 0:
        raise RuntimeError(
            "Expected an even number of input dirs. Each blends_dir needs to be followed by "
            "a preview_dir."
        )

    catalog_paths_to_uuid = {}
    # Do not save .blend1 with this script
    bpy.context.preferences.filepaths.save_version = 0

    extra_tags = args.extra_tags.split(",")
    for blends_path, previews_path in zip(args.INPUT_DIRS[::2], args.INPUT_DIRS[1::2]):
        if not os.path.isdir(blends_path):
            logger.critical(
                f"'{blends_path}' is not a directory. Permission issues? Does it exist?")
            sys.exit(1)

        if ("Products" in blends_path or "Builds" in blends_path) \
                and f"{args.addon_name}_addon" in blends_path:
            logger.critical("Bad idea.")
            sys.exit(1)

        blends_path = os.path.realpath(blends_path)
        previews_path = os.path.realpath(previews_path)
        index_asset_source(blends_path, previews_path, extra_tags, catalog_paths_to_uuid)

    # Write catalog definition file as described in
    # https://docs.blender.org/manual/en/3.2/files/asset_libraries/catalogs.html
    with open(os.path.join(blends_path, "..", "blender_assets.cats.txt"), "w") as f:
        print("""# This is an Asset Catalog Definition file for Blender.
#
# Empty lines and lines starting with `#` will be ignored.
# The first non-ignored line should be the version indicator.
# Other lines are of the format "UUID:catalog/path/for/assets:simple catalog name"

VERSION 1

""", file=f)
        for catalog_path, catalog_uuid in catalog_paths_to_uuid.items():
            print(f"{catalog_uuid}:{catalog_path}:{catalog_path.replace('/', '-')}", file=f)

    sys.exit(0)


if __name__ == "__main__":
    try:
        root_logger = logging.getLogger("polygoniq")
        assert not getattr(root_logger, "polygoniq_initialized", False)
        root_logger_formatter = logging.Formatter(
            "%(asctime)s:%(name)s:%(levelname)s: [%(filename)s:%(lineno)d] %(message)s", "%H:%M:%S")
        try:
            root_logger.setLevel(int(os.environ.get("POLYGONIQ_LOG_LEVEL", "20")))
        except (ValueError, TypeError):
            root_logger.setLevel(20)
        root_logger.propagate = False
        root_logger_stream_handler = logging.StreamHandler()
        root_logger_stream_handler.setFormatter(root_logger_formatter)
        root_logger.addHandler(root_logger_stream_handler)
        setattr(root_logger, "polygoniq_initialized", True)

        main()

    except Exception as e:
        logger.exception("Uncaught exception!")
        sys.exit(1)
