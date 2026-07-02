import sys
import os
from pypdf import PdfReader


def extract_text_from_pdf(pdf_path: str, output_path: str = None) -> str:
    reader = PdfReader(pdf_path)
    text_parts = []

    for i, page in enumerate(reader.pages):
        page_text = page.extract_text()
        if page_text:
            text_parts.append(f"--- Page {i + 1} ---\n{page_text}")

    full_text = "\n\n".join(text_parts)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(full_text)
        print(f"Output saved to: {output_path}")

    return full_text


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python parse_pdf.py <pdf_file> [output_txt]")
        sys.exit(1)

    pdf_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    if not os.path.exists(pdf_file):
        print(f"Error: file not found: {pdf_file}")
        sys.exit(1)

    text = extract_text_from_pdf(pdf_file, output_file)
    print(text[:3000] + ("\n..." if len(text) > 3000 else ""))
