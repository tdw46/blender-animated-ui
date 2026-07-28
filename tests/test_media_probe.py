from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
package = types.ModuleType("blender_animated_ui")
package.__path__ = [str(ROOT)]
sys.modules.setdefault("blender_animated_ui", package)

from blender_animated_ui.media_probe import parse_ffmpeg_probe  # noqa: E402


class MediaProbeTests(unittest.TestCase):
    def test_parses_native_rate_from_input_video_stream(self) -> None:
        result = parse_ffmpeg_probe(
            """
            Duration: 00:00:02.50, start: 0.000000, bitrate: 100 kb/s
            Stream #0:0: Video: h264, yuv420p, 1920x1080, 23.976 fps, 24 tbr
            """
        )
        self.assertEqual(result.duration_seconds, 2.5)
        self.assertEqual((result.width, result.height), (1920, 1080))
        self.assertAlmostEqual(result.source_fps, 23.976)

    def test_missing_rate_is_explicitly_unknown(self) -> None:
        result = parse_ffmpeg_probe("Stream #0:0: Video: png, rgba, 512x512")
        self.assertEqual(result.source_fps, 0.0)


if __name__ == "__main__":
    unittest.main()
