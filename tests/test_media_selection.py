from __future__ import annotations

import os
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

from blender_animated_ui.media_selection import (  # noqa: E402
    default_media_name,
    order_sequence_paths,
)


class MediaSelectionTests(unittest.TestCase):
    def test_default_media_name_is_shared_for_files_and_sequences(self) -> None:
        self.assertEqual(default_media_name(("/tmp/My Clip.mp4",)), "My Clip")
        self.assertEqual(
            default_media_name(
                (
                    "/tmp/Walk Cycle/frame_1.png",
                    "/tmp/Walk Cycle/frame_2.png",
                )
            ),
            "Walk Cycle",
        )
        self.assertEqual(default_media_name(()), "")

    def test_natural_order_handles_numeric_filename_runs(self) -> None:
        ordered = order_sequence_paths(
            ("/tmp/frame_10.png", "/tmp/frame_2.png", "/tmp/frame_1.png"),
            "ALPHANUMERIC_ASC",
        )
        self.assertEqual(
            [path.name for path in ordered],
            ["frame_1.png", "frame_2.png", "frame_10.png"],
        )

    def test_browser_order_is_preserved(self) -> None:
        ordered = order_sequence_paths(
            ("/tmp/c.png", "/tmp/a.png", "/tmp/b.png"),
            "FILE_BROWSER",
        )
        self.assertEqual([path.name for path in ordered], ["c.png", "a.png", "b.png"])

    def test_file_date_order_uses_portable_timestamp_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            older = root / "older.png"
            newer = root / "newer.png"
            older.touch()
            newer.touch()
            os.utime(older, (100.0, 100.0))
            os.utime(newer, (200.0, 200.0))
            ordered = order_sequence_paths(
                (newer, older),
                "FILE_DATE_ASC",
            )
            if hasattr(older.stat(), "st_birthtime"):
                self.assertEqual(set(ordered), {older.resolve(), newer.resolve()})
            else:
                self.assertEqual(ordered, (older.resolve(), newer.resolve()))


if __name__ == "__main__":
    unittest.main()
