"""Pure media classification, name filtering, and gallery sorting helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .gallery_settings import (
    DEFAULT_GALLERY_MEDIA_TYPE,
    DEFAULT_GALLERY_SEARCH,
    DEFAULT_GALLERY_SORT,
)

MEDIA_TYPE_FILTER_ITEMS = (
    ("ALL", "All Media Types", "Show every imported media type"),
    ("SEQUENCE", "Image Sequence", "Show imported image sequences"),
    ("GIF", "GIF", "Show GIF media"),
    ("APNG", "APNG", "Show animated PNG media"),
    ("WEBP", "WebP", "Show WebP media"),
    ("MP4", "MP4", "Show MP4 video"),
    ("MOV", "MOV", "Show QuickTime video"),
    ("M4V", "M4V", "Show M4V video"),
    ("AVI", "AVI", "Show AVI video"),
    ("MKV", "MKV", "Show Matroska video"),
    ("WEBM", "WebM", "Show WebM video"),
    ("MPEG", "MPEG", "Show MPEG video"),
    ("MPG", "MPG", "Show MPG video"),
    ("WMV", "WMV", "Show Windows Media video"),
    ("FLV", "FLV", "Show Flash video"),
    ("PNG", "PNG", "Show PNG images"),
    ("JPG", "JPG", "Show JPG images"),
    ("JPEG", "JPEG", "Show JPEG images"),
    ("BMP", "BMP", "Show bitmap images"),
    ("TIF", "TIF", "Show TIF images"),
    ("TIFF", "TIFF", "Show TIFF images"),
    ("OTHER", "Other", "Show media with another or unknown extension"),
)

GALLERY_SORT_ITEMS = (
    (
        "DATE_ADDED_DESC",
        "Date Added (Newest)",
        "Show newly imported media first",
    ),
    (
        "DATE_ADDED_ASC",
        "Date Added (Oldest)",
        "Show the oldest imported media first",
    ),
    ("NAME_ASC", "Name (A–Z)", "Sort names alphabetically"),
    ("NAME_DESC", "Name (Z–A)", "Sort names in reverse alphabetical order"),
)

_KNOWN_MEDIA_TYPES = frozenset(
    identifier
    for identifier, _name, _description in MEDIA_TYPE_FILTER_ITEMS
    if identifier not in {"ALL", "SEQUENCE", "OTHER"}
)


@dataclass(frozen=True, slots=True)
class GalleryQuery:
    """The reusable, Blender-independent state of one gallery query."""

    search_text: str = DEFAULT_GALLERY_SEARCH
    media_type: str = DEFAULT_GALLERY_MEDIA_TYPE
    sort_mode: str = DEFAULT_GALLERY_SORT


def source_media_type(
    source_paths: Iterable[str | Path],
    *,
    is_sequence: bool = False,
) -> str:
    """Return a stable extension-based media type stored at import time."""
    paths = tuple(Path(path) for path in source_paths)
    if is_sequence or len(paths) > 1:
        return "SEQUENCE"
    if not paths:
        return "OTHER"
    suffix = paths[0].suffix.lower().lstrip(".").upper()
    return suffix if suffix in _KNOWN_MEDIA_TYPES else "OTHER"


def _value(item, name: str, default=""):
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def filter_and_sort_media(
    items: Iterable,
    query: GalleryQuery,
) -> list:
    """Return matching media without mutating the caller's collection."""
    search = str(query.search_text or "").strip().casefold()
    requested_type = str(query.media_type or "ALL").upper()
    filtered = [
        item
        for item in items
        if (not search or search in str(_value(item, "name", "") or "").casefold())
        and (
            requested_type == "ALL"
            or str(_value(item, "source_type", "OTHER") or "OTHER").upper()
            == requested_type
        )
    ]

    mode = str(query.sort_mode or DEFAULT_GALLERY_SORT).upper()

    def name_key(item) -> tuple[str, str]:
        return (
            str(_value(item, "name", "") or "").casefold(),
            str(_value(item, "item_id", "") or ""),
        )

    if mode == "NAME_ASC":
        return sorted(filtered, key=name_key)
    if mode == "NAME_DESC":
        return sorted(filtered, key=name_key, reverse=True)

    def date_key(item) -> tuple[str, str]:
        return (
            str(_value(item, "date_added_utc", "") or ""),
            str(_value(item, "item_id", "") or ""),
        )

    return sorted(
        filtered,
        key=date_key,
        reverse=mode != "DATE_ADDED_ASC",
    )
