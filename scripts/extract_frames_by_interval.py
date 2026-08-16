from __future__ import annotations

"""extract_frames_by_interval.py - Extract still images from a video at a fixed
time interval, or a single frame at a given timestamp.

Supports:
  - Local video files
  - YouTube video IDs / URLs (via yt-dlp)

Examples:
  # Local file, every 5 minutes
  python extract_frames_by_interval.py --input talk.mp4 --interval-minutes 5

  # Single frame at 01:23:45 from a local file
  python extract_frames_by_interval.py --input talk.mp4 --time 01:23:45

  # Single frame from a YouTube video ID
  python extract_frames_by_interval.py --input dQw4w9WgXcQ --time 00:01:30

  # YouTube URL + interval
  python extract_frames_by_interval.py --input "https://www.youtube.com/watch?v=dQw4w9WgXcQ" --interval-minutes 2

  # YouTube + custom output + format
  python extract_frames_by_interval.py --input dQw4w9WgXcQ --time 00:02:15 --output-dir ./yt_frames --format png
"""

import argparse
import logging
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_DEFAULT_CONFIG = Path(__file__).parent.parent / "config" / "media-config.properties"

# ---------------------------------------------------------------------------
# Config helpers (unchanged)
# ---------------------------------------------------------------------------

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
    # Fall back to PATH
    found = shutil.which(name)
    return found if found else name


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def parse_ts(ts: str) -> float:
    """Parse HH:MM:SS, MM:SS or seconds into float seconds."""
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


# ---------------------------------------------------------------------------
# YouTube detection + download
# ---------------------------------------------------------------------------

_YT_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|embed/|shorts/)|youtu\.be/)?([a-zA-Z0-9_-]{11})"
)


def is_youtube(value: str) -> bool:
    """Return True if the value looks like a YouTube URL or bare video ID."""
    value = value.strip()
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", value):
        return True
    return bool(_YT_ID_RE.search(value))


def extract_youtube_id(value: str) -> str | None:
    m = _YT_ID_RE.search(value.strip())
    return m.group(1) if m else None


def download_youtube(
    video_id_or_url: str,
    dest_dir: Path,
    yt_dlp: str,
    logger: logging.Logger,
    format_selector: str = "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
) -> Path | None:
    """
    Download a YouTube video with yt-dlp and return the path to the file.
    Uses a temporary directory so we don't pollute the working folder.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Let yt-dlp choose a sensible filename; we capture it afterwards.
    out_template = str(dest_dir / "%(id)s.%(ext)s")

    cmd = [
        yt_dlp,
        "--no-playlist",
        "--no-warnings",
        "-f", format_selector,
        "--merge-output-format", "mp4",
        "-o", out_template,
        video_id_or_url,
    ]

    logger.info("Downloading YouTube video with yt-dlp …")
    logger.debug("yt-dlp command: %s", " ".join(cmd))

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        logger.error("yt-dlp failed:\n%s", proc.stderr.strip() or proc.stdout.strip())
        return None

    # Find the downloaded file (yt-dlp may produce .mp4, .webm, .mkv …)
    video_id = extract_youtube_id(video_id_or_url) or "video"
    candidates = list(dest_dir.glob(f"{video_id}.*"))
    # Prefer mp4, then anything else that is not a part file
    candidates = [c for c in candidates if c.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"}]
    if not candidates:
        # Fallback: any non-part file
        candidates = [c for c in dest_dir.iterdir() if c.is_file() and not c.name.endswith(".part")]

    if not candidates:
        logger.error("yt-dlp finished but no video file was found in %s", dest_dir)
        return None

    downloaded = candidates[0]
    logger.info("Downloaded: %s (%.1f MB)", downloaded.name, downloaded.stat().st_size / 1e6)
    return downloaded


# ---------------------------------------------------------------------------
# Core extraction helpers
# ---------------------------------------------------------------------------

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
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
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


def extract_single_frame(
    input_video: Path,
    output_path: Path,
    timestamp_s: float,
    quality: int,
    ffmpeg: str,
    logger: logging.Logger,
) -> bool:
    """Extract one frame at the given timestamp."""
    cmd = [
        ffmpeg, "-hide_banner", "-y",
        "-ss", f"{timestamp_s:.3f}",
        "-i", str(input_video),
        "-frames:v", "1",
    ]
    if output_path.suffix.lower() in (".jpg", ".jpeg"):
        cmd += ["-q:v", str(quality)]
    cmd.append(str(output_path))

    logger.info("Extracting single frame at %.3fs → %s", timestamp_s, output_path.name)
    return_code = run_logged_command(cmd, logger, "ffmpeg")
    if return_code != 0:
        logger.error("ffmpeg failed (exit %d)", return_code)
        return False
    return True


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
        logger.warning(
            "Interval (%.2fs) >= available range (%.2fs); extracting a single frame at %.2fs",
            interval_s, range_s, start_s,
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Extract still images from a video (local file or YouTube) "
            "at a fixed interval or at a specific timestamp."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--config", default=str(_DEFAULT_CONFIG), help="Config file path")
    p.add_argument(
        "--input",
        required=True,
        help="Local video path, YouTube video ID, or YouTube URL",
    )
    p.add_argument(
        "--output-dir",
        help="Directory to save extracted images (default: <video>_frames or ./yt_<id>_frames)",
    )
    p.add_argument(
        "--interval-minutes",
        type=float,
        help="Interval between captured frames, in minutes (e.g. 5 or 0.5). "
             "Mutually exclusive with --time.",
    )
    p.add_argument(
        "--time",
        default="",
        help="Extract a single frame at this timestamp (HH:MM:SS or seconds). "
             "Mutually exclusive with --interval-minutes.",
    )
    p.add_argument("--start", default="", help="Start time HH:MM:SS (default: beginning)")
    p.add_argument("--end", default="", help="End time HH:MM:SS (default: end of video)")
    p.add_argument("--prefix", default="frame", help="Filename prefix (default: frame)")
    p.add_argument(
        "--format",
        default="jpg",
        choices=["jpg", "jpeg", "png"],
        help="Image format (default: jpg)",
    )
    p.add_argument(
        "--quality",
        type=int,
        default=2,
        help="JPEG quality for ffmpeg -q:v (lower = better, default: 2)",
    )
    p.add_argument(
        "--keep-download",
        action="store_true",
        help="When downloading from YouTube, keep the temporary video file",
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
    logger = logging.getLogger("extract_frames")

    # ---- Validate mode -------------------------------------------------------
    if args.time and args.interval_minutes is not None:
        logger.error("Use either --time (single frame) or --interval-minutes, not both")
        return 1
    if not args.time and args.interval_minutes is None:
        logger.error("You must supply either --time or --interval-minutes")
        return 1
    if args.interval_minutes is not None and args.interval_minutes <= 0:
        logger.error("--interval-minutes must be greater than 0")
        return 1

    # ---- Tools ---------------------------------------------------------------
    config_path = Path(args.config).expanduser().resolve()
    tools_dir = Path()
    if config_path.exists():
        raw_props = load_properties(config_path)
        cfg = resolve_all(raw_props)
        tools_dir = Path(cfg.get("tools_dir", "")).expanduser()
    else:
        logger.warning("Config file not found (%s) – looking for tools on PATH", config_path)

    ffmpeg = resolve_tool(tools_dir, "ffmpeg")
    ffprobe = resolve_tool(tools_dir, "ffprobe")
    yt_dlp = resolve_tool(tools_dir, "yt-dlp")

    # ---- Resolve input (local or YouTube) ------------------------------------
    input_arg = args.input.strip()
    temp_dir: Path | None = None
    input_video: Path
    youtube_id: str | None = None

    if is_youtube(input_arg):
        youtube_id = extract_youtube_id(input_arg)
        if not youtube_id:
            logger.error("Could not extract a valid YouTube video ID from: %s", input_arg)
            return 1

        logger.info("YouTube video detected: %s", youtube_id)

        # Create a temporary download directory
        temp_dir = Path(tempfile.mkdtemp(prefix="yt_frames_"))
        downloaded = download_youtube(input_arg, temp_dir, yt_dlp, logger)
        if downloaded is None:
            return 1
        input_video = downloaded
    else:
        input_video = Path(input_arg).expanduser().resolve()
        if not input_video.exists():
            logger.error("Input file not found: %s", input_video)
            return 1

    # ---- Duration & time range -----------------------------------------------
    duration = probe_duration(input_video, ffprobe, logger)
    if duration <= 0:
        return 1

    start_s = parse_ts(args.start) if args.start else 0.0
    end_s = parse_ts(args.end) if args.end else duration

    if start_s >= end_s:
        logger.error("Start time (%.3f) must be before end time (%.3f)", start_s, end_s)
        return 1

    # ---- Output directory ----------------------------------------------------
    if args.output_dir:
        output_dir = Path(args.output_dir).expanduser().resolve()
    else:
        if youtube_id:
            output_dir = Path.cwd() / f"yt_{youtube_id}_frames"
        else:
            output_dir = input_video.parent / f"{input_video.stem}_frames"
    output_dir.mkdir(parents=True, exist_ok=True)

    ext = "jpg" if args.format == "jpeg" else args.format

    # ---- Single-frame mode ---------------------------------------------------
    if args.time:
        ts = parse_ts(args.time)
        if ts < 0 or ts > duration:
            logger.error("Requested time %.3fs is outside video duration (0 … %.3f)", ts, duration)
            return 1

        out_name = f"{args.prefix}_{format_hms(ts)}.{ext}"
        out_path = output_dir / out_name

        ok = extract_single_frame(
            input_video=input_video,
            output_path=out_path,
            timestamp_s=ts,
            quality=args.quality,
            ffmpeg=ffmpeg,
            logger=logger,
        )
        if not ok:
            return 1

        logger.info("Done: 1 frame saved to %s", out_path)

    # ---- Interval mode -------------------------------------------------------
    else:
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

    # ---- Cleanup -------------------------------------------------------------
    if temp_dir is not None and not args.keep_download:
        try:
            shutil.rmtree(temp_dir)
            logger.debug("Removed temporary download directory %s", temp_dir)
        except OSError as e:
            logger.warning("Could not remove temp dir %s: %s", temp_dir, e)

    return 0


if __name__ == "__main__":
    sys.exit(main())