"""
pdf_to_md.py

Convert a PDF file to Markdown using PyMuPDF (fitz).

Usage:
    python pdf_to_md.py input.pdf [output.md]

Requires:
    pip install pymupdf
"""
import sys
from pathlib import Path

import fitz


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text from a PDF and return it as a plain text string."""
    doc = fitz.open(pdf_path)
    try:
        pages = []
        for page in doc:
            page_text = page.get_text("text").strip()
            if page_text:
                pages.append(page_text)
        return "\n\n".join(pages)
    finally:
        doc.close()


def convert_pdf_to_markdown(input_pdf: str, output_md: str | None = None) -> Path:
    """Convert a PDF file into a Markdown file."""
    input_path = Path(input_pdf)
    if not input_path.exists():
        raise FileNotFoundError(f"Input PDF not found: {input_pdf}")

    if output_md is None:
        output_path = input_path.with_suffix(".md")
    else:
        output_path = Path(output_md)

    text_content = extract_text_from_pdf(str(input_path))
    if not text_content.strip():
        text_content = """
# Extracted content

No text could be extracted from the PDF.
""".strip()

    output_path.write_text(text_content, encoding="utf-8")
    return output_path


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python pdf_to_md.py input.pdf [output.md]")
        return 1

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        output_path = convert_pdf_to_markdown(input_file, output_file)
    except Exception as exc:  # pragma: no cover - CLI safety
        print(f"Error: {exc}")
        return 1

    print(f"Markdown written: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
