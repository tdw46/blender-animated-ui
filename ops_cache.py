"""Thumbnail library, cache-folder, item-menu, and deletion operators."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import bpy
from bpy.props import StringProperty

from .utils import find_scene_item, invoke_props_dialog_compat, set_status


class ANIMTHUMB_OT_RefreshLibrary(bpy.types.Operator):
    bl_idname = "animthumb.refresh_library"
    bl_label = "Refresh Animated Thumbnail Library"
    bl_description = "Rescan persistent thumbnail caches and reload preview icons"
    bl_options = {"REGISTER"}

    def execute(self, context):
        from . import library

        count = library.refresh_all_scenes()
        set_status(context, f"Loaded {count} animated thumbnail cache(s)")
        return {"FINISHED"}


class ANIMTHUMB_OT_OpenItemActions(bpy.types.Operator):
    bl_idname = "animthumb.open_item_actions"
    bl_label = "Animated Thumbnail Actions"
    bl_description = (
        "Show refresh, rename, cache-folder, and delete actions for this thumbnail"
    )
    bl_options = {"REGISTER"}

    item_id: StringProperty(options={"HIDDEN"})

    def execute(self, context):
        item = find_scene_item(context.scene, self.item_id)
        if item is None:
            self.report({"ERROR"}, "Animated thumbnail cache was not found")
            return {"CANCELLED"}
        item_id = self.item_id

        def draw_actions(menu, _menu_context):
            refresh_row = menu.layout.row()
            refresh_row.operator_context = "INVOKE_DEFAULT"
            refresh = refresh_row.operator(
                "animthumb.refresh_item",
                text="Refresh with New FPS Settings",
                icon="FILE_REFRESH",
            )
            refresh.item_id = item_id
            rename_row = menu.layout.row()
            rename_row.operator_context = "INVOKE_DEFAULT"
            rename = rename_row.operator(
                "animthumb.rename_item",
                text="Rename Thumbnail",
                icon="GREASEPENCIL",
            )
            rename.item_id = item_id
            open_directory = menu.layout.operator(
                "animthumb.open_cache_directory",
                text="Open Thumbnail Cache Directory",
                icon="FILE_FOLDER",
            )
            open_directory.item_id = item_id
            menu.layout.separator()
            delete_row = menu.layout.row()
            delete_row.operator_context = "INVOKE_DEFAULT"
            delete = delete_row.operator(
                "animthumb.delete_item",
                text="Delete Thumbnail",
                icon="TRASH",
            )
            delete.item_id = item_id

        context.window_manager.popup_menu(
            draw_actions,
            title=str(item.name or "Animated Thumbnail"),
            icon="IMAGE_DATA",
        )
        return {"FINISHED"}


class ANIMTHUMB_OT_RenameItem(bpy.types.Operator):
    bl_idname = "animthumb.rename_item"
    bl_label = "Rename Animated Thumbnail"
    bl_description = "Change the imported display name without rebuilding the cache"
    bl_options = {"REGISTER"}

    item_id: StringProperty(options={"HIDDEN"})
    new_name: StringProperty(
        name="Imported Name",
        description="Name shown for this media in the animated gallery",
    )

    def invoke(self, context, event):
        del event
        item = find_scene_item(context.scene, self.item_id)
        if item is None:
            self.report({"ERROR"}, "Animated thumbnail cache was not found")
            return {"CANCELLED"}
        self.new_name = str(item.name or "")
        return invoke_props_dialog_compat(
            context,
            self,
            width=360,
            title="Rename Animated Thumbnail",
            confirm_text="Rename Thumbnail",
        )

    def draw(self, _context):
        self.layout.prop(self, "new_name", text="Imported Name")

    def execute(self, context):
        resolved_name = str(self.new_name or "").strip()
        if not resolved_name:
            self.report({"ERROR"}, "Imported name cannot be empty")
            return {"CANCELLED"}
        from . import library

        try:
            renamed = library.rename_item(self.item_id, resolved_name)
        except (OSError, ValueError) as error:
            self.report({"ERROR"}, f"Could not rename thumbnail: {error}")
            return {"CANCELLED"}
        if not renamed:
            self.report({"ERROR"}, "Animated thumbnail cache was not found")
            return {"CANCELLED"}
        set_status(context, f"Renamed animated thumbnail to {resolved_name}")
        self.report({"INFO"}, f"Renamed animated thumbnail to {resolved_name}")
        return {"FINISHED"}


class ANIMTHUMB_OT_OpenCacheDirectory(bpy.types.Operator):
    bl_idname = "animthumb.open_cache_directory"
    bl_label = "Open Thumbnail Cache Directory"
    bl_description = (
        "Open this thumbnail's cache directory, or the active cache root when no "
        "thumbnail is specified"
    )
    bl_options = {"REGISTER"}

    item_id: StringProperty(options={"HIDDEN"})

    def execute(self, context):
        if self.item_id:
            item = find_scene_item(context.scene, self.item_id)
            if item is None:
                self.report({"ERROR"}, "Animated thumbnail cache was not found")
                return {"CANCELLED"}
            path = Path(str(item.cache_dir)).expanduser().resolve()
        else:
            from .paths import cache_root

            path = cache_root()
        if not path.is_dir():
            self.report({"ERROR"}, f"Thumbnail cache directory does not exist: {path}")
            return {"CANCELLED"}

        path_open = getattr(getattr(bpy.ops, "wm", None), "path_open", None)
        if path_open is not None:
            try:
                result = set(path_open(filepath=str(path)))
                if "FINISHED" in result:
                    return {"FINISHED"}
            except (AttributeError, RuntimeError, TypeError):
                pass
        try:
            if sys.platform == "win32":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(
                    ["open", str(path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                subprocess.Popen(
                    ["xdg-open", str(path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except (OSError, ValueError) as error:
            self.report({"ERROR"}, f"Could not open thumbnail cache: {error}")
            return {"CANCELLED"}
        return {"FINISHED"}


class ANIMTHUMB_OT_DeleteItem(bpy.types.Operator):
    bl_idname = "animthumb.delete_item"
    bl_label = "Delete Animated Thumbnail"
    bl_description = "Delete this generated thumbnail cache from extension storage"
    bl_options = {"REGISTER"}

    item_id: StringProperty(options={"HIDDEN"})

    def invoke(self, context, event):
        invoke_confirm = context.window_manager.invoke_confirm
        try:
            return invoke_confirm(
                self,
                event,
                title="Delete Animated Thumbnail",
                message="Delete this generated thumbnail cache from disk?",
                confirm_text="Delete Thumbnail",
                icon="WARNING",
            )
        except TypeError:
            return invoke_confirm(self, event)

    def execute(self, context):
        from . import library

        if not library.remove_item(self.item_id):
            self.report({"ERROR"}, "Animated thumbnail cache was not found")
            return {"CANCELLED"}
        set_status(context, "Deleted animated thumbnail cache")
        return {"FINISHED"}
