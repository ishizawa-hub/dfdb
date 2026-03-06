#!/usr/bin/env python3
"""
PDFからテキストを抽出し、data/raw/に保存する。
Usage: python scripts/extract-text.py --year 2023-2024
"""
import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

import fitz  # PyMuPDF

PDF_MAP = {
    "2023-2024": "CM・映像ディレクターズファイル2023-2024.pdf",
    "2021-2022": "CM・映像ディレクターズファイル2021-2022.pdf",
    "2020-2021": "CM・映像ディレクターズファイル2020-2021.pdf",
}

# Director data starts at these pages (0-indexed)
START_PAGE = {
    "2023-2024": 18,  # page 19
    "2021-2022": 17,  # page 18
    "2020-2021": 17,  # page 18
}

# End pages (production company directories start here)
END_PAGE = {
    "2023-2024": 367,
    "2021-2022": 375,
    "2020-2021": 355,
}

def extract_text(year: str, source_dir: str, output_dir: str, limit: int = 0):
    pdf_name = PDF_MAP.get(year)
    if not pdf_name:
        print(f"Unknown year: {year}")
        sys.exit(1)

    pdf_path = os.path.join(source_dir, pdf_name)
    if not os.path.exists(pdf_path):
        print(f"PDF not found: {pdf_path}")
        sys.exit(1)

    print(f"Opening {pdf_path}...")
    doc = fitz.open(pdf_path)

    start = START_PAGE.get(year, 0)
    end = min(END_PAGE.get(year, doc.page_count), doc.page_count)

    if limit > 0:
        end = min(start + limit, end)

    pages = []
    for i in range(start, end):
        text = doc[i].get_text()
        pages.append({
            "page_number": i + 1,
            "text": text
        })
        if (i - start) % 50 == 0:
            print(f"  Processing page {i + 1}/{end}...")

    doc.close()

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"raw_{year}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "source_year": year,
            "pdf_name": pdf_name,
            "total_pages_extracted": len(pages),
            "pages": pages
        }, f, ensure_ascii=False, indent=2)

    print(f"Extracted {len(pages)} pages to {output_path}")
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract text from Directors File PDF")
    parser.add_argument("--year", required=True, help="Source year (e.g., 2023-2024)")
    parser.add_argument("--limit", type=int, default=0, help="Limit pages to extract (0=all)")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    source_dir = os.path.dirname(base_dir)  # parent directory where PDFs are
    output_dir = os.path.join(base_dir, "data", "raw")

    extract_text(args.year, source_dir, output_dir, args.limit)
