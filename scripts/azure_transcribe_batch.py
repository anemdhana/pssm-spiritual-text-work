from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_AUDIO_FILES = [
    r"C:\Users\dhana\media-files\Our Body Is Our temple By Dr. Laxmi Newton - Shuddi Siddi Buddhi  Event At Tadipatri - PMC-compact_size_speech.m4a",
    r"C:\Users\dhana\media-files\Dr. Newton Kondaveeti  Speech  on Buddhi Yogam in the Event Shuddi Siddi Buddhi Tadipatri  Pa 08-compact_size_speech.m4a",
    r"C:\Users\dhana\media-files\Dr. Newton Kondaveeti Speech on Buddhi Yogam in the Event Shuddi Siddi Buddhi Tadipatri  Pa 07 - PMC-compact_size_speech.m4a",
    r"C:\Users\dhana\media-files\Dr. Newton Kondaveeti  Speech  on Buddhi Yogam in the Event Shuddi Siddi Buddhi Tadipatri Pa 06-compact_size_speech.m4a",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run azure_transcribe.py for a list of audio files.",
        epilog=(
            "Example:\n"
            "  python scripts/azure_transcribe_batch.py\n"
            "  python scripts/azure_transcribe_batch.py --lang te-IN\n"
            "  python scripts/azure_transcribe_batch.py --audio-list-file scripts/audio-files.txt\n"
            "  python scripts/azure_transcribe_batch.py --stop-on-error"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--lang",
        default="te-IN",
        help="Azure speech language code (default: te-IN)",
    )
    parser.add_argument(
        "--audio-list-file",
        type=Path,
        help="Optional text file with one audio path per line.",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop batch execution if any file fails.",
    )
    return parser.parse_args()


def load_audio_files(list_path: Path | None) -> list[str]:
    if list_path is None:
        return DEFAULT_AUDIO_FILES

    if not list_path.exists():
        raise FileNotFoundError(f"Audio list file does not exist: {list_path}")

    audio_files: list[str] = []
    for line in list_path.read_text(encoding="utf-8").splitlines():
        path = line.strip()
        if path and not path.startswith("#"):
            audio_files.append(path)

    return audio_files


def run_transcription(audio_file: str, lang: str, azure_script: Path) -> int:
    command = [
        sys.executable,
        str(azure_script),
        "--lang",
        lang,
        "--audio-file",
        audio_file,
    ]
    print("Running:", " ".join(command))
    result = subprocess.run(command)
    return result.returncode


def main() -> int:
    args = parse_args()
    batch_script = Path(__file__).resolve().parent / "azure_transcribe.py"

    if not batch_script.exists():
        print(f"Error: {batch_script} not found.")
        return 1

    try:
        audio_files = load_audio_files(args.audio_list_file)
    except FileNotFoundError as exc:
        print(exc)
        return 1

    if not audio_files:
        print("No audio files found to process.")
        return 1

    print(f"Transcribing {len(audio_files)} file(s) with lang={args.lang}")
    for audio_file in audio_files:
        print("\n=== Processing:", audio_file)
        return_code = run_transcription(audio_file, args.lang, batch_script)
        if return_code != 0:
            print(f"Failed: {audio_file} (exit {return_code})")
            if args.stop_on_error:
                return return_code

    print("\nBatch transcription complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
