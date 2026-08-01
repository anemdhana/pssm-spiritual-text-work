from __future__ import annotations

"""yt_download_video.py — Download a YouTube video clip and export it as a medium-quality MP4.

Usage:
    python scripts/yt_download_video.py --video-id VIDEO_ID --start 00:02:00 --end 00:05:00
    python scripts/yt_download_video.py --video-id VIDEO_ID --quality medium
    python scripts/yt_download_video.py --config config/media-config.properties

The script:
  1) downloads a YouTube video (best available MP4 stream pair),
  2) trims it using the supplied start/end time range, and
  3) re-encodes it to a medium-sized MP4 (default: 480p-style output).
"""

import argparse
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_DEFAULT_CONFIG = Path(__file__).parent.parent / "config" / "media-config.properties"
_SPRING_PLACEHOLDER = re.compile(r"\$\{([^}]+)\}")
_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_MULTI_DASH = re.compile(r"-{2,}")

QUALITY_PRESETS = {
    "small": "scale=-2:360",
    "medium": "scale=-2:480",
    "large": "scale=-2:720",
}


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
    def _replace(m: re.Match) -> str:
        key = m.group(1)
        if key == "user.home":
            return str(Path.home())
        return props.get(key, os.environ.get(key, m.group(0)))

    return _SPRING_PLACEHOLDER.sub(_replace, value)


def resolve_all(props: dict[str, str]) -> dict[str, str]:
    return {k: resolve_placeholders(v, props) for k, v in props.items()}


def resolve_tool(tools_dir: Path, name: str) -> str:
    for candidate in (tools_dir / name, tools_dir / f"{name}.exe"):
        if candidate.exists():
            return str(candidate)
    return name


def resolve_ytdlp(tools_dir: Path) -> list[str]:
    """Prefer the Python package so the script works in virtual environments."""
    try:
        import yt_dlp  # noqa: F401
        return [sys.executable, "-m", "yt_dlp"]
    except ImportError:
        pass

    repo_root = Path(__file__).resolve().parents[1]
    for candidate in (
        repo_root / ".venv" / "Scripts" / "python.exe",
        repo_root / ".venv" / "bin" / "python",
    ):
        if candidate.exists():
            test = subprocess.run(
                [str(candidate), "-c", "import yt_dlp; print('ok')"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if test.returncode == 0:
                return [str(candidate), "-m", "yt_dlp"]

    return [resolve_tool(tools_dir, "yt-dlp")]


def parse_ts(ts: str) -> float:
    """Parse HH:MM:SS[.mmm] or MM:SS → seconds."""
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


def slugify(title: str, max_len: int = 120) -> str:
    slug = _UNSAFE_CHARS.sub("-", title)
    slug = _MULTI_DASH.sub("-", slug).strip("- ")
    return slug[:max_len]


def fetch_video_title(video_id: str, ytdlp: list[str], logger: logging.Logger) -> str:
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        result = subprocess.run(
            [*ytdlp, "--print", "title", "--no-playlist", url],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            title = result.stdout.strip().splitlines()[0]
            logger.info("  Title: %s", title)
            return title
        logger.debug("yt-dlp title stderr: %s", result.stderr.strip())
    except Exception as exc:  # noqa: BLE001
        logger.debug("Title fetch error: %s", exc)
    return ""


def run_logged_command(
    command: list[str],
    logger: logging.Logger,
    label: str,
) -> int:
    """Run a command while streaming output to the log in real time."""
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


def download_raw_video(
    video_id: str,
    tmp_dir: Path,
    ytdlp: list[str],
    start_time: str,
    end_time: str,
    logger: logging.Logger,
) -> Path | None:
    """Download only the requested time range when provided, otherwise use a normal best-quality fetch."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    out_template = str(tmp_dir / "%(title)s.%(id)s.%(ext)s")
    cmd = [
        *ytdlp,
        "--no-playlist",
        "--no-update",
        "--socket-timeout",
        "30",
        "--retries",
        "3",
        "-f",
        "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]",
        "--merge-output-format",
        "mp4",
        "-o",
        out_template,
        url,
    ]
    if start_time and end_time:
        cmd += ["--download-sections", f"*{start_time}-{end_time}"]

    logger.info("[1/3] Downloading raw video …")
    if start_time and end_time:
        logger.info("     Requested section: %s → %s", start_time, end_time)
    return_code = run_logged_command(cmd, logger, "yt-dlp")
    if return_code != 0:
        logger.error("yt-dlp failed (exit %d)", return_code)
        return None

    for ext_glob in ("*.mp4", "*.mkv", "*.webm"):
        found = list(tmp_dir.glob(ext_glob))
        if found:
            logger.info("  Raw video: %s", found[0].name)
            return found[0]

    logger.error("yt-dlp succeeded but no video file was found in %s", tmp_dir)
    return None


def convert_video(
    source_video: Path,
    target_video: Path,
    quality: str,
    start_time: str,
    end_time: str,
    ffmpeg: str,
    logger: logging.Logger,
) -> bool:
    """Trim and re-encode the video to a medium-sized MP4."""
    if quality not in QUALITY_PRESETS:
        logger.error("Unsupported quality: %s", quality)
        return False

    filter_args = QUALITY_PRESETS[quality]
    cmd = [ffmpeg, "-hide_banner", "-y"]

    if start_time and end_time:
        cmd += ["-i", str(source_video)]
    elif start_time:
        cmd += ["-i", str(source_video), "-ss", start_time]
    elif end_time:
        end_s = parse_ts(end_time)
        cmd += ["-i", str(source_video), "-t", f"{end_s:.3f}"]
    else:
        cmd += ["-i", str(source_video)]

    cmd += [
        "-vf",
        filter_args,
        "-c:v",
        "libx264",
        "-preset",
        "faster",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        "-movflags",
        "+faststart",
        str(target_video),
    ]

    logger.info("[2/3] Re-encoding clip to %s quality …", quality)
    return_code = run_logged_command(cmd, logger, "ffmpeg")
    if return_code != 0:
        logger.error("ffmpeg failed (exit %d)", return_code)
        return False

    logger.info("  Output: %s", target_video)
    return True


def validate_video(video_file: Path, ffprobe: str, logger: logging.Logger) -> bool:
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration,size:stream=width,height,codec_name",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_file),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("ffprobe validation failed: %s", result.stderr.strip())
        return False

    values = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    logger.info("  ffprobe output: %s", " | ".join(values[:6]))
    return True


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Download a YouTube video clip and export it as a medium-quality MP4.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--config", default=str(_DEFAULT_CONFIG), help="Properties config path")
    p.add_argument("--video-id", dest="video_id", default="", help="YouTube video ID")
    p.add_argument(
        "--quality",
        default="medium",
        choices=sorted(QUALITY_PRESETS),
        help="Output quality preset: small (360p), medium (480p), large (720p)",
    )
    p.add_argument("--start", default="", help="Start time HH:MM:SS")
    p.add_argument("--end", default="", help="End time HH:MM:SS")
    p.add_argument("--verbose", action="store_true", help="Enable DEBUG logs")
    return p


def main() -> int:
    args = build_arg_parser().parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("yt_download_video")

    config_path = Path(args.config).expanduser().resolve()
    if not config_path.exists():
        logger.error("Config file not found: %s", config_path)
        return 1

    raw_props = load_properties(config_path)
    cfg = resolve_all(raw_props)

    def prop(key: str, cli_val: str, fallback: str = "") -> str:
        if cli_val:
            return cli_val
        return cfg.get(key, fallback)

    tools_dir = Path(prop("tools_dir", "")).expanduser()
    media_dir = Path(prop("media_dir", str(Path.home() / "media-files"))).expanduser()
    media_dir.mkdir(parents=True, exist_ok=True)

    ytdlp = resolve_ytdlp(tools_dir)
    ffmpeg = resolve_tool(tools_dir, "ffmpeg")
    ffprobe = resolve_tool(tools_dir, "ffprobe")

    video_id = prop("videoId", args.video_id).strip()
    url_match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", video_id)
    if url_match:
        video_id = url_match.group(1)
    if not video_id:
        logger.error("No video ID provided. Set videoId in config or pass --video-id.")
        return 1

    quality = prop("quality", args.quality, "medium").strip().lower()
    if quality not in QUALITY_PRESETS:
        logger.error("Invalid quality '%s'. Allowed: %s", quality, ", ".join(sorted(QUALITY_PRESETS)))
        return 1

    start_time = prop("startTime", args.start).strip()
    end_time = prop("endTime", args.end).strip()

    logger.info("Video ID    : %s", video_id)
    logger.info("Quality     : %s", quality)
    logger.info("Start       : %s", start_time or "(none)")
    logger.info("End         : %s", end_time or "(none)")

    with tempfile.TemporaryDirectory(prefix="ytdl_video_") as tmp_str:
        tmp_dir = Path(tmp_str)

        title = fetch_video_title(video_id, ytdlp, logger)
        stem = slugify(title) if title else video_id

        source_video = download_raw_video(
            video_id,
            tmp_dir,
            ytdlp,
            start_time,
            end_time,
            logger,
        )
        if source_video is None:
            return 1

        out_name = f"{stem}-{quality}.mp4"
        output_video = media_dir / out_name

        if not convert_video(
            source_video=source_video,
            target_video=output_video,
            quality=quality,
            start_time=start_time,
            end_time=end_time,
            ffmpeg=ffmpeg,
            logger=logger,
        ):
            return 1

        if not validate_video(output_video, ffprobe, logger):
            return 1

    logger.info("Done: %s", output_video)
    return 0


if __name__ == "__main__":
    sys.exit(main())
