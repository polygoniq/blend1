#!/usr/bin/python3
# copyright (c) 2018- polygoniq xyz s.r.o.

# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

from . import addon_updater
from . import addon_updater_ops
import os
import sys
import shutil
import hashlib
import glob
import time
import functools
import typing
import bpy
import tempfile
import logging
import logging.handlers
import importlib

root_logger = logging.getLogger("polygoniq")
logger = logging.getLogger(f"polygoniq.{__name__}")
if not getattr(root_logger, "polygoniq_initialized", False):
    root_logger_formatter = logging.Formatter(
        "P%(process)d:%(asctime)s:%(name)s:%(levelname)s: [%(filename)s:%(lineno)d] %(message)s",
        "%H:%M:%S",
    )
    try:
        root_logger.setLevel(int(os.environ.get("POLYGONIQ_LOG_LEVEL", "20")))
    except (ValueError, TypeError):
        root_logger.setLevel(20)
    root_logger.propagate = False
    root_logger_stream_handler = logging.StreamHandler()
    root_logger_stream_handler.setFormatter(root_logger_formatter)
    root_logger.addHandler(root_logger_stream_handler)
    try:
        log_path = os.path.join(tempfile.gettempdir(), "polygoniq_logs")
        os.makedirs(log_path, exist_ok=True)
        root_logger_handler = logging.handlers.TimedRotatingFileHandler(
            os.path.join(log_path, f"blender_addons.txt"),
            when="h",
            interval=1,
            backupCount=2,
            utc=True,
        )
        root_logger_handler.setFormatter(root_logger_formatter)
        root_logger.addHandler(root_logger_handler)
    except:
        logger.exception(
            f"Can't create rotating log handler for polygoniq root logger "
            f"in module \"{__name__}\", file \"{__file__}\""
        )
    setattr(root_logger, "polygoniq_initialized", True)
    logger.info(
        f"polygoniq root logger initialized in module \"{__name__}\", file \"{__file__}\" -----"
    )


# To comply with extension encapsulation, after the addon initialization:
# - sys.path needs to stay the same as before the initialization
# - global namespace can not contain any additional modules outside of __package__

# Dependencies for all 'production' addons are shipped in folder `./python_deps`
# So we do the following:
# - Add `./python_deps` to sys.path
# - Import all dependencies to global namespace
# - Manually remap the dependencies from global namespace in sys.modules to a subpackage of __package__
# - Clear global namespace of remapped dependencies
# - Remove `./python_deps` from sys.path
# - For developer experience, import "real" dependencies again, only if TYPE_CHECKING is True

# See https://docs.blender.org/manual/en/4.2/extensions/addons.html#extensions-and-namespace
# for more details
ADDITIONAL_DEPS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "python_deps"))
try:
    if os.path.isdir(ADDITIONAL_DEPS_DIR) and ADDITIONAL_DEPS_DIR not in sys.path:
        sys.path.insert(0, ADDITIONAL_DEPS_DIR)

    dependencies = {
        "polib",
        "hatchery",  # hatchery is a transitive dependency from polib, but we still need to move it
    }
    for dependency in dependencies:
        logger.debug(f"Importing additional dependency {dependency}")
        dependency_module = importlib.import_module(dependency)
        local_module_name = f"{__package__}.{dependency}"
        sys.modules[local_module_name] = dependency_module
    for module_name in list(sys.modules.keys()):
        if module_name.startswith(tuple(dependencies)):
            del sys.modules[module_name]

    from . import polib
    from . import hatchery

    if typing.TYPE_CHECKING:
        import polib
        import hatchery

finally:
    if ADDITIONAL_DEPS_DIR in sys.path:
        sys.path.remove(ADDITIONAL_DEPS_DIR)


bl_info = {
    "name": "blend1",
    "author": "polygoniq xyz s.r.o.",
    "version": (1, 0, 2),  # also bump version in register()
    "blender": (3, 3, 0),
    "location": "blend one tab in the sidebar of the 3D View window",
    "description": "Save Blender backup files to a different location than opened blend, with an easily accessible recall. Enhances cloud storage experience.",
    "category": "System",
}
telemetry = polib.get_telemetry("blend1")
telemetry.report_addon(bl_info, __file__)


ADDON_CLASSES: typing.List[typing.Type] = []


def autodetect_backup_path() -> str:
    return os.path.expanduser("~/blender_backups")


class ShowReleaseNotes(bpy.types.Operator):
    bl_idname = "blend1.show_release_notes"
    bl_label = "Show Release Notes"
    bl_description = "Show the release notes for the latest version of blend1"
    bl_options = {'REGISTER'}

    release_tag: bpy.props.StringProperty(
        name="Release Tag",
        default="",
    )

    def execute(self, context: bpy.types.Context):
        polib.ui_bpy.show_release_notes_popup(context, __package__, self.release_tag)
        return {'FINISHED'}


ADDON_CLASSES.append(ShowReleaseNotes)


@polib.log_helpers_bpy.logged_preferences
@addon_updater_ops.make_annotations
class Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    # Addon updater preferences.
    auto_check_update: bpy.props.BoolProperty(
        name="Auto-check for Update",
        description="If enabled, auto-check for updates using an interval",
        default=True,
    )

    updater_interval_months: bpy.props.IntProperty(
        name='Months', description="Number of months between checking for updates", default=0, min=0
    )

    updater_interval_days: bpy.props.IntProperty(
        name='Days',
        description="Number of days between checking for updates",
        default=7,
        min=0,
        max=31,
    )

    updater_interval_hours: bpy.props.IntProperty(
        name='Hours',
        description="Number of hours between checking for updates",
        default=0,
        min=0,
        max=23,
    )

    updater_interval_minutes: bpy.props.IntProperty(
        name='Minutes',
        description="Number of minutes between checking for updates",
        default=0,
        min=0,
        max=59,
    )

    backup_path: bpy.props.StringProperty(
        name="backup_path",
        subtype="DIR_PATH",
        default=autodetect_backup_path(),
        update=lambda self, context: polib.utils_bpy.absolutize_preferences_path(
            self, context, "backup_path"
        ),
        description="This is the directory where all the blend file backups are stored. "
        "User is responsible for keeping its size in check.",
    )

    save_versions: bpy.props.IntProperty(
        name="save_versions",
        default=1,
        min=1,
        max=256,
        description="The number of old versions to maintain. Similar to Blender's stock "
        "save versions property.",
    )

    hash_parent_directory: bpy.props.BoolProperty(
        name="hash_parent_directory",
        default=True,
        description="Put backups in a directory comprising of parent basename (e.g. MyProject) "
        "and a hash generated from the whole path. This avoids potential conflicts if you have "
        "blends of the same name in similarly named folders. It's recommended to enable this "
        "to lower the probability of file conflicts.",
    )

    def draw(self, context):
        row = self.layout.row()
        row.scale_y = 2
        row.scale_x = 2
        row.prop(self, "backup_path")

        row = self.layout.row()
        row.prop(self, "save_versions", text="Save Versions")
        row.prop(self, "hash_parent_directory", text="Hash Parent Directory")

        self.layout.separator()
        row = self.layout.row()
        row.operator(OpenBackupFolder.bl_idname, icon='FILE_FOLDER')
        row = self.layout.row()
        row.operator(PackLogs.bl_idname, icon='EXPERIMENTAL')

        self.layout.separator()
        row = self.layout.row()
        col = row.column()

        if bpy.app.version < (4, 2, 0) or (bpy.app.version >= (4, 2, 0) and bpy.app.online_access):
            self.draw_update_settings(context, col)

        polib.ui_bpy.draw_settings_footer(self.layout)

    def draw_update_settings(self, context: bpy.types.Context, layout: bpy.types.UILayout) -> None:
        col = layout.column()
        addon_updater_ops.update_settings_ui(self, context, col)
        split = col.split(factor=0.5)
        left_row = split.row()
        left_row.enabled = bool(addon_updater.Updater.update_ready)
        left_row.operator(
            ShowReleaseNotes.bl_idname, text="Latest Release Notes", icon='PRESET_NEW'
        ).release_tag = ""
        right_row = split.row()
        current_release_tag = polib.utils_bpy.get_release_tag_from_version(
            addon_updater.Updater.current_version
        )
        right_row.operator(
            ShowReleaseNotes.bl_idname, text="Current Release Notes", icon='PRESET'
        ).release_tag = current_release_tag


ADDON_CLASSES.append(Preferences)


@polib.log_helpers_bpy.logged_operator
class PackLogs(bpy.types.Operator):
    bl_idname = "blend1.pack_logs"
    bl_label = "Pack Logs"
    bl_description = "Archives polygoniq logs as zip file and opens its location"
    bl_options = {'REGISTER'}

    def execute(self, context):
        packed_logs_directory_path = polib.log_helpers_bpy.pack_logs(telemetry)
        polib.utils_bpy.xdg_open_file(packed_logs_directory_path)
        return {'FINISHED'}


ADDON_CLASSES.append(PackLogs)


def blend1_get_preferences(context):
    return context.preferences.addons[__package__].preferences


def generate_backup_directory_path(prefs, filepath: str) -> str:
    abspath = os.path.abspath(filepath)
    parent_dir = os.path.dirname(abspath)

    if prefs.hash_parent_directory:
        parent_of_parent = os.path.dirname(parent_dir)
        hashed_parent_of_parent = hashlib.sha1(parent_of_parent.encode("utf-8")).hexdigest()
        hashed_name = f"{os.path.basename(parent_dir)}_{hashed_parent_of_parent}"
        return os.path.join(prefs.backup_path, hashed_name)

    else:
        return os.path.join(prefs.backup_path, os.path.basename(parent_dir))


def get_suffix_from_backup_file(backup_basename: str, original_basename: str) -> int:
    assert len(backup_basename) > len(original_basename)
    assert backup_basename.startswith(original_basename)

    return int(backup_basename[len(original_basename) :])


def cycle_backups_in_directory(prefs, backup_directory: str, original_basename: str) -> None:
    assert os.path.basename(original_basename) == original_basename

    backup_files_to_cycle = glob.glob(os.path.join(backup_directory, f"{original_basename}*"))
    backups = {}
    for backup_file in backup_files_to_cycle:
        backup_basename = os.path.basename(backup_file)
        try:
            suffix = get_suffix_from_backup_file(backup_basename, original_basename)
            backups[suffix] = backup_basename

        except:
            logger.exception(f"Uncaught exception raised while cycling backups")

    for backup_nr in sorted(backups.keys(), reverse=True):
        new_backup_nr = backup_nr + 1
        old_backup_basename = backups[backup_nr]
        new_backup_basename = f"{original_basename}{new_backup_nr}"
        if new_backup_nr > prefs.save_versions:
            os.remove(os.path.join(backup_directory, old_backup_basename))
            continue

        os.rename(
            os.path.join(backup_directory, old_backup_basename),
            os.path.join(backup_directory, new_backup_basename),
        )

    assert not os.path.exists(os.path.join(backup_directory, f"{original_basename}1"))


@functools.lru_cache(maxsize=1)
def get_backup_versions_enum_items(context) -> typing.List[typing.Tuple[str, str, str]]:
    prefs = blend1_get_preferences(context)
    backup_directory_path = generate_backup_directory_path(prefs, bpy.data.filepath)
    original_basename = os.path.basename(bpy.data.filepath)

    backup_files = glob.glob(os.path.join(backup_directory_path, f"{original_basename}*"))
    backups = {}
    for backup_file in backup_files:
        backup_basename = os.path.basename(backup_file)
        try:
            suffix = get_suffix_from_backup_file(backup_basename, original_basename)
            backups[suffix] = backup_basename

        except Exception as e:
            logger.exception(f"Uncaught exception raised while generating backups' enum items")

    ret = []
    for backup_nr in sorted(backups.keys()):
        full_path = os.path.join(backup_directory_path, f"{original_basename}{backup_nr}")
        mtime = time.localtime(os.path.getmtime(full_path))
        str_mtime = time.strftime("%H:%M:%S %Y-%m-%d", mtime)
        ret.append(
            (full_path, f"blend{backup_nr} {str_mtime}", f"{full_path}, backup from {str_mtime}")
        )

    return ret


def recall_backup_by_full_path(backup_full_path: str) -> bool:
    # this is an elaborate hack to force blender to:
    # 1) recall the old version
    # 2) set bpy.data.filepath accordingly
    # 3) avoid overwriting whatever is currently saved at that path

    parent_dir = os.path.dirname(bpy.data.filepath)
    assert os.path.isdir(parent_dir)

    # we have to save the current blend so that we can move it back
    current_blend_backup_path_template = bpy.data.filepath + "_backup"
    suffix = 1
    while True:
        current_blend_backup_path = os.path.join(
            parent_dir, f"{current_blend_backup_path_template}{suffix}"
        )
        if not os.path.exists(current_blend_backup_path):
            break
        suffix += 1

    assert not os.path.exists(current_blend_backup_path)

    try:
        if os.path.exists(bpy.data.filepath):
            os.rename(bpy.data.filepath, current_blend_backup_path)
        assert not os.path.exists(bpy.data.filepath)
        shutil.copyfile(backup_full_path, bpy.data.filepath)
        assert os.path.exists(bpy.data.filepath)
        bpy.ops.wm.open_mainfile(filepath=bpy.data.filepath)
        os.remove(bpy.data.filepath)
        assert not os.path.exists(bpy.data.filepath)

        # TODO: Would be amazing to somehow set bpy.data.is_dirty to True
        # that way the user can press CTRL+S and overwrite current blend with
        # the recalled backup. Otherwise user has to make some change before
        # they can save :-(

    except Exception as e:
        logger.exception(f"Uncaught exception raised while recalling a backup")

    finally:
        # whatever happens we have to move the currently opened blend back
        if os.path.exists(current_blend_backup_path):
            os.rename(current_blend_backup_path, bpy.data.filepath)

    return True


@polib.log_helpers_bpy.logged_operator
class RecallBackupMultiple(bpy.types.Operator):
    bl_idname = "blend1.recall_backup_multiple"
    bl_label = "Recall Backup"
    bl_description = (
        "Replaces currently opened file with the selected backup. Does not change "
        "the original on disk. User has to CTRL+S after recalling to overwrite the "
        "blend file on disk!"
    )
    bl_options = {'REGISTER'}

    version: bpy.props.EnumProperty(
        name="Version",
        items=lambda self, context: get_backup_versions_enum_items(
            context,
        ),
    )

    def execute(self, context):
        if recall_backup_by_full_path(self.version):
            return {'FINISHED'}
        else:
            return {'CANCELLED'}

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text="This will replace your currently")
        col.label(text="opened file with chosen backup!")
        row = self.layout.row()
        row.alert = True
        row.label(text="Unsaved changes will be lost!", icon='ERROR')

        row = self.layout.row()
        row.prop(self, "version")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


ADDON_CLASSES.append(RecallBackupMultiple)


@polib.log_helpers_bpy.logged_operator
class RecallBackupSingle(bpy.types.Operator):
    bl_idname = "blend1.recall_backup_single"
    bl_label = "Recall Last Backup"
    bl_description = (
        "Replaces currently opened file with its last backup. Does not change "
        "the original on disk. User has to CTRL+S after recalling to overwrite the "
        "blend file on disk!"
    )
    bl_options = {'REGISTER'}

    def execute(self, context):
        backups = get_backup_versions_enum_items(context)
        if len(backups) != 1:
            return {'CANCELLED'}
        blend1_full_path = backups[0][0]

        if recall_backup_by_full_path(blend1_full_path):
            return {'FINISHED'}
        else:
            return {'CANCELLED'}

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text="This will replace your currently")
        col.label(text="opened file with chosen backup!")
        row = self.layout.row()
        row.alert = True
        row.label(text="Unsaved changes will be lost!", icon='ERROR')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


ADDON_CLASSES.append(RecallBackupSingle)


@polib.log_helpers_bpy.logged_operator
class ShowBackupFiles(bpy.types.Operator):
    bl_idname = "blend1.show_backup_files"
    bl_label = "Show Backup Files"
    bl_description = "Opens the folder where backups of the currently opened blend file are stored"
    bl_options = {'REGISTER'}

    def execute(self, context):
        prefs = blend1_get_preferences(context)
        backup_folder_path = generate_backup_directory_path(prefs, bpy.data.filepath)
        polib.utils_bpy.xdg_open_file(backup_folder_path)
        return {'FINISHED'}


ADDON_CLASSES.append(ShowBackupFiles)


@polib.log_helpers_bpy.logged_operator
class OpenBackupFolder(bpy.types.Operator):
    bl_idname = "blend1.open_backup_folder"
    bl_label = "Open Backup Folder"
    bl_description = "Opens the root backup folder where backups of all files are stored"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return os.path.isdir(blend1_get_preferences(context).backup_path)

    def execute(self, context):
        prefs = blend1_get_preferences(context)
        polib.utils_bpy.xdg_open_file(prefs.backup_path)

        return {'FINISHED'}


ADDON_CLASSES.append(OpenBackupFolder)


@polib.log_helpers_bpy.logged_panel
class BlendOnePanel(bpy.types.Panel):
    bl_idname = "VIEW_3D_PT_blend1"
    bl_label = str(bl_info.get("name", "blend1")).replace("_", " ")
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_context = "objectmode"
    bl_category = "polygoniq"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 200

    def draw_header(self, context: bpy.types.Context):
        self.layout.label(
            text="", icon_value=polib.ui_bpy.icon_manager.get_polygoniq_addon_icon_id("blend1")
        )

    def draw(self, context):
        row = self.layout.row()
        row.prop(blend1_get_preferences(context), "save_versions", text="Save Versions")

        row = self.layout.row()
        backups = get_backup_versions_enum_items(context)
        if bpy.data.filepath != "":
            row.label(text="Opened File:")
            row = self.layout.row()
            row.label(text=bpy.data.filepath)
        else:
            row.label(text="No file opened!")

        row = self.layout.row()

        if len(backups) > 0:
            row.label(text=f"Available backups: {len(backups)}")
            box = self.layout.box()
            backups = get_backup_versions_enum_items(context)
            for _, label, _ in backups:
                box.label(text=label)

            row = self.layout.row()
            if len(backups) > 1:
                row.operator(RecallBackupMultiple.bl_idname, icon='FILE_BACKUP')
            elif len(backups) == 1:
                row.operator(RecallBackupSingle.bl_idname, icon='FILE_BACKUP')

            row = self.layout.row()
            row.operator(ShowBackupFiles.bl_idname, icon='FILE')

        else:
            row.label(text="No backups available!")

        row = self.layout.row()
        row.operator(OpenBackupFolder.bl_idname, icon='FILE_FOLDER')


ADDON_CLASSES.append(BlendOnePanel)


@bpy.app.handlers.persistent
def external_save_pre_handler(_):
    try:
        # auto disable the Blender inbuilt save versions
        bpy.context.preferences.filepaths.save_version = 0

        if not bpy.data.filepath:
            # this was the first save of that file, there are no backups
            return

        if not os.path.isfile(bpy.data.filepath):
            # Hmm, blender thinks there should be a file at that path but
            # for some reason it doesn't exist. We can't backup a non-existent file
            logger.warning(
                f"bpy.data.filepath={bpy.data.filepath} does not exist while saving data!"
                f"Can't backup a non-existent file... Skipping the backup!"
            )
            return

        prefs = blend1_get_preferences(bpy.context)
        backup_directory_path = generate_backup_directory_path(prefs, bpy.data.filepath)
        os.makedirs(backup_directory_path, exist_ok=True)
        original_basename = os.path.basename(bpy.data.filepath)
        cycle_backups_in_directory(prefs, backup_directory_path, original_basename)
        # We would strongly prefer to move/rename instead of copy but we don't know if the user
        # wants to "save as" or just "save". This is very hard to get from bpy so we have to
        # copyfile :-(
        shutil.copyfile(
            bpy.data.filepath, os.path.join(backup_directory_path, f"{original_basename}1")
        )

    except:
        logger.exception(f"Uncaught exception raised while saving blend file")

    finally:
        get_backup_versions_enum_items.cache_clear()


@bpy.app.handlers.persistent
def external_load_post_handler(_):
    # new file has been loaded, clear the backups available cache
    get_backup_versions_enum_items.cache_clear()


def register():
    # We pass mock "bl_info" to the updater, since Blender 4.2.0 the "bl_info" is no longer
    # available in this scope.
    addon_updater_ops.register({"version": (1, 0, 2)})

    for cls in ADDON_CLASSES:
        bpy.utils.register_class(cls)

    bpy.app.handlers.save_pre.append(external_save_pre_handler)
    bpy.app.handlers.load_post.append(external_load_post_handler)


def unregister():
    bpy.app.handlers.load_post.remove(external_load_post_handler)
    bpy.app.handlers.save_pre.remove(external_save_pre_handler)

    for cls in reversed(ADDON_CLASSES):
        bpy.utils.unregister_class(cls)

    # Remove all nested modules from module cache, more reliable than importlib.reload(..)
    # Idea by BD3D / Jacques Lucke
    for module_name in list(sys.modules.keys()):
        if module_name.startswith(__package__):
            del sys.modules[module_name]

    addon_updater_ops.unregister()

    # We clear the master 'polib' icon manager to prevent ResourceWarning and leaks.
    # If other addon uses the icon_manager, the previews will be reloaded on demand.
    polib.ui_bpy.icon_manager.clear()
