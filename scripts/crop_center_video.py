from __future__ import annotations

"""crop_center_video.py - Trim a local video and crop it from the center.

Examples:
python scripts/crop_center_video.py --input "C:\Users\dhana\media-files\#SingGeetham ThankYou Meet - LIVE - Nag Ashwin - Singeetham Srinivasa Rao - Devi Sri Prasad-medium.mp4" --output "C:\Users\dhana\media-files\#SingGeetham Sailajamma-Wish.mp4" --crop-width 720 --crop-height 1280 --video-bitrate 800k --preset fast --audio-bitrate 48k
    python scripts/crop_center_video.py --input path/to/video.mp4 --output path/to/out.mp4 --start 00:00:30 --end 00:01:00
    python scripts/crop_center_video.py --input path/to/video.mp4 --output path/to/out.mp4 --crop-width 1080 --crop-height 1920
"""

import argparse
import logging
import os
import subprocess
import sys
import tempfile
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


def probe_video_dimensions(
    video_file: Path,
    ffprobe: str,
    logger: logging.Logger,
) -> tuple[int, int]:
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "csv=p=0",
        str(video_file),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("ffprobe failed: %s", result.stderr.strip())
        return 0, 0

    width_str, height_str = result.stdout.split(",", 1) if "," in result.stdout else (result.stdout.strip(), "")
    try:
        width = int(width_str.strip())
        height = int(height_str.strip())
    except ValueError:
        logger.error("Could not parse ffprobe dimensions: %r", result.stdout)
        return 0, 0

    logger.info("Input dimensions: %dx%d", width, height)
    return width, height


def build_crop_filter(crop_w: int, crop_h: int, scale_ratio: float) -> str:
    return (
        f"scale=trunc(iw*{scale_ratio}/2)*2:"
        f"trunc(ih*{scale_ratio}/2)*2,"
        f"crop={crop_w}:{crop_h}:x=(iw-{crop_w})/2:y=(ih-{crop_h})/2"
    )


def create_short_video(
    input_video: Path,
    output_video: Path,
    start_time: str,
    end_time: str,
    crop_w: int,
    crop_h: int,
    input_w: int,
    input_h: int,
    ffmpeg: str,
    logger: logging.Logger,
    crf: int,
    preset: str,
    audio_bitrate: str,
    video_bitrate: str,
) -> bool:
    cmd = [ffmpeg, "-hide_banner", "-y"]

    if start_time and end_time:
        start_s = parse_ts(start_time)
        end_s = parse_ts(end_time)
        duration = max(0.0, end_s - start_s)
        cmd += [
            "-ss",
            start_time,
            "-i",
            str(input_video),
            "-t",
            f"{duration:.3f}",
        ]
    elif start_time:
        cmd += ["-ss", start_time, "-i", str(input_video)]
    elif end_time:
        end_s = parse_ts(end_time)
        cmd += ["-i", str(input_video), "-t", f"{end_s:.3f}"]
    else:
        cmd += ["-i", str(input_video)]

    scale_ratio = max(crop_w / input_w, crop_h / input_h) if input_w and input_h else 1.0
    cmd += [
        "-vf",
        build_crop_filter(crop_w, crop_h, scale_ratio),
    ]

    cmd += [
        "-preset",
        preset,
    ]

    if video_bitrate:
        cmd += [
            "-b:v",
            video_bitrate,
            "-minrate",
            video_bitrate,
            "-maxrate",
            video_bitrate,
            "-bufsize",
            f"{int(video_bitrate[:-1]) * 2}{video_bitrate[-1]}",
        ]
    else:
        cmd += [
            "-crf",
            str(crf),
        ]

    cmd += [
        "-pix_fmt",
        "yuv420p",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
        "-movflags",
        "+faststart",
        str(output_video),
    ]

    logger.info("Creating short video from %s", input_video)
    logger.info("Output: %s", output_video)
    return_code = run_logged_command(cmd, logger, "ffmpeg")
    if return_code != 0:
        logger.error("ffmpeg failed (exit %d)", return_code)
        return False
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
    logger.info("ffprobe output: %s", " | ".join(values[:6]))
    return True


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Trim a local video and center-crop it into a short output clip."
    )
    p.add_argument("--config", default=str(_DEFAULT_CONFIG), help="Config file path")
    p.add_argument("--input", required=True, help="Path to the source video file")
    p.add_argument("--output", help="Output path for the cropped clip")
    p.add_argument("--start", default="", help="Start time HH:MM:SS")
    p.add_argument("--end", default="", help="End time HH:MM:SS")
    p.add_argument(
        "--crop-width",
        type=int,
        default=1080,
        help="Crop width in pixels (default: 1080)",
    )
    p.add_argument(
        "--crop-height",
        type=int,
        default=1920,
        help="Crop height in pixels (default: 1920)",
    )
    p.add_argument(
        "--crf",
        type=int,
        default=23,
        help="H.264 quality slider (lower is better quality, default: 23)",
    )
    p.add_argument(
        "--preset",
        default="fast",
        help="x264 preset for speed/quality tradeoff (default: fast)",
    )
    p.add_argument(
        "--audio-bitrate",
        default="96k",
        help="Audio bitrate for the output (default: 96k)",
    )
    p.add_argument(
        "--video-bitrate",
        default="",
        help="Optional target video bitrate, for example 2500k or 3M",
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
    logger = logging.getLogger("crop_center_video")

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

    input_w, input_h = probe_video_dimensions(input_video, ffprobe, logger)
    if input_w <= 0 or input_h <= 0:
        return 1

    if args.output:
        output_video = Path(args.output).expanduser().resolve()
    else:
        output_video = input_video.with_name(f"{input_video.stem}-center-crop.mp4")

    output_video.parent.mkdir(parents=True, exist_ok=True)

    if not create_short_video(
        input_video=input_video,
        output_video=output_video,
        start_time=args.start,
        end_time=args.end,
        crop_w=args.crop_width,
        crop_h=args.crop_height,
        input_w=input_w,
        input_h=input_h,
        ffmpeg=ffmpeg,
        logger=logger,
        crf=args.crf,
        preset=args.preset,
        audio_bitrate=args.audio_bitrate,
        video_bitrate=args.video_bitrate,
    ):
        return 1

    if not validate_video(output_video, ffprobe, logger):
        return 1

    logger.info("Done: %s", output_video)
    return 0


if __name__ == "__main__":
    sys.exit(main())
