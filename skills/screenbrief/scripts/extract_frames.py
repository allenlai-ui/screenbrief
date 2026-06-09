#!/usr/bin/env python3
"""Extract AI-ready scene-change and 1fps frames from a video."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


SHOWINFO_RE = re.compile(r"showinfo.*?\bn:\s*(?P<n>\d+).*?\bpts_time:(?P<pts_time>[-+0-9.eE]+|N/A)")


@dataclass(frozen=True)
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


def main() -> int:
    args = parse_args()
    try:
        validate_args(args)
        require_tool("ffmpeg")
        require_tool("ffprobe")

        source = args.source
        manual_requests = build_manual_requests(args.extra_timestamps, args.extra_neighbor_seconds)
        output_dir = resolve_output_dir(source, args.output_dir)
        priority_dir = output_dir / "priority-scenes"
        backup_dir = output_dir / "backup-1fps"
        manual_dir = output_dir / "manual-frames"
        ui_state_dir = output_dir / "ui-states"
        storyboard_dir = output_dir / "storyboard"
        logs_dir = output_dir / "logs"

        if args.append_manual_frames:
            if not output_dir.exists():
                raise FileNotFoundError(f"--output-dir does not exist: {output_dir}")
            if not (output_dir / "manifest.json").exists():
                raise FileNotFoundError(f"existing output folder has no manifest.json: {output_dir}")
            manual_dir.mkdir(exist_ok=True)
            storyboard_dir.mkdir(exist_ok=True)
            logs_dir.mkdir(exist_ok=True)
        else:
            output_dir.mkdir(parents=True, exist_ok=False)
            priority_dir.mkdir(exist_ok=True)
            backup_dir.mkdir(exist_ok=True)
            if manual_requests:
                manual_dir.mkdir(exist_ok=True)
            if not args.disable_ui_states:
                ui_state_dir.mkdir(exist_ok=True)
            if not args.disable_storyboard:
                storyboard_dir.mkdir(exist_ok=True)
            logs_dir.mkdir(exist_ok=True)

        ffprobe_result = run_command(ffprobe_command(source))
        write_text(logs_dir / "ffprobe.stdout.log", ffprobe_result.stdout)
        write_text(logs_dir / "ffprobe.stderr.log", ffprobe_result.stderr)
        if ffprobe_result.returncode != 0:
            raise RuntimeError("ffprobe failed. See logs/ffprobe.stderr.log.")

        metadata = parse_ffprobe_json(ffprobe_result.stdout)
        write_json(logs_dir / "ffprobe.json", metadata)
        validate_manual_requests(manual_requests, summarize_video_metadata(metadata).get("duration_seconds"))

        scale_filter = make_scale_filter(args.max_long_side)

        if args.append_manual_frames:
            manual_frames = extract_manual_frames(
                source=source,
                manual_requests=manual_requests,
                output_dir=output_dir,
                manual_dir=manual_dir,
                logs_dir=logs_dir,
                jpeg_quality=args.jpeg_quality,
                scale_filter=scale_filter,
                start_ordinal=count_existing_manual_frames(manual_dir) + 1,
            )
            append_frame_index(output_dir / "frame-index.tsv", manual_frames)
            manual_sheet = make_contact_sheet(
                image_pattern=manual_dir / "manual_%06d.jpg",
                output_path=output_dir / "contact-sheet-manual.jpg",
                tile="4x6",
                frame_count=count_existing_manual_frames(manual_dir),
            )
            manifest = append_manual_manifest(
                output_dir=output_dir,
                args=args,
                manual_requests=manual_requests,
                manual_frames=manual_frames,
                manual_sheet=manual_sheet,
            )
            if not args.disable_storyboard:
                storyboard = generate_storyboard(
                    output_dir=output_dir,
                    storyboard_dir=storyboard_dir,
                    logs_dir=logs_dir,
                    records=select_storyboard_records(
                        priority_frames=manifest.get("priority_frames", []),
                        ui_state_frames=manifest.get("ui_state_frames", []),
                        manual_frames=manifest.get("manual_frames", []),
                        backup_frames=manifest.get("backup_frames", []),
                        max_frames=args.max_storyboard_frames,
                    ),
                    columns=args.storyboard_columns,
                    rows=args.storyboard_rows,
                    card_width=args.storyboard_card_width,
                )
                manifest["storyboard"] = storyboard
            write_json(output_dir / "manifest.json", manifest)
            write_text(output_dir / "ai-summary-prompt.md", make_ai_prompt(manifest))
            print(json.dumps(summarize_for_stdout(manifest), ensure_ascii=False, indent=2))
            return 0

        scene_result = extract_priority_scenes(
            source=source,
            output_pattern=priority_dir / "scene_%06d.jpg",
            scene_threshold=args.scene_threshold,
            min_scene_gap=args.min_scene_gap,
            max_priority_frames=args.max_priority_frames,
            jpeg_quality=args.jpeg_quality,
            scale_filter=scale_filter,
        )
        write_text(logs_dir / "priority-scenes.stderr.log", scene_result.stderr)
        write_text(logs_dir / "priority-scenes.stdout.log", scene_result.stdout)
        if scene_result.returncode != 0:
            raise RuntimeError("ffmpeg scene-change extraction failed. See logs/priority-scenes.stderr.log.")

        scene_extraction = {
            "fallback_attempted": False,
            "fallback_used": False,
            "effective_scene_threshold": args.scene_threshold,
            "effective_min_scene_gap": args.min_scene_gap,
            "attempts": [
                {
                    "label": "primary",
                    "scene_threshold": args.scene_threshold,
                    "min_scene_gap": args.min_scene_gap,
                }
            ],
        }
        priority_frames = build_frame_records(
            kind="priority-scene",
            directory=priority_dir,
            filename_prefix="scene",
            stderr=scene_result.stderr,
            output_dir=output_dir,
        )

        if (
            not priority_frames
            and not args.disable_scene_fallback
            and args.scene_threshold > args.fallback_scene_threshold
        ):
            scene_extraction["fallback_attempted"] = True
            scene_result = extract_priority_scenes(
                source=source,
                output_pattern=priority_dir / "scene_%06d.jpg",
                scene_threshold=args.fallback_scene_threshold,
                min_scene_gap=args.fallback_min_scene_gap,
                max_priority_frames=args.max_priority_frames,
                jpeg_quality=args.jpeg_quality,
                scale_filter=scale_filter,
            )
            write_text(logs_dir / "priority-scenes.fallback.stderr.log", scene_result.stderr)
            write_text(logs_dir / "priority-scenes.fallback.stdout.log", scene_result.stdout)
            write_text(logs_dir / "priority-scenes.stderr.log", scene_result.stderr)
            write_text(logs_dir / "priority-scenes.stdout.log", scene_result.stdout)
            if scene_result.returncode != 0:
                raise RuntimeError(
                    "ffmpeg fallback scene-change extraction failed. See logs/priority-scenes.fallback.stderr.log."
                )
            priority_frames = build_frame_records(
                kind="priority-scene",
                directory=priority_dir,
                filename_prefix="scene",
                stderr=scene_result.stderr,
                output_dir=output_dir,
            )
            scene_extraction["fallback_used"] = bool(priority_frames)
            scene_extraction["effective_scene_threshold"] = args.fallback_scene_threshold
            scene_extraction["effective_min_scene_gap"] = args.fallback_min_scene_gap
            scene_extraction["attempts"].append(
                {
                    "label": "fallback",
                    "scene_threshold": args.fallback_scene_threshold,
                    "min_scene_gap": args.fallback_min_scene_gap,
                }
            )

        backup_result = extract_backup_frames(
            source=source,
            output_pattern=backup_dir / "frame_%06d.jpg",
            backup_fps=args.backup_fps,
            jpeg_quality=args.jpeg_quality,
            scale_filter=scale_filter,
        )
        write_text(logs_dir / "backup-1fps.stderr.log", backup_result.stderr)
        write_text(logs_dir / "backup-1fps.stdout.log", backup_result.stdout)
        if backup_result.returncode != 0:
            raise RuntimeError("ffmpeg 1fps extraction failed. See logs/backup-1fps.stderr.log.")

        backup_frames = build_frame_records(
            kind="backup-1fps",
            directory=backup_dir,
            filename_prefix="frame",
            stderr=backup_result.stderr,
            output_dir=output_dir,
        )

        manual_frames = []
        if manual_requests:
            manual_frames = extract_manual_frames(
                source=source,
                manual_requests=manual_requests,
                output_dir=output_dir,
                manual_dir=manual_dir,
                logs_dir=logs_dir,
                jpeg_quality=args.jpeg_quality,
                scale_filter=scale_filter,
                start_ordinal=1,
            )

        ui_state_frames = []
        if not args.disable_ui_states:
            ui_state_frames = extract_ui_state_frames(
                output_dir=output_dir,
                ui_state_dir=ui_state_dir,
                backup_frames=backup_frames,
                threshold=args.ui_state_threshold,
                thumb_size=args.ui_state_thumb_size,
                max_states=args.max_ui_states,
            )

        write_frame_index(output_dir / "frame-index.tsv", priority_frames + ui_state_frames + backup_frames + manual_frames)

        contact_sheets = []
        priority_sheet = make_contact_sheet(
            image_pattern=priority_dir / "scene_%06d.jpg",
            output_path=output_dir / "contact-sheet-priority.jpg",
            tile="4x6",
            frame_count=len(priority_frames),
        )
        if priority_sheet:
            contact_sheets.append(priority_sheet)

        backup_sheet = make_contact_sheet(
            image_pattern=backup_dir / "frame_%06d.jpg",
            output_path=output_dir / "contact-sheet-backup-1fps.jpg",
            tile="5x8",
            frame_count=len(backup_frames),
        )
        if backup_sheet:
            contact_sheets.append(backup_sheet)

        ui_state_sheet = make_contact_sheet(
            image_pattern=ui_state_dir / "state_%06d.jpg",
            output_path=output_dir / "contact-sheet-ui-states.jpg",
            tile="4x6",
            frame_count=len(ui_state_frames),
        )
        if ui_state_sheet:
            contact_sheets.append(ui_state_sheet)

        manual_sheet = make_contact_sheet(
            image_pattern=manual_dir / "manual_%06d.jpg",
            output_path=output_dir / "contact-sheet-manual.jpg",
            tile="4x6",
            frame_count=len(manual_frames),
        )
        if manual_sheet:
            contact_sheets.append(manual_sheet)

        storyboard = None
        if not args.disable_storyboard:
            storyboard = generate_storyboard(
                output_dir=output_dir,
                storyboard_dir=storyboard_dir,
                logs_dir=logs_dir,
                records=select_storyboard_records(
                    priority_frames=priority_frames,
                    ui_state_frames=ui_state_frames,
                    manual_frames=manual_frames,
                    backup_frames=backup_frames,
                    max_frames=args.max_storyboard_frames,
                ),
                columns=args.storyboard_columns,
                rows=args.storyboard_rows,
                card_width=args.storyboard_card_width,
            )

        manifest = build_manifest(
            source=source,
            output_dir=output_dir,
            args=args,
            metadata=metadata,
            priority_frames=priority_frames,
            backup_frames=backup_frames,
            ui_state_frames=ui_state_frames,
            manual_frames=manual_frames,
            manual_requests=manual_requests,
            contact_sheets=contact_sheets,
            scene_extraction=scene_extraction,
            storyboard=storyboard,
        )
        write_json(output_dir / "manifest.json", manifest)
        write_text(output_dir / "ai-summary-prompt.md", make_ai_prompt(manifest))

        print(json.dumps(summarize_for_stdout(manifest), ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract scene-change priority frames and regular backup frames for AI video understanding.",
    )
    parser.add_argument("source", help="Local video path or direct video URL.")
    parser.add_argument("--output-dir", help="Exact output folder. Defaults to ./<video-name>-ai-frames-YYYYMMDD-HHMMSS-ffffff.")
    parser.add_argument("--scene-threshold", type=float, default=0.35, help="Scene-change threshold. Lower values extract more frames.")
    parser.add_argument("--fallback-scene-threshold", type=float, default=0.05, help="Fallback scene threshold when the primary pass extracts no priority frames.")
    parser.add_argument("--backup-fps", type=float, default=1.0, help="Backup timeline frame rate. Default: 1 frame per second.")
    parser.add_argument("--max-long-side", type=int, default=1600, help="Maximum long side for output images. Default: 1600.")
    parser.add_argument("--min-scene-gap", type=float, default=1.5, help="Minimum seconds between priority scene frames.")
    parser.add_argument("--fallback-min-scene-gap", type=float, default=0.5, help="Fallback minimum seconds between priority scene frames.")
    parser.add_argument("--max-priority-frames", type=int, default=120, help="Maximum number of priority scene frames.")
    parser.add_argument(
        "--extra-timestamps",
        "--extra-at",
        action="append",
        default=[],
        help='Manual supplemental timestamps to extract into manual-frames. Supports "12", "18.5", "01:02", or comma-separated lists.',
    )
    parser.add_argument(
        "--extra-neighbor-seconds",
        type=float,
        default=0.0,
        help="Also extract frames this many seconds before and after each manual timestamp. Default: 0.",
    )
    parser.add_argument(
        "--append-manual-frames",
        action="store_true",
        help="Append manual frames to an existing --output-dir without rerunning automatic extraction. Requires --extra-timestamps.",
    )
    parser.add_argument("--ui-state-threshold", type=float, default=0.04, help="Normalized visual difference threshold for ui-states.")
    parser.add_argument("--ui-state-thumb-size", type=int, default=32, help="Thumbnail size used for ui-state visual comparison.")
    parser.add_argument("--max-ui-states", type=int, default=24, help="Maximum UI state frames to copy from backup frames.")
    parser.add_argument("--disable-ui-states", action="store_true", help="Disable UI state dedupe output.")
    parser.add_argument("--max-storyboard-frames", type=int, default=60, help="Maximum frames included in the storyboard.")
    parser.add_argument("--storyboard-columns", type=int, default=2, help="Storyboard page columns.")
    parser.add_argument("--storyboard-rows", type=int, default=3, help="Storyboard page rows.")
    parser.add_argument("--storyboard-card-width", type=int, default=360, help="Storyboard card width in pixels.")
    parser.add_argument("--disable-storyboard", action="store_true", help="Disable storyboard output.")
    parser.add_argument("--jpeg-quality", type=int, default=2, help="FFmpeg JPEG quality, 2 is high quality.")
    parser.add_argument("--disable-scene-fallback", action="store_true", help="Disable the low-threshold priority scene fallback pass.")
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not is_url(args.source):
        source_path = Path(args.source).expanduser()
        if not source_path.exists():
            raise FileNotFoundError(f"source file does not exist: {source_path}")
    if not 0 < args.scene_threshold < 1:
        raise ValueError("--scene-threshold must be between 0 and 1.")
    if not 0 < args.fallback_scene_threshold < 1:
        raise ValueError("--fallback-scene-threshold must be between 0 and 1.")
    if args.backup_fps <= 0:
        raise ValueError("--backup-fps must be greater than 0.")
    if args.max_long_side < 320:
        raise ValueError("--max-long-side should be at least 320.")
    if args.min_scene_gap < 0:
        raise ValueError("--min-scene-gap must be 0 or greater.")
    if args.fallback_min_scene_gap < 0:
        raise ValueError("--fallback-min-scene-gap must be 0 or greater.")
    if args.max_priority_frames <= 0:
        raise ValueError("--max-priority-frames must be greater than 0.")
    if args.extra_neighbor_seconds < 0:
        raise ValueError("--extra-neighbor-seconds must be 0 or greater.")
    if args.append_manual_frames:
        if not args.output_dir:
            raise ValueError("--append-manual-frames requires --output-dir.")
        if not args.extra_timestamps:
            raise ValueError("--append-manual-frames requires --extra-timestamps.")
    if not 0 <= args.ui_state_threshold <= 1:
        raise ValueError("--ui-state-threshold must be between 0 and 1.")
    if args.ui_state_thumb_size <= 0:
        raise ValueError("--ui-state-thumb-size must be greater than 0.")
    if args.max_ui_states <= 0:
        raise ValueError("--max-ui-states must be greater than 0.")
    if args.max_storyboard_frames <= 0:
        raise ValueError("--max-storyboard-frames must be greater than 0.")
    if args.storyboard_columns <= 0:
        raise ValueError("--storyboard-columns must be greater than 0.")
    if args.storyboard_rows <= 0:
        raise ValueError("--storyboard-rows must be greater than 0.")
    if args.storyboard_card_width < 160:
        raise ValueError("--storyboard-card-width should be at least 160.")
    if not 1 <= args.jpeg_quality <= 31:
        raise ValueError("--jpeg-quality must be between 1 and 31.")


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"{name} is required but was not found on PATH.")


def is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https", "ftp", "s3"}


def source_for_ffmpeg(source: str) -> str:
    if is_url(source):
        return source
    return str(Path(source).expanduser())


def resolve_output_dir(source: str, output_dir: str | None) -> Path:
    if output_dir:
        return Path(output_dir).expanduser().resolve()

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    slug = slugify(source_basename(source))
    return Path.cwd() / f"{slug}-ai-frames-{timestamp}"


def source_basename(source: str) -> str:
    if is_url(source):
        parsed = urlparse(source)
        name = Path(unquote(parsed.path)).stem
        return name or "video"
    return Path(source).expanduser().stem or "video"


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value.strip()).lower()
    pieces: list[str] = []
    previous_dash = False
    for character in normalized:
        if character.isalnum() or character in "._-":
            pieces.append(character)
            previous_dash = False
        elif not previous_dash:
            pieces.append("-")
            previous_dash = True

    slug = "".join(pieces).strip("-._")
    return (slug or "video")[:80]


def ffprobe_command(source: str) -> list[str]:
    return [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        source_for_ffmpeg(source),
    ]


def make_scale_filter(max_long_side: int) -> str:
    return f"scale='min({max_long_side},iw)':'min({max_long_side},ih)':force_original_aspect_ratio=decrease"


def escape_ffmpeg_filter_value(value: str | Path) -> str:
    special_characters = {"\\", "'", ":", ",", ";", "[", "]"}
    escaped: list[str] = []
    for character in str(value):
        if character in special_characters or character.isspace():
            escaped.append(f"\\{character}")
        else:
            escaped.append(character)
    return "".join(escaped)


def extract_priority_scenes(
    *,
    source: str,
    output_pattern: Path,
    scene_threshold: float,
    min_scene_gap: float,
    max_priority_frames: int,
    jpeg_quality: int,
    scale_filter: str,
) -> CommandResult:
    select_expr = (
        f"gt(scene,{scene_threshold:g})"
        f"*if(isnan(prev_selected_t),1,gte(t-prev_selected_t,{min_scene_gap:g}))"
    )
    vf = f"select='{select_expr}',showinfo,{scale_filter}"
    command = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        source_for_ffmpeg(source),
        "-vf",
        vf,
        "-vsync",
        "vfr",
        "-frames:v",
        str(max_priority_frames),
        "-q:v",
        str(jpeg_quality),
        str(output_pattern),
    ]
    return run_command(command)


def extract_backup_frames(
    *,
    source: str,
    output_pattern: Path,
    backup_fps: float,
    jpeg_quality: int,
    scale_filter: str,
) -> CommandResult:
    vf = f"fps={backup_fps:g},showinfo,{scale_filter}"
    command = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        source_for_ffmpeg(source),
        "-vf",
        vf,
        "-q:v",
        str(jpeg_quality),
        str(output_pattern),
    ]
    return run_command(command)


def extract_manual_frame(
    *,
    source: str,
    timestamp_seconds: float,
    output_path: Path,
    jpeg_quality: int,
    scale_filter: str,
) -> CommandResult:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-ss",
        f"{timestamp_seconds:.3f}",
        "-i",
        source_for_ffmpeg(source),
        "-vf",
        scale_filter,
        "-frames:v",
        "1",
        "-q:v",
        str(jpeg_quality),
        str(output_path),
    ]
    return run_command(command)


def extract_manual_frames(
    *,
    source: str,
    manual_requests: list[dict[str, Any]],
    output_dir: Path,
    manual_dir: Path,
    logs_dir: Path,
    jpeg_quality: int,
    scale_filter: str,
    start_ordinal: int,
) -> list[dict[str, Any]]:
    frames = []
    for ordinal, request in enumerate(manual_requests, start=start_ordinal):
        output_path = manual_dir / f"manual_{ordinal:06d}.jpg"
        result = extract_manual_frame(
            source=source,
            timestamp_seconds=request["timestamp_seconds"],
            output_path=output_path,
            jpeg_quality=jpeg_quality,
            scale_filter=scale_filter,
        )
        log_prefix = logs_dir / f"manual-frame-{ordinal:06d}"
        write_text(log_prefix.with_suffix(".stdout.log"), result.stdout)
        write_text(log_prefix.with_suffix(".stderr.log"), result.stderr)
        if result.returncode != 0 or not output_path.exists():
            raise RuntimeError(
                f"ffmpeg manual timestamp extraction failed at {request['timestamp_label']}. "
                f"See logs/{log_prefix.name}.stderr.log."
            )
        frames.append(
            {
                "kind": "manual-timestamp",
                "ordinal": ordinal,
                "relative_path": output_path.relative_to(output_dir).as_posix(),
                "timestamp_seconds": request["timestamp_seconds"],
                "timestamp_label": request["timestamp_label"],
                "requested_timestamp_seconds": request["requested_timestamp_seconds"],
                "requested_timestamp_label": request["requested_timestamp_label"],
                "offset_seconds": request["offset_seconds"],
            }
        )
    return frames


def count_existing_manual_frames(manual_dir: Path) -> int:
    return len(sorted(manual_dir.glob("manual_*.jpg")))


def extract_ui_state_frames(
    *,
    output_dir: Path,
    ui_state_dir: Path,
    backup_frames: list[dict[str, Any]],
    threshold: float,
    thumb_size: int,
    max_states: int,
) -> list[dict[str, Any]]:
    def thumbnail_provider(record: dict[str, Any]) -> bytes:
        return read_thumbnail_bytes(output_dir / record["relative_path"], thumb_size)

    selected = select_ui_state_records(
        backup_frames,
        thumbnail_provider=thumbnail_provider,
        threshold=threshold,
        max_states=max_states,
    )
    for record in selected:
        source_path = output_dir / record["source_relative_path"]
        destination_path = output_dir / record["relative_path"]
        destination_path.parent.mkdir(exist_ok=True)
        shutil.copy2(source_path, destination_path)
    return selected


def read_thumbnail_bytes(path: Path, size: int) -> bytes:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-v",
        "error",
        "-i",
        str(path),
        "-vf",
        f"scale={size}:{size},format=gray",
        "-f",
        "rawvideo",
        "-",
    ]
    result = subprocess.run(command, check=False, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"failed to create UI-state thumbnail for {path}")
    return result.stdout


def select_ui_state_records(
    backup_frames: list[dict[str, Any]],
    *,
    thumbnail_provider,
    threshold: float,
    max_states: int,
) -> list[dict[str, Any]]:
    candidates = []
    last_thumbnail = None
    for frame in backup_frames:
        thumbnail = thumbnail_provider(frame)
        difference = 1.0 if last_thumbnail is None else normalized_mean_absolute_difference(last_thumbnail, thumbnail)
        if last_thumbnail is None or difference >= threshold:
            candidates.append(
                {
                    "kind": "ui-state",
                    "source_relative_path": frame["relative_path"],
                    "timestamp_seconds": frame["timestamp_seconds"],
                    "timestamp_label": frame["timestamp_label"],
                    "difference_score": round(difference, 6),
                }
            )
            last_thumbnail = thumbnail
    selected = evenly_sample_records(candidates, max_states)
    return reindex_ui_state_records(selected)


def evenly_sample_records(records: list[dict[str, Any]], max_count: int) -> list[dict[str, Any]]:
    if len(records) <= max_count:
        return records
    if max_count == 1:
        return [records[0]]

    last_index = len(records) - 1
    indices = [round(index * last_index / (max_count - 1)) for index in range(max_count)]
    return [records[index] for index in indices]


def reindex_ui_state_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reindexed = []
    for ordinal, record in enumerate(records, start=1):
        item = dict(record)
        item["ordinal"] = ordinal
        item["relative_path"] = f"ui-states/state_{ordinal:06d}.jpg"
        reindexed.append(item)
    return reindexed


def normalized_mean_absolute_difference(left: bytes, right: bytes) -> float:
    if len(left) != len(right):
        raise ValueError("thumbnail byte lengths must match")
    if not left:
        return 0.0
    total = sum(abs(a - b) for a, b in zip(left, right))
    return total / (len(left) * 255)


def select_storyboard_records(
    *,
    priority_frames: list[dict[str, Any]],
    ui_state_frames: list[dict[str, Any]],
    manual_frames: list[dict[str, Any]],
    backup_frames: list[dict[str, Any]],
    max_frames: int,
) -> list[dict[str, Any]]:
    compact_records = dedupe_records_by_path(priority_frames + ui_state_frames + manual_frames)
    records = compact_records if compact_records else backup_frames
    return sorted(records, key=record_sort_key)[:max_frames]


def dedupe_records_by_path(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for record in records:
        path = record.get("relative_path")
        if path in seen:
            continue
        seen.add(path)
        deduped.append(record)
    return deduped


def record_sort_key(record: dict[str, Any]) -> tuple[float, str]:
    timestamp = record.get("timestamp_seconds")
    if timestamp is None:
        timestamp = float("inf")
    return float(timestamp), record.get("relative_path", "")


def generate_storyboard(
    *,
    output_dir: Path,
    storyboard_dir: Path,
    logs_dir: Path,
    records: list[dict[str, Any]],
    columns: int,
    rows: int,
    card_width: int,
) -> dict[str, Any] | None:
    if not records:
        return None

    storyboard_dir.mkdir(exist_ok=True)
    clear_storyboard_outputs(storyboard_dir)
    labeled_dir = logs_dir / "storyboard-labeled"
    labeled_dir.mkdir(exist_ok=True)
    page_work_dir = logs_dir / "storyboard-pages"
    page_work_dir.mkdir(exist_ok=True)

    card_height = int(card_width * 14 / 9)
    label_height = 72
    labeled_paths = []
    items = []
    for index, record in enumerate(records, start=1):
        source_path = output_dir / record["relative_path"]
        labeled_path = labeled_dir / f"labeled_{index:06d}.jpg"
        label_text = storyboard_label(record)
        label_file = labeled_dir / f"label_{index:06d}.txt"
        write_text(label_file, label_text)
        result = label_storyboard_card(
            source_path=source_path,
            output_path=labeled_path,
            label_file=label_file,
            card_width=card_width,
            card_height=card_height,
            label_height=label_height,
        )
        write_text((labeled_dir / f"labeled_{index:06d}.stdout.log"), result.stdout)
        write_text((labeled_dir / f"labeled_{index:06d}.stderr.log"), result.stderr)
        if result.returncode != 0:
            raise RuntimeError(f"failed to label storyboard card for {record['relative_path']}")
        labeled_paths.append(labeled_path)
        items.append(
            {
                "ordinal": index,
                "kind": record["kind"],
                "timestamp_seconds": record.get("timestamp_seconds"),
                "timestamp_label": record.get("timestamp_label", ""),
                "relative_path": record["relative_path"],
            }
        )

    page_size = columns * rows
    blank_path = page_work_dir / "blank.jpg"
    create_blank_card(blank_path, card_width, card_height + label_height)

    pages = []
    for page_index, start in enumerate(range(0, len(labeled_paths), page_size), start=1):
        page_dir = page_work_dir / f"page_{page_index:03d}"
        page_dir.mkdir(exist_ok=True)
        chunk = labeled_paths[start : start + page_size]
        for slot_index in range(page_size):
            slot_path = page_dir / f"slot_{slot_index + 1:06d}.jpg"
            source = chunk[slot_index] if slot_index < len(chunk) else blank_path
            shutil.copy2(source, slot_path)
        page_path = storyboard_dir / f"storyboard-page-{page_index:03d}.jpg"
        result = tile_storyboard_page(
            image_pattern=page_dir / "slot_%06d.jpg",
            output_path=page_path,
            columns=columns,
            rows=rows,
        )
        write_text((page_dir / "tile.stdout.log"), result.stdout)
        write_text((page_dir / "tile.stderr.log"), result.stderr)
        if result.returncode != 0:
            raise RuntimeError(f"failed to create storyboard page {page_index}")
        pages.append(page_path.relative_to(output_dir).as_posix())

    write_text(storyboard_dir / "storyboard.md", make_storyboard_markdown(pages, items))
    return {
        "pages": pages,
        "markdown": (storyboard_dir / "storyboard.md").relative_to(output_dir).as_posix(),
        "items": items,
        "columns": columns,
        "rows": rows,
    }


def clear_storyboard_outputs(storyboard_dir: Path) -> None:
    for path in storyboard_dir.glob("storyboard-page-*.jpg"):
        path.unlink()
    markdown = storyboard_dir / "storyboard.md"
    if markdown.exists():
        markdown.unlink()


def storyboard_label(record: dict[str, Any]) -> str:
    timestamp = record.get("timestamp_label") or ""
    kind = record.get("kind", "")
    path = record.get("relative_path", "")
    return f"{timestamp}  {kind}\n{path}"


def label_storyboard_card(
    *,
    source_path: Path,
    output_path: Path,
    label_file: Path,
    card_width: int,
    card_height: int,
    label_height: int,
) -> CommandResult:
    font = find_font_file()
    escaped_label_file = escape_ffmpeg_filter_value(label_file.name)
    drawtext = (
        f"drawtext=textfile={escaped_label_file}:fontcolor=black:fontsize=16:"
        f"x=10:y=10:line_spacing=4"
    )
    if font:
        drawtext += f":fontfile={escape_ffmpeg_filter_value(font)}"
    vf = (
        f"scale={card_width}:{card_height}:force_original_aspect_ratio=decrease,"
        f"pad={card_width}:{card_height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"pad={card_width}:{card_height + label_height}:0:{label_height}:color=white,"
        f"{drawtext}"
    )
    command = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(source_path),
        "-vf",
        vf,
        "-frames:v",
        "1",
        str(output_path),
    ]
    return run_command(command, cwd=label_file.parent)


def find_font_file() -> str | None:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None


def create_blank_card(path: Path, width: int, height: int) -> None:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=white:size={width}x{height}:duration=1",
        "-frames:v",
        "1",
        str(path),
    ]
    result = run_command(command)
    if result.returncode != 0:
        raise RuntimeError("failed to create storyboard blank card")


def tile_storyboard_page(
    *,
    image_pattern: Path,
    output_path: Path,
    columns: int,
    rows: int,
) -> CommandResult:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-framerate",
        "1",
        "-i",
        str(image_pattern),
        "-vf",
        f"tile={columns}x{rows}:margin=12:padding=8:color=white",
        "-frames:v",
        "1",
        str(output_path),
    ]
    return run_command(command)


def make_storyboard_markdown(pages: list[str], items: list[dict[str, Any]]) -> str:
    lines = [
        "# Video Storyboard",
        "",
        "## Pages",
        "",
    ]
    for page in pages:
        lines.append(f"- `{page}`")
    lines.extend(
        [
            "",
            "## Items",
            "",
            "| # | Time | Kind | Frame |",
            "|---:|---|---|---|",
        ]
    )
    for item in items:
        lines.append(
            f"| {item['ordinal']} | {item['timestamp_label']} | {item['kind']} | `{item['relative_path']}` |"
        )
    return "\n".join(lines) + "\n"


def run_command(args: list[str], *, cwd: Path | None = None) -> CommandResult:
    completed = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )
    return CommandResult(
        args=args,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def parse_ffprobe_json(stdout: str) -> dict[str, Any]:
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("ffprobe did not return valid JSON.") from error


def parse_showinfo(stderr: str) -> list[float | None]:
    timestamps: list[float | None] = []
    for line in stderr.splitlines():
        match = SHOWINFO_RE.search(line)
        if not match:
            continue
        value = match.group("pts_time")
        timestamps.append(None if value == "N/A" else float(value))
    return timestamps


def build_manual_requests(values: list[str], neighbor_seconds: float) -> list[dict[str, Any]]:
    base_timestamps = parse_timestamp_values(values)
    offsets = [0.0]
    if neighbor_seconds > 0:
        offsets = [-neighbor_seconds, 0.0, neighbor_seconds]

    seen = set()
    requests = []
    for requested in base_timestamps:
        for offset in offsets:
            timestamp = max(0.0, requested + offset)
            key = round(timestamp, 3)
            if key in seen:
                continue
            seen.add(key)
            requests.append(
                {
                    "timestamp_seconds": key,
                    "timestamp_label": format_timestamp(key),
                    "requested_timestamp_seconds": requested,
                    "requested_timestamp_label": format_timestamp(requested),
                    "offset_seconds": offset,
                }
            )
    return sorted(requests, key=lambda item: item["timestamp_seconds"])


def parse_timestamp_values(values: list[str]) -> list[float]:
    timestamps = []
    for value in values:
        for token in re.split(r"[,\s]+", value.strip()):
            if not token:
                continue
            timestamps.append(parse_timestamp_token(token))
    return timestamps


def parse_timestamp_token(token: str) -> float:
    parts = token.split(":")
    try:
        if len(parts) == 1:
            seconds = float(parts[0])
        elif len(parts) == 2:
            minutes = int(parts[0])
            seconds = minutes * 60 + float(parts[1])
        elif len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = hours * 3600 + minutes * 60 + float(parts[2])
        else:
            raise ValueError
    except ValueError as error:
        raise ValueError(f"invalid timestamp: {token}") from error

    if seconds < 0:
        raise ValueError(f"timestamp must be 0 or greater: {token}")
    return seconds


def validate_manual_requests(manual_requests: list[dict[str, Any]], duration_seconds: float | None) -> None:
    if duration_seconds is None:
        return
    for request in manual_requests:
        if request["timestamp_seconds"] > duration_seconds + 0.5:
            raise ValueError(
                f"manual timestamp {request['timestamp_label']} is beyond video duration "
                f"{format_timestamp(duration_seconds)}"
            )


def build_frame_records(
    *,
    kind: str,
    directory: Path,
    filename_prefix: str,
    stderr: str,
    output_dir: Path,
) -> list[dict[str, Any]]:
    timestamps = parse_showinfo(stderr)
    files = sorted(directory.glob(f"{filename_prefix}_*.jpg"))
    records = []
    for index, path in enumerate(files, start=1):
        timestamp = timestamps[index - 1] if index - 1 < len(timestamps) else None
        records.append(
            {
                "kind": kind,
                "ordinal": index,
                "relative_path": path.relative_to(output_dir).as_posix(),
                "timestamp_seconds": timestamp,
                "timestamp_label": format_timestamp(timestamp),
            }
        )
    return records


def format_timestamp(value: float | None) -> str:
    if value is None:
        return ""
    total_millis = max(0, int(round(value * 1000)))
    total_seconds = total_millis // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    millis = total_millis % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def write_frame_index(path: Path, records: list[dict[str, Any]]) -> None:
    lines = ["kind\tordinal\ttimestamp_seconds\ttimestamp_label\trelative_path"]
    for record in records:
        lines.append(format_frame_index_record(record))
    write_text(path, "\n".join(lines) + "\n")


def append_frame_index(path: Path, records: list[dict[str, Any]]) -> None:
    if not path.exists():
        write_frame_index(path, records)
        return
    lines = [format_frame_index_record(record) for record in records]
    if lines:
        with path.open("a", encoding="utf-8") as file:
            file.write("".join(f"{line}\n" for line in lines))


def format_frame_index_record(record: dict[str, Any]) -> str:
    timestamp = record["timestamp_seconds"]
    timestamp_text = "" if timestamp is None else f"{timestamp:.3f}"
    return "\t".join(
        [
            record["kind"],
            str(record["ordinal"]),
            timestamp_text,
            record["timestamp_label"],
            record["relative_path"],
        ]
    )


def make_contact_sheet(
    *,
    image_pattern: Path,
    output_path: Path,
    tile: str,
    frame_count: int,
) -> str | None:
    if frame_count == 0:
        return None
    command = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-framerate",
        "1",
        "-i",
        str(image_pattern),
        "-vf",
        f"scale=320:-1,tile={tile}",
        "-frames:v",
        "1",
        str(output_path),
    ]
    result = run_command(command)
    if result.returncode != 0:
        return None
    return output_path.name


def build_manifest(
    *,
    source: str,
    output_dir: Path,
    args: argparse.Namespace,
    metadata: dict[str, Any],
    priority_frames: list[dict[str, Any]],
    backup_frames: list[dict[str, Any]],
    ui_state_frames: list[dict[str, Any]],
    manual_frames: list[dict[str, Any]],
    manual_requests: list[dict[str, Any]],
    contact_sheets: list[str],
    scene_extraction: dict[str, Any],
    storyboard: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "source_type": "url" if is_url(source) else "file",
        "output_dir": str(output_dir),
        "parameters": {
            "scene_threshold": args.scene_threshold,
            "fallback_scene_threshold": args.fallback_scene_threshold,
            "backup_fps": args.backup_fps,
            "max_long_side": args.max_long_side,
            "min_scene_gap": args.min_scene_gap,
            "fallback_min_scene_gap": args.fallback_min_scene_gap,
            "max_priority_frames": args.max_priority_frames,
            "extra_timestamps": args.extra_timestamps,
            "extra_neighbor_seconds": args.extra_neighbor_seconds,
            "ui_state_threshold": args.ui_state_threshold,
            "ui_state_thumb_size": args.ui_state_thumb_size,
            "max_ui_states": args.max_ui_states,
            "ui_states_enabled": not args.disable_ui_states,
            "max_storyboard_frames": args.max_storyboard_frames,
            "storyboard_columns": args.storyboard_columns,
            "storyboard_rows": args.storyboard_rows,
            "storyboard_card_width": args.storyboard_card_width,
            "storyboard_enabled": not args.disable_storyboard,
            "jpeg_quality": args.jpeg_quality,
            "scene_fallback_enabled": not args.disable_scene_fallback,
        },
        "scene_extraction": scene_extraction,
        "manual_extraction": {
            "requested": bool(manual_requests),
            "requests": manual_requests,
        },
        "counts": {
            "priority_scene_frames": len(priority_frames),
            "ui_state_frames": len(ui_state_frames),
            "backup_frames": len(backup_frames),
            "manual_frames": len(manual_frames),
        },
        "contact_sheets": contact_sheets,
        "storyboard": storyboard,
        "video": summarize_video_metadata(metadata),
        "priority_frames": priority_frames,
        "ui_state_frames": ui_state_frames,
        "backup_frames": backup_frames,
        "manual_frames": manual_frames,
        "notes": [
            "Use storyboard/storyboard.md and storyboard pages for a timestamped overview.",
            "Use ui-states for deduped mobile UI states.",
            "Use priority-scenes for frames selected by large visual changes.",
            "Use backup-1fps when priority scenes miss slow UI changes or timeline context.",
            "Use manual-frames when the user requested specific supplemental timestamps.",
            "Timestamps are approximate and derived from ffmpeg showinfo output.",
        ],
    }


def append_manual_manifest(
    *,
    output_dir: Path,
    args: argparse.Namespace,
    manual_requests: list[dict[str, Any]],
    manual_frames: list[dict[str, Any]],
    manual_sheet: str | None,
) -> dict[str, Any]:
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    existing_manual_frames = manifest.get("manual_frames", [])
    manifest["manual_frames"] = existing_manual_frames + manual_frames

    counts = manifest.setdefault("counts", {})
    counts["manual_frames"] = len(manifest["manual_frames"])

    manual_extraction = manifest.setdefault("manual_extraction", {"requested": False, "requests": []})
    manual_extraction["requested"] = True
    manual_extraction.setdefault("requests", [])
    manual_extraction["requests"].extend(manual_requests)
    manual_extraction.setdefault("append_runs", [])
    manual_extraction["append_runs"].append(
        {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "extra_timestamps": args.extra_timestamps,
            "extra_neighbor_seconds": args.extra_neighbor_seconds,
            "frames_added": len(manual_frames),
            "requests": manual_requests,
            "frames": manual_frames,
        }
    )

    parameters = manifest.setdefault("parameters", {})
    parameters["last_extra_timestamps"] = args.extra_timestamps
    parameters["last_extra_neighbor_seconds"] = args.extra_neighbor_seconds

    contact_sheets = manifest.setdefault("contact_sheets", [])
    if manual_sheet and manual_sheet not in contact_sheets:
        contact_sheets.append(manual_sheet)

    notes = manifest.setdefault("notes", [])
    manual_note = "Use manual-frames when the user requested specific supplemental timestamps."
    if manual_note not in notes:
        notes.append(manual_note)

    manifest["updated_at"] = datetime.now().isoformat(timespec="seconds")
    return manifest


def summarize_video_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    streams = metadata.get("streams", [])
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    fmt = metadata.get("format", {})
    return {
        "duration_seconds": as_float(fmt.get("duration") or video_stream.get("duration")),
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "codec": video_stream.get("codec_name"),
        "avg_frame_rate": video_stream.get("avg_frame_rate"),
        "format_name": fmt.get("format_name"),
        "bit_rate": as_int(fmt.get("bit_rate")),
    }


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def make_ai_prompt(manifest: dict[str, Any]) -> str:
    counts = manifest["counts"]
    storyboard = manifest.get("storyboard")
    analysis_order = "Start with `priority-scenes/`. These frames were selected because the video changed visually at those moments."
    storyboard_lines = ""
    if storyboard:
        analysis_order = (
            "Start with `storyboard/storyboard.md` and `storyboard/storyboard-page-*.jpg` "
            "for the timestamped overview."
        )
        storyboard_lines = "\n- `storyboard/storyboard.md`: timestamped storyboard index.\n- `storyboard/storyboard-page-*.jpg`: visual pages with time and frame path labels.\n"
    return f"""# AI Video Understanding Prompt

You are given screenshots extracted from a video.

{analysis_order}

Use `ui-states/` for a deduped set of mobile UI states.

Use `priority-scenes/` for frames selected because the video changed visually at those moments.

Use `backup-1fps/` only when you need more timeline continuity, slow UI transitions, or context before/after a priority frame.

Use `manual-frames/` when the user requested exact supplemental timestamps after the first extraction pass.

Reference files:

- `manifest.json`: video metadata, parameters, and frame counts.
- `frame-index.tsv`: frame order, approximate timestamps, and relative paths.
- `contact-sheet-priority.jpg`: quick overview of priority frames when present.
- `contact-sheet-ui-states.jpg`: quick overview of deduped UI state frames when present.
- `contact-sheet-backup-1fps.jpg`: quick overview of backup frames when present.
- `contact-sheet-manual.jpg`: quick overview of manually requested frames when present.
{storyboard_lines}

Frame counts:

- Priority scene frames: {counts["priority_scene_frames"]}
- UI state frames: {counts["ui_state_frames"]}
- Backup timeline frames: {counts["backup_frames"]}
- Manual supplemental frames: {counts["manual_frames"]}

Task:

1. Summarize what happens in the video in chronological order.
2. Identify important UI states, transitions, errors, or user actions.
3. Mention exact frame paths and timestamps when citing evidence.
4. If priority frames are insufficient, request specific ranges from `backup-1fps/`.
"""


def summarize_for_stdout(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "output_dir": manifest["output_dir"],
        "priority_scene_frames": manifest["counts"]["priority_scene_frames"],
        "ui_state_frames": manifest["counts"].get("ui_state_frames", 0),
        "backup_frames": manifest["counts"]["backup_frames"],
        "manual_frames": manifest["counts"]["manual_frames"],
        "storyboard": manifest.get("storyboard", {}).get("markdown") if manifest.get("storyboard") else None,
        "manifest": "manifest.json",
        "frame_index": "frame-index.tsv",
        "prompt": "ai-summary-prompt.md",
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
