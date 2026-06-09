#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from types import SimpleNamespace
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "skills" / "screenbrief" / "scripts" / "extract_frames.py"


def load_extract_frames_module():
    spec = importlib.util.spec_from_file_location("screenbrief_extract_frames", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ExtractFramesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_extract_frames_module()

    def test_ui_state_cap_preserves_full_timeline_coverage(self):
        frames = [
            {
                "relative_path": f"backup-1fps/frame_{index:06d}.jpg",
                "timestamp_seconds": float(index),
                "timestamp_label": str(index),
            }
            for index in range(1, 101)
        ]

        selected = self.module.select_ui_state_records(
            frames,
            thumbnail_provider=lambda record: bytes([int(record["timestamp_seconds"]) % 256] * 16),
            threshold=0.0,
            max_states=10,
        )

        timestamps = [record["timestamp_seconds"] for record in selected]
        self.assertEqual(len(selected), 10)
        self.assertEqual(timestamps[0], 1.0)
        self.assertEqual(timestamps[-1], 100.0)
        self.assertGreaterEqual(max(timestamps), 90.0)
        self.assertEqual([record["ordinal"] for record in selected], list(range(1, 11)))
        self.assertEqual(selected[-1]["relative_path"], "ui-states/state_000010.jpg")

    def test_slugify_preserves_cjk_names(self):
        self.assertEqual(self.module.slugify("登入流程"), "登入流程")
        self.assertEqual(self.module.slugify("結帳 bug 重現"), "結帳-bug-重現")

    def test_default_output_dir_uses_unicode_slug_and_subsecond_timestamp(self):
        output_path = self.module.resolve_output_dir("登入流程.mp4", None)

        self.assertRegex(output_path.name, r"^登入流程-ai-frames-\d{8}-\d{6}-\d{6}$")

    def test_ffmpeg_filter_value_escapes_drawtext_path_separators(self):
        escaped = self.module.escape_ffmpeg_filter_value(Path("/tmp/My,Recordings/clip's:labels/label.txt"))

        self.assertEqual(escaped, r"/tmp/My\,Recordings/clip\'s\:labels/label.txt")

    def test_label_storyboard_card_uses_safe_relative_label_file(self):
        calls = []
        original_run_command = self.module.run_command
        original_find_font_file = self.module.find_font_file

        def fake_run_command(args, **kwargs):
            calls.append((args, kwargs))
            return self.module.CommandResult(args=args, returncode=0, stdout="", stderr="")

        try:
            self.module.run_command = fake_run_command
            self.module.find_font_file = lambda: None
            label_file = Path("/tmp/My,Recordings:clip's-output/logs/storyboard-labeled/label_000001.txt")

            self.module.label_storyboard_card(
                source_path=Path("/tmp/source.jpg"),
                output_path=Path("/tmp/output.jpg"),
                label_file=label_file,
                card_width=360,
                card_height=560,
                label_height=72,
            )
        finally:
            self.module.run_command = original_run_command
            self.module.find_font_file = original_find_font_file

        self.assertEqual(len(calls), 1)
        command, kwargs = calls[0]
        vf = command[command.index("-vf") + 1]
        self.assertIn("drawtext=textfile=label_000001.txt", vf)
        self.assertNotIn("My", vf)
        self.assertEqual(kwargs["cwd"], label_file.parent)

    def test_ai_prompt_is_storyboard_first_when_storyboard_exists(self):
        prompt = self.module.make_ai_prompt(
            {
                "counts": {
                    "priority_scene_frames": 2,
                    "ui_state_frames": 3,
                    "backup_frames": 10,
                    "manual_frames": 0,
                },
                "storyboard": {
                    "markdown": "storyboard/storyboard.md",
                    "pages": ["storyboard/storyboard-page-001.jpg"],
                },
            }
        )

        self.assertLess(prompt.index("storyboard/storyboard.md"), prompt.index("priority-scenes/"))

    def test_manifest_notes_are_storyboard_first(self):
        args = SimpleNamespace(
            scene_threshold=0.35,
            fallback_scene_threshold=0.05,
            backup_fps=1.0,
            max_long_side=1600,
            min_scene_gap=1.5,
            fallback_min_scene_gap=0.5,
            max_priority_frames=120,
            extra_timestamps=[],
            extra_neighbor_seconds=0.0,
            ui_state_threshold=0.04,
            ui_state_thumb_size=32,
            max_ui_states=24,
            disable_ui_states=False,
            max_storyboard_frames=60,
            storyboard_columns=2,
            storyboard_rows=3,
            storyboard_card_width=360,
            disable_storyboard=False,
            jpeg_quality=2,
            disable_scene_fallback=False,
        )

        manifest = self.module.build_manifest(
            source="input.mp4",
            output_dir=Path("/tmp/out"),
            args=args,
            metadata={"streams": [], "format": {}},
            priority_frames=[],
            backup_frames=[],
            ui_state_frames=[],
            manual_frames=[],
            manual_requests=[],
            contact_sheets=[],
            scene_extraction={},
            storyboard={
                "markdown": "storyboard/storyboard.md",
                "pages": ["storyboard/storyboard-page-001.jpg"],
            },
        )

        notes = "\n".join(manifest["notes"])
        self.assertLess(notes.index("storyboard/storyboard.md"), notes.index("priority-scenes"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
