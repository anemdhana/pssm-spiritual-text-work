"""Publish staged blog posts (blogger-posts/<Author>/<date>/) to Blogger.

For each entry in the date folder's `posts.txt` (format: `Title -> file.html`),
this script:
  - looks for an existing Blogger post with the same title and updates it
    (replace), or
  - creates a new post if no matching title is found (add).

Setup (one-time):
  1. pip install -r scripts/blogger_requirements.txt
  2. In Google Cloud Console, enable the "Blogger API v3" and create an
     OAuth 2.0 Client ID (Desktop app). Download the JSON as
     config/blogger-client-secret.json (gitignored).
  3. Find your numeric Blog ID (Blogger dashboard > Settings, or the URL
     when editing a post) and put it in config/blogger-config.properties:
         blog_id=1234567890123456789
  4. Run this script once; a browser window will open for you to grant
     access. The resulting token is cached at config/blogger-token.json.

Safety:
  - By default, NEW posts are created as drafts (not publicly visible) and
    EXISTING posts are updated in-place (Blogger preserves the existing
    published/draft state on update). Pass --publish to publish new posts
    immediately.
  - Use --dry-run to preview planned actions without calling the API.

Usage:
  python scripts/publish_to_blogger.py MaitreyaDadashreeji/2026-08-09
  python scripts/publish_to_blogger.py CaptainRita/2026-08-01 --publish
  python scripts/publish_to_blogger.py --author CaptainRita --date 2026-08-01 --dry-run
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BLOGGER_POSTS_ROOT = REPO_ROOT / "blogger-posts"
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "blogger-config.properties"
DEFAULT_CLIENT_SECRET_PATH = REPO_ROOT / "config" / "blogger-client-secret.json"
DEFAULT_TOKEN_PATH = REPO_ROOT / "config" / "blogger-token.json"

SCOPES = ["https://www.googleapis.com/auth/blogger"]

STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)
BODY_RE = re.compile(r"<body[^>]*>(.*?)</body>", re.IGNORECASE | re.DOTALL)
POST_LINE_RE = re.compile(r"^(.*?)\s*->\s*(\S+)\s*$")

log = logging.getLogger("publish_to_blogger")


def load_properties(path: Path) -> dict[str, str]:
    props: dict[str, str] = {}
    if not path.exists():
        return props
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        props[key.strip()] = value.strip()
    return props


def resolve_folder(value: str | None, author: str | None, date: str | None) -> Path:
    if value:
        candidate = Path(value)
        if not candidate.is_absolute():
            direct = REPO_ROOT / candidate
            scoped = BLOGGER_POSTS_ROOT / candidate
            candidate = direct if direct.exists() else scoped
        if candidate.exists():
            return candidate
        raise SystemExit(f"Folder not found: {value}")

    if author and date:
        candidate = BLOGGER_POSTS_ROOT / author / date
        if candidate.exists():
            return candidate
        raise SystemExit(f"Folder not found: {candidate}")

    raise SystemExit("Provide either a folder path, or both --author and --date.")


def parse_posts_txt(folder: Path) -> list[tuple[str, Path]]:
    posts_txt = folder / "posts.txt"
    if not posts_txt.exists():
        raise SystemExit(f"posts.txt not found in {folder}")

    entries: list[tuple[str, Path]] = []
    for line_no, line in enumerate(posts_txt.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        match = POST_LINE_RE.match(line)
        if not match:
            log.warning("Skipping unparseable line %d in %s: %r", line_no, posts_txt, line)
            continue
        title, filename = match.group(1).strip(), match.group(2).strip()
        html_path = folder / filename
        if not html_path.exists():
            log.warning("Skipping %r: file not found (%s)", title, html_path)
            continue
        entries.append((title, html_path))
    return entries


def extract_post_content(html_path: Path) -> str:
    """Combine the <style> block(s) and inner <body> content for Blogger.

    Blogger post content is injected into an existing page, so the
    surrounding <!DOCTYPE>/<html>/<head>/<body> wrapper tags are dropped;
    the <style> rules and body markup are kept so the card design renders.
    """
    html = html_path.read_text(encoding="utf-8")
    styles = "".join(STYLE_RE.findall(html))
    body_match = BODY_RE.search(html)
    body = body_match.group(1).strip() if body_match else html
    return f"{styles}\n{body}"


def get_blogger_service(client_secret_path: Path, token_path: Path):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover - environment setup guidance
        raise SystemExit(
            "Missing Google API libraries. Install them with:\n"
            "  pip install -r scripts/blogger_requirements.txt\n"
            f"Original error: {exc}"
        )

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not client_secret_path.exists():
                raise SystemExit(
                    f"Client secret file not found: {client_secret_path}\n"
                    "See the setup steps in this script's module docstring."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return build("blogger", "v3", credentials=creds)


def find_existing_post(service, blog_id: str, title: str) -> dict | None:
    normalized = title.strip().lower()
    request = service.posts().list(blogId=blog_id, fetchBodies=False, maxResults=500, status=["live", "draft"])
    while request is not None:
        response = request.execute()
        for item in response.get("items", []):
            if item.get("title", "").strip().lower() == normalized:
                return item
        request = service.posts().list_next(request, response)
    return None


def publish_folder(
    folder: Path,
    blog_id: str,
    client_secret_path: Path,
    token_path: Path,
    labels: list[str],
    publish_new: bool,
    dry_run: bool,
) -> None:
    entries = parse_posts_txt(folder)
    if not entries:
        log.warning("No valid posts found in %s", folder)
        return

    service = None if dry_run else get_blogger_service(client_secret_path, token_path)

    for title, html_path in entries:
        content = extract_post_content(html_path)

        if dry_run:
            log.info("[dry-run] Would look up title %r (from %s)", title, html_path.name)
            continue

        existing = find_existing_post(service, blog_id, title)
        if existing:
            log.info("Replacing existing post %r (id=%s)", title, existing["id"])
            body = {"title": title, "content": content}
            service.posts().patch(blogId=blog_id, postId=existing["id"], body=body).execute()
        else:
            log.info("Creating new post %r%s", title, " (draft)" if not publish_new else "")
            body = {"title": title, "content": content, "labels": labels}
            service.posts().insert(
                blogId=blog_id, body=body, isDraft=not publish_new
            ).execute()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "folder",
        nargs="?",
        help="Date folder to publish, e.g. MaitreyaDadashreeji/2026-08-09 "
        "(relative to blogger-posts/, or a full/relative path)",
    )
    parser.add_argument("--author", help="Author folder name, e.g. CaptainRita (used with --date)")
    parser.add_argument("--date", help="Date folder name, e.g. 2026-08-09 (used with --author)")
    parser.add_argument("--blog-id", help="Blogger numeric blog ID (overrides config file)")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to blogger-config.properties")
    parser.add_argument("--client-secret", default=str(DEFAULT_CLIENT_SECRET_PATH), help="OAuth client secret JSON path")
    parser.add_argument("--token", default=str(DEFAULT_TOKEN_PATH), help="Cached OAuth token JSON path")
    parser.add_argument("--label", action="append", default=[], help="Label to add to newly created posts (repeatable)")
    parser.add_argument("--publish", action="store_true", help="Publish new posts immediately instead of saving as drafts")
    parser.add_argument("--dry-run", action="store_true", help="Preview actions without calling the Blogger API")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s")

    folder = resolve_folder(args.folder, args.author, args.date)

    cfg = load_properties(Path(args.config))
    blog_id = args.blog_id or cfg.get("blog_id", "").strip()
    if not blog_id and not args.dry_run:
        raise SystemExit(
            f"No blog_id set. Pass --blog-id or add blog_id=... to {args.config}"
        )

    labels = args.label or ([folder.parent.name] if folder.parent != BLOGGER_POSTS_ROOT else [])

    publish_folder(
        folder=folder,
        blog_id=blog_id,
        client_secret_path=Path(args.client_secret),
        token_path=Path(args.token),
        labels=labels,
        publish_new=args.publish,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
