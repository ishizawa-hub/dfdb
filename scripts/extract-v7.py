#!/usr/bin/env python3
"""
v7 全面再抽出スクリプト - OCRベースのテキスト抽出版
- PyMuPDFのテキスト抽出(壊れたフォントエンコーディング)を廃止
- Tesseract OCR (jpn+eng) でレンダリング画像からテキスト抽出
- サムネイル-テキスト紐付けをY座標近接マッチングに変更
- プロフィール文の除外を強化
- サムネイル検出ロジックはv6を継続

Usage: python scripts/extract-v7.py --all [--dry-run] [--page N]
"""
import argparse
import os
import re
import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')

import fitz
import numpy as np
from PIL import Image
import pytesseract

# =========================================================
# Configuration
# =========================================================

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
os.environ['TESSDATA_PREFIX'] = os.path.expanduser('~/tessdata')

PDF_MAP = {
    "2023-2024": "CM・映像ディレクターズファイル2023-2024.pdf",
    "2021-2022": "CM・映像ディレクターズファイル2021-2022.pdf",
    "2020-2021": "CM・映像ディレクターズファイル2020-2021.pdf",
}

START_PAGE = {"2023-2024": 18, "2021-2022": 17, "2020-2021": 17}
END_PAGE = {"2023-2024": 367, "2021-2022": 375, "2020-2021": 355}

SCALE = 3.5
OCR_SCALE = 5.0  # Higher scale for OCR text quality
PORTRAIT_SCALE = 4.0

LEFT_COL_X = (12, 178)
RIGHT_COL_X = (185, 350)

PORTRAIT_SEARCH = {
    'left':  {'x': (115, 178), 'y': (0, 72)},
    'right': {'x': (285, 352), 'y': (0, 72)},
}

WORK_Y_START = 165
WORK_Y_END = 510
WORK_ZONE_Y = 220
SIDEBAR_X = 340

THUMB_QUALITY = 88
PORTRAIT_QUALITY = 90

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'prisma', 'dev.db')

# =========================================================
# Pixel Analysis Helpers (from v6 - proven to work well)
# =========================================================

def pixmap_to_numpy(pix):
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)


def find_photo_bbox(data, white_thresh=225, min_size=20):
    not_white = np.any(data < white_thresh, axis=2)
    rows_with_content = np.any(not_white, axis=1)
    cols_with_content = np.any(not_white, axis=0)
    if not np.any(rows_with_content) or not np.any(cols_with_content):
        return None
    r_indices = np.where(rows_with_content)[0]
    c_indices = np.where(cols_with_content)[0]
    r_min, r_max = r_indices[0], r_indices[-1]
    c_min, c_max = c_indices[0], c_indices[-1]
    if (r_max - r_min) < min_size or (c_max - c_min) < min_size:
        return None
    return (r_min, r_max + 1, c_min, c_max + 1)


def compute_row_block_scores(data, white_thresh=228, min_block=8):
    not_white = np.any(data < white_thresh, axis=2)
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


def find_image_regions(scores, min_score=0.12, min_height=20, gap_tolerance=10):
    if len(scores) < 10:
        return []
    kernel = np.ones(7) / 7
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


def trim_text_from_edges(img_data, scale, white_thresh=228):
    block_scores = compute_row_block_scores(img_data, white_thresh=white_thresh, min_block=int(4 * scale))
    h = img_data.shape[0]
    if h < 10:
        return 0, h
    text_thresh = 0.08
    img_thresh = 0.15
    bottom = h
    for i in range(h - 1, max(int(h * 0.3), -1), -1):
        if block_scores[i] > img_thresh:
            bottom = min(i + int(2 * scale), h)
            break
    top = 0
    for i in range(min(int(h * 0.7), h)):
        if block_scores[i] > img_thresh:
            top = max(i - int(2 * scale), 0)
            break
    min_keep = int(h * 0.30)
    if bottom - top < min_keep:
        top = 0
        bottom = h
    return top, bottom


def is_text_region(img_data, scale):
    block_scores = compute_row_block_scores(img_data, white_thresh=228, min_block=int(4 * scale))
    h = img_data.shape[0]
    if h == 0:
        return True
    image_rows = np.sum(block_scores > 0.15)
    image_ratio = image_rows / h
    if image_ratio < 0.20:
        return True
    not_white = np.any(img_data < 220, axis=2)
    dark_ratio = np.mean(not_white)
    if dark_ratio < 0.05:
        return True
    return False


# =========================================================
# Portrait Extraction (same as v6)
# =========================================================

def extract_portrait(page, col_side, scale=PORTRAIT_SCALE):
    region = PORTRAIT_SEARCH[col_side]
    x0, y0 = region['x'][0], region['y'][0]
    x1, y1 = region['x'][1], region['y'][1]
    clip = fitz.Rect(x0, y0, x1, y1)
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
    data = pixmap_to_numpy(pix)
    bbox = find_photo_bbox(data, white_thresh=225, min_size=int(20 * scale))
    if bbox is None:
        return None
    ry0, ry1, rx0, rx1 = bbox
    portrait_data = data[ry0:ry1, rx0:rx1]
    if portrait_data.size == 0:
        return None
    mean_per_pixel = np.mean(portrait_data, axis=2, keepdims=True)
    saturation = np.mean(np.abs(portrait_data.astype(float) - mean_per_pixel))
    r, g, b = portrait_data[:,:,0].astype(float), portrait_data[:,:,1].astype(float), portrait_data[:,:,2].astype(float)
    pixel_sat = np.maximum(np.maximum(np.abs(r-g), np.abs(g-b)), np.abs(r-b))
    colored_ratio = np.mean(pixel_sat > 10)
    if saturation < 5 and colored_ratio < 0.1:
        gray = np.mean(portrait_data, axis=2)
        gray_std = np.std(gray)
        if gray_std < 30:
            return None
    not_white = np.any(portrait_data < 220, axis=2)
    if np.mean(not_white) < 0.15:
        return None
    return Image.fromarray(portrait_data)


# =========================================================
# Work Thumbnail Extraction (from v6)
# =========================================================

def extract_work_thumbnails(page, col_side, scale=SCALE):
    """Extract work thumbnails using pixel analysis (v6 logic)."""
    if col_side == 'left':
        x0, x1 = LEFT_COL_X
    else:
        x0, x1 = RIGHT_COL_X

    x0_m = max(x0 - 3, 0)
    x1_m = min(x1 + 3, 362)

    clip = fitz.Rect(x0_m, WORK_Y_START, x1_m, WORK_Y_END)
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
    data = pixmap_to_numpy(pix)

    min_block = int(4 * scale)
    scores = compute_row_block_scores(data, white_thresh=228, min_block=min_block)

    regions = find_image_regions(
        scores,
        min_score=0.12,
        min_height=int(8 * scale),
        gap_tolerance=int(4 * scale)
    )

    thumbnails = []
    for start_row, end_row in regions:
        img_data = data[start_row:end_row, :]
        if is_text_region(img_data, scale):
            continue
        trim_top, trim_bottom = trim_text_from_edges(img_data, scale, white_thresh=228)
        img_data = img_data[trim_top:trim_bottom, :]
        if img_data.shape[0] < int(6 * scale):
            continue
        bbox = find_photo_bbox(img_data, white_thresh=225, min_size=int(6 * scale))
        if bbox is None:
            continue
        ry0, ry1, rx0, rx1 = bbox
        trimmed = img_data[ry0:ry1, rx0:rx1]
        if trimmed.shape[0] < 15 or trimmed.shape[1] < 20:
            continue
        aspect = trimmed.shape[1] / max(trimmed.shape[0], 1)
        if aspect > 15 or aspect < 0.05:
            continue

        pdf_y_start = WORK_Y_START + (start_row + trim_top + ry0) / scale
        pdf_y_end = WORK_Y_START + (start_row + trim_top + ry1) / scale

        thumbnails.append({
            'image': Image.fromarray(trimmed),
            'y_start': pdf_y_start,
            'y_end': pdf_y_end,
        })

    return thumbnails


# =========================================================
# v7: OCR-based Text Extraction
# =========================================================

def find_text_rows_in_column(col_img, scale):
    """Find rows in the column image that contain text (not images).
    Text rows have low but non-zero content coverage.
    Image rows have high content coverage (>35%).
    """
    not_white = np.any(col_img < 228, axis=2)
    row_coverage = not_white.mean(axis=1)

    # Classify each row
    # Image: >35% coverage, Text: 1-35%, Empty: <1%
    text_mask = (row_coverage > 0.005) & (row_coverage < 0.35)
    image_mask = row_coverage >= 0.35

    return text_mask, image_mask, row_coverage


def ocr_text_regions(page, col_side, thumb_regions_pdf, scale=OCR_SCALE):
    """v7: Extract text from gaps between thumbnails using Tesseract OCR.

    Strategy:
    1. Render column at high resolution
    2. Use pixel analysis to find text rows vs image rows
    3. Group contiguous text rows into text regions
    4. OCR each text region
    5. Filter out profile text, keep work info
    """
    if col_side == 'left':
        x0, x1 = LEFT_COL_X
    else:
        x0, x1 = RIGHT_COL_X

    # Render entire column work zone at OCR_SCALE
    clip = fitz.Rect(x0, WORK_Y_START, x1, WORK_Y_END)
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
    col_img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)

    # Find text rows using pixel analysis
    text_mask, image_mask, row_coverage = find_text_rows_in_column(col_img, scale)

    # Group contiguous text rows into regions
    text_regions = []
    in_text = False
    start = 0
    for y in range(len(text_mask)):
        if text_mask[y] and not in_text:
            start = y
            in_text = True
        elif not text_mask[y] and in_text:
            if y - start > int(8 * scale):  # Min height for text
                text_regions.append((start, y))
            in_text = False
    if in_text and len(text_mask) - start > int(8 * scale):
        text_regions.append((start, len(text_mask)))

    # Merge nearby text regions (within 15px gap)
    merged_regions = []
    for reg in text_regions:
        if merged_regions and reg[0] - merged_regions[-1][1] < int(3 * scale):
            merged_regions[-1] = (merged_regions[-1][0], reg[1])
        else:
            merged_regions.append(reg)

    # OCR each text region
    text_blocks = []
    for reg_start, reg_end in merged_regions:
        # Add small margin
        y0 = max(0, reg_start - 3)
        y1 = min(col_img.shape[0], reg_end + 3)

        region = col_img[y0:y1, :]
        if region.shape[0] < 10:
            continue

        # Check for actual content
        not_white = np.any(region < 220, axis=2)
        if np.mean(not_white) < 0.005:
            continue

        region_img = Image.fromarray(region)
        try:
            text = pytesseract.image_to_string(
                region_img, lang='jpn+eng',
                config='--psm 6 --oem 3'
            ).strip()
        except Exception:
            continue

        if not text or len(text) < 2:
            continue

        # Clean and filter garbage
        cleaned = clean_ocr_text(text)
        if len(cleaned) < 2:
            continue

        # Skip single-character garbage lines
        lines = [l for l in cleaned.split('\n') if len(l.strip()) > 1]
        if not lines:
            continue
        cleaned = '\n'.join(lines)

        # Calculate PDF Y-coordinate
        pdf_y_center = WORK_Y_START + (y0 + y1) / 2 / scale

        text_blocks.append({
            'text': cleaned,
            'y_center': pdf_y_center,
            'y_start': WORK_Y_START + y0 / scale,
            'y_end': WORK_Y_START + y1 / scale,
        })

    return text_blocks


def is_profile_text(text):
    """v7: Detect if text is a profile/biography sentence rather than work info."""
    text = text.strip()
    if not text:
        return False

    # Work-like indicators (if found, definitely NOT profile)
    work_indicators = [
        r'(19|20)\d{2}\s*$',             # Ends with year
        r'(19|20)\d{2}\s*ー?\s*$',       # Ends with year + ー
        r'[+＋].*[+＋]',                  # Agency+Production pattern
        r'\bCM\b',                         # CM keyword
        r'\bTVCM\b',
        r'\bMV\b',
        r'\bPV\b',
        r'\bWeb\b',
        r'電通|博報堂|ADK|東急エージェンシー',  # Known agencies
        r'TYO|AOI|東北新社|太陽企画|ギークピクチュアズ',  # Known productions
    ]
    for pat in work_indicators:
        if re.search(pat, text):
            return False

    # Sentences ending with period → profile text
    if text.endswith('。') or re.search(r'。\s*$', text):
        return True

    # Common profile patterns
    profile_patterns = [
        r'より独立', r'として活動', r'にて.*学ぶ', r'を経て',
        r'年生まれ', r'出身', r'卒業', r'入社', r'設立',
        r'所属', r'在籍', r'手がけ', r'携わ',
        r'受賞歴', r'グランプリ', r'ファイナリスト',
        r'ショートフィルム', r'ドキュメンタリー',
        r'TVCF.*手掛', r'映画.*監督',
    ]
    for pat in profile_patterns:
        if re.search(pat, text):
            return True

    # Long text without any structure AND without work indicators → likely profile
    if len(text) > 80 and '「' not in text and '（' not in text and '(' not in text:
        # Double check: if it has year or agency patterns, it's a work
        if not re.search(r'(19|20)\d{2}', text):
            return True

    return False


def collapse_japanese_spaces(text):
    """Remove spaces between Japanese characters that Tesseract incorrectly adds."""
    result = []
    chars = list(text)
    i = 0
    while i < len(chars):
        if chars[i] == ' ' and i > 0 and i < len(chars) - 1:
            prev_is_jp = is_cjk(chars[i-1]) or chars[i-1] in 'ー・、。」』）!?'
            next_is_jp = is_cjk(chars[i+1]) or chars[i+1] in 'ー・「『（'
            # Also check katakana/hiragana
            prev_cp = ord(chars[i-1])
            next_cp = ord(chars[i+1])
            prev_is_kana = (0x3040 <= prev_cp <= 0x30FF) or (0xFF65 <= prev_cp <= 0xFF9F)
            next_is_kana = (0x3040 <= next_cp <= 0x30FF) or (0xFF65 <= next_cp <= 0xFF9F)

            if (prev_is_jp or prev_is_kana) and (next_is_jp or next_is_kana):
                # Skip space between Japanese characters
                i += 1
                continue
        result.append(chars[i])
        i += 1
    return ''.join(result)


def clean_ocr_text(text):
    """v7: Clean OCR output for better parsing.
    IMPORTANT: Preserves newlines as they separate title from agency lines.
    """
    # Process each line separately to preserve structure
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        line = collapse_japanese_spaces(line)
        # Normalize full-width characters
        line = line.replace('＋', '+').replace('＝', '=').replace('：', ':')
        # Fix common OCR substitutions
        line = line.replace('_', ' ')
        # Remove garbage characters but keep useful ones
        line = re.sub(r'[\\|]', '', line)
        # Collapse multiple spaces (but not newlines)
        line = re.sub(r'[ \t]+', ' ', line).strip()
        if line:
            cleaned_lines.append(line)

    return '\n'.join(cleaned_lines)


def parse_ocr_work_text(raw_text, source_year):
    """v7: Parse OCR text block into structured work data.

    PDF work text format (typical):
      Line 1: ClientName ProductName「Title」
      Line 2: Agency+Production Year

    Strategy:
      1. First check if text has a year → if yes, it's a work (not profile)
      2. Separate agency/year line from title/client lines
      3. Extract bracket titles「」from any line
      4. Parse remaining text into client/product
    """
    lines = raw_text.strip().split('\n')
    lines = [l.strip() for l in lines if l.strip()]

    if not lines:
        return None

    # Clean each line
    cleaned_lines = []
    for line in lines:
        line = clean_ocr_text(line)
        if len(line) < 2:
            continue
        if re.match(r'^\d{2,3}$', line):  # page numbers
            continue
        # Remove P= producer credits (can appear mid-line or at start)
        line = re.sub(r'\s*P\s*[=＝]\s*[三二一]?\s*\S+(\s+\S+)?$', '', line).strip()
        if len(line) < 2:
            continue
        # Replace "十" (OCR artifact for "+") between non-number contexts
        line = re.sub(r'(?<=[ぁ-ん゛゜ゝゞァ-ヶヽヾ一-龥a-zA-Z])\s*十\s*(?=[ぁ-ん゛゜ゝゞァ-ヶヽヾ一-龥a-zA-Z])', '+', line)
        cleaned_lines.append(line)

    if not cleaned_lines:
        return None

    # Check if there's a year in any line → indicates this is a work block
    has_year = any(re.search(r'(19|20)\d{2}', line) for line in cleaned_lines)

    # Only filter as profile if NO year pattern found
    if not has_year:
        full_text_check = ' '.join(cleaned_lines)
        if is_profile_text(full_text_check):
            return None

    # Find year and agency/production team
    year = None
    agency = ""
    year_line_idx = -1

    for i, line in enumerate(cleaned_lines):
        # Pattern: "...Year" at end of line (after P= removal)
        m = re.search(r'((?:19|20)\d{2})\s*[ー\-]*\s*$', line)
        if m:
            year = int(m.group(1))
            before_year = line[:m.start()].strip()
            before_year = re.sub(r'[。、\s]+$', '', before_year)

            # Extract any bracket text from the year line (it's actually a title)
            bracket_in_agency = re.search(r'[「『](.+?)[」』]', before_year)
            if bracket_in_agency:
                # Move bracket text to a separate "title from agency line"
                agency = before_year[:bracket_in_agency.start()].strip()
                # We'll handle this bracket text below
            else:
                agency = before_year

            year_line_idx = i
            break

    # Collect all non-year lines as title/client content
    title_lines = []
    for i, line in enumerate(cleaned_lines):
        if i == year_line_idx:
            # But if year line has bracket text, include just that part
            bracket_in_line = re.search(r'[「『].+?[」』]', line)
            if bracket_in_line:
                title_lines.append(bracket_in_line.group(0))
            continue
        if re.match(r'^P\s*[=＝]', line):
            continue
        title_lines.append(line)

    if not title_lines:
        if agency:
            title_lines = [agency]
            agency = ""
        else:
            return None

    full_text = ' '.join(title_lines)

    # Remove trailing period/punctuation (OCR garbage)
    full_text = re.sub(r'\s*[。、]+\s*$', '', full_text)
    full_text = full_text.strip()

    client_name = ""
    product_name = ""
    title = ""

    # Look for bracket patterns: 「title」
    bracket_match = re.search(r'[「『](.+?)[」』]', full_text)
    if not bracket_match:
        bracket_match = re.search(r'[（\(](.+?)[）\)]', full_text)

    if bracket_match:
        title = bracket_match.group(0)
        before_bracket = full_text[:bracket_match.start()].strip()
        after_bracket = full_text[bracket_match.end():].strip()

        if before_bracket:
            parts = smart_split_client_product(before_bracket)
            client_name = parts[0]
            product_name = parts[1] if len(parts) > 1 else ""

        if after_bracket:
            if re.match(r'^(篇|編|Web|MV|PV|TVCM|CM|Movie|Ver|シリーズ)', after_bracket):
                title = title + after_bracket
            else:
                title = title + ' ' + after_bracket
    else:
        # No brackets - use smart splitting
        parts = smart_split_client_product(full_text)
        if len(parts) >= 2:
            client_name = parts[0]
            title = parts[1]
        else:
            title = full_text

    client_name = client_name.strip()
    product_name = product_name.strip()
    title = title.strip()
    agency = agency.strip()

    # Clean up: OCR reads "十" instead of "+"
    agency = re.sub(r'\s*十\s*', '+', agency)
    # Remove leading/trailing + from agency
    agency = agency.strip('+').strip()

    if not client_name and not title:
        return None

    # Fallback year
    if not year:
        sy = source_year.split('-')[0] if '-' in source_year else source_year
        try:
            year = int(sy)
        except:
            year = 0

    return {
        "clientName": client_name or None,
        "productName": product_name or None,
        "title": title or client_name,
        "agency": agency or None,
        "year": year,
        "sourceYear": source_year,
    }


def smart_split_client_product(text):
    """Split text like 'ClientName ProductName' into parts.
    Handles Japanese company names that may contain spaces from OCR.
    """
    text = text.strip()
    if not text:
        return [""]

    # If text has CJK characters, try to find the boundary where
    # client name ends and product/title begins
    # Common patterns:
    #   "日本コカ・コーラ チームコカ・コーラ あなた色の未来を"
    #   → client="日本コカ・コーラ", rest="チームコカ・コーラ あなた色の未来を"

    # Strategy: Split on space, but try to keep CJK compound words together
    parts = text.split()
    if len(parts) <= 1:
        return [text]

    # If first part looks like a company name (ends with common suffixes), split there
    company_suffixes = ['コーラ', 'ビール', 'ハウス', 'フーズ', 'グループ',
                        'ジャパン', 'マーケット', 'Market', 'Inc', 'inc',
                        'Corp', 'Co', 'Ltd']
    for i in range(1, len(parts)):
        prefix = ' '.join(parts[:i])
        for suffix in company_suffixes:
            if prefix.endswith(suffix):
                return [prefix, ' '.join(parts[i:])]

    # Default: first word is client, rest is product/title
    return [parts[0], ' '.join(parts[1:])]


def match_thumbnails_to_text(thumbnails, text_blocks, source_year):
    """v7: Match thumbnails to text blocks by Y-coordinate proximity.

    Each thumbnail should be paired with the text that appears
    immediately BELOW it (text description follows the image in the PDF).
    """
    if not thumbnails:
        return []

    works = []

    for ti, thumb in enumerate(thumbnails):
        thumb_y_end = thumb['y_end']  # Bottom of thumbnail

        # Find the text block closest to (and below) this thumbnail
        best_text = None
        best_distance = float('inf')

        for tb in text_blocks:
            # Text should be BELOW the thumbnail (or overlapping slightly)
            distance = tb['y_start'] - thumb_y_end
            if distance >= -10 and distance < best_distance:  # Allow small overlap
                best_distance = distance
                best_text = tb

        # Also check text ABOVE thumbnail (some layouts have text above)
        if best_text is None or best_distance > 50:
            for tb in text_blocks:
                distance = thumb['y_start'] - tb['y_end']
                if 0 <= distance < best_distance:
                    best_distance = distance
                    best_text = tb

        work_data = None
        if best_text and best_distance < 80:  # Max 80 PDF units distance
            work_data = parse_ocr_work_text(best_text['text'], source_year)
            # Mark text block as used
            best_text['_used'] = True

        if work_data:
            work_data['_thumb_idx'] = ti
        else:
            # No matching text found - create placeholder
            work_data = {
                "clientName": None,
                "productName": None,
                "title": f"作品{ti+1}",
                "agency": None,
                "year": 0,
                "sourceYear": source_year,
                "_thumb_idx": ti,
            }

        works.append(work_data)

    # Also process any unused text blocks (works without thumbnails)
    for tb in text_blocks:
        if tb.get('_used'):
            continue
        work_data = parse_ocr_work_text(tb['text'], source_year)
        if work_data:
            work_data['_thumb_idx'] = None
            works.append(work_data)

    return works


# =========================================================
# v7: Director Name via OCR
# =========================================================

def extract_director_name_ocr(page, col_side, scale=OCR_SCALE):
    """v7: Extract director name from the top of the column using OCR.
    Director names are typically in large font at the top of the column.
    """
    if col_side == 'left':
        x0, x1 = LEFT_COL_X
    else:
        x0, x1 = RIGHT_COL_X

    # Name is typically in the top portion (y=0-40 PDF coords)
    clip = fitz.Rect(x0, 0, x1, 45)
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
    data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)

    # Check if there's content
    not_white = np.any(data < 220, axis=2)
    if np.mean(not_white) < 0.01:
        return None

    img = Image.fromarray(data)
    try:
        text = pytesseract.image_to_string(img, lang='jpn+eng', config='--psm 7 --oem 3').strip()
    except:
        return None

    # Clean up
    text = re.sub(r'\s+', '', text)  # Remove spaces
    if len(text) < 2 or len(text) > 20:
        return None

    # Check for CJK characters
    cjk_count = sum(1 for c in text if is_cjk(c))
    if cjk_count < 2:
        return None

    return text


def is_cjk(ch):
    cp = ord(ch)
    return ((0x4E00 <= cp <= 0x9FFF) or (0x3400 <= cp <= 0x4DBF) or
            (0x3040 <= cp <= 0x309F) or (0x30A0 <= cp <= 0x30FF) or
            (0xFF65 <= cp <= 0xFF9F))


# =========================================================
# v7: Fallback to PyMuPDF for director name (it's ok for large text)
# =========================================================

def get_director_name_fitz(page, col_side):
    """Use PyMuPDF for director name - large fonts are usually decoded OK."""
    mid = page.rect.width / 2
    d = page.get_text('dict')
    for block in d['blocks']:
        if block['type'] != 0:
            continue
        for line in block['lines']:
            spans = line['spans']
            if not spans:
                continue
            lx0 = line['bbox'][0]
            ly0 = line['bbox'][1]
            max_fs = max(s['size'] for s in spans)
            text = ''.join(s['text'] for s in spans).strip()

            # Check column
            if col_side == 'left' and lx0 >= mid:
                continue
            if col_side == 'right' and lx0 < mid:
                continue

            # Large text near top with CJK characters
            if max_fs >= 9.5 and 2 <= len(text) <= 15 and ly0 < 60:
                cjk = sum(1 for c in text if is_cjk(c))
                if cjk >= 2:
                    return text

    return None


# =========================================================
# Main Processing
# =========================================================

def process_page(page, page_num, year, output_base, stats):
    results = {'left': None, 'right': None}

    for col_side in ['left', 'right']:
        # Get director name - try PyMuPDF first (works for large fonts), fallback to OCR
        name = get_director_name_fitz(page, col_side)
        if not name:
            name = extract_director_name_ocr(page, col_side)
        if not name:
            continue

        # Extract portrait (v6 logic)
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

        # Extract thumbnails (v6 logic)
        work_thumbnails = extract_work_thumbnails(page, col_side, scale=SCALE)
        thumb_paths = []
        for ti, thumb in enumerate(work_thumbnails):
            thumb_dir = os.path.join(output_base, "thumbnails_v7", year)
            os.makedirs(thumb_dir, exist_ok=True)
            fname = f"p{page_num}_{col_side}_{ti+1}.jpg"
            fpath = os.path.join(thumb_dir, fname)
            thumb['image'].save(fpath, "JPEG", quality=THUMB_QUALITY)
            thumb_paths.append({
                'path': f"/thumbnails_v7/{year}/{fname}",
                'y_start': thumb['y_start'],
                'y_end': thumb['y_end'],
            })
            stats['thumbnails'] += 1

        # v7: OCR text extraction from gaps between thumbnails
        text_blocks = ocr_text_regions(page, col_side, thumb_paths, scale=OCR_SCALE)

        # v7: Match thumbnails to text by Y-coordinate proximity
        works = match_thumbnails_to_text(
            [{'y_start': t['y_start'], 'y_end': t['y_end']} for t in thumb_paths],
            text_blocks,
            year
        )

        results[col_side] = {
            'name': name,
            'page': page_num,
            'portrait_path': portrait_path,
            'thumbnails': thumb_paths,
            'works': works,
        }

    return results


def process_pdf(year, source_dir, output_base, stats):
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

    all_results = {}

    for pi in range(start, end):
        page = doc[pi]
        page_num = pi + 1
        results = process_page(page, page_num, year, output_base, stats)
        all_results[page_num] = results

        if (pi - start) % 20 == 0:
            print(f"  Page {page_num}/{end} ... (portraits: {stats['portraits']}, thumbnails: {stats['thumbnails']})")

    doc.close()
    return all_results


def update_database(all_data, db_path):
    """v7: Update DB - replaces all work text data and thumbnails."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    directors = cur.execute("""
        SELECT d.id, d.name, dys.sourceYear, dys.sourcePage
        FROM Director d
        JOIN DirectorYearSource dys ON dys.directorId = d.id
        ORDER BY dys.sourceYear, dys.sourcePage, d.id
    """).fetchall()

    page_groups = {}
    for d in directors:
        key = f"{d['sourceYear']}|{d['sourcePage']}"
        if key not in page_groups:
            page_groups[key] = []
        page_groups[key].append(dict(d))

    portrait_updated = 0
    thumb_updated = 0
    text_updated = 0
    works_created = 0
    works_deleted = 0

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

                # v7: Delete ALL existing works for this director+year, then recreate
                old_works = cur.execute(
                    'SELECT COUNT(*) FROM Work WHERE directorId = ? AND sourceYear = ?',
                    (dir_id, year)
                ).fetchone()[0]

                # Clear youtubeUrl but keep the work records for now
                # Actually, let's delete and recreate to ensure clean data
                cur.execute('DELETE FROM Work WHERE directorId = ? AND sourceYear = ?',
                            (dir_id, year))
                works_deleted += old_works

                # Create new works from v7 extraction
                v7_works = col_data['works']
                v7_thumbs = col_data['thumbnails']

                for wi, work in enumerate(v7_works):
                    thumb_idx = work.get('_thumb_idx')
                    thumb_path = None
                    if thumb_idx is not None and thumb_idx < len(v7_thumbs):
                        thumb_path = v7_thumbs[thumb_idx]['path']
                        thumb_updated += 1

                    cur.execute('''INSERT INTO Work (directorId, title, clientName, productName,
                                   agency, year, sourceYear, thumbnailPath, youtubeUrl)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)''',
                                (dir_id,
                                 work['title'],
                                 work.get('clientName'),
                                 work.get('productName'),
                                 work.get('agency'),
                                 work.get('year', 0),
                                 year,
                                 thumb_path))
                    works_created += 1
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

    print(f"\n--- v7 DB Update Results ---")
    print(f"  Portraits updated: {portrait_updated}")
    print(f"  Thumbnails attached: {thumb_updated}")
    print(f"  Works deleted (old): {works_deleted}")
    print(f"  Works created (new): {works_created}")
    print(f"  Text data updated: {text_updated}")
    print(f"\n--- DB Stats ---")
    print(f"  Directors: {total_dirs} (with portrait: {with_portrait})")
    print(f"  Works: {total_works} (with thumb: {with_thumb}, with YouTube: {with_yt})")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="v7 OCR-based Re-extraction")
    parser.add_argument("--year", help="Specific year")
    parser.add_argument("--all", action="store_true", help="Process all years")
    parser.add_argument("--dry-run", action="store_true", help="Extract images only, don't update DB")
    parser.add_argument("--page", type=int, help="Process a specific page only")
    args = parser.parse_args()

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = os.path.dirname(base)  # PDF directory
    output_base = os.path.join(base, "public")

    years = ["2023-2024", "2021-2022", "2020-2021"] if args.all else [args.year or "2023-2024"]

    stats = {'portraits': 0, 'thumbnails': 0}
    all_data = {}

    for y in years:
        if args.page:
            # Process single page for testing
            pdf_name = PDF_MAP.get(y)
            pdf_path = os.path.join(src, pdf_name)
            doc = fitz.open(pdf_path)
            page = doc[args.page - 1]
            result = process_page(page, args.page, y, output_base, stats)
            all_data[y] = {args.page: result}

            # Print detailed results for debugging
            for side in ['left', 'right']:
                col = result.get(side)
                if col:
                    print(f"\n--- {side.upper()} column ---")
                    print(f"  Director: {col['name']}")
                    print(f"  Portrait: {col['portrait_path']}")
                    print(f"  Thumbnails: {len(col['thumbnails'])}")
                    for wi, w in enumerate(col['works']):
                        t_idx = w.get('_thumb_idx', '?')
                        print(f"  Work {wi}: [{w.get('clientName', '')}] [{w.get('productName', '')}] [{w['title']}] (thumb:{t_idx})")
                        if w.get('agency'):
                            print(f"         Agency: {w['agency']}, Year: {w.get('year')}")
            doc.close()
        else:
            all_data[y] = process_pdf(y, src, output_base, stats)

    print(f"\n{'='*60}")
    print(f"v7 Extraction Complete")
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
