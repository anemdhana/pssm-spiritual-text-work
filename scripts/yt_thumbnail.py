#!/usr/bin/env python3
"""yt_thumbnail.py — Download the best available YouTube thumbnail for a video ID.

Usage:
    python scripts/yt_thumbnail.py --video-id 9bZkp7q19f0
    python scripts/yt_thumbnail.py --video-id 9bZkp7q19f0 --output-dir images
    python scripts/yt_thumbnail.py --video-id 9bZkp7q19f0 --output thumbnail.jpg

Dependencies: None (stdlib only — urllib, pathlib)
"""

from __future__ import annotations

import argparse
import logging
import sys
import urllib.error
import urllib.request
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

THUMB_URLS = [
    "https://img.youtube.com/vi/{vid}/maxresdefault.jpg",
    "https://img.youtube.com/vi/{vid}/sddefault.jpg",
    "https://img.youtube.com/vi/{vid}/hqdefault.jpg",
    "https://img.youtube.com/vi/{vid}/mqdefault.jpg",
    "https://img.youtube.com/vi/{vid}/default.jpg",
]


def build_thumbnail_urls(video_id: str) -> list[str]:
    return [template.format(vid=video_id) for template in THUMB_URLS]


def download_thumbnail(video_id: str, output_path: Path) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for url in build_thumbnail_urls(video_id):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                image_data = resp.read()
                if len(image_data) < 5000:
                    log.debug("Skipping placeholder thumbnail from %s (%d bytes)", url, len(image_data))
                    continue
                output_path.write_bytes(image_data)
                log.info("Downloaded thumbnail for %s from %s", video_id, url)
                return True
        except urllib.error.HTTPError as ex:
            log.debug("HTTP %d for %s", ex.code, url)
            continue
        except urllib.error.URLError as ex:
            log.debug("URL error for %s: %s", url, ex)
            continue
        except Exception as ex:
            log.debug("Unexpected error for %s: %s", url, ex)
            continue

    log.error("Failed to download thumbnail for %s", video_id)
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download YouTube thumbnail for a given video ID."
    )
    parser.add_argument(
        "--video-id",
        required=True,
        help="YouTube video ID to download the thumbnail for.",
    )
    parser.add_argument(
        "--output",
        help="Output file path for the downloaded thumbnail. Defaults to <video-id>.jpg.",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory to save the thumbnail when --output is not provided. Defaults to current directory.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    video_id = args.video_id.strip()
    if not video_id:
        log.error("Video ID cannot be empty.")
        return 1

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = Path(args.output_dir) / f"{video_id}.jpg"

    if download_thumbnail(video_id, output_path):
        log.info("Saved thumbnail to %s", output_path)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
