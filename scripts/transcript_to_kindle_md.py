import re
from pathlib import Path

BASE = Path("c:/Users/dhana/media-files")
TARGET = Path("c:/Users/dhana/GitHub/spiritual-text-work/booklets")

files = [
    (
        "Buddhi Takes The Final Decision - PMC-compact_size_speech.azure.transcript.txt",
        "Dr. Newton Kondaveti Buddhi Yogam Tadipatri - Buddhi Takes The Final Decision",
        "## బుద్ధి తుది నిర్ణయం తీసుకోవడం"
    ),
    (
        "How to gain Shuddhi, Siddhi and Buddhi through Pyramid Meditation-  LIVE FROM TADIPATRI - PMC-compact_size_speech.azure.transcript.txt",
        "Dr. Newton Kondaveti Buddhi Yogam Tadipatri - Shuddhi, Siddhi and Buddhi through Pyramid Meditation",
        "## శుద్ధి, సిద్ధి, బుద్ధి: పిరమిడ్ ధ్యానంలో"
    ),
]

for filename, title, subtitle in files:
    src = BASE / filename
    if not src.exists():
        raise FileNotFoundError(src)

    text = src.read_text(encoding="utf-8", errors="replace")
    lines = []
    for raw in text.splitlines():
        cleaned = re.sub(r"^\[.*?\]\s*Dr Newton Kondaveti:\s*", "", raw)
        cleaned = cleaned.strip()
        if not cleaned:
            continue
        lines.append(cleaned)

    out_path = TARGET / ("dr-newton-kondaveeti-buddhi-yogam-tadipatri-" + re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") + ".kindle.md")
    title_line = f"# {title}"
    content = [title_line, "", subtitle, "", "Source transcript: " + filename, ""]
    content.extend(lines)
    out_path.write_text("\n".join(content), encoding="utf-8")
    print(f"Wrote {out_path}")
