"""Pure adaptive pagination helpers for memory-bounded animated galleries."""

from __future__ import annotations

from dataclasses import dataclass

from .constants import (
    GALLERY_PAGE_BUTTON_BASE_WIDTH_PX,
    GALLERY_PAGE_SIZE,
    GALLERY_RESIDENT_FRAMES_PER_ANIMATED_ITEM,
)


@dataclass(frozen=True, slots=True)
class PaginationButton:
    """One renderer-independent page control."""

    label: str
    page: int
    kind: str


def adaptive_page_size(
    item_count: int,
    ram_budget_bytes: int,
    frame_bytes: int,
    resident_poster_bytes: int = 0,
    *,
    max_page_size: int = GALLERY_PAGE_SIZE,
    resident_frames_per_item: int = GALLERY_RESIDENT_FRAMES_PER_ANIMATED_ITEM,
) -> int:
    """Return a stable page size that leaves a warm playback set per card."""
    resolved_count = max(0, int(item_count))
    if resolved_count == 0:
        return 1
    resolved_frame_bytes = max(1, int(frame_bytes))
    resolved_frames = max(1, int(resident_frames_per_item))
    reserved_posters = max(0, int(resident_poster_bytes))
    available_bytes = max(0, int(ram_budget_bytes) - reserved_posters)
    additional_frames_per_item = max(1, resolved_frames - 1)
    capacity = available_bytes // (resolved_frame_bytes * additional_frames_per_item)
    return min(resolved_count, max(1, min(int(max_page_size), capacity)))


def page_count(item_count: int, page_size: int) -> int:
    resolved_count = max(0, int(item_count))
    resolved_size = max(1, int(page_size))
    return max(1, (resolved_count + resolved_size - 1) // resolved_size)


def clamp_page(page: int, total_pages: int) -> int:
    return min(max(0, int(page)), max(1, int(total_pages)) - 1)


def page_bounds(page: int, item_count: int, page_size: int) -> tuple[int, int]:
    resolved_size = max(1, int(page_size))
    resolved_page = clamp_page(page, page_count(item_count, resolved_size))
    start = resolved_page * resolved_size
    return start, min(max(0, int(item_count)), start + resolved_size)


def pagination_layout_metrics(
    region_width: int | float,
    display_scale: int | float,
    *,
    base_button_width_px: int | float = GALLERY_PAGE_BUTTON_BASE_WIDTH_PX,
) -> dict[str, float | int]:
    """Return equal-width button metrics for a DPI-aware wrapped layout."""
    resolved_scale = max(0.5, float(display_scale))
    target_width = max(1.0, float(base_button_width_px)) * resolved_scale
    resolved_width = max(1.0, float(region_width))
    return {
        "columns": max(1, int(resolved_width // target_width)),
        "ui_units_x": target_width / 20.0,
    }


def pagination_buttons(
    total_pages: int,
) -> tuple[PaginationButton, ...]:
    """Return first, numbered, and last controls in reading order."""
    resolved_total = max(1, int(total_pages))
    if resolved_total <= 1:
        return ()
    return (
        PaginationButton("<<", 0, "FIRST"),
        *(
            PaginationButton(str(page + 1), page, "PAGE")
            for page in range(resolved_total)
        ),
        PaginationButton(">>", resolved_total - 1, "LAST"),
    )


def pagination_button_rows(
    total_pages: int,
    columns: int,
) -> tuple[tuple[PaginationButton, ...], ...]:
    """Wrap equal-width page controls into renderer-independent rows."""
    controls = pagination_buttons(total_pages)
    resolved_columns = max(1, int(columns))
    return tuple(
        controls[start : start + resolved_columns]
        for start in range(0, len(controls), resolved_columns)
    )
