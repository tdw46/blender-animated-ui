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

from blender_animated_ui.gallery_pagination import (  # noqa: E402
    adaptive_page_size,
    clamp_page,
    page_bounds,
    page_count,
    pagination_button_rows,
    pagination_buttons,
    pagination_layout_metrics,
)

MIB = 1024 * 1024


class GalleryPaginationTests(unittest.TestCase):
    def test_default_budget_keeps_the_twelve_item_page_cap(self) -> None:
        frame_bytes = 192 * 192 * 4
        poster_bytes = 20 * frame_bytes
        self.assertEqual(
            adaptive_page_size(20, 32 * MIB, frame_bytes, poster_bytes),
            12,
        )

    def test_large_library_reserves_warm_posters_before_page_frames(self) -> None:
        frame_bytes = 256 * 256 * 4
        poster_bytes = 60 * frame_bytes
        self.assertEqual(
            adaptive_page_size(60, 16 * MIB, frame_bytes, poster_bytes),
            1,
        )

    def test_budget_can_reduce_the_page_without_hiding_items(self) -> None:
        frame_bytes = 256 * 256 * 4
        poster_bytes = 12 * frame_bytes
        resolved_size = adaptive_page_size(
            12,
            8 * MIB,
            frame_bytes,
            poster_bytes,
        )
        self.assertEqual(resolved_size, 5)
        self.assertEqual(page_count(12, resolved_size), 3)
        self.assertEqual(page_bounds(2, 12, resolved_size), (10, 12))

    def test_page_clamping(self) -> None:
        self.assertEqual(clamp_page(99, 3), 2)

    def test_page_controls_include_every_number_between_first_and_last(self) -> None:
        controls = pagination_buttons(4)
        self.assertEqual(
            [(control.label, control.page, control.kind) for control in controls],
            [
                ("<<", 0, "FIRST"),
                ("1", 0, "PAGE"),
                ("2", 1, "PAGE"),
                ("3", 2, "PAGE"),
                ("4", 3, "PAGE"),
                (">>", 3, "LAST"),
            ],
        )
        self.assertEqual(pagination_buttons(1), ())

    def test_equal_width_controls_wrap_in_reading_order(self) -> None:
        rows = pagination_button_rows(10, 5)
        self.assertEqual(
            [[button.label for button in row] for row in rows],
            [
                ["<<", "1", "2", "3", "4"],
                ["5", "6", "7", "8", "9"],
                ["10", ">>"],
            ],
        )

    def test_layout_metrics_scale_button_width_and_column_count(self) -> None:
        ordinary = pagination_layout_metrics(300, 1.0)
        high_dpi = pagination_layout_metrics(300, 1.5)
        self.assertEqual(ordinary, {"columns": 5, "ui_units_x": 2.6})
        self.assertEqual(high_dpi, {"columns": 3, "ui_units_x": 3.9})


if __name__ == "__main__":
    unittest.main()
