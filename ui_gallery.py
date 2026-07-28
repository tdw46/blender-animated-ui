"""N-panel animated gallery and its Beyond VRM-style settings popover."""

from __future__ import annotations

import textwrap

import bpy

from .constants import (
    GALLERY_BASE_TILE_WIDTH_PX,
    GALLERY_ICON_SCALE,
)
from .gallery_pagination import (
    adaptive_page_size,
    clamp_page,
    page_bounds,
    page_count,
    pagination_button_rows,
    pagination_layout_metrics,
)
from .gallery_query import GalleryQuery, filter_and_sort_media
from .gallery_settings import (
    DEFAULT_GALLERY_SETTINGS,
    normalized_thumbnail_scale,
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
    thumbnail_scale = normalized_thumbnail_scale(
        getattr(
            context.window_manager,
            "animthumb_thumbnail_scale",
            DEFAULT_GALLERY_SETTINGS.thumbnail_scale,
        )
    )
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
        display_box = layout.box()
        display_box.label(text="Display", icon="PREFERENCES")
        display_box.prop(
            wm,
            "animthumb_thumbnail_scale",
            text="Thumbnail Scale",
            slider=True,
        )
        display_box.prop(
            wm,
            "animthumb_preview_fps",
            text="Live Playback FPS Ceiling",
            slider=True,
        )
        display_box.prop(
            wm,
            "animthumb_preview_ram_budget_mb",
            text="Preview RAM Budget",
            slider=True,
        )
        from . import preview_cache

        memory_stats = preview_cache.memory_stats()
        display_box.label(
            text=(
                f"{memory_stats['estimated_mebibytes']:.1f} MiB · "
                f"{memory_stats['loaded_frames']} frames loaded"
            ),
            icon="MEMORY",
        )
        requested_budget = int(memory_stats["requested_budget_bytes"])
        effective_budget = int(memory_stats["effective_budget_bytes"])
        if requested_budget > 0 and effective_budget > requested_budget:
            display_box.label(
                text=(
                    "Protected working set: "
                    f"{memory_stats['effective_budget_mebibytes']:.1f} MiB"
                ),
                icon="INFO",
            )
        display_box.prop(
            wm,
            "animthumb_optimized_playback",
            text="Optimized Playback Mode",
        )
        library_box = layout.box()
        library_box.label(text="Library", icon="FILTER")
        library_box.prop(
            wm,
            "animthumb_gallery_search",
            text="Search",
        )
        library_box.prop(
            wm,
            "animthumb_gallery_media_type",
            text="Media Type",
        )
        library_box.prop(
            wm,
            "animthumb_gallery_sort",
            text="Sort",
        )
        filtered_count = len(
            filter_and_sort_media(
                context.scene.animthumb_items,
                GalleryQuery(
                    search_text=wm.animthumb_gallery_search,
                    media_type=wm.animthumb_gallery_media_type,
                    sort_mode=wm.animthumb_gallery_sort,
                ),
            )
        )
        library_box.label(
            text=f"Showing {filtered_count} of {len(context.scene.animthumb_items)}"
        )
        layout.operator(
            "animthumb.reset_gallery_settings",
            text="Reset Settings",
            icon="LOOP_BACK",
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

        all_items = list(scene.animthumb_items)
        if not all_items:
            layout.label(
                text="Add media to generate the first thumbnail cache.",
                icon="INFO",
            )
            from . import preview_engine

            preview_engine.register_ui_region(context, ())
            return

        items = filter_and_sort_media(
            all_items,
            GalleryQuery(
                search_text=wm.animthumb_gallery_search,
                media_type=wm.animthumb_gallery_media_type,
                sort_mode=wm.animthumb_gallery_sort,
            ),
        )
        if not items:
            layout.label(
                text="No thumbnails match the gallery filters.",
                icon="INFO",
            )
            from . import preview_engine

            preview_engine.register_ui_region(context, ())
            return

        from . import preview_cache, preview_engine

        paging_memory = preview_cache.pagination_memory_estimate()
        resolved_page_size = adaptive_page_size(
            len(items),
            preview_engine.preview_ram_budget_bytes(),
            paging_memory["largest_frame_bytes"],
            paging_memory["resident_poster_bytes"],
        )
        resolved_page_count = page_count(len(items), resolved_page_size)
        current_page = clamp_page(
            int(scene.animthumb_gallery_page),
            resolved_page_count,
        )
        start, end = page_bounds(current_page, len(items), resolved_page_size)
        visible_items = items[start:end]

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
                actions = action_row.operator(
                    "animthumb.open_item_actions",
                    text="",
                    icon="DOWNARROW_HLT",
                )
                actions.item_id = str(item.item_id)
            if row_start + columns < len(visible_items):
                gallery_box.separator(factor=0.6)

        if resolved_page_count > 1:
            pagination_metrics = pagination_layout_metrics(
                max(1, int(getattr(context.region, "width", 300) or 300)),
                _display_scale(context),
            )
            pagination_columns = int(pagination_metrics["columns"])
            pagination_ui_units_x = float(pagination_metrics["ui_units_x"])
            for pagination_buttons in pagination_button_rows(
                resolved_page_count,
                pagination_columns,
            ):
                pagination_row = layout.row(align=False)
                pagination_row.alignment = "LEFT"
                for pagination_button in pagination_buttons:
                    slot = pagination_row.column(align=True)
                    slot.ui_units_x = pagination_ui_units_x
                    button = slot.row(align=True)
                    button.ui_units_x = pagination_ui_units_x
                    button.scale_y = 1.08
                    button.alignment = "EXPAND"
                    is_current = (
                        pagination_button.kind == "PAGE"
                        and pagination_button.page == current_page
                    )
                    if pagination_button.kind == "FIRST":
                        button.enabled = current_page > 0
                    elif pagination_button.kind == "LAST":
                        button.enabled = current_page + 1 < resolved_page_count
                    else:
                        button.enabled = not is_current
                    button.operator(
                        "animthumb.set_gallery_page",
                        text=pagination_button.label,
                        depress=is_current,
                    ).page = pagination_button.page
