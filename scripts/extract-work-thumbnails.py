#!/usr/bin/env python3
"""
PDFから作品サムネイル画像を抽出する。
各ディレクターのカラム内の作品エリアをクロップしてWebPで保存。
Usage: python scripts/extract-work-thumbnails.py --year 2023-2024
"""
import argparse
import json
import os
import re
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")

import fitz
from PIL import Image
import io

PDF_MAP = {
    "2023-2024": "CM・映像ディレクターズファイル2023-2024.pdf",
    "2021-2022": "CM・映像ディレクターズファイル2021-2022.pdf",
    "2020-2021": "CM・映像ディレクターズファイル2020-2021.pdf",
}

# Page dimensions: 361 x 514 points
# Left column: x=34-180, Right column: x=198-340
LEFT_COL = (30, 0, 183, 514)
RIGHT_COL = (194, 0, 345, 514)
COLUMN_BOUNDARY = 180.0
ZOOM = 3


def get_director_column_from_db(db_path, director_id, year):
    """DBのportraitマッピングからカラム位置を取得"""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT portraitImagePath FROM Director WHERE id = ?", (director_id,)
    )
    row = cur.fetchone()
    conn.close()
    # Portraits extracted with left/right crop info in the mapping JSON
    return row[0] if row else None


def find_works_region(page, column, page_height):
    """作品エリアのY座標範囲を特定する"""
    blocks = page.get_text("blocks")
    col_x0, col_x1 = (30, 183) if column == "left" else (194, 345)

    # Find blocks in this column
    col_blocks = []
    for block in blocks:
        bx0, by0, bx1, by1, text = block[0], block[1], block[2], block[3], block[4]
        if bx0 >= col_x0 - 5 and bx1 <= col_x1 + 5:
            col_blocks.append((by0, by1, text.strip()))

    if not col_blocks:
        return None

    # Find the Y where works start:
    # Works have pattern "Agency＋Production Year" or copyright marks
    work_start_y = page_height * 0.4  # Default: 40% down
    for by0, by1, text in col_blocks:
        # Look for work captions (contain ＋ or + with year)
        if re.search(r'[＋+].*(?:19|20)\d{2}', text):
            # The thumbnail is above this text
            work_start_y = min(work_start_y, by0 - 80)  # thumbnail ~80pt above caption
            break
        # Or look for copyright marks
        if text.startswith('©') or text.startswith('Ⓒ'):
            work_start_y = min(work_start_y, by0 - 10)
            break

    return max(work_start_y, 100)  # Don't go above y=100 (portrait area)


def extract_work_areas(page, column, page_width, page_height):
    """作品サムネイルのリスト（クロップ領域）を返す"""
    blocks = page.get_text("blocks")
    col_x0, col_x1 = (30, 183) if column == "left" else (194, 345)

    # Find work caption blocks in this column
    work_captions = []
    for block in blocks:
        bx0, by0, bx1, by1, text = block[0], block[1], block[2], block[3], block[4]
        if bx0 >= col_x0 - 5 and bx1 <= col_x1 + 15:
            # Work caption: contains Agency+Production Year
            if re.search(r'[＋+].*(?:19|20)\d{2}', text):
                work_captions.append((by0, by1, text.strip()))

    if not work_captions:
        return []

    # Sort by Y position
    work_captions.sort(key=lambda x: x[0])

    # For each work caption, the thumbnail is above it
    thumbnails = []
    for i, (caption_y0, caption_y1, caption_text) in enumerate(work_captions):
        # Thumbnail is above the caption
        # The bottom of the thumbnail is near caption_y0
        # The top depends on spacing - typically 60-90 points for thumbnail height
        thumb_bottom = caption_y0 - 2
        if i > 0:
            # Previous caption's bottom is the ceiling
            prev_bottom = work_captions[i - 1][1]
            thumb_top = prev_bottom + 2
        else:
            # First thumbnail - top is after profile area
            thumb_top = max(caption_y0 - 100, 100)

        # Ensure reasonable size
        if thumb_bottom - thumb_top < 20:
            continue

        thumbnails.append({
            "rect": fitz.Rect(col_x0, thumb_top, col_x1, thumb_bottom),
            "caption": caption_text,
        })

    return thumbnails


def extract_thumbnails(year: str):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    source_dir = os.path.dirname(base_dir)
    pdf_name = PDF_MAP.get(year)
    if not pdf_name:
        print(f"Unknown year: {year}")
        return

    pdf_path = os.path.join(source_dir, pdf_name)
    if not os.path.exists(pdf_path):
        print(f"PDF not found: {pdf_path}")
        return

    output_dir = os.path.join(base_dir, "public", "thumbnails")
    os.makedirs(output_dir, exist_ok=True)

    db_path = os.path.join(base_dir, "prisma", "dev.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Get works with their directors' page info
    cur.execute("""
        SELECT w.id, w.title, w.directorId, w.sourceYear, w.agency,
               d.name, dys.sourcePage
        FROM Work w
        JOIN Director d ON d.id = w.directorId
        JOIN DirectorYearSource dys ON dys.directorId = d.id AND dys.sourceYear = w.sourceYear
        WHERE w.sourceYear = ?
        ORDER BY dys.sourcePage, w.directorId, w.id
    """, (year,))
    works = cur.fetchall()
    print(f"Found {len(works)} works for {year}")

    # Load portrait mapping to determine column
    portrait_map_path = os.path.join(base_dir, "data", "intermediate", f"portraits_{year}.json")
    portrait_map = {}
    if os.path.exists(portrait_map_path):
        with open(portrait_map_path, "r", encoding="utf-8") as f:
            portrait_map = json.load(f)

    doc = fitz.open(pdf_path)
    mat = fitz.Matrix(ZOOM, ZOOM)

    # Group works by director+page
    director_page_works = {}
    for w_id, w_title, d_id, w_sy, w_agency, d_name, d_page in works:
        key = (d_id, d_page)
        if key not in director_page_works:
            director_page_works[key] = {
                "director_name": d_name,
                "page": d_page,
                "director_id": d_id,
                "works": [],
            }
        director_page_works[key]["works"].append({
            "id": w_id,
            "title": w_title,
            "agency": w_agency,
        })

    extracted = 0
    for (d_id, d_page), info in sorted(director_page_works.items()):
        if d_page is None or d_page < 1 or d_page > doc.page_count:
            continue

        # Determine column from portrait map
        column = "left"
        d_id_str = str(d_id)
        if d_id_str in portrait_map:
            column = portrait_map[d_id_str].get("column", "left")

        page = doc[d_page - 1]

        # Extract work thumbnail areas
        thumbnails = extract_work_areas(
            page, column, page.rect.width, page.rect.height
        )

        # Match thumbnails to works (by order)
        for idx, work_info in enumerate(info["works"]):
            if idx < len(thumbnails):
                thumb = thumbnails[idx]
                try:
                    pix = page.get_pixmap(matrix=mat, clip=thumb["rect"])
                    img_data = pix.tobytes("png")
                    img = Image.open(io.BytesIO(img_data))
                    if img.mode != "RGB":
                        img = img.convert("RGB")

                    filename = f"work_{work_info['id']}.webp"
                    filepath = os.path.join(output_dir, filename)
                    img.save(filepath, "WEBP", quality=80)

                    web_path = f"/thumbnails/{filename}"
                    cur.execute(
                        "UPDATE Work SET thumbnailPath = ? WHERE id = ?",
                        (web_path, work_info["id"]),
                    )
                    extracted += 1
                except Exception as e:
                    print(f"  Error: work {work_info['id']}: {e}")

        if d_page % 50 == 0:
            print(f"  Page {d_page}... ({extracted} thumbnails)")

    conn.commit()
    conn.close()
    doc.close()

    print(f"\nExtracted {extracted} work thumbnails")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", required=True)
    args = parser.parse_args()
    extract_thumbnails(args.year)
