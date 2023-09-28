# copyright (c) 2018- polygoniq xyz s.r.o.

import os
import typing
import enum
import collections
import bpy
import logging
logger = logging.getLogger(f"polygoniq.{__name__}")


if "installation_utils_bpy" not in locals():
    from . import installation_utils_bpy
    from . import bl_info_utils
else:
    import importlib
    installation_utils_bpy = importlib.reload(installation_utils_bpy)
    bl_info_utils = importlib.reload(bl_info_utils)

# We search both "megaddon_addon" and "addon", because we need to consider the vscode
# environment, where the megaddon has "_addon" suffix.
MEGADDON_MODULE_NAMES = ["megaddon_addon", "megaddon"]


class MegaddonState(enum.Enum):
    VALID = 0  # current megaddon version is the same as required by addon
    INSTALLED = 1  # megaddon installed from bundled addon zip file, no megaddon was present
    MINOR_UPDATED = 2  # megaddon updated from bundled zip file, other older minor version present
    MAJOR_UPDATED = 3  # major updated from bundled zip, other addons may need update from this point
    ADDON_UPDATE_REQUIRED = 4  # newer major megaddon present, addon requires lower major version
    DEVELOPMENT = 5  # addon with module name "megaddon_addon" is present (vscode development)
    NO_ZIP = 6  # this is really unlikely, but the bundled zip is missing from the addon zip

    # There can be more instances of this class if Blender reloads polib when reinstalling addons,
    # overriding equality comparison ensures that we don't return True for two equal states from
    # different instances of this enum.
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MegaddonState):
            return False

        return self.value == other.value


# Available versions of megaddon to store more information about the current state
MegaddonVersions = collections.namedtuple('MegaddonVersions', ['required', 'installed', 'zip'])


def get_installed_megaddon() -> typing.Tuple[typing.Optional[str], typing.Optional[typing.Tuple[int, int, int]]]:
    """Returns megaddon module name and its version if present"""
    found_module_name = None
    installed_megaddon_version: typing.Optional[typing.Tuple[int, int, int]] = None
    for name_candidate in MEGADDON_MODULE_NAMES:
        installed_megaddon_version = installation_utils_bpy.get_addon_version_in_blender(
            name_candidate)
        if installed_megaddon_version is not None:
            found_module_name = name_candidate
            break

    return found_module_name, installed_megaddon_version


def ensure_megaddon(
    minimal_version: typing.Tuple[int, int, int],
    addon_module_name: str
) -> typing.Tuple[MegaddonState, MegaddonVersions]:
    """Ensures that usable version for this addon is installed or reports that update should happen.
    """

    installed_module_name, installed_version = get_installed_megaddon()

    # Is megaddon development version used?
    if installed_module_name is not None and installed_module_name == "megaddon_addon":
        logger.debug(f"megaddon development version from vscode is used")
        return MegaddonState.DEVELOPMENT, MegaddonVersions(minimal_version, installed_version, None)

    zip_candidate_paths = [
        os.path.abspath(os.path.join(
            p,
            addon_module_name,
            "addon_deps",
            "megaddon.zip"
        )) for p in bpy.utils.script_paths(subdir="addons", check_all=False)]

    megaddon_zip_file = None
    for path in zip_candidate_paths:
        if os.path.isfile(path):
            megaddon_zip_file = path
            break

    if megaddon_zip_file is None:
        logger.error(f"No megaddon zip found at any location from {zip_candidate_paths}")
        return MegaddonState.NO_ZIP, MegaddonVersions(minimal_version, installed_version, None)

    zip_version = bl_info_utils.infer_version_from_bl_info_from_zip_file(megaddon_zip_file)

    megaddon_versions = MegaddonVersions(
        minimal_version,
        installed_version,
        zip_version
    )

    # This shouldn't happen, it either is development with no zip or
    # shipped addon with megaddon present
    if zip_version is None:
        logger.error(
            f"No megaddon zip found at any location from {zip_candidate_paths}. "
            f"Found versions: '{megaddon_versions}'")
        return MegaddonState.NO_ZIP, megaddon_versions

    assert zip_version is not None
    # If no megaddon installation was found, then we can be sure other polygoniq addon didn't
    # install it already, thus we install the required version by this addon ouselves.
    if installed_version is None:
        # We should never ship incompatible megaddon version
        assert zip_version == minimal_version
        # We install "megaddon" module, because it is the only module name under what
        # megaddon can be shipped.
        logger.info(
            f"Installing megaddon version from '{megaddon_zip_file}', '{megaddon_versions}'")
        installation_utils_bpy.install_addon_zip(megaddon_zip_file, "megaddon")
        return MegaddonState.INSTALLED, megaddon_versions

    # This or other addon may have already installed megaddon. We check whether the installed
    # version is suitable to use with this addon. If not and a newer MAJOR version is present in
    # the zip we install that version, which may deprecate other addon dependencies and we inform
    # user that they should update them ASAP (at this point MAJOR version of megaddon changed,
    # thus it should be released with all addons).
    if installed_version[0] > minimal_version[0]:
        logger.error(
            f"Incompatible megaddon versions, addon outdated, '{megaddon_versions}'!")
        return MegaddonState.ADDON_UPDATE_REQUIRED, megaddon_versions
    elif installed_version[0] < minimal_version[0]:
        # required version is higher than installed, thus the zip version has to be higher too
        assert zip_version > installed_version
        logger.info(
            f"Updated major version from '{megaddon_zip_file}', '{megaddon_versions}'. "
            f"Other addons not supporting the '{installed_version}' became outdated.")
        installation_utils_bpy.install_addon_zip(megaddon_zip_file, "megaddon")
        return MegaddonState.MAJOR_UPDATED, megaddon_versions

    assert installed_version[0] == minimal_version[0]
    # In case of newer MINOR verison available we install it, as it doesn't break API.
    if zip_version > installed_version:
        logger.info(
            f"Updating megaddon minor version from '{installed_version}' to '{zip_version}'")

        installation_utils_bpy.install_addon_zip(megaddon_zip_file, "megaddon")
        return MegaddonState.MINOR_UPDATED, megaddon_versions

    # Here the present megaddon version is either equal to the required one or it is newer MINOR
    # version, both cases are VALID
    return MegaddonState.VALID, megaddon_versions


def draw_megaddon_state(
    layout: bpy.types.UILayout,
    state: MegaddonState,
    versions: MegaddonVersions,
) -> None:
    box = layout.box()
    row = box.row(align=True)
    row.label(text="polygoniq megaddon dependency state", icon='NODE_INSERT_OFF')
    _, installed_megaddon_version = get_installed_megaddon()
    col = row.column()
    col.alignment = 'RIGHT'
    col.enabled = False
    col.label(text=f"Required: {versions.required} Present: {installed_megaddon_version}")
    row = box.row()
    row.enabled = False
    if state == MegaddonState.VALID:
        row.label(text="Checked successfully", icon='FAKE_USER_ON')
    elif state == MegaddonState.INSTALLED:
        row.label(text=f"Installed version {versions.zip}", icon='CHECKMARK')
    elif state == MegaddonState.MINOR_UPDATED:
        row.label(text=f"Updated from {versions.installed} to {versions.zip}", icon='SORT_DESC')
    elif state == MegaddonState.ADDON_UPDATE_REQUIRED:
        row.alert = True
        row.enabled = True
        row.label(text="Some features may not work, update this addon!", icon='INDIRECT_ONLY_ON')
        col = box.column(align=True)
        col.enabled = False
        col.label(text=f"Other addon updated megaddon to version {versions.installed}, but this")
        col.label(text=f"addon requires older version {versions.required}. Newer version should")
        col.label(text=f"be available at the vendor, where you purchased this product.")
    elif state == MegaddonState.MAJOR_UPDATED:
        row.alert = True
        row.enabled = True
        row.label(text="Check other addons versions, there is new update ready!", icon='ERROR')
        col = box.column(align=True)
        col.enabled = False
        col.label(text=f"This addon updated megaddon to version {versions.zip}, but if there is")
        col.label(text=f"another polygoniq addon, it may be using older version that may not be")
        col.label(text=f"supported anymore. Check other addons preferences, newer versions should")
        col.label(text=f"be available at the vendor,where you purchased this product.")
    elif state == MegaddonState.NO_ZIP:
        row.alert = True
        row.enabled = True
        row.label(text=f"No bundled 'megaddon.zip' found!", icon='ERROR')
    elif state == MegaddonState.DEVELOPMENT:
        row.label(
            text=f"Using megaddon from vscode development environment, enjoy!",
            icon='PLUGIN'
        )
    else:
        row.label(text=f"{state}")

    col = box.column(align=True)
    col.label(text="Information", icon='INFO')
    col.label(text="polygoniq is going to be changing how our addons are installed soon.")
    col.label(text="Asset libraries and code features are going to be downloadable separately.")
    col.label(text="There is 'megaddon' addon installed automatically for now as an intermediate")
    col.label(text="step of this transition during the beta phase.")
    col.label(text="This addon contains all the functionality for materialiq and its asset browser.")
    col.label(text="When materialiq version becomes stable, 'megaddon' will be the one place where")
    col.label(text="you work with all polygoniq assets.")
    col.label(text="Thanks to this, features and bugfixes will be in your hands much faster and you")
    col.label(text="do not have to download all the assets for a bugfix.")
