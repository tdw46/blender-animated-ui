from __future__ import annotations

import ast
import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "blender_manifest.toml"


class ManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = tomllib.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_manifest_and_legacy_versions_match(self) -> None:
        tree = ast.parse((ROOT / "__init__.py").read_text(encoding="utf-8"))
        bl_info = next(
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "bl_info"
                for target in node.targets
            )
        )
        legacy_version = ".".join(str(value) for value in bl_info["version"])
        self.assertEqual(self.manifest["version"], legacy_version)

    def test_permission_reasons_fit_blender_limit(self) -> None:
        for permission, reason in self.manifest.get("permissions", {}).items():
            with self.subTest(permission=permission):
                self.assertLessEqual(len(reason), 64)

    def test_runtime_and_legal_files_exist(self) -> None:
        required = (
            "__init__.py",
            "animated_webp.py",
            "auto_load.py",
            "blender_manifest.toml",
            "LICENSE",
            "THIRD_PARTY_NOTICES.md",
        )
        self.assertEqual(
            [name for name in required if not (ROOT / name).is_file()],
            [],
        )

    def test_manifest_declares_complete_media_wheel_matrix(self) -> None:
        declared = {Path(value).name for value in self.manifest.get("wheels", ())}
        present = {path.name for path in (ROOT / "wheels").glob("*.whl")}
        self.assertEqual(declared, present)
        self.assertEqual(len(declared), 15)
        imageio_wheels = {
            name for name in declared if name.startswith("imageio_ffmpeg-")
        }
        pillow_wheels = {name for name in declared if name.startswith("pillow-")}
        self.assertEqual(len(imageio_wheels), 5)
        self.assertEqual(len(pillow_wheels), 10)
        for platform_tag in (
            "macosx_11_0_arm64",
            "macosx_10_",
            "manylinux_2_27_aarch64",
            "manylinux_2_27_x86_64",
            "win_amd64",
        ):
            with self.subTest(platform_tag=platform_tag):
                matches = {name for name in pillow_wheels if platform_tag in name}
                self.assertEqual(len(matches), 2)
                self.assertTrue(any("-cp311-cp311-" in name for name in matches))
                self.assertTrue(any("-cp313-cp313-" in name for name in matches))

    def test_readme_uses_only_the_two_current_animated_previews(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        previews = re.findall(r"\((resources/[^)]+\.webp)\)", readme)
        self.assertEqual(
            previews,
            [
                "resources/blender-animated-thumbs-1.webp",
                "resources/blender-animated-thumbs-2.webp",
            ],
        )
        self.assertTrue(all((ROOT / path).is_file() for path in previews))

    def test_build_excludes_development_and_generated_files(self) -> None:
        exclusions = set(self.manifest["build"]["paths_exclude_pattern"])
        for required_pattern in (
            "/.github/",
            "/.venv/",
            "/tests/",
            "/tools/",
            "*.zip",
            "*.pyc",
            "*.sh",
            "*.bat",
        ):
            with self.subTest(pattern=required_pattern):
                self.assertIn(required_pattern, exclusions)


if __name__ == "__main__":
    unittest.main()
