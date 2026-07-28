"""Pure helpers for deterministic image-sequence ordering."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

DEFAULT_SEQUENCE_ORDER = "ALPHANUMERIC_ASC"
SEQUENCE_ORDER_ITEMS = (
    (
        "ALPHANUMERIC_ASC",
        "Alphanumeric (A–Z)",
        "Natural filename order from lowest to highest",
    ),
    (
        "ALPHANUMERIC_DESC",
        "Alphanumeric (Z–A)",
        "Natural filename order from highest to lowest",
    ),
    (
        "FILE_DATE_ASC",
        "File Date (Oldest First)",
        "Creation date when available, otherwise modification date",
    ),
    (
        "FILE_DATE_DESC",
        "File Date (Newest First)",
        "Creation date when available, otherwise modification date",
    ),
    (
        "FILE_BROWSER",
        "File Browser Order",
        "Keep the order supplied by Blender's file selection",
    ),
)


def default_media_name(paths: Iterable[str | Path]) -> str:
    """Derive the shared import name for one source or an image sequence."""
    resolved = tuple(Path(path).expanduser().resolve() for path in paths)
    if not resolved:
        return ""
    return resolved[0].parent.name if len(resolved) > 1 else resolved[0].stem


def natural_key(path: str | Path) -> tuple:
    """Return a stable filename key where numeric runs sort numerically."""
    resolved = Path(path)
    return tuple(
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", resolved.name)
    )


def _file_date(path: Path) -> float:
    stat = path.stat()
    return float(getattr(stat, "st_birthtime", stat.st_mtime))


def order_sequence_paths(
    paths: Iterable[str | Path],
    order: str = DEFAULT_SEQUENCE_ORDER,
) -> tuple[Path, ...]:
    """Order selected sequence paths without depending on Blender."""
    resolved = tuple(Path(path).expanduser().resolve() for path in paths)
    mode = str(order or DEFAULT_SEQUENCE_ORDER).upper()
    if mode == "FILE_BROWSER":
        return resolved
    if mode == "ALPHANUMERIC_DESC":
        return tuple(sorted(resolved, key=natural_key, reverse=True))
    if mode in {"FILE_DATE_ASC", "FILE_DATE_DESC"}:
        reverse = mode == "FILE_DATE_DESC"
        return tuple(
            sorted(
                resolved,
                key=lambda path: (_file_date(path), natural_key(path)),
                reverse=reverse,
            )
        )
    return tuple(sorted(resolved, key=natural_key))
