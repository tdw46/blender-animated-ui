"""Pure parsing helpers for FFmpeg's media probe output."""

from __future__ import annotations

import re
from dataclasses import dataclass

_DURATION_PATTERN = re.compile(
    r"Duration:\s*(?P<hours>\d+):(?P<minutes>\d+):(?P<seconds>\d+(?:\.\d+)?)"
)
_DIMENSION_PATTERN = re.compile(r"(?<!\d)(?P<width>\d{2,6})x(?P<height>\d{2,6})(?!\d)")
_FRAME_RATE_PATTERN = re.compile(
    r"(?<![\d.])(?P<fps>\d+(?:\.\d+)?)\s+fps\b",
    flags=re.IGNORECASE,
)
_FRAME_COUNT_PATTERN = re.compile(r"\bframe=\s*(?P<count>\d+)")


@dataclass(frozen=True, slots=True)
class MediaProbe:
    duration_seconds: float
    width: int
    height: int
    source_fps: float
    has_alpha: bool
    frame_count: int


def parse_ffmpeg_probe(output: str) -> MediaProbe:
    """Parse duration, dimensions, and native video rate from FFmpeg text."""
    text = str(output or "")
    duration_seconds = 0.0
    duration_match = _DURATION_PATTERN.search(text)
    if duration_match is not None:
        duration_seconds = (
            int(duration_match.group("hours")) * 3600
            + int(duration_match.group("minutes")) * 60
            + float(duration_match.group("seconds"))
        )

    video_lines = tuple(
        line for line in text.splitlines() if "Stream #" in line and "Video:" in line
    )
    dimension_match = None
    frame_rate_match = None
    for line in video_lines:
        if dimension_match is None:
            dimension_match = _DIMENSION_PATTERN.search(line)
        if frame_rate_match is None:
            frame_rate_match = _FRAME_RATE_PATTERN.search(line)
        if dimension_match is not None and frame_rate_match is not None:
            break
    if dimension_match is None:
        dimension_match = _DIMENSION_PATTERN.search(text)
    if frame_rate_match is None:
        frame_rate_match = _FRAME_RATE_PATTERN.search(text)

    width = int(dimension_match.group("width")) if dimension_match else 0
    height = int(dimension_match.group("height")) if dimension_match else 0
    source_fps = float(frame_rate_match.group("fps")) if frame_rate_match else 0.0
    alpha_formats = (
        "rgba",
        "bgra",
        "argb",
        "abgr",
        "yuva",
        "gbrap",
        "ya8",
        "pal8",
    )
    has_alpha = any(
        alpha_format in line.casefold()
        for line in video_lines
        for alpha_format in alpha_formats
    )
    frame_counts = tuple(
        int(match.group("count")) for match in _FRAME_COUNT_PATTERN.finditer(text)
    )
    return MediaProbe(
        duration_seconds=max(0.0, duration_seconds),
        width=max(0, width),
        height=max(0, height),
        source_fps=max(0.0, source_fps),
        has_alpha=has_alpha,
        frame_count=max(frame_counts, default=0),
    )
