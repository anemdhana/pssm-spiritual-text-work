from __future__ import annotations

"""download_video_url.py — Download any video-player URL as a .mp4 file.

Works with any site supported by yt-dlp (YouTube, Vimeo, direct video-player
embeds, etc.) — not just YouTube video IDs.

Usage:
    python scripts/download_video_url.py --url "https://example.com/watch?v=abc"
    python scripts/download_video_url.py --url "https://youtu.be/abc123" --output "C:\\media-files\\my-clip.mp4"
    python scripts/download_video_url.py --url "https://example.com/video" --start 00:02:00 --end 00:05:00
"""

import argparse
import logging
import re
import subprocess
import sys
from pathlib import Path

_DEFAULT_CONFIG = Path(__file__).parent.parent / "config" / "media-config.properties"
_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_MULTI_DASH = re.compile(r"-{2,}")


def load_properties(props_path: Path) -> dict[str, str]:
    props: dict[str, str] = {}
    if not props_path.exists():
        return props
    for line in props_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            props[key.strip()] = value.strip()
    return props


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


def slugify(title: str, max_len: int = 120) -> str:
    slug = _UNSAFE_CHARS.sub("-", title)
    slug = _MULTI_DASH.sub("-", slug).strip("- ")
    return slug[:max_len]


def fetch_title(url: str, ytdlp: list[str], logger: logging.Logger) -> str:
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


def download_video(
    url: str,
    output_path: Path,
    ytdlp: list[str],
    start_time: str,
    end_time: str,
    logger: logging.Logger,
) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        *ytdlp,
        "--no-playlist",
        "--no-update",
        "--socket-timeout",
        "30",
        "--retries",
        "3",
        "-f",
        "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format",
        "mp4",
        "-o",
        str(output_path),
        url,
    ]
    if start_time and end_time:
        cmd += ["--download-sections", f"*{start_time}-{end_time}"]

    logger.info("Downloading %s …", url)
    if start_time and end_time:
        logger.info("  Requested section: %s → %s", start_time, end_time)

    return_code = run_logged_command(cmd, logger, "yt-dlp")
    if return_code != 0:
        logger.error("yt-dlp failed (exit %d)", return_code)
        return False
    return True


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Download any video-player URL as a .mp4 file using yt-dlp.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--url", required=True, help="URL of the video/player page to download")
    p.add_argument("--output", default="", help="Destination .mp4 path (default: <media_dir>/<title>.mp4)")
    p.add_argument("--config", default=str(_DEFAULT_CONFIG), help="Properties config path (for tools_dir/media_dir)")
    p.add_argument("--start", default="", help="Start time HH:MM:SS (optional, trims to this range)")
    p.add_argument("--end", default="", help="End time HH:MM:SS (optional, trims to this range)")
    p.add_argument("--verbose", action="store_true", help="Enable DEBUG logs")
    return p


def main() -> int:
    args = build_arg_parser().parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("download_video_url")

    cfg = load_properties(Path(args.config).expanduser())
    tools_dir = Path(cfg.get("tools_dir", "")).expanduser()
    media_dir = Path(cfg.get("media_dir", str(Path.home() / "media-files")).replace("${user.home}", str(Path.home()))).expanduser()

    ytdlp = resolve_ytdlp(tools_dir)

    if args.output:
        output_path = Path(args.output).expanduser()
    else:
        title = fetch_title(args.url, ytdlp, logger)
        stem = slugify(title) if title else "video"
        output_path = media_dir / f"{stem}.mp4"

    logger.info("URL         : %s", args.url)
    logger.info("Output      : %s", output_path)

    if not download_video(args.url, output_path, ytdlp, args.start.strip(), args.end.strip(), logger):
        return 1

    if not output_path.exists():
        logger.error("Expected output file not found: %s", output_path)
        return 1

    logger.info("Done: %s", output_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
