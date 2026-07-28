"""User-facing media, dependency, cache, and pagination operators."""

from __future__ import annotations

import math
import os
import subprocess
import sys
from pathlib import Path

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import OperatorFileListElement

from . import ffmpeg_bridge
from .constants import (
    CACHE_FRAME_WARNING_THRESHOLD,
    MAX_PREVIEW_FPS,
    MIN_PREVIEW_FPS,
)
from .media_selection import (
    DEFAULT_SEQUENCE_ORDER,
    SEQUENCE_ORDER_ITEMS,
    order_sequence_paths,
)


def _set_status(context, message: str, level: str = "INFO") -> None:
    wm = getattr(context, "window_manager", None)
    if wm is not None:
        wm.animthumb_status = str(message or "")
        wm.animthumb_status_level = str(level or "INFO").upper()
    from . import preview_engine

    preview_engine.tag_targeted_layout_refresh()


def _online_access_allowed() -> bool:
    return bool(getattr(bpy.app, "online_access", True))


def _selected_media_paths(operator) -> tuple[Path, ...]:
    selected = tuple(
        Path(str(operator.directory or "")) / entry.name
        for entry in operator.files
        if str(entry.name or "")
    )
    if not selected and str(operator.filepath or ""):
        selected = (Path(operator.filepath),)
    return tuple(path.expanduser().resolve() for path in selected)


def _find_scene_item(scene, item_id: str):
    for item in getattr(scene, "animthumb_items", ()):
        if str(getattr(item, "item_id", "") or "") == str(item_id):
            return item
    return None


def _invoke_props_dialog_compat(
    context,
    operator,
    *,
    width: int,
    title: str,
    confirm_text: str,
):
    invoke_props_dialog = context.window_manager.invoke_props_dialog
    try:
        return invoke_props_dialog(
            operator,
            width=width,
            title=title,
            confirm_text=confirm_text,
        )
    except TypeError:
        try:
            return invoke_props_dialog(operator, width=width)
        except TypeError:
            return invoke_props_dialog(operator)


def _prepare_ffmpeg(context, operator) -> dict | None:
    dependency_status = ffmpeg_bridge.status()
    if dependency_status.get("ready"):
        return dependency_status
    if not _online_access_allowed():
        message = "FFmpeg is unavailable and Blender Online Access is disabled"
        _set_status(context, message, "ERROR")
        operator.report({"ERROR"}, message)
        return None
    _set_status(context, "Preparing the platform FFmpeg wheel…")
    success, detail = ffmpeg_bridge.install_wheel()
    dependency_status = ffmpeg_bridge.refresh_status()
    if not success or not dependency_status.get("ready"):
        _set_status(context, detail, "ERROR")
        operator.report({"ERROR"}, "FFmpeg could not be prepared")
        return None
    return dependency_status


def _expected_sample_fps(operator) -> float:
    from .frame_rate import target_sample_fps

    return target_sample_fps(
        float(getattr(operator, "analysis_duration_seconds", 0.0) or 0.0),
        int(getattr(operator, "target_fps", MAX_PREVIEW_FPS) or MAX_PREVIEW_FPS),
        1,
        source_fps=float(getattr(operator, "analysis_source_fps", 0.0) or 0.0),
    )


def _selected_frame_count(operator, full_frame_count: int) -> int:
    count = max(0, int(full_frame_count))
    if count <= 0 or not bool(getattr(operator, "trim_media", False)):
        return count
    start_frame = min(count, max(1, int(operator.trim_start_frame)))
    requested_end = int(operator.trim_end_frame)
    end_frame = count if requested_end <= 0 else min(count, requested_end)
    return max(0, end_frame - start_frame + 1)


def _draw_trim_settings(settings_box, operator, full_frame_count: int) -> None:
    settings_box.separator(factor=0.5)
    settings_box.prop(operator, "trim_media", text="Trim Media")
    trim_column = settings_box.column(align=True)
    trim_column.enabled = bool(operator.trim_media)
    trim_column.prop(operator, "trim_start_frame", text="Begin Frame")
    end_label = "End Frame"
    if int(operator.trim_end_frame) <= 0 and full_frame_count <= 0:
        end_label = "End Frame (0 = Media End)"
    trim_column.prop(operator, "trim_end_frame", text=end_label)
    if not operator.trim_media:
        settings_box.label(
            text="Full source range will be cached",
            icon="CHECKMARK",
        )


def _draw_cache_size_warning(settings_box, estimated_frames: int) -> None:
    if estimated_frames <= CACHE_FRAME_WARNING_THRESHOLD:
        return
    warning = settings_box.row()
    warning.alert = True
    warning.label(
        text=(
            f"Large cache: about {estimated_frames:,} frames. "
            "Lower FPS or enable Trim Media if desired."
        ),
        icon="ERROR",
    )


def _draw_media_settings(layout, context, operator, paths: tuple[Path, ...]) -> None:
    is_sequence = len(paths) > 1 or bool(
        getattr(operator, "analysis_is_sequence", False)
    )
    settings_box = layout.box()
    if is_sequence:
        count = int(getattr(operator, "analysis_selection_count", 0) or 0)
        if count <= 0:
            count = len(paths)
        settings_box.label(
            text=f"Image Sequence · {count} selected", icon="SEQ_STRIP_META"
        )
        settings_box.prop(operator, "target_fps", text="Playback FPS", slider=True)
        settings_box.prop(operator, "sequence_order", text="Frame Order")
        full_frame_count = max(
            count,
            int(getattr(operator, "analysis_total_frames", 0) or 0),
        )
        _draw_trim_settings(settings_box, operator, full_frame_count)
        cached_frames = _selected_frame_count(operator, full_frame_count)
        duration = (
            cached_frames / max(1.0, float(operator.target_fps))
            if cached_frames
            else 0.0
        )
        settings_box.label(
            text=f"Expected cache: {cached_frames} frames · {duration:.2f} seconds",
            icon="INFO",
        )
        _draw_cache_size_warning(settings_box, cached_frames)
    else:
        settings_box.label(text="Selected Media Analysis", icon="FILE_MOVIE")
        if paths:
            settings_box.label(text=paths[0].name, icon="FILE")
        source_fps = float(getattr(operator, "analysis_source_fps", 0.0) or 0.0)
        duration = float(getattr(operator, "analysis_duration_seconds", 0.0) or 0.0)
        if source_fps > 0.0:
            settings_box.label(text=f"Native frame rate: {source_fps:.3f} FPS")
        else:
            message = str(
                getattr(operator, "analysis_message", "") or "Select media to analyze"
            )
            settings_box.label(text=message, icon="INFO")
        if duration > 0.0:
            settings_box.label(text=f"Source duration: {duration:.2f} seconds")
        settings_box.prop(
            operator,
            "target_fps",
            text="Import FPS Ceiling",
            slider=True,
        )
        sample_fps = _expected_sample_fps(operator)
        full_frame_count = max(
            0,
            int(getattr(operator, "analysis_total_frames", 0) or 0),
        )
        _draw_trim_settings(settings_box, operator, full_frame_count)
        selected_frames = _selected_frame_count(operator, full_frame_count)
        if operator.trim_media and source_fps > 0.0 and selected_frames > 0:
            selected_duration = selected_frames / source_fps
        else:
            selected_duration = duration
        estimated_frames = (
            max(1, int(math.ceil(selected_duration * sample_fps)))
            if selected_duration > 0.0
            else 1
        )
        preview_seconds = (
            estimated_frames / sample_fps
            if estimated_frames > 1 and sample_fps > 0.0
            else 0.0
        )
        settings_box.label(
            text=f"Expected import rate: {sample_fps:.3f} FPS",
            icon="TIME",
        )
        if preview_seconds > 0.0:
            settings_box.label(
                text=(
                    f"Expected cache: {estimated_frames} frames · "
                    f"{preview_seconds:.2f} seconds"
                ),
                icon="INFO",
            )
        _draw_cache_size_warning(settings_box, estimated_frames)
    live_limit = int(getattr(context.window_manager, "animthumb_preview_fps", 10) or 10)
    settings_box.separator(factor=0.5)
    settings_box.label(
        text=f"Current gallery playback ceiling: {live_limit} FPS",
        icon="PLAY",
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
    target_fps: IntProperty(
        name="Import FPS Ceiling",
        description=(
            "Maximum cache sampling rate; encoded media remains capped by its "
            "native frame rate"
        ),
        default=MAX_PREVIEW_FPS,
        min=MIN_PREVIEW_FPS,
        max=MAX_PREVIEW_FPS,
        soft_min=MIN_PREVIEW_FPS,
        soft_max=MAX_PREVIEW_FPS,
    )
    sequence_order: EnumProperty(
        name="Sequence Order",
        description="How selected image files are ordered into playback frames",
        items=SEQUENCE_ORDER_ITEMS,
        default=DEFAULT_SEQUENCE_ORDER,
    )
    trim_media: BoolProperty(
        name="Trim Media",
        description=(
            "Cache only the selected frame range; disabled always preserves the "
            "full source range"
        ),
        default=False,
    )
    trim_start_frame: IntProperty(
        name="Begin Frame",
        description="First source frame to include (1-based and inclusive)",
        default=1,
        min=1,
    )
    trim_end_frame: IntProperty(
        name="End Frame",
        description="Last source frame to include (inclusive); 0 uses the media end",
        default=0,
        min=0,
    )
    analysis_signature: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    analysis_message: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    analysis_source_fps: FloatProperty(options={"HIDDEN", "SKIP_SAVE"}, min=0.0)
    analysis_duration_seconds: FloatProperty(
        options={"HIDDEN", "SKIP_SAVE"},
        min=0.0,
    )
    analysis_selection_count: IntProperty(
        options={"HIDDEN", "SKIP_SAVE"},
        min=0,
    )
    analysis_total_frames: IntProperty(
        options={"HIDDEN", "SKIP_SAVE"},
        min=0,
    )
    analysis_is_sequence: BoolProperty(options={"HIDDEN", "SKIP_SAVE"})
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

    def _refresh_analysis(self, context) -> None:
        paths = _selected_media_paths(self)
        signature = "\n".join(str(path) for path in paths)
        if signature == self.analysis_signature:
            return
        self.analysis_signature = signature
        self.analysis_selection_count = len(paths)
        self.analysis_is_sequence = len(paths) > 1
        self.analysis_source_fps = 0.0
        self.analysis_duration_seconds = 0.0
        self.analysis_total_frames = 0
        self.analysis_message = ""
        if not paths:
            self.analysis_message = "Select a file to analyze"
            return
        if len(paths) > 1:
            self.analysis_total_frames = len(paths)
            self.trim_start_frame = 1
            self.trim_end_frame = len(paths)
            self.analysis_message = "Image sequences use the selected playback FPS"
            return
        dependency_status = ffmpeg_bridge.status()
        executable = str(dependency_status.get("executable", "") or "")
        if not executable:
            self.analysis_message = "FFmpeg will be prepared when the media is added"
            return
        try:
            from .media_ingest import probe_media

            probe = probe_media(executable, paths[0])
            self.analysis_source_fps = max(0.0, float(probe.source_fps))
            self.analysis_duration_seconds = max(
                0.0,
                float(probe.duration_seconds),
            )
            if self.analysis_source_fps > 0.0 and self.analysis_duration_seconds > 0.0:
                self.analysis_total_frames = max(
                    1,
                    int(
                        round(self.analysis_source_fps * self.analysis_duration_seconds)
                    ),
                )
            else:
                self.analysis_total_frames = 1
            self.trim_start_frame = 1
            self.trim_end_frame = self.analysis_total_frames
            if self.analysis_source_fps <= 0.0:
                self.analysis_message = "Still image or native FPS unavailable"
        except Exception as error:
            self.analysis_message = f"Media analysis unavailable: {error}"

    def check(self, context):
        self._refresh_analysis(context)
        return False

    def draw(self, context):
        self._refresh_analysis(context)
        _draw_media_settings(
            self.layout,
            context,
            self,
            _selected_media_paths(self),
        )

    def execute(self, context):
        selected = _selected_media_paths(self)
        if not selected:
            self.report({"ERROR"}, "No media was selected")
            return {"CANCELLED"}
        if len(selected) > 1:
            selected = order_sequence_paths(selected, self.sequence_order)

        dependency_status = _prepare_ffmpeg(context, self)
        if dependency_status is None:
            return {"CANCELLED"}

        _set_status(context, f"Converting {len(selected)} selected media file(s)…")
        try:
            from .media_ingest import ingest_media

            result = ingest_media(
                str(dependency_status.get("executable", "") or ""),
                selected,
                target_fps=int(self.target_fps),
                sequence_order=self.sequence_order,
                trim_media=bool(self.trim_media),
                trim_start_frame=int(self.trim_start_frame),
                trim_end_frame=int(self.trim_end_frame),
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
                f"Added {result['name']}: {result['frame_count']} cached frames "
                f"at {float(result['effective_fps']):.2f} FPS, "
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


class ANIMTHUMB_OT_RefreshItem(bpy.types.Operator):
    bl_idname = "animthumb.refresh_item"
    bl_label = "Refresh with New FPS Settings"
    bl_description = (
        "Rebuild this thumbnail cache from its original media with new settings"
    )
    bl_options = {"REGISTER"}

    item_id: StringProperty(options={"HIDDEN"})
    source_path: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    item_name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    target_fps: IntProperty(
        name="Import FPS Ceiling",
        description=(
            "Maximum cache sampling rate; encoded media remains capped by its "
            "native frame rate"
        ),
        default=MAX_PREVIEW_FPS,
        min=MIN_PREVIEW_FPS,
        max=MAX_PREVIEW_FPS,
        soft_min=MIN_PREVIEW_FPS,
        soft_max=MAX_PREVIEW_FPS,
    )
    sequence_order: EnumProperty(
        name="Sequence Order",
        description="How selected image files are ordered into playback frames",
        items=SEQUENCE_ORDER_ITEMS,
        default=DEFAULT_SEQUENCE_ORDER,
    )
    trim_media: BoolProperty(
        name="Trim Media",
        description=(
            "Cache only the selected frame range; disabled always preserves the "
            "full source range"
        ),
        default=False,
    )
    trim_start_frame: IntProperty(
        name="Begin Frame",
        description="First source frame to include (1-based and inclusive)",
        default=1,
        min=1,
    )
    trim_end_frame: IntProperty(
        name="End Frame",
        description="Last source frame to include (inclusive); 0 uses the media end",
        default=0,
        min=0,
    )
    analysis_message: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    analysis_source_fps: FloatProperty(options={"HIDDEN", "SKIP_SAVE"}, min=0.0)
    analysis_duration_seconds: FloatProperty(
        options={"HIDDEN", "SKIP_SAVE"},
        min=0.0,
    )
    analysis_selection_count: IntProperty(
        options={"HIDDEN", "SKIP_SAVE"},
        min=0,
    )
    analysis_total_frames: IntProperty(
        options={"HIDDEN", "SKIP_SAVE"},
        min=0,
    )
    analysis_is_sequence: BoolProperty(options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        del event
        item = _find_scene_item(context.scene, self.item_id)
        if item is None:
            self.report({"ERROR"}, "Animated thumbnail cache was not found")
            return {"CANCELLED"}
        try:
            from .cache_format import read_metadata

            metadata = read_metadata(str(item.cache_dir))
        except Exception as error:
            self.report({"ERROR"}, f"Could not read thumbnail settings: {error}")
            return {"CANCELLED"}
        source_paths = tuple(
            Path(path).expanduser().resolve()
            for path in metadata.get("source_paths", ())
        )
        if not source_paths:
            self.report({"ERROR"}, "Original media paths are unavailable")
            return {"CANCELLED"}
        self.source_path = str(source_paths[0])
        self.item_name = str(metadata.get("name", "") or item.name)
        self.target_fps = int(
            round(
                float(
                    metadata.get("target_fps", 0.0)
                    or metadata.get("sample_fps", 0.0)
                    or MAX_PREVIEW_FPS
                )
            )
        )
        self.sequence_order = str(
            metadata.get("sequence_order", DEFAULT_SEQUENCE_ORDER)
            or DEFAULT_SEQUENCE_ORDER
        )
        self.analysis_source_fps = max(
            0.0,
            float(metadata.get("source_fps", 0.0) or 0.0),
        )
        self.analysis_duration_seconds = max(
            0.0,
            float(metadata.get("source_duration_ms", 0) or 0) / 1000.0,
        )
        self.analysis_selection_count = len(source_paths)
        self.analysis_is_sequence = len(source_paths) > 1
        if self.analysis_is_sequence:
            self.analysis_total_frames = len(source_paths)
        elif self.analysis_source_fps > 0.0 and self.analysis_duration_seconds > 0.0:
            self.analysis_total_frames = max(
                1,
                int(round(self.analysis_source_fps * self.analysis_duration_seconds)),
            )
        else:
            self.analysis_total_frames = 1
        self.trim_media = bool(metadata.get("trim_media", False))
        self.trim_start_frame = max(
            1,
            int(metadata.get("trim_start_frame", 1) or 1),
        )
        self.trim_end_frame = max(
            0,
            int(metadata.get("trim_end_frame", 0) or self.analysis_total_frames),
        )
        self.analysis_message = (
            "Image sequences use the selected playback FPS"
            if self.analysis_is_sequence
            else ""
        )
        return _invoke_props_dialog_compat(
            context,
            self,
            width=440,
            title=f"Refresh {self.item_name}",
            confirm_text="Rebuild Preview",
        )

    def draw(self, context):
        paths = (Path(self.source_path),) if self.source_path else ()
        _draw_media_settings(self.layout, context, self, paths)

    def execute(self, context):
        item = _find_scene_item(context.scene, self.item_id)
        if item is None:
            self.report({"ERROR"}, "Animated thumbnail cache was not found")
            return {"CANCELLED"}
        try:
            from .cache_format import read_metadata

            metadata = read_metadata(str(item.cache_dir))
            source_paths = tuple(
                Path(path).expanduser().resolve()
                for path in metadata.get("source_paths", ())
            )
        except Exception as error:
            self.report({"ERROR"}, f"Could not read thumbnail settings: {error}")
            return {"CANCELLED"}
        missing = tuple(path for path in source_paths if not path.is_file())
        if missing:
            self.report({"ERROR"}, f"Original media is missing: {missing[0]}")
            return {"CANCELLED"}
        if len(source_paths) > 1:
            source_paths = order_sequence_paths(source_paths, self.sequence_order)
        dependency_status = _prepare_ffmpeg(context, self)
        if dependency_status is None:
            return {"CANCELLED"}
        _set_status(context, f"Rebuilding {item.name}…")
        try:
            from .media_ingest import ingest_media

            result = ingest_media(
                str(dependency_status.get("executable", "") or ""),
                source_paths,
                display_name=str(metadata.get("name", "") or item.name),
                target_fps=int(self.target_fps),
                cache_item_id=self.item_id,
                sequence_order=self.sequence_order,
                trim_media=bool(self.trim_media),
                trim_start_frame=int(self.trim_start_frame),
                trim_end_frame=int(self.trim_end_frame),
            )
        except Exception as error:
            _set_status(context, str(error), "ERROR")
            self.report({"ERROR"}, f"Thumbnail rebuild failed: {error}")
            return {"CANCELLED"}
        from . import library

        library.refresh_all_scenes()
        _set_status(
            context,
            (
                f"Rebuilt {result['name']}: {result['frame_count']} frames at "
                f"{float(result['effective_fps']):.2f} FPS"
            ),
        )
        return {"FINISHED"}


class ANIMTHUMB_OT_OpenItemActions(bpy.types.Operator):
    bl_idname = "animthumb.open_item_actions"
    bl_label = "Animated Thumbnail Actions"
    bl_description = "Show refresh, cache-folder, and delete actions for this thumbnail"
    bl_options = {"REGISTER"}

    item_id: StringProperty(options={"HIDDEN"})

    def execute(self, context):
        item = _find_scene_item(context.scene, self.item_id)
        if item is None:
            self.report({"ERROR"}, "Animated thumbnail cache was not found")
            return {"CANCELLED"}
        item_id = self.item_id

        def draw_actions(menu, _menu_context):
            refresh_row = menu.layout.row()
            refresh_row.operator_context = "INVOKE_DEFAULT"
            refresh = refresh_row.operator(
                ANIMTHUMB_OT_RefreshItem.bl_idname,
                text="Refresh with New FPS Settings",
                icon="FILE_REFRESH",
            )
            refresh.item_id = item_id
            open_directory = menu.layout.operator(
                ANIMTHUMB_OT_OpenCacheDirectory.bl_idname,
                text="Open Thumbnail Cache Directory",
                icon="FILE_FOLDER",
            )
            open_directory.item_id = item_id
            menu.layout.separator()
            delete_row = menu.layout.row()
            delete_row.operator_context = "INVOKE_DEFAULT"
            delete = delete_row.operator(
                ANIMTHUMB_OT_DeleteItem.bl_idname,
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
            item = _find_scene_item(context.scene, self.item_id)
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
