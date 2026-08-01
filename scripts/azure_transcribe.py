from __future__ import annotations

"""azure_transcribe.py — Transcribe local audio with Azure Speech to Text.

Configuration is driven by config/media-config.properties.

Usage:
    python scripts/azure_transcribe.py --audio-file /path/to/audio.m4a
    python scripts/azure_transcribe.py --config config/media-config.properties
    python scripts/azure_transcribe.py --audio-file /path/to/audio.m4a --lang te-IN
    python scripts/azure_transcribe.py --audio-file /path/to/audio.m4a --resume
    python scripts/azure_transcribe.py --audio-file /path/to/audio.m4a --resume --resume-overlap-s 1.0

Output:
    <media_dir>/<audio-stem>.azure.transcript.txt
    [HH:MM:SS.mmm -> HH:MM:SS.mmm] Speaker Name: text

Dependencies:
    pip install azure-cognitiveservices-speech
    Tools (ffmpeg) configured via tools_dir in media-config.properties
"""

import argparse
import logging
import os
import re
import shlex
import subprocess
import sys
import wave
from pathlib import Path


_DEFAULT_CONFIG = Path(__file__).parent.parent / "config" / "media-config.properties"
_SPRING_PLACEHOLDER = re.compile(r"\$\{([^}]+)\}")
_TRANSCRIPT_LINE_PATTERN = re.compile(r"^\[(?P<start>[^\]]+?)\s*->\s*(?P<end>[^\]]+?)\]\s+")


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
    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key == "user.home":
            return str(Path.home())
        return props.get(key, os.environ.get(key, match.group(0)))

    return _SPRING_PLACEHOLDER.sub(_replace, value)


def resolve_all(props: dict[str, str]) -> dict[str, str]:
    return {key: resolve_placeholders(value, props) for key, value in props.items()}


def resolve_tool(tools_dir: Path, name: str) -> str:
    for candidate in (tools_dir / name, tools_dir / f"{name}.exe"):
        if candidate.exists():
            return str(candidate)
    return name


def resolve_secret(cfg: dict[str, str], direct_key: str, env_key_name: str) -> tuple[str, str]:
    direct_value = cfg.get(direct_key, "").strip()
    if direct_value and not _SPRING_PLACEHOLDER.fullmatch(direct_value):
        return direct_value, direct_key

    env_var_name = cfg.get(env_key_name, "").strip()
    if env_var_name:
        env_value = os.environ.get(env_var_name, "").strip()
        if env_value:
            return env_value, f"env:{env_var_name}"

    return "", env_var_name


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


def format_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    hrs = total_ms // 3_600_000
    rem = total_ms % 3_600_000
    mins = rem // 60_000
    rem %= 60_000
    secs = rem // 1000
    ms = rem % 1000
    return f"{hrs:02d}:{mins:02d}:{secs:02d}.{ms:03d}"


def read_last_transcript_end(transcript_path: Path) -> float | None:
    if not transcript_path.exists():
        return None

    last_end: float | None = None
    for raw_line in transcript_path.read_text(encoding="utf-8").splitlines():
        match = _TRANSCRIPT_LINE_PATTERN.match(raw_line.strip())
        if not match:
            continue
        last_end = parse_ts(match.group("end"))

    return last_end


_SPEAKER_PATTERNS = [
    re.compile(r"^>>\s*(?P<speaker>[^:<>\[\]]+?)\s*:\s*(?P<text>.+)$"),
    re.compile(r"^\[(?P<speaker>[A-Z][^\[\]]{1,40}?)\]\s*:\s*(?P<text>.+)$"),
    re.compile(r"^\[(?P<speaker>[A-Z][^\[\]]{1,40}?)\]\s+(?P<text>.+)$"),
    re.compile(r"^(?P<speaker>[A-Z][A-Za-z .'-]{1,30}):\s+(?P<text>\S.+)$"),
]


def detect_speaker(text: str, current_speaker: str) -> tuple[str, str]:
    for pat in _SPEAKER_PATTERNS:
        match = pat.match(text.strip())
        if match:
            return match.group("speaker").strip(), match.group("text").strip()
    return current_speaker, text.strip()


def convert_audio_for_azure(
    raw_audio: Path,
    output_path: Path,
    start_time: str,
    end_time: str,
    ffmpeg: str,
    logger: logging.Logger,
) -> bool:
    cmd = [ffmpeg, "-y"]
    if start_time:
        cmd += ["-ss", start_time]
    if end_time:
        cmd += ["-to", end_time]
    cmd += [
        "-i",
        str(raw_audio),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(output_path),
    ]

    logger.info("[1/2] Preprocessing audio to mono 16k WAV for Azure Speech …")
    logger.debug("  cmd: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("ffmpeg failed (exit %d):\n%s", result.returncode, result.stderr[-2000:])
        return False
    logger.info("  Output wav: %s", output_path.name)
    return True


def transcribe_with_azure(
    audio_path: Path,
    speech_key: str,
    speech_region: str,
    speech_language: str,
    logger: logging.Logger,
) -> list[dict] | None:
    try:
        import azure.cognitiveservices.speech as speechsdk
    except ImportError:
        logger.error(
            "azure-cognitiveservices-speech not installed. Run: pip install azure-cognitiveservices-speech"
        )
        return None

    logger.info("[2/2] Connecting to Azure Speech …")
    logger.info("  Speech language: %s", speech_language)
    logger.info("  Transcribing: %s", audio_path.name)

    speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=speech_region)
    speech_config.speech_recognition_language = speech_language
    audio_config = speechsdk.audio.AudioConfig(filename=str(audio_path))
    recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)

    results: list[dict] = []
    done = {"value": False}

    logger.info("[Azure] Transcription session started.")

    def on_recognized(evt: speechsdk.SpeechRecognitionEventArgs) -> None:
        result = evt.result
        if result.reason != speechsdk.ResultReason.RecognizedSpeech:
            return

        offset_seconds = result.offset / 10_000_000
        duration_seconds = result.duration / 10_000_000
        text = result.text.strip()
        logger.info("[Azure] Segment: [%s - %s] %s", format_ts(offset_seconds), format_ts(offset_seconds + duration_seconds), text)
        results.append(
            {
                "start": offset_seconds,
                "end": offset_seconds + duration_seconds,
                "text": text,
            }
        )

    def on_canceled(evt: speechsdk.SpeechRecognitionCanceledEventArgs) -> None:
        reason = evt.result.cancellation_details.reason
        # EndOfStream is expected for file-based transcription when input is fully consumed.
        if reason == speechsdk.CancellationReason.EndOfStream:
            logger.info("[Azure] Transcription reached end of audio stream.")
        else:
            logger.error("[Azure] Transcription canceled: %s", reason)
            error_details = evt.result.cancellation_details.error_details
            if error_details:
                logger.error("[Azure] Error details: %s", error_details)
        done["value"] = True

    def on_session_stopped(_: object) -> None:
        logger.info("[Azure] Transcription session stopped.")
        done["value"] = True

    recognizer.recognized.connect(on_recognized)
    recognizer.canceled.connect(on_canceled)
    recognizer.session_stopped.connect(on_session_stopped)

    recognizer.start_continuous_recognition()
    while not done["value"]:
        import time
        time.sleep(0.2)
    recognizer.stop_continuous_recognition()

    logger.info("[Azure] Transcription complete. Segments: %d", len(results))
    return results


def get_wav_duration_seconds(wav_path: Path) -> float | None:
    try:
        with wave.open(str(wav_path), "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
        if frame_rate <= 0:
            return None
        return frame_count / float(frame_rate)
    except (wave.Error, OSError):
        return None


def log_transcription_coverage(
    segments: list[dict],
    analyzed_audio_path: Path,
    start_offset: float,
    logger: logging.Logger,
) -> None:
    audio_duration = get_wav_duration_seconds(analyzed_audio_path)
    if audio_duration is None:
        logger.info("[Azure] Coverage summary: unable to determine audio duration.")
        return

    if segments:
        last_end = max(seg.get("end", 0.0) for seg in segments)
    else:
        last_end = 0.0

    gap = audio_duration - last_end
    logger.info(
        "[Azure] Coverage summary: audio=%s, last_segment_end=%s, trailing_gap=%+.3fs",
        format_ts(audio_duration),
        format_ts(last_end),
        gap,
    )
    logger.info(
        "[Azure] Coverage summary (absolute timeline): start=%s, last_segment_end=%s",
        format_ts(start_offset),
        format_ts(last_end + start_offset),
    )


def write_transcript(
    segments: list[dict],
    output_path: Path,
    default_speaker: str,
    start_offset: float,
    append: bool,
    logger: logging.Logger,
) -> None:
    lines: list[str] = []
    current_speaker = default_speaker

    for seg in segments:
        speaker, text = detect_speaker(seg["text"], current_speaker)
        current_speaker = speaker
        ts_start = format_ts(seg["start"] + start_offset)
        ts_end = format_ts(seg["end"] + start_offset)
        lines.append(f"[{ts_start} -> {ts_end}] {speaker}: {text}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if append and output_path.exists() and output_path.stat().st_size > 0 and lines:
        with output_path.open("a", encoding="utf-8") as out_file:
            out_file.write("\n")
            out_file.write("\n".join(lines))
    else:
        output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("  Transcript: %s  (%d new lines)", output_path, len(lines))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Transcribe local audio with Azure Speech to Text.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        default=str(_DEFAULT_CONFIG),
        help="Properties config file (default: config/media-config.properties)",
    )
    parser.add_argument("--start", default="", help="Start time HH:MM:SS")
    parser.add_argument("--end", default="", help="End time HH:MM:SS")
    parser.add_argument("--lang", default="", help="Azure speech locale, e.g. te-IN")
    parser.add_argument("--speaker", default="", help="Default speaker label")
    parser.add_argument("--audio-file", dest="audio_file", default="", help="Local audio file path")
    parser.add_argument(
        "--preprocess",
        action="store_true",
        help="Convert audio to mono 16k WAV before sending to Azure Speech (use only if direct input fails)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from last timestamp found in existing output transcript and append new lines.",
    )
    parser.add_argument(
        "--resume-overlap-s",
        default="0.0",
        help="Optional overlap (seconds) before last transcript timestamp when resuming (default: 0.0).",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("azure_transcribe")

    config_path = Path(args.config).expanduser().resolve()
    if not config_path.exists():
        logger.error("Config file not found: %s", config_path)
        logger.error("Expected at: %s", _DEFAULT_CONFIG)
        return 1

    raw_props = load_properties(config_path)
    cfg = resolve_all(raw_props)
    logger.info("Config: %s", config_path)

    def prop(key: str, cli_val: str, fallback: str = "") -> str:
        if cli_val:
            return cli_val
        return cfg.get(key, fallback)

    media_dir = Path(prop("media_dir", str(Path.home() / "media-files"))).expanduser()
    media_dir.mkdir(parents=True, exist_ok=True)

    raw_audio_file = args.audio_file or cfg.get("audio_file", "")
    if not raw_audio_file:
        logger.error("No local audio input found. Set audio_file in config or pass --audio-file.")
        return 1

    audio_file_path = Path(raw_audio_file.strip('"').strip("'")).expanduser().resolve()
    if not audio_file_path.exists():
        logger.error("Local audio file not found: %s", audio_file_path)
        return 1
    logger.info("Audio file: %s", audio_file_path)

    start_raw = prop("startTime", args.start).strip()
    end_raw = prop("endTime", args.end).strip()
    speech_language = prop("azure_speech_lang", args.lang, "te-IN")
    speaker = prop("speaker", args.speaker, "Speaker 1")
    out_suffix = cfg.get("azure_output_suffix", ".azure.transcript")
    transcript_path = media_dir / (audio_file_path.stem + out_suffix + ".txt")

    speech_key, key_source = resolve_secret(cfg, "azure_speech_key", "azure_speech_key_env")
    speech_region = cfg.get("azure_speech_region", "").strip()
    if not speech_key:
        env_hint = cfg.get("azure_speech_key_env", "").strip()
        if env_hint:
            logger.error(
                "Azure Speech key is missing. Set 'azure_speech_key' or environment variable '%s'.",
                env_hint,
            )
        else:
            logger.error("Missing 'azure_speech_key' in %s", config_path)
        return 1
    if not speech_region:
        logger.error("Missing 'azure_speech_region' in %s", config_path)
        return 1

    logger.info("  Start    : %s", start_raw or "(none)")
    logger.info("  End      : %s", end_raw or "(none)")
    logger.info("  Language : %s", speech_language)
    logger.info("  Speaker  : %s", speaker)
    logger.info("  Key via  : %s", key_source)

    configured_start = parse_ts(start_raw) if start_raw else 0.0
    start_offset = configured_start
    resume_last_end_abs: float | None = None
    append_output = False

    try:
        resume_overlap_s = max(float(args.resume_overlap_s), 0.0)
    except ValueError:
        logger.error("Invalid --resume-overlap-s value: %s", args.resume_overlap_s)
        return 1

    if args.resume:
        resume_last_end_abs = read_last_transcript_end(transcript_path)
        if resume_last_end_abs is None:
            logger.info("[Azure] Resume requested, but no existing transcript timestamps found. Starting fresh.")
        else:
            effective_start = max(configured_start, resume_last_end_abs - resume_overlap_s)
            if end_raw:
                configured_end = parse_ts(end_raw)
                if effective_start >= configured_end:
                    logger.info(
                        "[Azure] Resume skipped: last transcript end (%s) is at/after configured end (%s).",
                        format_ts(resume_last_end_abs),
                        format_ts(configured_end),
                    )
                    return 0
            start_raw = format_ts(effective_start)
            start_offset = effective_start
            append_output = True
            logger.info(
                "[Azure] Resume enabled: existing_end=%s, overlap=%.3fs, restart_from=%s",
                format_ts(resume_last_end_abs),
                resume_overlap_s,
                start_raw,
            )

    # Azure Speech SDK requires WAV/PCM; convert automatically for any other format.
    needs_wav = audio_file_path.suffix.lower() != ".wav" or args.preprocess
    if needs_wav:
        tools_dir = Path(prop("tools_dir", "")).expanduser()
        ffmpeg = resolve_tool(tools_dir, "ffmpeg")
        import tempfile
        with tempfile.TemporaryDirectory(prefix="azuretranscribe_") as tmp_str:
            tmp_dir = Path(tmp_str)
            wav_path = tmp_dir / (audio_file_path.stem + ".azure.wav")
            if not convert_audio_for_azure(audio_file_path, wav_path, start_raw, end_raw, ffmpeg, logger):
                return 1
            segments = transcribe_with_azure(wav_path, speech_key, speech_region, speech_language, logger)
            if segments is None:
                return 1
            if resume_last_end_abs is not None:
                segments = [
                    seg
                    for seg in segments
                    if (seg["end"] + start_offset) > (resume_last_end_abs + 0.01)
                ]
                logger.info("[Azure] Resume filtering kept %d segments after %s", len(segments), format_ts(resume_last_end_abs))
            log_transcription_coverage(segments, wav_path, start_offset, logger)
            write_transcript(segments, transcript_path, speaker, start_offset, append_output, logger)
    else:
        logger.info("[1/2] WAV input detected, passing directly to Azure Speech")
        segments = transcribe_with_azure(audio_file_path, speech_key, speech_region, speech_language, logger)
        if segments is None:
            return 1
        if resume_last_end_abs is not None:
            segments = [
                seg
                for seg in segments
                if (seg["end"] + start_offset) > (resume_last_end_abs + 0.01)
            ]
            logger.info("[Azure] Resume filtering kept %d segments after %s", len(segments), format_ts(resume_last_end_abs))
        log_transcription_coverage(segments, audio_file_path, start_offset, logger)
        write_transcript(segments, transcript_path, speaker, start_offset, append_output, logger)

    logger.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())