"""N-panel animated gallery and its Beyond VRM-style settings popover."""

from __future__ import annotations

import math
import textwrap

import bpy

from .constants import (
    GALLERY_BASE_TILE_WIDTH_PX,
    GALLERY_ICON_SCALE,
    GALLERY_PAGE_SIZE,
)


def _display_scale(context) -> float:
    preferences = getattr(context, "preferences", None)
    system = getattr(preferences, "system", None)
    view = getattr(preferences, "view", None)
    try:
        return max(
            0.5,
            float(
                getattr(system, "ui_scale", None)
                or getattr(view, "ui_scale", 1.0)
                or 1.0
            ),
        )
    except (TypeError, ValueError):
        return 1.0


def gallery_layout_metrics(context, region_width: int) -> dict[str, float | int]:
    display_scale = _display_scale(context)
    try:
        thumbnail_scale = float(
            getattr(context.window_manager, "animthumb_thumbnail_scale", 1.0) or 1.0
        )
    except (TypeError, ValueError):
        thumbnail_scale = 1.0
    thumbnail_scale = max(0.5, min(thumbnail_scale, 2.0))
    target_tile_width = GALLERY_BASE_TILE_WIDTH_PX * display_scale * thumbnail_scale
    columns = max(1, int(max(1.0, float(region_width)) // target_tile_width))
    return {
        "columns": columns,
        "ui_units_x": target_tile_width / 20.0,
        "icon_scale": GALLERY_ICON_SCALE * thumbnail_scale,
    }


def _wrapped_title_lines(text: str, ui_units_x: float) -> list[str]:
    character_width = max(1, int((max(1.0, ui_units_x) * 20.0) / 7.0))
    return textwrap.wrap(
        str(text or ""),
        width=character_width,
        break_long_words=True,
        break_on_hyphens=True,
    ) or [""]


def _draw_title(layout, text: str, ui_units_x: float, line_count: int) -> None:
    lines = _wrapped_title_lines(text, ui_units_x)
    for line in lines:
        layout.label(text=line)
    for _index in range(max(0, line_count - len(lines))):
        layout.label(text="")


def tag_layout_refresh() -> None:
    from . import preview_engine

    preview_engine.tag_targeted_layout_refresh()


class ANIMTHUMB_PT_GallerySettingsPopover(bpy.types.Panel):
    bl_label = "Gallery Settings"
    bl_idname = "ANIMTHUMB_PT_gallery_settings_popover"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 14

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager
        layout.prop(
            wm,
            "animthumb_thumbnail_scale",
            text="Thumbnail Scale",
            slider=True,
        )
        layout.prop(
            wm,
            "animthumb_preview_fps",
            text="Maximum Preview FPS",
            slider=True,
        )
        layout.prop(
            wm,
            "animthumb_optimized_playback",
            text="Optimized Playback Mode",
        )


class ANIMTHUMB_PT_AnimatedGallery(bpy.types.Panel):
    bl_label = "Animated Thumbnail Gallery"
    bl_idname = "ANIMTHUMB_PT_animated_gallery"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Animated Previews"

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager
        scene = context.scene

        header = layout.row(align=True)
        header.label(text="Preview Library", icon="IMAGE_DATA")
        header.operator(
            "animthumb.refresh_library",
            text="",
            icon="FILE_REFRESH",
        )
        header.popover(
            panel=ANIMTHUMB_PT_GallerySettingsPopover.bl_idname,
            text="",
            icon="PREFERENCES",
        )

        from . import ffmpeg_bridge

        dependency_status = ffmpeg_bridge.status()
        if not dependency_status.get("wheel_ready"):
            dependency_box = layout.box()
            row = dependency_box.row()
            row.alert = not bool(dependency_status.get("ready"))
            if dependency_status.get("system_executable"):
                row.label(text="System FFmpeg found; wheel is optional", icon="INFO")
            else:
                row.label(text="FFmpeg wheel required for media ingest", icon="ERROR")
            dependency_box.operator(
                "animthumb.install_ffmpeg",
                icon="IMPORT",
            )

        add_row = layout.row()
        add_row.scale_y = 1.3
        add_row.operator(
            "animthumb.ingest_media",
            text="Add Animated Media",
            icon="FILEBROWSER",
        )

        status_text = str(getattr(wm, "animthumb_status", "") or "")
        if status_text:
            status_box = layout.box()
            status_level = str(
                getattr(wm, "animthumb_status_level", "INFO") or "INFO"
            ).upper()
            status_row = status_box.row()
            status_row.alert = status_level in {"ERROR", "WARN", "WARNING"}
            status_row.label(
                text=status_text,
                icon="ERROR" if status_level == "ERROR" else "INFO",
            )

        items = list(scene.animthumb_items)
        if not items:
            layout.label(
                text="Add media to generate the first thumbnail cache.",
                icon="INFO",
            )
            from . import preview_engine

            preview_engine.register_ui_region(context, ())
            return

        page_count = max(1, int(math.ceil(len(items) / GALLERY_PAGE_SIZE)))
        current_page = min(
            max(0, int(scene.animthumb_gallery_page)),
            page_count - 1,
        )
        start = current_page * GALLERY_PAGE_SIZE
        visible_items = items[start : start + GALLERY_PAGE_SIZE]

        if page_count > 1:
            page_row = layout.row(align=True)
            previous = page_row.row(align=True)
            previous.enabled = current_page > 0
            previous.operator(
                "animthumb.set_gallery_page",
                text="",
                icon="TRIA_LEFT",
            ).page = max(0, current_page - 1)
            page_row.label(
                text=f"Page {current_page + 1} / {page_count}",
            )
            following = page_row.row(align=True)
            following.enabled = current_page + 1 < page_count
            following.operator(
                "animthumb.set_gallery_page",
                text="",
                icon="TRIA_RIGHT",
            ).page = min(page_count - 1, current_page + 1)

        from . import preview_cache, preview_engine

        visible_ids: list[str] = []
        for item in visible_items:
            if preview_cache.load_item(item) is not None:
                visible_ids.append(str(item.item_id))
        preview_engine.register_ui_region(context, tuple(visible_ids))
        if visible_ids:
            preview_engine.schedule_start()

        _preview_tick = int(getattr(wm, "animthumb_preview_tick", 0) or 0)
        del _preview_tick
        now_ms = preview_engine.current_preview_ms()
        preview_fps = preview_engine.preview_frame_rate()
        metrics = gallery_layout_metrics(
            context,
            max(1, int(getattr(context.region, "width", 300) or 300)),
        )
        columns = int(metrics["columns"])
        ui_units_x = float(metrics["ui_units_x"])
        icon_scale = float(metrics["icon_scale"])

        gallery_box = layout.box()
        for row_start in range(0, len(visible_items), columns):
            row_items = visible_items[row_start : row_start + columns]
            row_title_lines = max(
                (
                    len(_wrapped_title_lines(str(item.name), ui_units_x))
                    for item in row_items
                ),
                default=1,
            )
            row = gallery_box.row(align=False)
            for column_index in range(columns):
                item_index = row_start + column_index
                column = row.column(align=True)
                column.ui_units_x = ui_units_x
                if item_index >= len(visible_items):
                    column.label(text="")
                    continue
                item = visible_items[item_index]
                _draw_title(
                    column,
                    str(item.name or "Animated Media"),
                    ui_units_x,
                    row_title_lines,
                )
                icon_id = preview_cache.icon_id(
                    str(item.item_id),
                    now_ms,
                    fps_limit=preview_fps,
                )
                thumbnail_row = column.row(align=True)
                thumbnail_row.scale_y = 0.78
                if icon_id:
                    thumbnail_row.template_icon(
                        icon_value=icon_id,
                        scale=icon_scale,
                    )
                else:
                    thumbnail_row.label(text="(Preview unavailable)")
                action_row = column.row(align=True)
                action_row.scale_y = 0.82
                action_row.alignment = "CENTER"
                frame_count = int(item.frame_count)
                display_fps = preview_cache.display_frame_rate(
                    str(item.item_id),
                    fps_limit=preview_fps,
                )
                rate_text = (
                    f"{display_fps:.1f} FPS"
                    if frame_count > 1 and display_fps > 0.0
                    else "Still"
                )
                action_row.label(
                    text=f"{frame_count}f · {rate_text}",
                    icon="TIME",
                )
                delete = action_row.operator(
                    "animthumb.delete_item",
                    text="",
                    icon="TRASH",
                )
                delete.item_id = str(item.item_id)
            if row_start + columns < len(visible_items):
                gallery_box.separator(factor=0.6)
