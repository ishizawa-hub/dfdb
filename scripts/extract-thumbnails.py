#!/usr/bin/env python3
"""
PDFから作品サムネイルを座標ベースでクロップ抽出。
全ページを高解像度レンダリングし、作品位置に対応する領域を切り出す。

Usage: python scripts/extract-thumbnails.py --all
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

START_PAGE = {"2023-2024": 18, "2021-2022": 17, "2020-2021": 17}
END_PAGE = {"2023-2024": 367, "2021-2022": 375, "2020-2021": 355}

# PDF座標系での作品サムネイル位置（おおよそ）
# ページサイズ: ~361 x ~515
# 左カラム: x=15-170, 右カラム: x=190-350
# 作品1: y=250-370 (上段), 作品2: y=390-490 (下段)
# サムネイルは各作品テキストの上に配置（約100x60ポイント）

WORK_REGIONS = {
    # (x0, y0, x1, y1) in PDF coordinates for each work slot
    "left_1":  (12, 250, 172, 365),   # Left column, work 1
    "left_2":  (12, 390, 172, 490),   # Left column, work 2
    "right_1": (188, 250, 348, 365),  # Right column, work 1
    "right_2": (188, 390, 348, 490),  # Right column, work 2
}

# Scale factor for rendering
SCALE = 2.0


def extract_thumbnails(year, source_dir, output_dir):
    pdf_name = PDF_MAP.get(year)
    if not pdf_name:
        return {}
    pdf_path = os.path.join(source_dir, pdf_name)
    if not os.path.exists(pdf_path):
        print(f"PDF not found: {pdf_path}")
        return {}

    print(f"\nExtracting thumbnails from {pdf_name}...")
    doc = fitz.open(pdf_path)
    start = START_PAGE.get(year, 0)
    end = min(END_PAGE.get(year, doc.page_count), doc.page_count)

    thumb_dir = os.path.join(output_dir, "thumbnails", year)
    os.makedirs(thumb_dir, exist_ok=True)

    results = {}  # page_side_slot -> filepath
    count = 0

    for pi in range(start, end):
        page = doc[pi]
        pw, ph = page.rect.width, page.rect.height

        for slot_name, (x0, y0, x1, y1) in WORK_REGIONS.items():

            # Crop using clip parameter on page rendering
            clip_rect = fitz.Rect(x0, y0, x1, y1)
            mat_crop = fitz.Matrix(SCALE, SCALE)
            pix_crop = page.get_pixmap(matrix=mat_crop, clip=clip_rect, alpha=False)

            if pix_crop.width < 10 or pix_crop.height < 10:
                pix_crop = None
                continue

            fname = f"p{pi+1}_{slot_name}.jpg"
            fpath = os.path.join(thumb_dir, fname)
            # Save as JPEG with lower quality for smaller file size
            pix_crop.save(fpath, jpg_quality=60)
            pix_crop = None

            key = f"{pi+1}_{slot_name}"
            results[key] = f"/thumbnails/{year}/{fname}"
            count += 1

        if (pi - start) % 50 == 0:
            print(f"  Page {pi+1}/{end} ({count} thumbnails)")

    doc.close()
    print(f"  Total: {count} thumbnails for {year}")
    return results


def match_thumbnails_to_works(year, data_dir, thumb_results):
    """v4データと照合してサムネイルをワークに紐付け"""
    json_path = os.path.join(data_dir, f"v4_{year}.json")
    if not os.path.exists(json_path):
        return

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    matched = 0
    for d in data['directors']:
        page = d['sourcePage']
        # Determine column from the v4 data
        # v4 doesn't directly store column side, but we can check from multiple directors on the same page
        # Use a simpler approach: assign thumbnails by position

        for wi, work in enumerate(d['works']):
            # Each director has up to 2 works visible on their page slot
            # Director is on left or right column - we need to figure out which
            # For now, try both sides and pick the one that exists
            slot = f"{'1' if wi == 0 else '2'}"

            for side in ['left', 'right']:
                key = f"{page}_{side}_{slot}"
                if key in thumb_results:
                    work['thumbnailPath'] = thumb_results[key]
                    matched += 1
                    # Remove from results so it's not double-assigned
                    del thumb_results[key]
                    break

    # Save updated data
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"  Matched {matched} thumbnails to works for {year}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", help="Specific year")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = os.path.dirname(base)
    out = base  # Save to public/thumbnails
    data_dir = os.path.join(base, "data", "v4")

    # Output to public dir for serving
    pub_out = os.path.join(base, "public")

    years = ["2023-2024", "2021-2022", "2020-2021"] if args.all else [args.year or "2023-2024"]

    for y in years:
        results = extract_thumbnails(y, src, pub_out)
        match_thumbnails_to_works(y, data_dir, results)
