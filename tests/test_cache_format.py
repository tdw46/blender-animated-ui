from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
package = types.ModuleType("blender_animated_ui")
package.__path__ = [str(ROOT)]
sys.modules.setdefault("blender_animated_ui", package)

from blender_animated_ui.cache_format import (  # noqa: E402
    build_uniform_records,
    frame_filename,
    parse_frame_filename,
    read_metadata,
    stable_item_id,
    write_metadata,
)


class CacheFormatTests(unittest.TestCase):
    def test_timed_frame_filename_round_trip(self) -> None:
        name = frame_filename(12, 345, 678)
        record = parse_frame_filename(name)
        self.assertIsNotNone(record)
        self.assertEqual(record.index, 12)
        self.assertEqual(record.start_ms, 345)
        self.assertEqual(record.end_ms, 678)
        self.assertEqual(frame_filename(1, 0, 100, "jpg").split(".")[-1], "jpg")
        self.assertIsNotNone(parse_frame_filename("frame_001__00000000_00000100.webp"))

    def test_uniform_records_are_cumulative(self) -> None:
        records = build_uniform_records(
            ["a.png", "b.png", "c.png"],
            125,
        )
        self.assertEqual(
            [(record.start_ms, record.end_ms) for record in records],
            [(0, 125), (125, 250), (250, 375)],
        )

    def test_metadata_round_trip_validates_frame_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache_dir = Path(temporary)
            paths = [
                cache_dir / frame_filename(index, index * 100, (index + 1) * 100)
                for index in range(3)
            ]
            for path in paths:
                path.write_bytes(b"png")
            records = build_uniform_records(paths, 100)
            write_metadata(
                cache_dir,
                item_id="test",
                name="Test",
                source_paths=["/tmp/source.gif"],
                records=records,
                width=320,
                height=180,
                target_fps=12,
                source_fps=24,
                sample_fps=12,
                source_duration_ms=1250,
                media_kind="MEDIA",
            )
            metadata = read_metadata(cache_dir)
            self.assertEqual(metadata["item_id"], "test")
            self.assertEqual(metadata["duration_ms"], 300)
            self.assertEqual(metadata["preview_duration_ms"], 300)
            self.assertEqual(metadata["source_duration_ms"], 1250)
            self.assertEqual(metadata["media_kind"], "MEDIA")
            self.assertEqual(metadata["cache_image_format"], "PNG")
            self.assertFalse(metadata["trim_media"])
            self.assertEqual(metadata["target_fps"], 12.0)
            self.assertEqual(metadata["source_fps"], 24.0)
            self.assertEqual(metadata["sample_fps"], 12.0)
            self.assertEqual(metadata["effective_fps"], 10.0)
            self.assertEqual(len(metadata["records"]), 3)

    def test_item_id_is_stable(self) -> None:
        first = stable_item_id(["/tmp/a.gif", "/tmp/b.gif"])
        second = stable_item_id(["/tmp/a.gif", "/tmp/b.gif"])
        self.assertEqual(first, second)
        self.assertEqual(len(first), 16)


if __name__ == "__main__":
    unittest.main()
