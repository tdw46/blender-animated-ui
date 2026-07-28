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

from blender_animated_ui.frame_rate import (  # noqa: E402
    active_display_fps,
    bounded_sample_indices,
    clamp_preview_fps,
    effective_fps,
    frame_interval_ms,
    sample_wait_ms,
    sampled_clock_ms,
    target_sample_fps,
)


class FrameRateTests(unittest.TestCase):
    def test_rate_is_clamped_to_supported_range(self) -> None:
        self.assertEqual(clamp_preview_fps(None), 10)
        self.assertEqual(clamp_preview_fps(-4), 8)
        self.assertEqual(clamp_preview_fps(17), 17)
        self.assertEqual(clamp_preview_fps(120), 60)

    def test_clock_is_quantized_only_when_limit_is_requested(self) -> None:
        self.assertEqual(sampled_clock_ms(255, None), 255)
        self.assertEqual(frame_interval_ms(5), 200)
        self.assertEqual(frame_interval_ms(60), 17)
        self.assertEqual(sampled_clock_ms(255, 5), 200)

    def test_long_media_uses_floor_instead_of_stretching_cache(self) -> None:
        self.assertEqual(target_sample_fps(1.0, 60, 60), 60.0)
        self.assertEqual(target_sample_fps(10.0, 60, 60), 8.0)
        self.assertEqual(
            target_sample_fps(1.0, 60, 60, source_fps=12.0),
            12.0,
        )
        self.assertEqual(
            target_sample_fps(1.0, 30, 60, source_fps=60.0),
            30.0,
        )
        self.assertEqual(
            target_sample_fps(30.0, 60, 60, source_fps=4.0),
            4.0,
        )

    def test_wait_aligns_source_boundary_to_rate_grid(self) -> None:
        self.assertEqual(sample_wait_ms(255, 200, 100, 5), 145)
        self.assertEqual(sample_wait_ms(255, 255, 100, None), 100)

    def test_effective_rate_uses_finished_cache_duration(self) -> None:
        self.assertAlmostEqual(effective_fps(12, 1000), 12.0)
        self.assertEqual(effective_fps(1, 1000), 0.0)

    def test_active_display_rate_respects_every_item_limit(self) -> None:
        self.assertEqual(
            active_display_fps(24, source_fps=24, requested_fps=8),
            8.0,
        )
        self.assertEqual(
            active_display_fps(24, source_fps=12, requested_fps=60),
            12.0,
        )
        self.assertEqual(
            active_display_fps(4, source_fps=4, requested_fps=8),
            4.0,
        )

    def test_sequence_sampling_is_evenly_bounded(self) -> None:
        indices = bounded_sample_indices(100, 60)
        self.assertEqual(len(indices), 60)
        self.assertEqual(indices[0], 0)
        self.assertEqual(indices[-1], 99)
        self.assertEqual(len(set(indices)), 60)


if __name__ == "__main__":
    unittest.main()
