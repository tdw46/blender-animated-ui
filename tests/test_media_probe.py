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

from blender_animated_ui.media_ingest import _alpha_decoder_name  # noqa: E402
from blender_animated_ui.media_probe import MediaProbe, parse_ffmpeg_probe  # noqa: E402


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
        self.assertFalse(result.has_alpha)
        self.assertEqual(result.frame_count, 0)
        self.assertEqual(result.video_codec, "h264")

    def test_missing_rate_is_explicitly_unknown(self) -> None:
        result = parse_ffmpeg_probe("Stream #0:0: Video: png, rgba, 512x512")
        self.assertEqual(result.source_fps, 0.0)
        self.assertTrue(result.has_alpha)
        self.assertEqual(result.frame_count, 0)

    def test_parses_terminal_frame_count(self) -> None:
        result = parse_ffmpeg_probe(
            """
            Duration: N/A, bitrate: N/A
            Stream #0:0: Video: apng, rgba, 128x96, 12 fps
            frame=   24 fps=0.0 q=-1.0 time=00:00:01.99
            """
        )
        self.assertEqual(result.frame_count, 24)

    def test_webm_alpha_metadata_is_detected_despite_opaque_pixel_format(self) -> None:
        result = parse_ffmpeg_probe(
            """
            Stream #0:0: Video: vp9 (Profile 0), yuv420p, 1024x1024, 30 fps
              Metadata:
                alpha_mode      : 1
            """
        )
        self.assertTrue(result.has_alpha)
        self.assertEqual(result.video_codec, "vp9")

    def test_transparent_webm_selects_the_alpha_capable_decoder(self) -> None:
        probe = MediaProbe(
            duration_seconds=1.0,
            width=192,
            height=192,
            source_fps=30.0,
            has_alpha=True,
            frame_count=30,
            video_codec="vp9",
        )
        self.assertEqual(
            _alpha_decoder_name(Path("transparent.webm"), probe),
            "libvpx-vp9",
        )
        self.assertEqual(_alpha_decoder_name(Path("transparent.mp4"), probe), "")


if __name__ == "__main__":
    unittest.main()
