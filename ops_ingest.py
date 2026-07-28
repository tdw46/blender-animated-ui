"""File-browser ingest and per-item atomic refresh operators."""

from __future__ import annotations

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
from .constants import MAX_PREVIEW_FPS, MIN_PREVIEW_FPS
from .media_selection import (
    DEFAULT_SEQUENCE_ORDER,
    SEQUENCE_ORDER_ITEMS,
    order_sequence_paths,
)
from .ops_dependency import prepare_ffmpeg
from .ui_media_settings import draw_media_settings
from .utils import find_scene_item, invoke_props_dialog_compat, set_status

_MEDIA_FILTER_GLOB = (
    "*.gif;*.apng;*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.tif;*.tiff;"
    "*.mp4;*.mov;*.m4v;*.avi;*.mkv;*.webm;*.mpeg;*.mpg;*.wmv;*.flv"
)


def selected_media_paths(operator) -> tuple[Path, ...]:
    """Resolve Blender's single- and multi-file selector values consistently."""
    selected = tuple(
        Path(str(operator.directory or "")) / entry.name
        for entry in operator.files
        if str(entry.name or "")
    )
    if not selected and str(operator.filepath or ""):
        selected = (Path(operator.filepath),)
    return tuple(path.expanduser().resolve() for path in selected)


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
    filter_glob: StringProperty(default=_MEDIA_FILTER_GLOB, options={"HIDDEN"})

    def invoke(self, context, event):
        del event
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def _refresh_analysis(self, context) -> None:
        del context
        paths = selected_media_paths(self)
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
        executable = str(ffmpeg_bridge.status().get("executable", "") or "")
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
        draw_media_settings(
            self.layout,
            context,
            self,
            selected_media_paths(self),
        )

    def execute(self, context):
        selected = selected_media_paths(self)
        if not selected:
            self.report({"ERROR"}, "No media was selected")
            return {"CANCELLED"}
        if len(selected) > 1:
            selected = order_sequence_paths(selected, self.sequence_order)

        dependency_status = prepare_ffmpeg(context, self)
        if dependency_status is None:
            return {"CANCELLED"}

        set_status(context, f"Converting {len(selected)} selected media file(s)…")
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
            set_status(context, str(error), "ERROR")
            self.report({"ERROR"}, f"Animated media conversion failed: {error}")
            return {"CANCELLED"}

        from . import library

        library.refresh_all_scenes()
        set_status(
            context,
            (
                f"Added {result.name}: {result.frame_count} cached frames "
                f"at {result.effective_fps:.2f} FPS, {result.duration_ms} ms"
            ),
        )
        self.report({"INFO"}, f"Added animated thumbnail: {result.name}")
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
        item = find_scene_item(context.scene, self.item_id)
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
        return invoke_props_dialog_compat(
            context,
            self,
            width=440,
            title=f"Refresh {self.item_name}",
            confirm_text="Rebuild Preview",
        )

    def draw(self, context):
        paths = (Path(self.source_path),) if self.source_path else ()
        draw_media_settings(self.layout, context, self, paths)

    def execute(self, context):
        item = find_scene_item(context.scene, self.item_id)
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
        dependency_status = prepare_ffmpeg(context, self)
        if dependency_status is None:
            return {"CANCELLED"}
        set_status(context, f"Rebuilding {item.name}…")
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
            set_status(context, str(error), "ERROR")
            self.report({"ERROR"}, f"Thumbnail rebuild failed: {error}")
            return {"CANCELLED"}
        from . import library

        library.refresh_all_scenes()
        set_status(
            context,
            (
                f"Rebuilt {result.name}: {result.frame_count} frames at "
                f"{result.effective_fps:.2f} FPS"
            ),
        )
        return {"FINISHED"}
