from __future__ import annotations

"""trim_audio.py - Trim local audio/video to an audio clip for Instagram reels.

Examples:
    python scripts/trim_audio.py --input "C:/Users/dhana/media-files/speech.mp4" --output "C:/Users/dhana/media-files/speech-reel.m4a" --start 00:00:30 --end 00:00:45
    python scripts/trim_audio.py --input "C:/Users/dhana/media-files/song.wav" --start 00:01:00 --end 00:01:20 --output-format mp3 --audio-bitrate 192k
"""

import argparse
import logging
import os
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
            props[key.strip()] = value.strip().strip('"')
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


def build_audio_command(
    input_file: Path,
    output_file: Path,
    start_time: str,
    end_time: str,
    ffmpeg: str,
    audio_bitrate: str,
    sample_rate: int,
    channels: int,
    output_format: str,
) -> list[str]:
    cmd = [ffmpeg, "-hide_banner", "-y"]
    if start_time:
        cmd += ["-ss", start_time]
    cmd += ["-i", str(input_file)]

    if start_time and end_time:
        duration = max(0.0, parse_ts(end_time) - parse_ts(start_time))
        cmd += ["-t", f"{duration:.3f}"]
    elif end_time:
        cmd += ["-t", f"{parse_ts(end_time):.3f}"]

    if output_format.lower() == "mp3":
        cmd += ["-c:a", "libmp3lame"]
    else:
        cmd += ["-c:a", "aac"]

    cmd += ["-b:a", audio_bitrate, "-ar", str(sample_rate), "-ac", str(channels), str(output_file)]
    return cmd


def validate_audio(audio_file: Path, ffprobe: str, logger: logging.Logger) -> bool:
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration,size",
        "-show_entries",
        "stream=codec_name,channels,sample_rate",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(audio_file),
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
        description="Trim an audio or video input into an audio clip using start/end times."
    )
    p.add_argument("--config", default=str(_DEFAULT_CONFIG), help="Config file path")
    p.add_argument("--input", required=True, help="Path to the source audio or video file")
    p.add_argument("--output", help="Output path for the trimmed audio file")
    p.add_argument("--start", default="", help="Start time HH:MM:SS or seconds")
    p.add_argument("--end", default="", help="End time HH:MM:SS or seconds")
    p.add_argument(
        "--output-format",
        default="m4a",
        choices=["m4a", "mp3"],
        help="Output audio format for Instagram reels (default: m4a)",
    )
    p.add_argument(
        "--audio-bitrate",
        default="128k",
        help="Audio bitrate for the output clip (default: 128k)",
    )
    p.add_argument(
        "--sample-rate",
        type=int,
        default=44100,
        help="Sample rate for output audio (default: 44100)",
    )
    p.add_argument(
        "--channels",
        type=int,
        default=2,
        help="Number of audio channels for output (default: 2)",
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
    logger = logging.getLogger("trim_audio")

    config_path = Path(args.config).expanduser().resolve()
    if not config_path.exists():
        logger.error("Config file not found: %s", config_path)
        return 1

    raw_props = load_properties(config_path)
    cfg = resolve_all(raw_props)

    tools_dir = Path(cfg.get("tools_dir", "")).expanduser()
    input_file = Path(args.input).expanduser().resolve()
    if not input_file.exists():
        logger.error("Input file not found: %s", input_file)
        return 1

    output_format = args.output_format.lower()
    if args.output:
        output_file = Path(args.output).expanduser().resolve()
    else:
        output_file = input_file.with_name(f"{input_file.stem}-trim.{output_format}")

    if output_file.suffix.lower() != f".{output_format}":
        output_file = output_file.with_suffix(f".{output_format}")

    output_file.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = resolve_tool(tools_dir, "ffmpeg")
    ffprobe = resolve_tool(tools_dir, "ffprobe")

    cmd = build_audio_command(
        input_file=input_file,
        output_file=output_file,
        start_time=args.start,
        end_time=args.end,
        ffmpeg=ffmpeg,
        audio_bitrate=args.audio_bitrate,
        sample_rate=args.sample_rate,
        channels=args.channels,
        output_format=output_format,
    )

    logger.info("Trimming audio: %s", input_file)
    logger.info("Output file: %s", output_file)
    return_code = run_logged_command(cmd, logger, "ffmpeg")
    if return_code != 0:
        logger.error("ffmpeg failed (exit %d)", return_code)
        return 1

    if not validate_audio(output_file, ffprobe, logger):
        return 1

    logger.info("Done: %s", output_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
