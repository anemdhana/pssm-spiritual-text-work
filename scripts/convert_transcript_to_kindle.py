from __future__ import annotations

from pathlib import Path

TRANSCRIPT_PATH = Path(
    r"C:\Users\dhana\media-files\Dr. Newton Kondaveeti  Speech  on Buddhi Yogam in the Event Shuddi Siddi Buddhi Tadipatri Pa 06-compact_size_speech.azure.transcript.txt"
)
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "booklets" / "dr-newton-kondaveeti-buddhi-yogam-tadipatri-pa-06.kindle.md"
THUMBNAIL_URI = "file:///C:/Users/dhana/media-files/1uJtTrkOF_w.jpg"
YOUTUBE_LINK = "https://www.youtube.com/watch?v=1uJtTrkOF_w"

HEADINGS = [
    ("మరి ఈరోజు మన మూడవ టాపిక్", "## బుద్ధి బుద్ధియోగం — ఈరోజు అంశం"),
    ("మొదటి రోజు మనం చెప్పుకున్నాం. అంతఃకరణ శుద్ధి.", "## అంతఃకరణ శుద్ధి మరియు భావోద్వేగ శుద్ధి"),
    ("ఇప్పుడు మీకు ఒక కాన్సెప్ట్ చెప్తాను.", "## అహంకారం, ఇగో, మరియు ఆధ్యాత్మిక స్వభావం"),
    (
        "ఈ దుష్ట తితుష్టయం గురించి చక్కగా అర్ధం చేసుకుంటారో",
        "## దుష్ట చతుష్టయం మరియు మహాభారత పాత్రలు",
    ),
    (
        "బుద్ధుడు అంటే ఎవరు? అని అడిగాడు.",
        "## బుద్ధి అంటే ఎవరు? మేల్కొలుపు మరియు ఆధ్యాత్మిక విజ్ఞానం",
    ),
    ("ఫైనల్ గా.", "## ధర్మం, ఆధ్యాత్మిక విజ్ఞానం, మరియు యోధుడు కర్ణుడు"),
    ("ఇప్పుడు మన జీవితంలో ఎన్నో సమస్యలు వస్తుంటాయి.", "## సమస్యలు ఉపాధ్యాయులే"),
    ("ఒక్కసారి మీరందరూ కూడా ఒక ఆలోచన చేయండి.", "## అనుభవం, పాఠాలు, మరియు ఆత్మపరిశీలన"),
    ("చావు కూడా గొప్పదే అండి.", "## మరణం, సహజత్వం, మరియు శరీరాన్ని వదులుకోవడం"),
    (
        "మరి ఇప్పటి నుంచి మీకు ఏదైనా సమస్య వస్తే మీరు ఎలా ఫీల్ అవుతారు?",
        "## ధన్యవాద మార్పు: సమస్యలకు థ్యాంక్ యూ చెప్పడం",
    ),
]


def parse_transcript(path: Path) -> list[str]:
    lines = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        if "] Dr Newton Kondaveti:" in raw_line:
            _, spoken = raw_line.split("] Dr Newton Kondaveti:", 1)
            lines.append(spoken.strip())
        else:
            lines.append(raw_line)
    return lines


CHUNK_SIZE = 10


def make_paragraphs(lines: list[str], chunk_size: int = CHUNK_SIZE) -> list[str]:
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        current.append(line)
        if len(current) >= chunk_size:
            paragraph = " ".join(current).replace("  ", " ").strip()
            paragraphs.append(paragraph)
            current = []
    if current:
        paragraphs.append(" ".join(current).replace("  ", " ").strip())
    return paragraphs


def write_markdown(lines: list[str], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    headings = list(HEADINGS)
    chapters: list[str] = []

    with output.open("w", encoding="utf-8") as out:
        out.write("# Dr. Newton Kondaveeti\n")
        out.write("## Buddhi Yogam in the Event Shuddi Siddi Buddhi Tadipatri — Part 06\n\n")
        out.write(f"![Front Cover]({THUMBNAIL_URI})\n\n")
        out.write(f"**Source:** [YouTube — Dr. Newton Kondaveeti Speech on Buddhi Yogam]({YOUTUBE_LINK})\n\n")
        out.write(f"**Cover / Thumbnail image:** `{THUMBNAIL_URI.replace('file:///', '')}`\n\n")
        out.write("---\n\n")
        out.write("## Table of Contents\n\n")
        for _, title in HEADINGS:
            chapters.append(title)
            out.write(f"- {title}\n")
        out.write("\n---\n\n")
        out.write("## Introduction\n\n")
        out.write(
            "This reading edition preserves the full Telugu transcript and structures it with spiritual chapters and context. "
            "The original speech is presented in a modern Kindle-friendly format with fewer line breaks and clear chapter headings.\n\n"
        )
        out.write("---\n\n")

        paragraphs = make_paragraphs(lines)
        marker_index = 0
        for paragraph in paragraphs:
            if marker_index < len(headings) and headings[marker_index][0] in paragraph:
                out.write(f"{headings[marker_index][1]}\n\n")
                out.write("---\n\n")
                marker_index += 1
            out.write(paragraph + "\n\n")

        out.write("---\n\n")
        out.write("## Final Reflection\n\n")
        out.write(
            "The speech is a powerful reminder that every challenge is a teacher, every problem is a lesson, "
            "and every spiritual practice must be grounded in clarity, gratitude, and steady attention.\n"
        )


def main() -> int:
    lines = parse_transcript(TRANSCRIPT_PATH)
    write_markdown(lines, OUTPUT_PATH)
    print(f"Wrote markdown file to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
