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
