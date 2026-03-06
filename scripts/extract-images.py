#!/usr/bin/env python3
"""
PDFから監督写真を抽出してWebPで保存する。
PDFは全ページスキャン画像のため、ページレンダリング→クロップ方式で抽出。
Usage: python scripts/extract-images.py --year 2023-2024 [--limit 20]
"""
import argparse
import json
import os
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

# Portrait crop regions in PDF points (page is 361 x 514)
# Left column portrait: top-right area of left half
LEFT_PORTRAIT = fitz.Rect(115, 2, 180, 80)
# Right column portrait: top-right area of right half
RIGHT_PORTRAIT = fitz.Rect(280, 2, 345, 80)
# Column boundary: x < this = left column
COLUMN_BOUNDARY = 180.0
# Render zoom factor (3x for good quality WebP)
ZOOM = 3


def find_director_column(page, director_name: str) -> str:
    """ページ内のテキストブロックから監督名を探し、左右カラムを判定"""
    blocks = page.get_text("blocks")
    for block in blocks:
        x0, y0, x1, y1, text = block[0], block[1], block[2], block[3], block[4]
        # テキストブロックに監督名が含まれるか
        cleaned = text.replace(" ", "").replace("　", "").strip()
        name_clean = director_name.replace(" ", "").replace("　", "")
        if name_clean in cleaned:
            return "left" if x0 < COLUMN_BOUNDARY else "right"
    # 名前が見つからない場合、名前の一部（姓のみ）で検索
    if len(director_name) >= 2:
        family_name = director_name[:2]
        for block in blocks:
            x0, text = block[0], block[4]
            if family_name in text:
                return "left" if x0 < COLUMN_BOUNDARY else "right"
    return "unknown"


def extract_portraits(year: str, limit: int = 0):
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

    output_dir = os.path.join(base_dir, "public", "portraits")
    os.makedirs(output_dir, exist_ok=True)

    # DBから監督→ページマッピングを取得
    db_path = os.path.join(base_dir, "prisma", "dev.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT d.id, d.name, dys.sourcePage
        FROM Director d
        JOIN DirectorYearSource dys ON d.id = dys.directorId
        WHERE dys.sourceYear = ?
        ORDER BY dys.sourcePage, d.id
    """,
        (year,),
    )
    directors = cur.fetchall()
    print(f"Found {len(directors)} directors for {year}")

    if limit > 0:
        directors = directors[:limit]

    doc = fitz.open(pdf_path)
    mat = fitz.Matrix(ZOOM, ZOOM)

    extracted = 0
    failed = 0
    portrait_map = {}

    # ページごとにグループ化
    page_groups = {}
    for d_id, d_name, d_page in directors:
        if d_page is None:
            continue
        if d_page not in page_groups:
            page_groups[d_page] = []
        page_groups[d_page].append((d_id, d_name))

    for page_num, page_directors in sorted(page_groups.items()):
        if page_num < 1 or page_num > doc.page_count:
            continue

        page = doc[page_num - 1]  # 0-indexed

        for d_id, d_name in page_directors:
            column = find_director_column(page, d_name)

            if column == "left":
                clip = LEFT_PORTRAIT
            elif column == "right":
                clip = RIGHT_PORTRAIT
            else:
                # 不明な場合、ページ上の位置が1人目なら左、2人目なら右
                idx = [x[0] for x in page_directors].index(d_id)
                clip = LEFT_PORTRAIT if idx == 0 else RIGHT_PORTRAIT
                column = "left" if idx == 0 else "right"

            try:
                pix = page.get_pixmap(matrix=mat, clip=clip)
                img_data = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_data))

                if img.mode != "RGB":
                    img = img.convert("RGB")

                filename = f"{year}_{d_id}.webp"
                filepath = os.path.join(output_dir, filename)
                img.save(filepath, "WEBP", quality=82)

                # DB更新
                web_path = f"/portraits/{filename}"
                cur.execute(
                    "UPDATE Director SET portraitImagePath = ? WHERE id = ?",
                    (web_path, d_id),
                )

                portrait_map[str(d_id)] = {
                    "filename": filename,
                    "path": web_path,
                    "page": page_num,
                    "column": column,
                    "size": [img.width, img.height],
                }

                extracted += 1
            except Exception as e:
                print(f"  Error: {d_name} (id={d_id}, page={page_num}): {e}")
                failed += 1

        if page_num % 50 == 0:
            print(f"  Processing page {page_num}... ({extracted} extracted)")

    conn.commit()
    conn.close()
    doc.close()

    # マッピング保存
    map_path = os.path.join(base_dir, "data", "intermediate", f"portraits_{year}.json")
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump(portrait_map, f, ensure_ascii=False, indent=2)

    print(f"\nExtracted {extracted} portraits ({failed} failed)")
    print(f"Portrait map saved to {map_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    extract_portraits(args.year, args.limit)
