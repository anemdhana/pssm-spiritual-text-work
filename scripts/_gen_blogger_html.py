"""Generate an author-card HTML snippet with an embedded photo, and insert it
into a blog post HTML file (before </article>, or before </body> if there's
no <article> tag).

Usage:
  python scripts/_gen_blogger_html.py --html blogger-posts/CaptainRita/2026-08-01/post.html \
      --image PSSM_Content/02_Media/Raw/Photos/CaptainRita.png \
      --name "Captain Rita" --caption "Daily Quotations - July 31, 2026"

Re-running with the same --html updates the existing author card in place
(it is wrapped in <!-- author-card:start/end --> markers) instead of
duplicating it. Pass --print-only to just print the snippet without
touching any file.
"""
from __future__ import annotations

import argparse
import base64
import io
import re
import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]

AUTHOR_CARD_START = "<!-- author-card:start -->"
AUTHOR_CARD_END = "<!-- author-card:end -->"


def build_author_card(image_path: Path, name: str, caption: str, size: int) -> str:
    img = Image.open(image_path).convert("RGB")
    img = img.resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode()
    data_uri = f"data:image/jpeg;base64,{b64}"

    caption_html = f'<span style="font-size:13px;color:#8a6a4a;">{caption}</span>' if caption else ""

    return (
        '<div style="display:flex;align-items:center;gap:16px;margin-top:32px;'
        'padding:18px 20px;border-radius:18px;background:rgba(186,122,58,0.08);'
        'border:1px solid rgba(186,122,58,0.2);">'
        f'<img src="{data_uri}" alt="{name}" style="width:{size}px;height:{size}px;'
        'border-radius:50%;object-fit:cover;object-position:center top;'
        'border:3px solid #ba7a3a;flex-shrink:0;">'
        f'<div><strong style="display:block;font-size:16px;color:#2a241f;">{name}</strong>'
        f'{caption_html}</div></div>'
    )


def insert_into_html(html_path: Path, card_html: str) -> None:
    html = html_path.read_text(encoding="utf-8")
    wrapped = f"{AUTHOR_CARD_START}\n{card_html}\n{AUTHOR_CARD_END}"

    existing_re = re.compile(re.escape(AUTHOR_CARD_START) + r".*?" + re.escape(AUTHOR_CARD_END), re.DOTALL)
    if existing_re.search(html):
        html = existing_re.sub(wrapped, html)
    elif "</article>" in html:
        html = html.replace("</article>", f"{wrapped}\n</article>", 1)
    elif "</body>" in html:
        html = html.replace("</body>", f"{wrapped}\n</body>", 1)
    else:
        html = html.rstrip("\n") + "\n" + wrapped + "\n"

    html_path.write_text(html, encoding="utf-8")


def resolve_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or path.exists():
        return path
    return REPO_ROOT / value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--html", required=True, help="Path to the blog post HTML file to update")
    parser.add_argument("--image", required=True, help="Path to the author photo to embed")
    parser.add_argument("--name", required=True, help="Author display name")
    parser.add_argument("--caption", default="", help="Subtitle/caption text under the name")
    parser.add_argument("--size", type=int, default=72, help="Thumbnail size in px (default: 72)")
    parser.add_argument("--print-only", action="store_true", help="Print the snippet instead of writing it into --html")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    image_path = resolve_path(args.image)
    if not image_path.exists():
        raise SystemExit(f"Image not found: {image_path}")

    card_html = build_author_card(image_path, args.name, args.caption, args.size)

    if args.print_only:
        print(card_html)
        return 0

    html_path = resolve_path(args.html)
    if not html_path.exists():
        raise SystemExit(f"HTML file not found: {html_path}")

    insert_into_html(html_path, card_html)
    print(f"Author card inserted into {html_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
