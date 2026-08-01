import tempfile
import unittest
from pathlib import Path

import fitz

from scripts.pdf_to_md import convert_pdf_to_markdown


class PdfToMarkdownTests(unittest.TestCase):
    def test_convert_pdf_to_markdown_extracts_text(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_pdf = tmp_path / "sample.pdf"
            output_md = tmp_path / "sample.md"

            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), "Hello from PDF")
            doc.save(input_pdf)
            doc.close()

            convert_pdf_to_markdown(str(input_pdf), str(output_md))

            self.assertTrue(output_md.exists())
            content = output_md.read_text(encoding="utf-8")
            self.assertIn("Hello from PDF", content)


if __name__ == "__main__":
    unittest.main()
