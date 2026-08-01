from __future__ import annotations

"""extract_frames_by_interval.py - Extract still images from a video at a fixed time interval.

Examples:
    python scripts/extract_frames_by_interval.py --input "C:\\Users\\dhana\\media-files\\talk.mp4" --interval-minutes 5
    python scripts/extract_frames_by_interval.py --input path/to/video.mp4 --output-dir path/to/frames --interval-minutes 2 --start 00:01:00 --end 00:10:00
    python scripts/extract_frames_by_interval.py --input path/to/video.mp4 --interval-minutes 0.5 --format png
"""

import argparse
import logging
import subprocess
import sys
from pathlib import Path

_DEFAULT_CONFIG = Path(__file__).parent.parent / "config" / "media-config.properties"


def load_properties(props_path: Path) -> dict[str, str]:
    props: dict[str, str] = {}
    for line in props_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            props[key.strip()] = value.strip()
    return props


def resolve_placeholders(value: str, props: dict[str, str]) -> str:
    if value.startswith("${") and value.endswith("}"):
        key = value[2:-1]
        if key == "user.home":
            return str(Path.home())
        import os

        return props.get(key, os.environ.get(key, value))
    return value


def resolve_all(props: dict[str, str]) -> dict[str, str]:
    return {k: resolve_placeholders(v, props) for k, v in props.items()}


def resolve_tool(tools_dir: Path, name: str) -> str:
    for candidate in (tools_dir / name, tools_dir / f"{name}.exe"):
        if candidate.exists():
            return str(candidate)
    return name


def parse_ts(ts: str) -> float:
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(parts[0])
    except (ValueError, IndexError):
        return 0.0


def format_hms(seconds: float) -> str:
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}h{m:02d}m{s:02d}s"


def run_logged_command(command: list[str], logger: logging.Logger, label: str) -> int:
    logger.info("[%s] %s", label, " ".join(command))
    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for raw_line in proc.stdout:
        line = raw_line.rstrip("\r\n")
        if line:
            logger.info("[%s] %s", label, line)
    return proc.wait()


def probe_duration(video_file: Path, ffprobe: str, logger: logging.Logger) -> float:
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_file),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("ffprobe failed: %s", result.stderr.strip())
        return 0.0
    try:
        duration = float(result.stdout.strip())
    except ValueError:
        logger.error("Could not parse ffprobe duration: %r", result.stdout)
        return 0.0
    logger.info("Input duration: %.3f seconds", duration)
    return duration


def extract_frames(
    input_video: Path,
    output_dir: Path,
    prefix: str,
    ext: str,
    start_s: float,
    end_s: float,
    interval_s: float,
    quality: int,
    ffmpeg: str,
    logger: logging.Logger,
) -> bool:
    cmd = [ffmpeg, "-hide_banner", "-y"]

    if start_s > 0:
        cmd += ["-ss", f"{start_s:.3f}"]
    cmd += ["-i", str(input_video)]

    range_s = end_s - start_s
    single_frame = interval_s >= range_s
    if single_frame:
        # The requested interval is longer than the selected range, so the fps
        # filter would never reach its first output timestamp. Grab one frame
        # from the start of the range instead.
        logger.warning(
            "Interval (%.2fs) >= available range (%.2fs); extracting a single frame at %.2fs",
            interval_s,
            range_s,
            start_s,
        )
        cmd += ["-frames:v", "1"]
    elif end_s > start_s:
        cmd += ["-t", f"{range_s:.3f}"]

    vf = "format=yuvj420p" if ext in ("jpg", "jpeg") else None
    if not single_frame:
        vf = f"fps=1/{interval_s:.6f}" + (f",{vf}" if vf else "")
    if vf:
        cmd += ["-vf", vf]

    if ext in ("jpg", "jpeg"):
        cmd += ["-q:v", str(quality)]

    tmp_pattern = output_dir / f"{prefix}_%06d.{ext}"
    cmd += [str(tmp_pattern)]

    logger.info("Extracting frames every %.2f seconds from %s", interval_s, input_video)
    return_code = run_logged_command(cmd, logger, "ffmpeg")
    if return_code != 0:
        logger.error("ffmpeg failed (exit %d)", return_code)
        return False
    return True


def rename_frames_with_timestamps(
    output_dir: Path,
    prefix: str,
    ext: str,
    start_s: float,
    interval_s: float,
    logger: logging.Logger,
) -> int:
    frames = sorted(output_dir.glob(f"{prefix}_[0-9][0-9][0-9][0-9][0-9][0-9].{ext}"))
    for index, frame_path in enumerate(frames):
        timestamp_s = start_s + index * interval_s
        new_name = f"{prefix}_{format_hms(timestamp_s)}.{ext}"
        frame_path.rename(output_dir / new_name)
    logger.info("Renamed %d frame(s) with timestamp labels", len(frames))
    return len(frames)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Extract still images from a video at a fixed time interval (in minutes)."
    )
    p.add_argument("--config", default=str(_DEFAULT_CONFIG), help="Config file path")
    p.add_argument("--input", required=True, help="Path to the source video file")
    p.add_argument("--output-dir", help="Directory to save extracted images (default: <video>_frames)")
    p.add_argument(
        "--interval-minutes",
        type=float,
        required=True,
        help="Interval between captured frames, in minutes (e.g. 5 or 0.5)",
    )
    p.add_argument("--start", default="", help="Start time HH:MM:SS (default: beginning of video)")
    p.add_argument("--end", default="", help="End time HH:MM:SS (default: end of video)")
    p.add_argument("--prefix", default="frame", help="Filename prefix for extracted images (default: frame)")
    p.add_argument(
        "--format",
        default="jpg",
        choices=["jpg", "jpeg", "png"],
        help="Image format for extracted frames (default: jpg)",
    )
    p.add_argument(
        "--quality",
        type=int,
        default=2,
        help="JPEG quality for ffmpeg -q:v, lower is better (default: 2, ignored for png)",
    )
    p.add_argument("--verbose", action="store_true", help="Enable DEBUG logs")
    return p


def main() -> int:
    args = build_arg_parser().parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("extract_frames_by_interval")

    if args.interval_minutes <= 0:
        logger.error("--interval-minutes must be greater than 0")
        return 1

    config_path = Path(args.config).expanduser().resolve()
    if not config_path.exists():
        logger.error("Config file not found: %s", config_path)
        return 1

    raw_props = load_properties(config_path)
    cfg = resolve_all(raw_props)

    tools_dir = Path(cfg.get("tools_dir", "")).expanduser()
    input_video = Path(args.input).expanduser().resolve()
    if not input_video.exists():
        logger.error("Input file not found: %s", input_video)
        return 1

    ffmpeg = resolve_tool(tools_dir, "ffmpeg")
    ffprobe = resolve_tool(tools_dir, "ffprobe")

    duration = probe_duration(input_video, ffprobe, logger)
    if duration <= 0:
        return 1

    start_s = parse_ts(args.start) if args.start else 0.0
    end_s = parse_ts(args.end) if args.end else duration

    if start_s >= end_s:
        logger.error("Start time (%.3f) must be before end time (%.3f)", start_s, end_s)
        return 1

    if args.output_dir:
        output_dir = Path(args.output_dir).expanduser().resolve()
    else:
        output_dir = input_video.parent / f"{input_video.stem}_frames"

    output_dir.mkdir(parents=True, exist_ok=True)

    ext = "jpg" if args.format == "jpeg" else args.format
    interval_s = args.interval_minutes * 60.0

    if not extract_frames(
        input_video=input_video,
        output_dir=output_dir,
        prefix=args.prefix,
        ext=ext,
        start_s=start_s,
        end_s=end_s,
        interval_s=interval_s,
        quality=args.quality,
        ffmpeg=ffmpeg,
        logger=logger,
    ):
        return 1

    frame_count = rename_frames_with_timestamps(
        output_dir=output_dir,
        prefix=args.prefix,
        ext=ext,
        start_s=start_s,
        interval_s=interval_s,
        logger=logger,
    )

    if frame_count == 0:
        logger.error("No frames were extracted")
        return 1

    logger.info("Done: %d frame(s) saved to %s", frame_count, output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
