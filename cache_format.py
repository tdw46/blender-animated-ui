"""Pure-Python cache schema helpers reusable outside Blender."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .constants import CACHE_SCHEMA_VERSION, DEFAULT_STATIC_FRAME_MS
from .frame_rate import effective_fps

_FRAME_PATTERN = re.compile(
    r"^frame_(?P<index>\d+)__(?P<start>\d+)_(?P<end>\d+)\.png$",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class FrameRecord:
    index: int
    start_ms: int
    end_ms: int
    path: Path

    @property
    def duration_ms(self) -> int:
        return max(1, self.end_ms - self.start_ms)


def stable_item_id(source_paths: Iterable[str | Path]) -> str:
    normalized = "\n".join(
        str(Path(path).expanduser().resolve()) for path in source_paths
    )
    return hashlib.sha1(normalized.encode("utf-8", errors="ignore")).hexdigest()[:16]


def safe_cache_name(name: str, fallback: str = "animated_media") -> str:
    cleaned = re.sub(r"[^\w.-]+", "_", str(name or "").strip(), flags=re.UNICODE)
    cleaned = cleaned.strip("._")
    return cleaned[:80] or fallback


def frame_filename(index: int, start_ms: int, end_ms: int) -> str:
    safe_index = max(0, int(index))
    safe_start = max(0, int(start_ms))
    safe_end = max(safe_start + 1, int(end_ms))
    return f"frame_{safe_index:03d}__{safe_start:08d}_{safe_end:08d}.png"


def parse_frame_filename(path: str | Path) -> FrameRecord | None:
    resolved_path = Path(path)
    match = _FRAME_PATTERN.match(resolved_path.name)
    if match is None:
        return None
    start_ms = max(0, int(match.group("start")))
    end_ms = max(start_ms + 1, int(match.group("end")))
    return FrameRecord(
        index=max(0, int(match.group("index"))),
        start_ms=start_ms,
        end_ms=end_ms,
        path=resolved_path,
    )


def build_uniform_records(
    frame_paths: Iterable[str | Path],
    frame_duration_ms: int,
) -> tuple[FrameRecord, ...]:
    duration_ms = max(1, int(frame_duration_ms or DEFAULT_STATIC_FRAME_MS))
    records: list[FrameRecord] = []
    cursor_ms = 0
    for index, path in enumerate(frame_paths):
        end_ms = cursor_ms + duration_ms
        records.append(
            FrameRecord(
                index=index,
                start_ms=cursor_ms,
                end_ms=end_ms,
                path=Path(path),
            )
        )
        cursor_ms = end_ms
    return tuple(records)


def write_metadata(
    cache_dir: Path,
    *,
    item_id: str,
    name: str,
    source_paths: Iterable[str | Path],
    records: Iterable[FrameRecord],
    width: int,
    height: int,
    target_fps: int | float | None = None,
    source_fps: int | float | None = None,
    sample_fps: int | float | None = None,
    source_duration_ms: int | None = None,
) -> Path:
    resolved_records = tuple(records)
    duration_ms = max(1, int(resolved_records[-1].end_ms)) if resolved_records else 0
    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "item_id": item_id,
        "name": name,
        "source_paths": [str(Path(path).resolve()) for path in source_paths],
        "width": max(0, int(width)),
        "height": max(0, int(height)),
        "duration_ms": duration_ms,
        "preview_duration_ms": duration_ms,
        "effective_fps": round(
            effective_fps(len(resolved_records), duration_ms),
            6,
        ),
        "frames": [
            {
                "index": record.index,
                "start_ms": record.start_ms,
                "end_ms": record.end_ms,
                "file": record.path.name,
            }
            for record in resolved_records
        ],
    }
    if target_fps is not None:
        payload["target_fps"] = max(0.0, float(target_fps))
    if source_fps is not None and float(source_fps) > 0.0:
        payload["source_fps"] = max(0.0, float(source_fps))
    if sample_fps is not None:
        payload["sample_fps"] = max(0.0, float(sample_fps))
    if source_duration_ms is not None:
        payload["source_duration_ms"] = max(0, int(source_duration_ms))
    metadata_path = cache_dir / "metadata.json"
    temporary_path = cache_dir / "metadata.json.tmp"
    temporary_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary_path.replace(metadata_path)
    return metadata_path


def read_metadata(cache_dir: str | Path) -> dict:
    resolved_dir = Path(cache_dir)
    payload = json.loads((resolved_dir / "metadata.json").read_text(encoding="utf-8"))
    if int(payload.get("schema_version", -1)) != CACHE_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported thumbnail cache schema: {payload.get('schema_version')!r}"
        )
    frame_payloads = payload.get("frames")
    if not isinstance(frame_payloads, list) or not frame_payloads:
        raise ValueError("Thumbnail cache does not contain frames")
    records: list[FrameRecord] = []
    for frame_payload in frame_payloads:
        start_ms = max(0, int(frame_payload["start_ms"]))
        end_ms = max(start_ms + 1, int(frame_payload["end_ms"]))
        frame_path = resolved_dir / str(frame_payload["file"])
        if not frame_path.is_file():
            raise FileNotFoundError(frame_path)
        records.append(
            FrameRecord(
                index=max(0, int(frame_payload["index"])),
                start_ms=start_ms,
                end_ms=end_ms,
                path=frame_path,
            )
        )
    records.sort(key=lambda record: (record.start_ms, record.end_ms, record.index))
    payload["records"] = tuple(records)
    payload["duration_ms"] = max(1, int(records[-1].end_ms))
    return payload
