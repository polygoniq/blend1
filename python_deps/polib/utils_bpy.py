#!/usr/bin/python3
# copyright (c) 2018- polygoniq xyz s.r.o.

import bpy
import sys
import os
import pathlib
import typing
import datetime
import functools
import itertools
import subprocess
import math
import time
import re
import logging
logger = logging.getLogger(f"polygoniq.{__name__}")


def autodetect_install_path(product: str, init_path: str, install_path_checker: typing.Callable[[str], bool]) -> str:
    # TODO: We should submit a patch to blender_vscode and deal with this from there in the future
    try:
        vscode_product_path = os.path.expanduser(
            os.path.join("~", "polygoniq", "blender_addons", product))
        if os.path.commonpath([os.path.abspath(os.path.realpath(init_path)), vscode_product_path]) == vscode_product_path:
            staging_path_base = os.path.expanduser(
                os.path.join("~", "polygoniq", "bazel-bin", "blender_addons", product)
            )
            # Possible sources of built assets from bazel
            FLIP_OF_THE_COIN = [
                os.path.join(staging_path_base, f"{product}_staging"),
                os.path.join(staging_path_base, f"data_final")
            ]
            for flip in FLIP_OF_THE_COIN:
                if os.path.isdir(flip):
                    print(
                        f"Detected blender_vscode development environment. Going to use {flip} as "
                        f"the install path for {product}."
                    )
                    return flip

    except ValueError:  # Paths don't have the same drive
        pass

    big_zip_path = os.path.abspath(os.path.dirname(init_path))
    if install_path_checker(big_zip_path):
        print(f"{product} install dir autodetected as {big_zip_path} (big zip embedded)")
        return big_zip_path

    if sys.platform == "win32":
        SHOTS_IN_THE_DARK = [
            f"C:/{product}",
            f"D:/{product}",
            f"C:/polygoniq/{product}",
            f"D:/polygoniq/{product}",
        ]

        for shot in SHOTS_IN_THE_DARK:
            if install_path_checker(shot):
                print(f"{product} install dir autodetected as {shot}")
                return os.path.abspath(shot)

    elif sys.platform in ["linux", "darwin"]:
        SHOTS_IN_THE_DARK = [
            os.path.expanduser(f"~/{product}"),
            os.path.expanduser(f"~/Desktop/{product}"),
            os.path.expanduser(f"~/Documents/{product}"),
            os.path.expanduser(f"~/Downloads/{product}"),
            os.path.expanduser(f"~/polygoniq/{product}"),
            os.path.expanduser(f"~/Desktop/polygoniq/{product}"),
            os.path.expanduser(f"~/Documents/polygoniq/{product}"),
            os.path.expanduser(f"~/Downloads/polygoniq/{product}"),
            f"/var/lib/{product}",
            f"/usr/local/{product}",
            f"/opt/{product}",
        ]

        for shot in SHOTS_IN_THE_DARK:
            if install_path_checker(shot):
                print(f"{product} install dir autodetected as {shot}")
                return os.path.abspath(shot)

    print(
        f"{product} is not installed in one of the default locations, please make "
        f"sure the path is set in {product} addon preferences!", file=sys.stderr)
    return ""


def absolutize_preferences_path(
    self: bpy.types.AddonPreferences,
    context: bpy.types.Context,
    path_property_name: str
) -> None:
    assert hasattr(self, path_property_name)
    abs_ = os.path.abspath(getattr(self, path_property_name))
    if abs_ != getattr(self, path_property_name):
        setattr(self, path_property_name, abs_)


def contains_object_duplicate_suffix(name: str) -> bool:
    pattern = re.compile(r"^\.[0-9]{3}$")
    return bool(pattern.match(name[-4:]))


def remove_object_duplicate_suffix(name: str) -> str:
    splitted_name = name.rsplit(".", 1)
    if len(splitted_name) == 1:
        return splitted_name[0]

    if splitted_name[1].isnumeric():
        return splitted_name[0]

    return name


def generate_unique_name(old_name: str, container: typing.Iterable[typing.Any]) -> str:
    # TODO: Unify this with renderset unique naming generation
    name_without_suffix = remove_object_duplicate_suffix(old_name)
    i = 1
    new_name = name_without_suffix
    while new_name in container:
        new_name = f"{name_without_suffix}.{i:03d}"
        i += 1

    return new_name


DuplicateFilter = typing.Callable[[bpy.types.ID], bool]


def is_duplicate_filtered(data: bpy.types.ID, filters: typing.Iterable[DuplicateFilter]) -> bool:
    filtered = False
    for filter_ in filters:
        if not filter_(data):
            filtered = True
            break

    return filtered


def remove_duplicate_datablocks(datablocks: bpy.types.bpy_prop_collection, filters: typing.Optional[typing.Iterable[DuplicateFilter]] = None) -> typing.List[str]:
    to_remove = []

    for datablock in datablocks:
        if filters is not None and is_duplicate_filtered(datablock, filters):
            continue

        # ok, so it's a duplicate, let's figure out the "proper" datablock
        orig_datablock_name = remove_object_duplicate_suffix(datablock.name)
        if orig_datablock_name in datablocks:
            orig_node_group = datablocks[orig_datablock_name]
            datablock.user_remap(orig_node_group)
            if datablock.users == 0:
                to_remove.append(datablock)
        else:
            # the original datablock is gone, we should rename this one
            datablock.name = orig_datablock_name
    ret = []
    for datablock in to_remove:
        ret.append(datablock.name)
        datablocks.remove(datablock)
    return ret


def convert_size(size_bytes: int) -> str:
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    index = int(math.floor(math.log(size_bytes, 1024)))
    size = round(size_bytes / math.pow(1024, index), 2)
    return f"{size} {size_name[index]}"


def blender_cursor(cursor_name: str = 'WAIT'):
    """Decorator that sets a modal cursor in Blender to whatever the caller desires,
    then sets it back when the function returns. This is useful for long running
    functions or operators. Showing a WAIT cursor makes it less likely that the user
    will think that Blender froze.

    Unfortunately this can only be used in cases we control and only when 'context' is
    available.

    TODO: Maybe we could use bpy.context and drop the context requirement?
    """

    def cursor_decorator(fn):
        def wrapper(self, context: bpy.types.Context, *args, **kwargs):
            context.window.cursor_modal_set(cursor_name)
            try:
                return fn(self, context, *args, **kwargs)
            finally:
                context.window.cursor_modal_restore()

        return wrapper

    return cursor_decorator


def timeit(fn):
    def timed(*args, **kw):
        ts = time.time()
        result = fn(*args, **kw)
        te = time.time()
        print(f"{fn.__name__!r}  {(te - ts) * 1000:2.2f} ms")
        return result
    return timed


def timed_cache(**timedelta_kwargs):
    def _wrapper(f):
        update_delta = datetime.timedelta(**timedelta_kwargs)
        next_update = datetime.datetime.utcnow() + update_delta
        f = functools.lru_cache(None)(f)

        @functools.wraps(f)
        def _wrapped(*args, **kwargs):
            nonlocal next_update
            now = datetime.datetime.utcnow()
            if now >= next_update:
                f.cache_clear()
                next_update = now + update_delta
            return f(*args, **kwargs)
        return _wrapped
    return _wrapper


def xdg_open_file(path):
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.call(["open", path])
    else:
        subprocess.call(["xdg-open", path])


def integrate_addon_to_asset_browser(
    context: bpy.types.Context,
    addon_name: str,
    vendor: str,
    addon_path: str,
    paths: typing.Iterable[typing.Tuple[str, str]]
) -> str:
    if bpy.app.version < (3, 2, 0):
        raise RuntimeError(
            "Only Blender 3.2.0 or newer is supported for asset browser integration!")

    asset_browser_indexer_bpy_path = os.path.realpath(
        os.path.abspath(os.path.join(os.path.dirname(__file__), "asset_browser_indexer_bpy.py")))
    if not os.path.isfile(asset_browser_indexer_bpy_path):
        raise RuntimeError(
            f"Cannot detect file path of the asset_browser_indexer_bpy. "
            f"{asset_browser_indexer_bpy_path} is not a file."
        )

    # Toggle console to show users progress. It's available only on Windows
    if sys.platform == "win32":
        bpy.ops.wm.console_toggle()

    try:
        indexing_process = subprocess.Popen(
            [
                bpy.app.binary_path,
                "-b",
                "-noaudio",
                "--factory-startup",
                # by default blender will exit with 0 even in a case of uncaught exception
                # or syntax error! if we set this we get more safety with louder failures
                "--python-exit-code",
                "1",
                "--python",
                asset_browser_indexer_bpy_path,
                "--",
                "--addon_name",
                addon_name,
                "--extra_tags",
                f"{addon_name},{vendor}",
            ] + list(itertools.chain.from_iterable(paths)),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )

        if hasattr(context.preferences.filepaths, "asset_libraries"):
            # Make sure the library is registered
            for asset_library in context.preferences.filepaths.asset_libraries:
                if asset_library.path == addon_path:
                    break
            else:
                bpy.ops.preferences.asset_library_add()
                library = context.preferences.filepaths.asset_libraries[-1]
                library.name = addon_name
                library.path = addon_path

        # Read from indexing process until it's running
        for line in indexing_process.stdout:
            logger.info(line.decode())

    finally:
        if sys.platform == "win32":
            bpy.ops.wm.console_toggle()

    if indexing_process.wait() == 0:
        return f"{addon_name} from {vendor} has been successfully integrated into Asset Browser."

    else:
        return \
            f"{addon_name} from {vendor} failed to integrate into Asset Browser! This is most " \
            f"likely a bug. Please contact us about this!"


def run_logging_subprocess(
    subprocess_args: typing.List[str],
    logger_: typing.Optional[logging.Logger] = None
) -> int:
    """Runs `subprocess_args` as subprocess and logs stdout and stderr of the subprocess.

    If 'logger_' is None, logger from polib will be used.

    Returns returncode from the subprocess, 0 means that no errors ocurred.
    """
    if logger_ is None:
        logger_ = logger

    process = subprocess.Popen(
        subprocess_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )

    # Read from indexing process till it's running
    for line in process.stdout:
        logger_.info(line.decode())
    process.wait()
    return process.returncode


def normalize_path(path: str) -> str:
    """Makes path OS independent."""
    return path.replace("\\", "/")


def get_bpy_filepath_relative_to_dir(input_dir: str, filepath: str, library=None) -> str:
    file_abspath = bpy.path.abspath(filepath, library=library)
    rel_path = bpy.path.relpath(file_abspath, start=input_dir)
    return normalize_path(rel_path.strip("//"))


def get_first_existing_ancestor_directory(file_path: str, whitelist: typing.Optional[set[str]] = None) -> typing.Optional[str]:
    if whitelist is None:
        whitelist = set()
    if file_path not in whitelist and not os.path.exists(file_path):
        return None
    current_dir = pathlib.Path(os.path.dirname(file_path)).resolve()
    while not os.path.exists(current_dir):
        current_dir = current_dir.parent.resolve()
    return str(current_dir)


def relink_datablock(library_path, datablock_type, old_datablock, new_datablock_name: str) -> bool:
    """Try to relink datablock from library, return True if succesfull, otherwise False."""

    with bpy.data.libraries.load(library_path, link=True) as (_, data_to):
        setattr(data_to, datablock_type, [new_datablock_name])

    new_datablock = bpy.data.node_groups.get(new_datablock_name, None)
    if new_datablock is not None:
        old_datablock.user_remap(new_datablock)
        return True
    return False
