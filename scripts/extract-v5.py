#!/usr/bin/env python3
"""
v5 全面再抽出スクリプト
- 監督ポートレート抽出（ピクセル解析で写真領域を自動検出）
- 作品サムネイル抽出（テキスト除外、画像のみ自動クロップ）
- テキスト再パース（クライアント名・商品名・作品タイトル・制作体制を正確に分離）
- DB直接更新

Usage: python scripts/extract-v5.py --all [--dry-run] [--portraits-only] [--thumbnails-only]
"""
import argparse
import json
import os
import re
import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')

import fitz
import numpy as np
from PIL import Image

# =========================================================
# Configuration
# =========================================================

PDF_MAP = {
    "2023-2024": "CM・映像ディレクターズファイル2023-2024.pdf",
    "2021-2022": "CM・映像ディレクターズファイル2021-2022.pdf",
    "2020-2021": "CM・映像ディレクターズファイル2020-2021.pdf",
}

START_PAGE = {"2023-2024": 18, "2021-2022": 17, "2020-2021": 17}
END_PAGE = {"2023-2024": 367, "2021-2022": 375, "2020-2021": 355}

# Rendering scale (3x for good web resolution)
SCALE = 3.0
PORTRAIT_SCALE = 4.0  # Higher res for portraits

# Column X boundaries (PDF coordinates)
LEFT_COL_X = (12, 178)
RIGHT_COL_X = (185, 350)

# Portrait search regions within each column header
# The portrait photo sits on the RIGHT side of each column header
# Tightened x-range to avoid capturing name/phone text on the left
PORTRAIT_SEARCH = {
    'left':  {'x': (115, 178), 'y': (0, 72)},
    'right': {'x': (285, 352), 'y': (0, 72)},
}

# Work zone Y range (PDF coordinates)
WORK_Y_START = 180
WORK_Y_END = 495

# Text zone constants
WORK_ZONE_Y = 230  # Works text starts below this y
SIDEBAR_X = 340

# Thumbnail JPEG quality
THUMB_QUALITY = 85
PORTRAIT_QUALITY = 90

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'prisma', 'dev.db')

# =========================================================
# Pixel Analysis Helpers
# =========================================================

def pixmap_to_numpy(pix):
    """Convert fitz.Pixmap to numpy array"""
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)


def find_photo_bbox(data, white_thresh=230, min_size=25):
    """Find bounding box of photographic content in an image region.
    Returns (y0, y1, x0, x1) or None if no photo found."""
    # Non-white pixels (at least one channel below threshold)
    not_white = np.any(data < white_thresh, axis=2)

    rows_with_content = np.any(not_white, axis=1)
    cols_with_content = np.any(not_white, axis=0)

    if not np.any(rows_with_content) or not np.any(cols_with_content):
        return None

    r_indices = np.where(rows_with_content)[0]
    c_indices = np.where(cols_with_content)[0]

    r_min, r_max = r_indices[0], r_indices[-1]
    c_min, c_max = c_indices[0], c_indices[-1]

    # Minimum size check
    if (r_max - r_min) < min_size or (c_max - c_min) < min_size:
        return None

    return (r_min, r_max + 1, c_min, c_max + 1)


def compute_row_image_scores(data, white_thresh=235):
    """For each row, compute the fraction of non-white pixels."""
    # data shape: (H, W, 3)
    not_white = np.any(data < white_thresh, axis=2)  # (H, W) bool
    scores = np.mean(not_white, axis=1)  # (H,) float
    return scores


def compute_row_block_scores(data, white_thresh=230, min_block=8):
    """For each row, compute the fraction covered by WIDE non-white blocks.
    This filters out thin text strokes (which are narrow) and keeps
    actual image content (which spans wide continuous blocks)."""
    not_white = np.any(data < white_thresh, axis=2)  # (H, W) bool
    width = data.shape[1]
    scores = np.zeros(data.shape[0])

    for y in range(data.shape[0]):
        row = not_white[y]
        block_pixels = 0
        run = 0
        for x in range(width):
            if row[x]:
                run += 1
            else:
                if run >= min_block:
                    block_pixels += run
                run = 0
        if run >= min_block:
            block_pixels += run
        scores[y] = block_pixels / width

    return scores


def find_image_regions(scores, min_score=0.25, min_height=25, gap_tolerance=5):
    """Find contiguous regions of high image scores.
    Returns list of (start_row, end_row) tuples."""
    if len(scores) < 10:
        return []
    kernel = np.ones(5) / 5
    smoothed = np.convolve(scores, kernel, mode='same')

    in_region = False
    regions = []
    start = 0
    gap_count = 0

    for i, s in enumerate(smoothed):
        if s > min_score:
            if not in_region:
                start = i
                in_region = True
            gap_count = 0
        else:
            if in_region:
                gap_count += 1
                if gap_count > gap_tolerance:
                    end = i - gap_count
                    if end - start > min_height:
                        regions.append((start, end))
                    in_region = False
                    gap_count = 0

    if in_region:
        end = len(scores)
        if end - start > min_height:
            regions.append((start, end))

    return regions


def trim_text_from_edges(img_data, scale, white_thresh=232):
    """Trim text rows from top and bottom edges of a thumbnail.
    Text rows have scattered thin dark pixels on white background.
    Image rows have wide continuous blocks of colored content."""
    block_scores = compute_row_block_scores(img_data, white_thresh=white_thresh, min_block=int(6 * scale))

    # Image threshold: rows with >25% covered by wide blocks are "image"
    img_thresh = 0.20
    h = img_data.shape[0]

    # Find bottom boundary: scan from bottom, skip text/white rows
    bottom = h
    for i in range(h - 1, -1, -1):
        if block_scores[i] > img_thresh:
            bottom = i + 1
            break

    # Find top boundary: scan from top, skip text/white rows
    top = 0
    for i in range(h):
        if block_scores[i] > img_thresh:
            top = i
            break

    # Safety: ensure we keep at least 60% of the region
    min_height = int(h * 0.5)
    if bottom - top < min_height:
        top = 0
        bottom = h

    return top, bottom


# =========================================================
# Portrait Extraction
# =========================================================

def extract_portrait(page, col_side, scale=PORTRAIT_SCALE):
    """Extract director portrait from column header area."""
    region = PORTRAIT_SEARCH[col_side]
    x0, y0 = region['x'][0], region['y'][0]
    x1, y1 = region['x'][1], region['y'][1]

    clip = fitz.Rect(x0, y0, x1, y1)
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
    data = pixmap_to_numpy(pix)

    # Find the photo bounding box (trim white space)
    bbox = find_photo_bbox(data, white_thresh=225, min_size=int(20 * scale))
    if bbox is None:
        return None

    ry0, ry1, rx0, rx1 = bbox
    portrait_data = data[ry0:ry1, rx0:rx1]

    # Check if it's actually a photo (not just text)
    # Photos have more color variance than text
    if portrait_data.size == 0:
        return None

    # Compute color saturation: difference between channels
    mean_per_pixel = np.mean(portrait_data, axis=2, keepdims=True)
    saturation = np.mean(np.abs(portrait_data.astype(float) - mean_per_pixel))

    # Also check the ratio of "colored" pixels (not pure black/white/gray)
    r, g, b = portrait_data[:,:,0].astype(float), portrait_data[:,:,1].astype(float), portrait_data[:,:,2].astype(float)
    pixel_sat = np.maximum(np.maximum(np.abs(r-g), np.abs(g-b)), np.abs(r-b))
    colored_ratio = np.mean(pixel_sat > 10)

    # If very low color saturation and low colored pixel ratio, it's likely just text
    if saturation < 5 and colored_ratio < 0.1:
        # Try grayscale photo detection: check if there's smooth gradient
        gray = np.mean(portrait_data, axis=2)
        # Text has bimodal distribution (white + black), photos have spread
        gray_std = np.std(gray)
        if gray_std < 30:
            return None  # Likely just text or blank

    # Check minimum non-white area
    not_white = np.any(portrait_data < 220, axis=2)
    if np.mean(not_white) < 0.15:
        return None  # Too much white space

    return Image.fromarray(portrait_data)


# =========================================================
# Work Thumbnail Extraction
# =========================================================

def extract_work_thumbnails(page, col_side, scale=SCALE):
    """Extract work thumbnail images from the work zone of a column.
    Uses row-by-row pixel analysis with block scoring to find image boundaries,
    automatically excluding text rows."""

    if col_side == 'left':
        x0, x1 = LEFT_COL_X
    else:
        x0, x1 = RIGHT_COL_X

    # Add small margins
    x0 = max(x0 - 2, 0)
    x1 = min(x1 + 2, 362)

    clip = fitz.Rect(x0, WORK_Y_START, x1, WORK_Y_END)
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
    data = pixmap_to_numpy(pix)

    # Use block scoring (filters out thin text strokes)
    scores = compute_row_block_scores(data, white_thresh=230, min_block=int(6 * scale))

    # Find image regions with higher threshold
    regions = find_image_regions(scores, min_score=0.25, min_height=int(15 * scale), gap_tolerance=int(2 * scale))

    thumbnails = []
    for start_row, end_row in regions:
        img_data = data[start_row:end_row, :]

        # Additional text trimming pass on this specific region
        trim_top, trim_bottom = trim_text_from_edges(img_data, scale, white_thresh=230)
        img_data = img_data[trim_top:trim_bottom, :]

        if img_data.shape[0] < int(10 * scale):
            continue

        # Trim white borders on all sides
        bbox = find_photo_bbox(img_data, white_thresh=232, min_size=int(10 * scale))
        if bbox is None:
            continue

        ry0, ry1, rx0, rx1 = bbox
        trimmed = img_data[ry0:ry1, rx0:rx1]

        if trimmed.shape[0] < 20 or trimmed.shape[1] < 30:
            continue

        # Convert y coordinates back to PDF space
        pdf_y_start = WORK_Y_START + (start_row + trim_top + ry0) / scale
        pdf_y_end = WORK_Y_START + (start_row + trim_top + ry1) / scale

        thumbnails.append({
            'image': Image.fromarray(trimmed),
            'y_start': pdf_y_start,
            'y_end': pdf_y_end,
        })

    return thumbnails


# =========================================================
# Text Extraction & Parsing (improved v5)
# =========================================================

def is_cjk(ch):
    cp = ord(ch)
    return ((0x4E00 <= cp <= 0x9FFF) or (0x3400 <= cp <= 0x4DBF) or
            (0x3040 <= cp <= 0x309F) or (0x30A0 <= cp <= 0x30FF) or
            (0xFF65 <= cp <= 0xFF9F))


def hw2fw_katakana(text):
    hw2fw = str.maketrans(
        'ｦｧｨｩｪｫｬｭｮｯｰｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝﾞﾟ',
        'ヲァィゥェォャュョッーアイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワン゛゜')
    r = text.translate(hw2fw)
    for pair, repl in [('カ゛','ガ'),('キ゛','ギ'),('ク゛','グ'),('ケ゛','ゲ'),('コ゛','ゴ'),
                        ('サ゛','ザ'),('シ゛','ジ'),('ス゛','ズ'),('セ゛','ゼ'),('ソ゛','ゾ'),
                        ('タ゛','ダ'),('チ゛','ヂ'),('ツ゛','ヅ'),('テ゛','デ'),('ト゛','ド'),
                        ('ハ゛','バ'),('ヒ゛','ビ'),('フ゛','ブ'),('ヘ゛','ベ'),('ホ゛','ボ'),
                        ('ハ゜','パ'),('ヒ゜','ピ'),('フ゜','プ'),('ヘ゜','ペ'),('ホ゜','ポ')]:
        r = r.replace(pair, repl)
    return r


def fix_ocr(text):
    t = hw2fw_katakana(text)
    t = t.replace('十', '+').replace('＋', '+').replace('＝', '=').replace('：', ':')
    return t


def norm_spaced(text):
    s = text.strip()
    if not s or len(s) < 3:
        return s
    chars = list(s)
    sp = sum(1 for i, c in enumerate(chars) if c != ' ' and i+2 < len(chars) and chars[i+1] == ' ' and chars[i+2] != ' ')
    ns = sum(1 for c in chars if c != ' ')
    if ns > 2 and sp / ns > 0.5:
        return s.replace(' ', '')
    return s


def get_page_lines(page):
    """Extract all text lines with positions and font sizes."""
    lines = []
    d = page.get_text('dict')
    for block in d['blocks']:
        if block['type'] != 0:
            continue
        for line in block['lines']:
            spans = line['spans']
            if not spans:
                continue
            text = ''.join(s['text'] for s in spans).strip()
            if not text:
                continue
            lx0, ly0, lx1, ly1 = line['bbox']
            max_fs = max(s['size'] for s in spans)
            lines.append({
                'x0': lx0, 'y0': ly0, 'x1': lx1, 'y1': ly1,
                'cx': (lx0 + lx1) / 2, 'text': text, 'fs': max_fs,
            })
    return sorted(lines, key=lambda l: (l['y0'], l['x0']))


def split_columns(lines, page_width):
    """Split text lines into left and right columns."""
    mid = page_width / 2
    left, right = [], []
    for l in lines:
        if l['fs'] > 15 and len(l['text']) <= 3:
            continue
        if l['fs'] < 1.5:
            continue
        if l['x0'] > SIDEBAR_X and len(l['text']) <= 3:
            continue
        if re.match(r'^0?\d{2,3}\s*[\'"]?\s*$', l['text']):
            continue
        if len(l['text']) <= 1:
            continue
        if l['cx'] < mid:
            left.append(l)
        else:
            right.append(l)
    left.sort(key=lambda l: l['y0'])
    right.sort(key=lambda l: l['y0'])
    return left, right


def find_name(col):
    """Find director name by font size."""
    for i, l in enumerate(col):
        if l['fs'] >= 9.5 and 2 <= len(l['text']) <= 15:
            cjk = sum(1 for c in l['text'] if is_cjk(c))
            if cjk >= 2:
                return i, l['text'].strip()
    return -1, ""


def merge_same_y(lines, y_threshold=3):
    """Merge lines at the same y coordinate."""
    if not lines:
        return []
    result = []
    current_y = lines[0]['y0']
    current_texts = [lines[0]['text']]
    current_fs = lines[0]['fs']

    for l in lines[1:]:
        if abs(l['y0'] - current_y) < y_threshold:
            current_texts.append(l['text'])
            current_fs = max(current_fs, l['fs'])
        else:
            merged = norm_spaced(' '.join(current_texts))
            if merged:
                result.append({'y': current_y, 'text': merged, 'fs': current_fs})
            current_y = l['y0']
            current_texts = [l['text']]
            current_fs = l['fs']

    merged = norm_spaced(' '.join(current_texts))
    if merged:
        result.append({'y': current_y, 'text': merged, 'fs': current_fs})
    return result


def is_garbage_text(text):
    s = text.strip()
    if len(s) <= 2:
        return True
    if re.match(r'^[Ii1l_\-\.\'\"\`\^]+$', s):
        return True
    if re.match(r'^[` つJ\'\"\^ー]+$', s):
        return True
    if re.match(r'^0?\d{2,3}[\'\"e]?$', s):
        return True
    return False


def parse_work_cluster_v5(cluster, source_year):
    """v5: Parse a work cluster into client, product, title, production team, year.

    Work text format in PDF:
      Line 1: [Client] [Product/Brand] [Title in 「」brackets]
      Line 2: [ProductionTeam] [Year]

    Examples:
      明治 TANPACT 「たんばく党」篇 / 電通+二番工房 2023
      Sony Music Labels 日向坂46 「One choice」 / P.I.C.S. 2023
      バスクリン アーュルタイム「あったかくなったのは」篇 / バスクリン+jeki+パラゴン 2022
    """
    raw_lines = [fix_ocr(cl['text']) for cl in cluster]
    lines = [l for l in raw_lines if not is_garbage_text(l)]
    if not lines:
        return None

    # Find year and production team line
    year = None
    production_team = ""
    year_line_idx = -1

    for i, line in enumerate(lines):
        m = re.search(r'((?:19|20)\d{2})\s*$', line)
        if m:
            year = int(m.group(1))
            before_year = line[:m.start()].strip()
            if before_year:
                production_team = before_year
            year_line_idx = i
            break

    # Collect non-year lines as title/client lines
    title_lines = []
    for i, line in enumerate(lines):
        if i == year_line_idx:
            continue
        if re.match(r'^P\s*[=]', line):
            continue
        cleaned = line.strip()
        if cleaned:
            title_lines.append(cleaned)

    if not title_lines:
        return None

    # Join all title lines into one string for parsing
    full_text = ' '.join(title_lines)

    # Parse: extract title in 「」brackets
    client_name = ""
    product_name = ""
    title = ""

    bracket_match = re.search(r'[「『（\(](.+?)[」』）\)]', full_text)
    if bracket_match:
        title = bracket_match.group(0)  # Include brackets: 「タイトル」
        before_bracket = full_text[:bracket_match.start()].strip()
        after_bracket = full_text[bracket_match.end():].strip()

        # Text before brackets = client + product
        # Try to split: first word/phrase = client, rest = product
        parts = before_bracket.split()
        if len(parts) >= 2:
            # Heuristic: if first part looks like a company name, it's the client
            # and the rest is the product name
            client_name = parts[0]
            product_name = ' '.join(parts[1:])
        elif len(parts) == 1:
            client_name = parts[0]

        # Append any suffix after the bracket to the title (e.g., 「xxx」篇 WebMovie)
        if after_bracket:
            # Check if it's a suffix like 篇, 編, WebMovie, etc.
            if re.match(r'^(篇|編|Web|MV|PV|TVCM|CM|Movie|Ver)', after_bracket):
                title = title + after_bracket
            else:
                # It's additional title text
                title = title + ' ' + after_bracket
    else:
        # No brackets found - use heuristics
        parts = full_text.split()
        if len(parts) >= 3:
            client_name = parts[0]
            # Check if there's a clear brand/product separation
            title = ' '.join(parts[1:])
        elif len(parts) == 2:
            client_name = parts[0]
            title = parts[1]
        else:
            title = full_text

    # Clean up
    client_name = client_name.strip()
    product_name = product_name.strip()
    title = title.strip()
    production_team = production_team.strip()

    # If client_name is empty but title has content, use title as-is
    if not client_name and not title:
        return None

    return {
        "clientName": client_name or None,
        "productName": product_name or None,
        "title": title or client_name,
        "agency": production_team or None,  # "agency" field stores production team
        "year": year or 0,
        "sourceYear": source_year,
    }


def extract_work_text(col_lines, source_year):
    """Extract work information from column text lines below work zone Y."""
    work_lines = [l for l in col_lines if l['y0'] >= WORK_ZONE_Y]
    work_merged = merge_same_y(work_lines)

    # Cluster by Y gap
    if not work_merged:
        return []
    clusters = []
    current = [work_merged[0]]
    for wl in work_merged[1:]:
        if wl['y'] - current[-1]['y'] > 50:  # CLUSTER_GAP
            clusters.append(current)
            current = [wl]
        else:
            current.append(wl)
    clusters.append(current)

    works = []
    for cluster in clusters:
        w = parse_work_cluster_v5(cluster, source_year)
        if w:
            works.append(w)
    return works


# =========================================================
# Main Processing
# =========================================================

def process_page(page, page_num, year, output_base, stats):
    """Process a single PDF page: extract portraits, thumbnails, and text for both columns."""
    results = {'left': None, 'right': None}

    lines = get_page_lines(page)
    left_lines, right_lines = split_columns(lines, page.rect.width)

    for col_side, col_lines in [('left', left_lines), ('right', right_lines)]:
        if len(col_lines) < 3:
            continue

        # Find director name
        name_idx = -1
        name = ""
        for i, l in enumerate(col_lines):
            if l['fs'] >= 9.5 and 2 <= len(l['text']) <= 15:
                cjk = sum(1 for c in l['text'] if is_cjk(c))
                if cjk >= 2:
                    name_idx = i
                    name = l['text'].strip()
                    break
        if name_idx < 0:
            continue

        # Extract portrait
        portrait_img = extract_portrait(page, col_side, PORTRAIT_SCALE)
        portrait_path = None
        if portrait_img is not None:
            portrait_dir = os.path.join(output_base, "portraits", year)
            os.makedirs(portrait_dir, exist_ok=True)
            fname = f"p{page_num}_{col_side}.jpg"
            fpath = os.path.join(portrait_dir, fname)
            portrait_img.save(fpath, "JPEG", quality=PORTRAIT_QUALITY)
            portrait_path = f"/portraits/{year}/{fname}"
            stats['portraits'] += 1

        # Extract work thumbnails
        work_thumbnails = extract_work_thumbnails(page, col_side, SCALE)
        thumb_paths = []
        for ti, thumb in enumerate(work_thumbnails):
            thumb_dir = os.path.join(output_base, "thumbnails_v5", year)
            os.makedirs(thumb_dir, exist_ok=True)
            fname = f"p{page_num}_{col_side}_{ti+1}.jpg"
            fpath = os.path.join(thumb_dir, fname)
            thumb['image'].save(fpath, "JPEG", quality=THUMB_QUALITY)
            thumb_paths.append({
                'path': f"/thumbnails_v5/{year}/{fname}",
                'y_start': thumb['y_start'],
                'y_end': thumb['y_end'],
            })
            stats['thumbnails'] += 1

        # Extract work text data
        works = extract_work_text(col_lines, year)

        results[col_side] = {
            'name': name,
            'page': page_num,
            'portrait_path': portrait_path,
            'thumbnails': thumb_paths,
            'works': works,
        }

    return results


def process_pdf(year, source_dir, output_base, stats):
    """Process an entire PDF file."""
    pdf_name = PDF_MAP.get(year)
    if not pdf_name:
        return {}
    pdf_path = os.path.join(source_dir, pdf_name)
    if not os.path.exists(pdf_path):
        print(f"PDF not found: {pdf_path}")
        return {}

    print(f"\n{'='*60}")
    print(f"Processing: {pdf_name}")
    print(f"{'='*60}")

    doc = fitz.open(pdf_path)
    start = START_PAGE.get(year, 0)
    end = min(END_PAGE.get(year, doc.page_count), doc.page_count)

    # page_num -> {left: {...}, right: {...}}
    all_results = {}

    for pi in range(start, end):
        page = doc[pi]
        page_num = pi + 1
        results = process_page(page, page_num, year, output_base, stats)
        all_results[page_num] = results

        if (pi - start) % 50 == 0:
            print(f"  Page {page_num}/{end} ... (portraits: {stats['portraits']}, thumbnails: {stats['thumbnails']})")

    doc.close()
    return all_results


def update_database(all_data, db_path):
    """Update the database with new portraits, thumbnails, and text data."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Get all directors with their source info
    directors = cur.execute("""
        SELECT d.id, d.name, dys.sourceYear, dys.sourcePage
        FROM Director d
        JOIN DirectorYearSource dys ON dys.directorId = d.id
        ORDER BY dys.sourceYear, dys.sourcePage, d.id
    """).fetchall()

    # Group by (year, page)
    page_groups = {}
    for d in directors:
        key = f"{d['sourceYear']}|{d['sourcePage']}"
        if key not in page_groups:
            page_groups[key] = []
        page_groups[key].append(dict(d))

    portrait_updated = 0
    thumb_updated = 0
    text_updated = 0

    for year, year_results in all_data.items():
        for page_num, page_results in year_results.items():
            key = f"{year}|{page_num}"
            if key not in page_groups:
                continue

            dirs_on_page = page_groups[key]

            for di, d in enumerate(dirs_on_page[:2]):
                col_side = 'left' if di == 0 else 'right'
                col_data = page_results.get(col_side)
                if col_data is None:
                    continue

                dir_id = d['id']

                # Update portrait
                if col_data['portrait_path']:
                    cur.execute('UPDATE Director SET portraitImagePath = ? WHERE id = ?',
                                (col_data['portrait_path'], dir_id))
                    portrait_updated += 1

                # Get works for this director
                works = cur.execute(
                    'SELECT id, title FROM Work WHERE directorId = ? AND sourceYear = ? ORDER BY id',
                    (dir_id, year)
                ).fetchall()

                # Update thumbnails (match by order)
                for wi, work in enumerate(works):
                    if wi < len(col_data['thumbnails']):
                        thumb_info = col_data['thumbnails'][wi]
                        cur.execute('UPDATE Work SET thumbnailPath = ? WHERE id = ?',
                                    (thumb_info['path'], work['id']))
                        thumb_updated += 1

                # Update text data (match by order)
                for wi, work in enumerate(works):
                    if wi < len(col_data['works']):
                        new_data = col_data['works'][wi]
                        cur.execute('''UPDATE Work SET
                            title = ?,
                            clientName = ?,
                            productName = ?,
                            agency = ?
                            WHERE id = ?''',
                            (new_data['title'],
                             new_data['clientName'],
                             new_data['productName'],
                             new_data['agency'],
                             work['id']))
                        text_updated += 1

    conn.commit()

    # Rebuild FTS
    print("Rebuilding FTS5...")
    try:
        cur.execute("INSERT INTO director_fts(director_fts) VALUES('rebuild');")
        conn.commit()
    except Exception as e:
        print(f"  FTS rebuild warning: {e}")

    # Stats
    total_dirs = cur.execute('SELECT COUNT(*) FROM Director').fetchone()[0]
    total_works = cur.execute('SELECT COUNT(*) FROM Work').fetchone()[0]
    with_portrait = cur.execute("SELECT COUNT(*) FROM Director WHERE portraitImagePath IS NOT NULL AND portraitImagePath != ''").fetchone()[0]
    with_thumb = cur.execute("SELECT COUNT(*) FROM Work WHERE thumbnailPath IS NOT NULL AND thumbnailPath != ''").fetchone()[0]
    with_yt = cur.execute("SELECT COUNT(*) FROM Work WHERE youtubeUrl IS NOT NULL AND youtubeUrl != ''").fetchone()[0]

    print(f"\n--- DB Update Results ---")
    print(f"  Portraits updated: {portrait_updated}")
    print(f"  Thumbnails updated: {thumb_updated}")
    print(f"  Text data updated: {text_updated}")
    print(f"\n--- DB Stats ---")
    print(f"  Directors: {total_dirs} (with portrait: {with_portrait})")
    print(f"  Works: {total_works} (with thumb: {with_thumb}, with YouTube: {with_yt})")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="v5 Complete Re-extraction")
    parser.add_argument("--year", help="Specific year")
    parser.add_argument("--all", action="store_true", help="Process all years")
    parser.add_argument("--dry-run", action="store_true", help="Extract images only, don't update DB")
    parser.add_argument("--page", type=int, help="Process a specific page only (for testing)")
    args = parser.parse_args()

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = os.path.dirname(base)  # PDF directory
    output_base = os.path.join(base, "public")

    years = ["2023-2024", "2021-2022", "2020-2021"] if args.all else [args.year or "2023-2024"]

    stats = {'portraits': 0, 'thumbnails': 0}
    all_data = {}

    for y in years:
        all_data[y] = process_pdf(y, src, output_base, stats)

    print(f"\n{'='*60}")
    print(f"Extraction Complete")
    print(f"  Total portraits: {stats['portraits']}")
    print(f"  Total thumbnails: {stats['thumbnails']}")
    print(f"{'='*60}")

    if not args.dry_run:
        print("\nUpdating database...")
        update_database(all_data, DB_PATH)
    else:
        print("\n(Dry run - database not updated)")


if __name__ == "__main__":
    main()
