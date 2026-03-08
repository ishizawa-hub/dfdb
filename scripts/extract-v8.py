#!/usr/bin/env python3
"""
extract-v8.py - Directors File DB: 完全再構築スクリプト
=====================================================
PDFテキストレイヤー + 画像抽出のハイブリッドアプローチ

v7の失敗分析:
- cp932エンコーディングでテキストが文字化けに見え、不要なOCRに切替
- 実際にはPDFテキストレイヤーは高品質な日本語テキストを含む
- OCRに切り替えたことで精度が大幅に低下

v8のアプローチ:
- テキストデータ: PDFテキストレイヤーから直接取得（高品質）
- 画像データ: 埋め込みJPEGから切り出し（ポートレート・サムネイル）
- ページ分類: テキストレイヤーの位置情報で1/2監督を正確判定
- 厳格なページ/カラム境界: データの混在を完全に防止
"""

import fitz  # PyMuPDF
import os
import sys
import json
import re
import argparse
import time
from pathlib import Path
from PIL import Image
import numpy as np
import io

sys.stdout.reconfigure(encoding="utf-8")

# ============================================================
# 設定
# ============================================================
BASE_DIR = Path(__file__).resolve().parent.parent
PDF_DIR = BASE_DIR.parent
OUTPUT_DIR = BASE_DIR / "extracted_data"
PORTRAIT_DIR = BASE_DIR / "public" / "portraits_v8"
THUMBNAIL_DIR = BASE_DIR / "public" / "thumbnails_v8"

PDF_CONFIGS = {
    "2023-2024": {
        "filename": "CM・映像ディレクターズファイル2023-2024.pdf",
        "start_page": 9,
        "end_page": 367,
    },
    "2021-2022": {
        "filename": "CM・映像ディレクターズファイル2021-2022.pdf",
        "start_page": 13,
        "end_page": 375,
    },
    "2020-2021": {
        "filename": "CM・映像ディレクターズファイル2020-2021.pdf",
        "start_page": 10,
        "end_page": 355,
    },
}

# テキストレイヤーの位置パラメータ
NAME_Y_MAX = 45.0         # 監督名のY上限 (PDF pt)
NAME_SIZE_MIN = 10.5      # 監督名フォント下限
NAME_SIZE_MAX = 16.0      # 監督名フォント上限
CONTACT_Y_MAX = 135.0     # 連絡先エリアの下限
PROFILE_Y_MAX = 200.0     # プロフィールエリアの下限
WORKS_Y_MIN = 200.0       # 作品エリアの上限

# 画像抽出パラメータ (ガイドラインに基づく)
# ①ポートレート: カラム右側上部（名前・連絡先の右隣）
PORTRAIT_X_RATIO = (0.48, 0.98)  # カラム幅の右48-98%
PORTRAIT_Y_RATIO = (0.01, 0.28)  # カラム高さの上1-28%

# 作品領域パラメータ (②③④)
WORKS_AREA_START_RATIO = 0.33    # 作品エリア開始 (カラム高さの33%)
WORK_TEXT_HEIGHT_PT = 28         # 作品テキスト推定高さ (PDF pt, 約3行)

# 最小サイズ閾値
MIN_PORTRAIT_DIM = 40            # ポートレート最小寸法 (px)
MIN_THUMB_HEIGHT = 60            # サムネイル最小高さ (px)
MIN_THUMB_WIDTH = 80             # サムネイル最小幅 (px)


def ensure_dirs():
    for d in [OUTPUT_DIR, PORTRAIT_DIR, THUMBNAIL_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    for year in PDF_CONFIGS:
        (PORTRAIT_DIR / year).mkdir(exist_ok=True)
        (THUMBNAIL_DIR / year).mkdir(exist_ok=True)


def log(msg, level="INFO"):
    print(f"[{level}] {msg}", flush=True)


# ============================================================
# テキストレイヤー処理
# ============================================================

def get_all_spans(page):
    """
    ページの全テキストスパンを位置情報付きで取得する。

    Returns:
        list of dict: [{x, y, x1, y1, size, text, font}, ...]
    """
    text_dict = page.get_text("dict")
    spans = []

    for block in text_dict["blocks"]:
        if "lines" not in block:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                text = span["text"]
                if not text.strip():
                    continue
                x0, y0 = span["origin"]
                bbox = span.get("bbox", line["bbox"])
                spans.append({
                    "x": x0,
                    "y": y0,
                    "x1": bbox[2] if len(bbox) >= 4 else x0 + len(text) * span["size"] * 0.5,
                    "y1": bbox[3] if len(bbox) >= 4 else y0 + span["size"],
                    "size": span["size"],
                    "text": text,
                    "font": span.get("font", ""),
                })

    return spans


def split_spans_by_column(spans, page_width):
    """
    スパンを左右カラムに分割する。

    ウォーターマーク（ページ端の縦書きテキスト）を除外する。
    ページ番号・装飾テキスト等のノイズを除外する。
    """
    mid_x = page_width / 2
    left_margin = 10       # 左端マージン
    right_edge = page_width - 15  # 右端（ウォーターマーク除外）

    left_spans = []
    right_spans = []

    for s in spans:
        # ページ番号除外: Y > 498 の小テキスト（底部のページ番号）
        if s["y"] > 498:
            continue

        # 装飾テキスト除外: 異常に大きなフォント
        if s["size"] > 30:
            continue

        # ウォーターマーク除外: ページ端の小さなテキスト
        if s["x"] < left_margin and s["size"] < 6:
            continue
        if s["x"] > right_edge:
            continue

        # カラム分割
        if s["x"] < mid_x - 5:
            left_spans.append(s)
        elif s["x"] > mid_x + 5:
            right_spans.append(s)
        # mid_x ± 5 のスパンは無視（カラム境界上）

    return left_spans, right_spans


def reconstruct_lines(spans, y_tolerance=3.0):
    """
    Y座標が近いスパンを行として結合する。

    Returns:
        list of dict: [{y, text, spans}, ...] sorted by y
    """
    if not spans:
        return []

    # Y座標でグループ化
    sorted_spans = sorted(spans, key=lambda s: (s["y"], s["x"]))
    lines = []
    current_line = {"y": sorted_spans[0]["y"], "spans": [sorted_spans[0]]}

    for s in sorted_spans[1:]:
        if abs(s["y"] - current_line["y"]) <= y_tolerance:
            current_line["spans"].append(s)
        else:
            lines.append(current_line)
            current_line = {"y": s["y"], "spans": [s]}
    lines.append(current_line)

    # 各行のスパンをX座標順にソートし、テキストを結合
    for line in lines:
        line["spans"].sort(key=lambda s: s["x"])
        line["text"] = "".join(s["text"] for s in line["spans"]).strip()
        line["max_size"] = max(s["size"] for s in line["spans"])
        line["x_start"] = line["spans"][0]["x"]

    return sorted(lines, key=lambda l: l["y"])


def classify_page(page):
    """ページの監督数を判定"""
    spans = get_all_spans(page)
    page_w = page.rect.width
    mid_x = page_w / 2

    # 監督名候補を検出
    has_left = False
    has_right = False

    for s in spans:
        if s["size"] >= 9.0 and s["y"] < NAME_Y_MAX and s["size"] <= 30:
            if s["x"] < mid_x - 15:
                has_left = True
            elif s["x"] > mid_x + 10:
                has_right = True

    if has_left and has_right:
        return "2-dir"
    elif has_left:
        return "1-dir-left"
    elif has_right:
        return "1-dir-right"
    else:
        return "no-dir"


# ============================================================
# 監督情報の抽出
# ============================================================

def extract_cjk_chars(text):
    """テキストからCJK文字（漢字・ひらがな・カタカナ）のみ抽出"""
    return re.sub(r'[^\u3000-\u9fff\u30a0-\u30ff\u3040-\u309f\uff00-\uffef]', '', text)


def extract_director_from_spans(col_spans):
    """
    カラムのスパンから監督情報を構造化する。

    名前抽出はスパン単位で行い、フォントサイズで
    漢字名(大)とローマ字名(小)を正確に分離する。

    Returns:
        dict: {name, nameRomaji, phone, company, email, website, profile, works_raw}
    """
    if not col_spans:
        return None

    result = {
        "name": "",
        "nameRomaji": "",
        "phone": "",
        "phoneMg": "",  # マネージャー電話
        "company": "",
        "email": "",
        "website": "",
        "profile": "",
        "works_raw": [],
    }

    # === STEP 1: 名前エリア (Y < 50) のスパンを分類 ===
    name_area_spans = []    # Y < 50 の全スパン

    for s in col_spans:
        if s["y"] >= 50:
            continue
        name_area_spans.append(s)

    # --- 漢字名の抽出 ---
    # 全スパン（サイズ問わず）からCJK文字を収集
    # ※ P13右のように漢字が複数サイズに分散しているケースに対応
    name_area_spans.sort(key=lambda s: s["x"])
    all_cjk = ""
    for s in name_area_spans:
        if s["size"] >= 7.0:  # 極小フォントは除外
            cjk = extract_cjk_chars(s["text"])
            if cjk:
                all_cjk += cjk

    if len(all_cjk) >= 2:
        result["name"] = all_cjk
    elif name_area_spans:
        # CJK文字が少ない場合（"A.T."のようなケース）
        # 大フォントスパンのテキストを使う
        large_spans = [s for s in name_area_spans if s["size"] >= 9.0]
        if large_spans:
            raw_name = "".join(s["text"] for s in large_spans)
            clean_name = re.sub(r'[^\w\s.\-]', '', raw_name).strip()
            if clean_name and len(clean_name) >= 2:
                result["name"] = clean_name

    # --- ローマ字名の抽出 ---
    romaji_spans = [s for s in name_area_spans if s["size"] < 8 and s["y"] > 30]
    if romaji_spans:
        romaji_spans.sort(key=lambda s: s["x"])
        romaji = " ".join(s["text"] for s in romaji_spans).strip()
        # encoding artifacts修正
        romaji = romaji.replace(";", "i").replace(",", "i")
        romaji = re.sub(r'\s+', ' ', romaji).strip()
        if re.search(r'[A-Za-z]{3,}', romaji):
            result["nameRomaji"] = romaji

    # === STEP 2: 連絡先・プロフィール・作品をライン単位で処理 ===
    # Y >= 50 のスパンのみ
    body_spans = [s for s in col_spans if s["y"] >= 50]
    lines = reconstruct_lines(body_spans)

    for line in lines:
        y = line["y"]
        text = line["text"]
        max_size = line["max_size"]

        # --- 連絡先エリア (Y 50-135) ---
        if 50 <= y < CONTACT_Y_MAX:
            # 電話番号
            phone_match = re.search(r'(\d{2,4}[-ー]\d{2,4}[-ー]\d{3,4})', text)
            if phone_match:
                phone_num = phone_match.group(1).replace("ー", "-")
                # (Mg)パターン → マネージャー電話
                if "(Mg)" in text or "(mg)" in text or "Mg)" in text:
                    if not result["phoneMg"]:
                        result["phoneMg"] = phone_num
                elif not result["phone"]:
                    result["phone"] = phone_num

            # メールアドレス
            email_match = re.search(r'[\w.+-]+@[\w.-]+\.\w{2,}', text)
            if email_match and not result["email"]:
                result["email"] = email_match.group()

            # ウェブサイト
            url_match = re.search(r'(?:https?://|www\.)\S+', text)
            if url_match and not result["website"]:
                result["website"] = url_match.group()

            # 会社名の判定（電話・メール・URL・(Mg)行を除外）
            if not result["company"] and not phone_match and not email_match and not url_match:
                clean = text.strip()
                # 短すぎる、住所（〒）、数字のみの行はスキップ
                if len(clean) > 3 and not clean.startswith("〒") and not re.match(r'^[\d\-\s]+$', clean):
                    result["company"] = clean
            elif not result["company"] and max_size > 5:
                # 特定キーワードがある行は会社名として認識
                if any(kw in text for kw in ["事務所", "Inc", "Ltd", "株式会社", "有限会社",
                                              "プロダクション", "スタジオ", "Pro.", "制作"]):
                    # (Mg)行の場合は電話番号部分を除いたテキストを使う
                    company_text = re.sub(r'\d{2,4}[-ー]\d{2,4}[-ー]\d{3,4}', '', text)
                    company_text = re.sub(r'\(Mg\)', '', company_text).strip()
                    if company_text and len(company_text) > 2:
                        result["company"] = company_text
            continue

        # --- プロフィール (Y 130-200) ---
        if CONTACT_Y_MAX <= y < WORKS_Y_MIN and max_size < 10:
            if result["profile"]:
                result["profile"] += " " + text
            else:
                result["profile"] = text
            continue

        # --- 作品エリア (Y >= 200) ---
        if y >= WORKS_Y_MIN and max_size < 15:
            # 装飾テキスト除外（1文字の縦書き等）
            if len(text) <= 1 and max_size < 6:
                continue
            result["works_raw"].append({
                "y": y,
                "text": text,
                "size": max_size,
            })

    # 名前がない場合はNone
    if not result["name"]:
        # ローマ字名だけある場合は名前として使用
        if result["nameRomaji"]:
            result["name"] = result["nameRomaji"]
        else:
            return None

    return result


def parse_works_from_raw(works_raw, source_year):
    """
    生の作品テキスト行から構造化された作品データを生成する。

    作品テキストのパターン:
    - クライアント名 商品名「タイトル」篇
    - 制作会社＋代理店 年

    行のグルーピング: Y座標の大きなギャップ(>15pt)で作品を分割
    """
    if not works_raw:
        return []

    # Y座標のギャップで作品グループに分割
    sorted_lines = sorted(works_raw, key=lambda l: l["y"])
    groups = []
    current_group = [sorted_lines[0]]

    for line in sorted_lines[1:]:
        gap = line["y"] - current_group[-1]["y"]
        if gap > 15:  # 15pt以上のギャップ = 新しい作品
            groups.append(current_group)
            current_group = [line]
        else:
            current_group.append(line)
    groups.append(current_group)

    works = []
    for group in groups:
        texts = [l["text"] for l in group]
        full_text = " ".join(texts)

        # 短すぎるテキストはスキップ
        if len(full_text) < 3:
            continue

        # プロフィール文を除外
        if is_profile_text(full_text):
            continue

        work = parse_single_work(texts, source_year)
        if work:
            work["_y"] = group[0]["y"]
            works.append(work)

    return works


def parse_single_work(text_lines, source_year):
    """テキスト行群から1つの作品を解析"""
    if not text_lines:
        return None

    full_text = " ".join(text_lines)

    result = {
        "title": "",
        "clientName": "",
        "productName": "",
        "agency": "",
        "year": None,
        "sourceYear": source_year,
    }

    # 括弧内タイトル
    bracket_match = re.search(r'[「『【](.+?)[」』】]', full_text)
    bracket_title = bracket_match.group(1) if bracket_match else ""

    # 年の検出
    year_match = re.search(r'(20\d{2})', full_text)
    if year_match:
        result["year"] = int(year_match.group(1))

    # 最初の行がメインのタイトル行
    main_line = text_lines[0]

    # クライアント/商品の分割
    # パターン: "クライアント名商品名「タイトル」篇"
    # または: "クライアント名/商品名" (スラッシュ区切り)
    if bracket_title:
        # 括弧の前がクライアント+商品
        before_bracket = re.split(r'[「『【]', main_line)[0].strip()
        result["clientName"] = before_bracket
        result["title"] = f"{before_bracket}「{bracket_title}」"
    else:
        result["title"] = main_line
        result["clientName"] = main_line

    # ゴミタイトル除外: 2文字以下の記号・文字はノイズ
    clean_title = re.sub(r'[\s\W]', '', result["title"])
    if len(clean_title) <= 2:
        return None

    # 制作体制 (2行目以降)
    if len(text_lines) > 1:
        agency_parts = []
        for line in text_lines[1:]:
            # 年を除去
            clean = re.sub(r'20\d{2}', '', line).strip()
            if clean and len(clean) > 2:
                agency_parts.append(clean)
        result["agency"] = " ".join(agency_parts)

    return result


def is_profile_text(text):
    """プロフィール文判定"""
    indicators = [
        "年生まれ", "卒業", "独立", "入社", "受賞", "として活躍",
        "手がける", "を中心に", "をはじめ", "多数", "など幅広",
        "ディレクター", "に在籍", "年より", "年から", "フリー",
    ]
    count = sum(1 for ind in indicators if ind in text)
    if count >= 2:
        return True
    if len(text) > 80 and "。" in text:
        return True
    return False


# ============================================================
# 画像抽出 (ポートレート・サムネイル)
# ============================================================

def extract_page_image(doc, page):
    """ページの埋め込みJPEG画像を取得"""
    images = page.get_images(full=True)
    if not images:
        return None
    xref = images[0][0]
    base = doc.extract_image(xref)
    return Image.open(io.BytesIO(base["image"]))


def get_column_image(full_img, page_width, col_side):
    """フルページ画像からカラム画像を切り出す"""
    w, h = full_img.size
    mid_x = w // 2

    # カラム境界のマージン
    margin = 15

    if col_side == "left":
        return full_img.crop((0, 0, mid_x - margin, h))
    elif col_side == "right":
        return full_img.crop((mid_x + margin, 0, w, h))
    else:  # full
        return full_img


def extract_portrait(col_img, year, page_num, col_side):
    """
    ガイドライン①に基づくポートレート抽出

    ポートレートはカラム上部の右側に位置する（名前・連絡先テキストの右隣）。
    キャプチャー範囲: カラム右側約50%、上部約28%
    """
    w, h = col_img.size

    # ポートレート検索領域: 右約50%、上部約28%
    x0 = int(w * PORTRAIT_X_RATIO[0])
    y0 = int(h * PORTRAIT_Y_RATIO[0])
    x1 = int(w * PORTRAIT_X_RATIO[1])
    y1 = int(h * PORTRAIT_Y_RATIO[1])

    search_region = col_img.crop((x0, y0, x1, y1))

    # コンテンツ検出
    gray = np.array(search_region.convert("L"))
    rh, rw = gray.shape

    if rh < 20 or rw < 20:
        return None

    # 白背景でないピクセルを検出（写真・イラストは色がある）
    not_white = gray < 242

    row_content = np.mean(not_white, axis=1)
    col_content = np.mean(not_white, axis=0)

    content_rows = np.where(row_content > 0.05)[0]
    content_cols = np.where(col_content > 0.05)[0]

    if len(content_rows) < MIN_PORTRAIT_DIM or len(content_cols) < MIN_PORTRAIT_DIM:
        return None

    # タイトクロップ
    py0 = max(0, content_rows[0] - 5)
    py1 = min(rh, content_rows[-1] + 5)
    px0 = max(0, content_cols[0] - 5)
    px1 = min(rw, content_cols[-1] + 5)

    portrait = search_region.crop((px0, py0, px1, py1))
    pw, ph = portrait.size

    # サイズチェック
    if pw < MIN_PORTRAIT_DIM or ph < MIN_PORTRAIT_DIM:
        return None

    # 色バリエーションチェック（テキストのみでないことを確認）
    portrait_gray = np.array(portrait.convert("L"))
    if np.std(portrait_gray) < 20:
        return None

    # 保存
    fname = f"p{page_num}_{col_side}.jpg"
    rel_path = f"/portraits_v8/{year}/{fname}"
    abs_path = PORTRAIT_DIR / year / fname
    portrait.save(abs_path, "JPEG", quality=90)

    return rel_path


def extract_thumbnails(col_img, works, year, page_num, col_side, page_height_pt=515.0):
    """
    ガイドライン②③④に基づくサムネイル抽出

    各作品の構造: [サムネイル画像] → [テキストキャプション]
    テキストレイヤーのY座標をアンカーとして:
    - 各作品テキストの上方にあるサムネイル画像を正確に特定
    - 作品間の境界をテキスト位置から計算
    - 1作品ごとに画像を切り出して紐付け
    """
    w, h = col_img.size

    if not works:
        return []

    # PDFポイント → ピクセル変換
    scale = h / page_height_pt

    # _y（PDFポイント）をピクセルに変換して作品情報を整理
    work_infos = []
    for i, work in enumerate(works):
        if "_y" in work:
            text_y_px = int(work["_y"] * scale)
            work_infos.append({
                "index": i,
                "work": work,
                "text_y_px": text_y_px,
            })

    if not work_infos:
        # _yがない場合はギャップベースのフォールバック
        return _extract_thumbnails_gap_based(col_img, works, year, page_num, col_side)

    # テキストブロック高さ（ピクセル）
    text_h_px = int(WORK_TEXT_HEIGHT_PT * scale)

    # 作品エリア開始位置
    works_area_top = int(h * WORKS_AREA_START_RATIO)
    # 最大サムネイル高さ（カラム高さの22%）
    max_thumb_px = int(h * 0.22)

    thumbnails = []

    for idx, info in enumerate(work_infos):
        work = info["work"]
        text_y = info["text_y_px"]

        # === サムネイル領域の計算 ===
        # 上端: 前作品テキスト下端 or 作品テキストの上方
        if idx == 0:
            # 最初の作品: 作品エリア開始 or テキスト上方max_thumb_px のどちらか遅い方
            # プロフィール文を含まないよう、テキストに近い位置から開始
            thumb_top = max(works_area_top, text_y - max_thumb_px)
        else:
            prev_text_y = work_infos[idx - 1]["text_y_px"]
            thumb_top = prev_text_y + text_h_px

        # 下端: この作品のテキスト開始の少し上
        thumb_bottom = text_y - int(3 * scale)  # 3pt分のマージン

        # 高さチェック
        region_height = thumb_bottom - thumb_top
        if region_height < MIN_THUMB_HEIGHT:
            work["thumbnailPath"] = None
            continue

        # 切り出し（X方向は少しマージン）
        x_margin = int(w * 0.01)
        region = col_img.crop((
            x_margin,
            max(0, thumb_top),
            w - x_margin,
            min(h, thumb_bottom)
        ))

        # === コンテンツ検出 ===
        gray = np.array(region.convert("L"))
        rh_r, rw_r = gray.shape

        if rh_r < 20 or rw_r < 20:
            work["thumbnailPath"] = None
            continue

        not_white = gray < 242
        row_content = np.mean(not_white, axis=1)

        # === 領域が大きすぎる場合、最初の画像ブロックのみ使用 ===
        # テキスト欠落時に2作品分の画像を含む領域が来る場合の対策
        max_thumb_px = int(h * 0.22)  # カラム高さの22%が1サムネイルの上限
        if rh_r > max_thumb_px:
            # 行ごとのコンテンツ密度で最初の画像ブロックを検出
            img_rows = row_content > 0.10
            in_content = False
            content_end = rh_r
            gap = 0
            for y in range(rh_r):
                if img_rows[y]:
                    in_content = True
                    gap = 0
                    content_end = y + 1
                elif in_content:
                    gap += 1
                    if gap > 40:  # 40pxギャップ = 作品間の区切り
                        break

            # ギャップが見つかった場合はその位置で切る
            # 見つからなかった場合はmax_thumb_pxでハードキャップ
            if content_end < max_thumb_px:
                crop_h = content_end + 15
            else:
                crop_h = max_thumb_px  # ハードキャップ

            if crop_h >= MIN_THUMB_HEIGHT:
                region = region.crop((0, 0, rw_r, min(crop_h, rh_r)))
                gray = np.array(region.convert("L"))
                rh_r, rw_r = gray.shape
                not_white = gray < 242
                row_content = np.mean(not_white, axis=1)

        col_content = np.mean(not_white, axis=0)

        content_rows = np.where(row_content > 0.06)[0]
        content_cols = np.where(col_content > 0.06)[0]

        if len(content_rows) < 20 or len(content_cols) < 40:
            work["thumbnailPath"] = None
            continue

        # タイトクロップ
        ry0 = max(0, content_rows[0] - 3)
        ry1 = min(rh_r, content_rows[-1] + 3)
        rx0 = max(0, content_cols[0] - 3)
        rx1 = min(rw_r, content_cols[-1] + 3)

        thumb = region.crop((rx0, ry0, rx1, ry1))
        tw, th = thumb.size

        # === フィルタリング ===
        if th < MIN_THUMB_HEIGHT or tw < MIN_THUMB_WIDTH:
            work["thumbnailPath"] = None
            continue

        # 色バリエーションチェック
        thumb_gray = np.array(thumb.convert("L"))
        if np.std(thumb_gray) < 22:
            work["thumbnailPath"] = None
            continue

        # アスペクト比チェック（極端に横長 = テキスト行）
        if tw / max(th, 1) > 10:
            work["thumbnailPath"] = None
            continue

        # === 保存 ===
        fname = f"p{page_num}_{col_side}_{info['index']}.jpg"
        rel_path = f"/thumbnails_v8/{year}/{fname}"
        abs_path = THUMBNAIL_DIR / year / fname
        thumb.save(abs_path, "JPEG", quality=85)

        work["thumbnailPath"] = rel_path
        thumbnails.append({"path": rel_path, "idx": info["index"]})

    # _yがない作品にはNoneを設定
    for work in works:
        if "thumbnailPath" not in work:
            work["thumbnailPath"] = None

    return thumbnails


def _extract_thumbnails_gap_based(col_img, works, year, page_num, col_side):
    """
    フォールバック: テキストY座標がない場合のギャップベース抽出

    作品領域のピクセル分析で画像行を検出し、
    白い行のギャップで個別サムネイルを分離する。
    """
    w, h = col_img.size
    works_y_start = int(h * WORKS_AREA_START_RATIO)
    works_region = col_img.crop((0, works_y_start, w, h))

    gray = np.array(works_region.convert("L"))
    rh, rw = gray.shape

    # コンテンツ密度
    row_content = np.mean(gray < 200, axis=1)
    image_rows = row_content > 0.40

    # 連続する画像行をグループ化
    thumb_regions = []
    in_region = False
    start = 0
    gap_count = 0

    for y in range(rh):
        if image_rows[y]:
            if not in_region:
                start = y
                in_region = True
            gap_count = 0
        else:
            if in_region:
                gap_count += 1
                if gap_count > 10:
                    end = y - gap_count
                    if end - start >= MIN_THUMB_HEIGHT:
                        thumb_regions.append((start, end))
                    in_region = False
                    gap_count = 0

    if in_region:
        end = rh
        if end - start >= MIN_THUMB_HEIGHT:
            thumb_regions.append((start, end))

    # サムネイル切り出し
    thumbnails = []
    for t_idx, (ty0, ty1) in enumerate(thumb_regions):
        region = gray[ty0:ty1, :]
        col_content_r = np.mean(region < 200, axis=0)
        content_cols = np.where(col_content_r > 0.10)[0]

        if len(content_cols) < 50:
            continue

        tx0 = max(0, content_cols[0] - 3)
        tx1 = min(rw, content_cols[-1] + 3)

        thumb_w = tx1 - tx0
        thumb_h = ty1 - ty0

        if thumb_h < MIN_THUMB_HEIGHT or thumb_w < MIN_THUMB_WIDTH:
            continue
        if thumb_w / max(thumb_h, 1) > 8:
            continue

        region_img = works_region.crop((tx0, ty0, tx1, ty1))
        if np.std(np.array(region_img.convert("L"))) < 25:
            continue

        fname = f"p{page_num}_{col_side}_{t_idx}.jpg"
        rel_path = f"/thumbnails_v8/{year}/{fname}"
        abs_path = THUMBNAIL_DIR / year / fname
        region_img.save(abs_path, "JPEG", quality=85)

        thumbnails.append({"path": rel_path, "y": works_y_start + ty0, "idx": t_idx})

    # インデックス順で作品に紐付け
    for work in works:
        work["thumbnailPath"] = None
    for i, work in enumerate(works):
        if i < len(thumbnails):
            work["thumbnailPath"] = thumbnails[i]["path"]

    return thumbnails


# ============================================================
# メイン処理
# ============================================================

def process_page(doc, page, page_num, year):
    """1ページを処理"""
    page_type = classify_page(page)

    if page_type == "no-dir":
        return []

    spans = get_all_spans(page)
    page_w = page.rect.width
    left_spans, right_spans = split_spans_by_column(spans, page_w)

    # ページ画像取得
    full_img = extract_page_image(doc, page)

    directors = []

    columns = []
    if page_type == "2-dir":
        columns = [("left", left_spans), ("right", right_spans)]
    elif page_type == "1-dir-left":
        columns = [("left", left_spans)]
    elif page_type == "1-dir-right":
        columns = [("right", right_spans)]

    for col_side, col_spans in columns:
        # テキスト抽出
        dir_data = extract_director_from_spans(col_spans)
        if dir_data is None:
            continue

        # 作品テキスト解析
        works = parse_works_from_raw(dir_data.pop("works_raw", []), year)

        # 画像抽出（ガイドラインに基づく座標系）
        portrait_path = None
        page_h_pt = page.rect.height
        if full_img:
            col_img = get_column_image(full_img, page_w, col_side)
            portrait_path = extract_portrait(col_img, year, page_num, col_side)
            extract_thumbnails(col_img, works, year, page_num, col_side, page_h_pt)

        directors.append({
            "name": dir_data["name"],
            "nameRomaji": dir_data["nameRomaji"],
            "phone": dir_data["phone"],
            "phoneMg": dir_data.get("phoneMg", ""),
            "company": dir_data["company"],
            "email": dir_data["email"],
            "website": dir_data["website"],
            "profile": dir_data["profile"],
            "portraitPath": portrait_path,
            "works": works,
            "sourceYear": year,
            "_page": page_num,
            "_column": col_side,
        })

    return directors


def process_pdf(year, config, max_pages=None):
    """1つのPDFを処理"""
    pdf_path = PDF_DIR / config["filename"]
    if not pdf_path.exists():
        log(f"PDF not found: {pdf_path}", "ERROR")
        return []

    doc = fitz.open(str(pdf_path))
    log(f"Processing {year}: {doc.page_count} pages")

    start = config["start_page"]
    end = min(config["end_page"], doc.page_count - 1)
    if max_pages:
        end = min(end, start + max_pages - 1)

    all_directors = []
    t0 = time.time()

    for i in range(start, end + 1):
        page = doc[i]
        page_num = i + 1

        try:
            directors = process_page(doc, page, page_num, year)
            all_directors.extend(directors)

            if directors:
                names = ", ".join([d["name"][:8] for d in directors])
                log(f"  P{page_num}: {len(directors)} [{names}]")
        except Exception as e:
            log(f"  P{page_num}: ERROR - {e}", "ERROR")

        # 進捗
        done = i - start + 1
        total = end - start + 1
        if done % 50 == 0:
            elapsed = time.time() - t0
            rate = done / elapsed if elapsed > 0 else 0
            eta = (total - done) / rate if rate > 0 else 0
            log(f"  [{done}/{total}] {len(all_directors)} directors ({rate:.1f} pages/s, ETA {eta:.0f}s)")

    doc.close()

    n_works = sum(len(d["works"]) for d in all_directors)
    n_portraits = sum(1 for d in all_directors if d.get("portraitPath"))
    n_thumbs = sum(1 for d in all_directors for w in d["works"] if w.get("thumbnailPath"))

    log(f"  {year}: {len(all_directors)} directors, {n_works} works, "
        f"{n_portraits} portraits, {n_thumbs} thumbnails")

    return all_directors


def main():
    parser = argparse.ArgumentParser(description="Extract directors v8")
    parser.add_argument("--year", choices=["2023-2024", "2021-2022", "2020-2021", "all"],
                       default="all")
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--test", action="store_true", help="Process 5 pages only")
    args = parser.parse_args()

    if args.test:
        args.max_pages = 5

    ensure_dirs()

    years = list(PDF_CONFIGS.keys()) if args.year == "all" else [args.year]
    all_data = {}

    for year in years:
        directors = process_pdf(year, PDF_CONFIGS[year], args.max_pages)
        all_data[year] = directors

    # JSON出力
    output_file = OUTPUT_DIR / "directors_v8.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)

    # サマリー
    total_dirs = sum(len(dirs) for dirs in all_data.values())
    total_works = sum(len(d["works"]) for dirs in all_data.values() for d in dirs)
    log(f"\n=== TOTAL: {total_dirs} directors, {total_works} works ===")
    log(f"Output: {output_file}")


if __name__ == "__main__":
    t0 = time.time()
    main()
    log(f"Done in {time.time() - t0:.1f}s")
