from __future__ import annotations

import struct
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("blender_animated_ui")
package.__path__ = [str(ROOT)]
sys.modules.setdefault("blender_animated_ui", package)

from blender_animated_ui.animated_webp import (  # noqa: E402
    inspect_animated_webp,
)
from blender_animated_ui.media_ingest import (  # noqa: E402
    _timed_frame_input_args,
    probe_media,
)


def _chunk(fourcc: bytes, payload: bytes) -> bytes:
    padding = b"\0" if len(payload) & 1 else b""
    return fourcc + struct.pack("<I", len(payload)) + payload + padding


def _uint24(value: int) -> bytes:
    return int(value).to_bytes(3, byteorder="little", signed=False)


def _animated_webp_bytes() -> bytes:
    vp8x = bytes((0x12, 0, 0, 0)) + _uint24(191) + _uint24(107)
    anim = bytes((0, 0, 0, 0)) + struct.pack("<H", 0)
    frame_1 = b"\0" * 12 + _uint24(50) + b"\0"
    frame_2 = b"\0" * 12 + _uint24(100) + b"\0"
    chunks = (
        _chunk(b"VP8X", vp8x)
        + _chunk(b"ANIM", anim)
        + _chunk(b"ANMF", frame_1)
        + _chunk(b"ANMF", frame_2)
    )
    return b"RIFF" + struct.pack("<I", len(chunks) + 4) + b"WEBP" + chunks


class AnimatedWebPTests(unittest.TestCase):
    def test_container_probe_reads_animation_timing_and_alpha(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "animation.webp"
            path.write_bytes(_animated_webp_bytes())
            info = inspect_animated_webp(path)

        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual((info.width, info.height), (192, 108))
        self.assertEqual(info.durations_ms, (50, 100))
        self.assertTrue(info.has_alpha)
        self.assertEqual(info.frame_count, 2)
        self.assertEqual(info.duration_ms, 150)
        self.assertAlmostEqual(info.source_fps, 1000.0 * 2.0 / 150.0)

    def test_tiny_webp_durations_use_browser_compatible_minimum(self) -> None:
        data = _animated_webp_bytes().replace(_uint24(50), _uint24(0), 1)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "animation.webp"
            path.write_bytes(data)
            info = inspect_animated_webp(path)

        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info.durations_ms, (100, 100))

    def test_probe_bypasses_ffmpeg_for_animated_webp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "animation.webp"
            executable = root / "ffmpeg"
            path.write_bytes(_animated_webp_bytes())
            executable.write_bytes(b"not executed")
            probe = probe_media(str(executable), path)

        self.assertEqual(probe.video_codec, "webp")
        self.assertEqual(probe.frame_count, 2)
        self.assertTrue(probe.has_alpha)
        self.assertAlmostEqual(probe.duration_seconds, 0.15)

    def test_timed_concat_repeats_last_frame_for_final_duration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frames = (root / "one.png", root / "two.png")
            for frame in frames:
                frame.write_bytes(b"frame")
            arguments = _timed_frame_input_args(frames, (50, 100), root)
            concat_text = (root / "animated_webp.ffconcat").read_text(encoding="utf-8")

        self.assertEqual(arguments[:4], ["-f", "concat", "-safe", "0"])
        self.assertEqual(concat_text.count("file '"), 3)
        self.assertIn("duration 0.050000000", concat_text)
        self.assertIn("duration 0.100000000", concat_text)

    def test_still_webp_is_not_claimed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "still.webp"
            chunks = _chunk(b"VP8 ", b"still")
            path.write_bytes(
                b"RIFF" + struct.pack("<I", len(chunks) + 4) + b"WEBP" + chunks
            )
            self.assertIsNone(inspect_animated_webp(path))


if __name__ == "__main__":
    unittest.main()
