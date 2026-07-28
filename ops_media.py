"""User-facing media, dependency, cache, and pagination operators."""

from __future__ import annotations

import re
from pathlib import Path

import bpy
from bpy.props import CollectionProperty, IntProperty, StringProperty
from bpy.types import OperatorFileListElement

from . import ffmpeg_bridge


def _set_status(context, message: str, level: str = "INFO") -> None:
    wm = getattr(context, "window_manager", None)
    if wm is not None:
        wm.animthumb_status = str(message or "")
        wm.animthumb_status_level = str(level or "INFO").upper()
    from . import preview_engine

    preview_engine.tag_targeted_layout_refresh()


def _online_access_allowed() -> bool:
    return bool(getattr(bpy.app, "online_access", True))


def _natural_key(path: Path) -> tuple:
    return tuple(
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", path.name)
    )


class ANIMTHUMB_OT_InstallFFmpeg(bpy.types.Operator):
    bl_idname = "animthumb.install_ffmpeg"
    bl_label = "Install FFmpeg Wheel"
    bl_description = (
        "Install the platform-specific imageio-ffmpeg wheel into this "
        "extension's persistent user storage"
    )
    bl_options = {"REGISTER"}

    def execute(self, context):
        if not _online_access_allowed():
            message = "Enable Online Access in Preferences before installing FFmpeg"
            _set_status(context, message, "ERROR")
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        _set_status(context, "Installing the platform FFmpeg wheel…")
        success, detail = ffmpeg_bridge.install_wheel()
        ffmpeg_bridge.refresh_status()
        if not success:
            _set_status(context, detail, "ERROR")
            self.report({"ERROR"}, "FFmpeg wheel installation failed")
            return {"CANCELLED"}
        _set_status(context, detail)
        self.report({"INFO"}, "FFmpeg wheel installed")
        return {"FINISHED"}


class ANIMTHUMB_OT_IngestMedia(bpy.types.Operator):
    bl_idname = "animthumb.ingest_media"
    bl_label = "Add Animated Media"
    bl_description = (
        "Select a GIF, APNG, image, video, or multiple ordered image files "
        "and build an optimized animated thumbnail cache"
    )
    bl_options = {"REGISTER"}

    filepath: StringProperty(subtype="FILE_PATH")
    directory: StringProperty(subtype="DIR_PATH")
    files: CollectionProperty(type=OperatorFileListElement)
    filter_glob: StringProperty(
        default=(
            "*.gif;*.apng;*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.tif;*.tiff;"
            "*.mp4;*.mov;*.m4v;*.avi;*.mkv;*.webm;*.mpeg;*.mpg;*.wmv;*.flv"
        ),
        options={"HIDDEN"},
    )

    def invoke(self, context, event):
        del event
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        selected = [
            Path(self.directory) / entry.name
            for entry in self.files
            if str(entry.name or "")
        ]
        if not selected and self.filepath:
            selected = [Path(self.filepath)]
        selected.sort(key=_natural_key)
        if not selected:
            self.report({"ERROR"}, "No media was selected")
            return {"CANCELLED"}

        dependency_status = ffmpeg_bridge.status()
        if not dependency_status.get("ready"):
            if not _online_access_allowed():
                message = "FFmpeg is unavailable and Blender Online Access is disabled"
                _set_status(context, message, "ERROR")
                self.report({"ERROR"}, message)
                return {"CANCELLED"}
            _set_status(context, "Preparing the platform FFmpeg wheel…")
            success, detail = ffmpeg_bridge.install_wheel()
            dependency_status = ffmpeg_bridge.refresh_status()
            if not success or not dependency_status.get("ready"):
                _set_status(context, detail, "ERROR")
                self.report({"ERROR"}, "FFmpeg could not be prepared")
                return {"CANCELLED"}

        _set_status(context, f"Converting {len(selected)} selected media file(s)…")
        try:
            from .media_ingest import ingest_media

            result = ingest_media(
                str(dependency_status.get("executable", "") or ""),
                selected,
            )
        except Exception as error:
            _set_status(context, str(error), "ERROR")
            self.report({"ERROR"}, f"Animated media conversion failed: {error}")
            return {"CANCELLED"}

        from . import library

        library.refresh_all_scenes()
        _set_status(
            context,
            (
                f"Added {result['name']}: {result['frame_count']} cached frames, "
                f"{result['duration_ms']} ms"
            ),
        )
        self.report({"INFO"}, f"Added animated thumbnail: {result['name']}")
        return {"FINISHED"}


class ANIMTHUMB_OT_RefreshLibrary(bpy.types.Operator):
    bl_idname = "animthumb.refresh_library"
    bl_label = "Refresh Animated Thumbnail Library"
    bl_description = "Rescan persistent thumbnail caches and reload preview icons"
    bl_options = {"REGISTER"}

    def execute(self, context):
        from . import library

        count = library.refresh_all_scenes()
        _set_status(context, f"Loaded {count} animated thumbnail cache(s)")
        return {"FINISHED"}


class ANIMTHUMB_OT_DeleteItem(bpy.types.Operator):
    bl_idname = "animthumb.delete_item"
    bl_label = "Delete Animated Thumbnail"
    bl_description = "Delete this generated thumbnail cache from extension storage"
    bl_options = {"REGISTER"}

    item_id: StringProperty(options={"HIDDEN"})

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        from . import library

        if not library.remove_item(self.item_id):
            self.report({"ERROR"}, "Animated thumbnail cache was not found")
            return {"CANCELLED"}
        _set_status(context, "Deleted animated thumbnail cache")
        return {"FINISHED"}


class ANIMTHUMB_OT_SetGalleryPage(bpy.types.Operator):
    bl_idname = "animthumb.set_gallery_page"
    bl_label = "Set Animated Thumbnail Page"
    bl_options = {"INTERNAL"}

    page: IntProperty(default=0, min=0)

    def execute(self, context):
        context.scene.animthumb_gallery_page = max(0, int(self.page))
        from . import preview_engine

        preview_engine.tag_targeted_layout_refresh()
        return {"FINISHED"}
