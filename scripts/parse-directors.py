#!/usr/bin/env python3
"""
抽出したテキストから監督データをパースする。
Usage: python scripts/parse-directors.py --year 2023-2024 [--limit 20]
"""
import argparse
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')


def is_cjk_char(ch):
    cp = ord(ch)
    return (
        (0x4E00 <= cp <= 0x9FFF) or (0x3400 <= cp <= 0x4DBF) or
        (0x3040 <= cp <= 0x309F) or (0x30A0 <= cp <= 0x30FF) or
        (0xFF65 <= cp <= 0xFF9F)
    )


def is_japanese_person_name(text: str) -> bool:
    text = text.strip()
    if len(text) < 2 or len(text) > 12:
        return False
    if not is_cjk_char(text[0]):
        return False

    cjk_count = sum(1 for ch in text if is_cjk_char(ch))
    if cjk_count < 2:
        return False

    # Reject if contains non-name characters
    for ch in text:
        if not is_cjk_char(ch) and ch not in 'ー・／':
            return False

    # Exclude company/product/place keywords
    excludes = [
        '株式会社', '事務所', '企画', '放送', '制作', '広告', '製菓', '飲料',
        '食品', '保険', '銀行', '鉄道', 'ビル', 'マンション', '大学', '映像',
        '映画', 'ムービー', 'ドーナツ', 'チョコ', 'バー', 'カード', 'ホーム',
        'ドッグフード', 'ゲーム', 'ワーク', 'マーケ', 'ステージ', 'ブルボン',
        'リクルート', 'オリコ', 'サントリー', 'カルピス', '味の素', '明治',
        'マクドナルド', 'カンロ', 'テレビ', '日本電気', 'キューピー', '金鳥',
        'ソニー', '森永', 'バスクリン', 'ファンケル', 'モグワン', 'ネピア',
        'タマホーム', 'エアウィーヴ', 'プロダクツ', 'メニコン', '世田谷',
        '龍角散', '崎陽軒', '東洋水産', '凸版印刷', 'アリーナ', 'ツアー',
        'スポーツ', 'フォース', 'ユニリーバ', 'ジャパン', 'マカロニ',
        '自然食品', '朝日飲料', 'レゴ', 'ポプラ社',
    ]
    for ex in excludes:
        if ex in text:
            return False

    return True


def fix_romaji_ocr(text: str) -> str:
    """ローマ字名のOCRエラーを修正"""
    s = text.strip()
    # Remove leading garbage chars
    s = re.sub(r'^[|｜\[\]]+\s*', '', s)
    # Fix leading 'l' that should be 'I' (e.g., "lshii" → "Ishii", "lto" → "Ito")
    if s and s[0] == 'l' and len(s) > 1 and s[1].islower():
        s = 'I' + s[1:]
    # Fix leading '1' that should be 'I' in romaji context
    if s and s[0] == '1' and len(s) > 1 and s[1].islower():
        s = 'I' + s[1:]
    return s


def split_camelcase_romaji(text: str) -> str:
    """CamelCase のローマ字を分割: 'AritomoKenji' → 'Aritomo Kenji'"""
    # Insert space before uppercase letters that follow lowercase
    result = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    return result


def is_romaji_person_name(text: str) -> bool:
    text = fix_romaji_ocr(text)
    if len(text) < 4 or len(text) > 35:
        return False

    # Must NOT contain these
    if any(c in text for c in ['@', '+', '＋', ':', '{', '}', '=']):
        return False
    # Allow / only if not URL-like
    if '/' in text and ('http' in text.lower() or 'www' in text.lower() or '.co' in text.lower()):
        return False

    # Must NOT start with digit
    if text[0].isdigit():
        return False

    # Try splitting camelCase
    text_split = split_camelcase_romaji(text)

    # Split into words
    parts = text_split.split()
    if len(parts) < 2 or len(parts) > 5:
        return False

    # First word must start with uppercase letter
    if not parts[0][0].isupper():
        return False

    # At least 2 words should start with uppercase
    upper_starts = sum(1 for p in parts if p and p[0].isupper())
    if upper_starts < 2:
        return False

    # Majority should be ASCII alpha
    alpha_count = sum(1 for c in text_split if c.isalpha() and ord(c) < 128)
    total_non_space = len(text_split.replace(' ', ''))
    if total_non_space == 0 or alpha_count / total_non_space < 0.7:
        return False

    # Exclude URLs, technical terms
    lower = text_split.lower()
    if any(kw in lower for kw in [
        'http', 'www', '.com', '.jp', '.co', 'inc.', 'ltd.', 'fax',
        'management', 'film', 'studio', 'music', 'video', 'project',
        'this', 'the', 'champagne', 'super', 'official', 'opening',
        'lux', 'luminique', 'tanpact', 'bred', 'track',
    ]):
        return False

    return True


def normalize_spaced_text(line: str) -> str:
    """文字間スペースを詰める: 'A d a c h i' → 'Adachi', '0 7 0 - 1 2 3 4' → '070-1234'"""
    stripped = line.strip()
    if not stripped or len(stripped) < 3:
        return stripped

    chars = list(stripped)
    # Count: how many non-space chars are followed by exactly one space then another non-space?
    space_after_single = 0
    total_non_space = 0
    for i, c in enumerate(chars):
        if c != ' ':
            total_non_space += 1
            if (i + 2 < len(chars) and chars[i + 1] == ' ' and chars[i + 2] != ' '):
                space_after_single += 1

    if total_non_space > 2 and space_after_single / total_non_space > 0.5:
        collapsed = stripped.replace(' ', '')
        # Fix common OCR errors after collapsing
        collapsed = re.sub(r'(?<!\w)l(?=\d{3})', '1', collapsed)  # l983 → 1983
        return collapsed

    return stripped


def join_split_romaji(lines: list) -> list:
    """複数行に分割されたローマ字名を結合: ['A d a c h i', 'K o h t a r o'] → ['Adachi Kohtaro']"""
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Check if this looks like a partial romaji name (single word, starts with uppercase)
        normalized = normalize_spaced_text(line)
        if (i + 1 < len(lines) and
            normalized and normalized[0].isupper() and
            len(normalized.split()) == 1 and
            all(c.isalpha() or c in "'-,;" for c in normalized) and
            len(normalized) >= 2):
            next_norm = normalize_spaced_text(lines[i + 1])
            if (next_norm and next_norm[0].isupper() and
                len(next_norm.split()) == 1 and
                all(c.isalpha() or c in "'-,;" for c in next_norm) and
                len(next_norm) >= 2):
                result.append(f"{normalized} {next_norm}")
                i += 2
                continue
        result.append(line)
        i += 1
    return result


def clean_page_text(text: str) -> str:
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        # Skip sidebar nav chars
        if len(s) <= 2 and re.match(r'^[ーかさたなはまやらわ゜ゎり、\'`5．]$', s):
            continue
        # Skip vertical DIRECTOR'S FILE fragments
        if s in ['D', 'I', 'R', 'E', 'C', 'T', 'O', 'R', "'", 'S', 'F', 'L',
                 'm', 'M', '!', '。', '刀', 'U', '^', 'p']:
            continue
        # Skip standalone page numbers
        if re.match(r'^0?\d{2,3}\s*[\'"]?\s*$', s):
            continue
        # Skip OCR garbage (very short non-CJK lines)
        if len(s) <= 3 and not any(is_cjk_char(c) for c in s):
            continue
        # Normalize character-spaced text
        s = normalize_spaced_text(s)
        cleaned.append(s)

    # Join split romaji names
    cleaned = join_split_romaji(cleaned)
    return '\n'.join(cleaned)


def has_phone_nearby(lines: list, start: int, window: int = 8) -> bool:
    """指定位置の近くに電話番号があるかチェック"""
    for i in range(start, min(start + window, len(lines))):
        line = lines[i]
        # Normalize spaced text for phone detection
        normalized = normalize_spaced_text(line)
        if re.search(r'0\d{1,4}-\d{1,4}-\d{3,4}', normalized):
            return True
        # Also match phone without hyphens
        stripped = re.sub(r'[\s\-]', '', normalized)
        if re.match(r'^0\d{9,10}', stripped):
            return True
    return False


def find_director_boundaries(lines: list) -> list:
    boundaries = []
    used = set()
    for i in range(len(lines) - 1):
        if i in used:
            continue
        line = lines[i].strip()
        if not is_japanese_person_name(line):
            continue
        # Look for romaji name in next 1-3 lines (allowing OCR garbage in between)
        for gap in range(1, 4):
            if i + gap >= len(lines):
                break
            candidate = lines[i + gap].strip()
            if is_romaji_person_name(candidate):
                phone_start = i + gap + 1
                if has_phone_nearby(lines, phone_start):
                    boundaries.append(i)
                    used.add(i)
                    break
    return boundaries


def extract_email_clean(lines: list) -> str:
    for line in lines:
        s = line.strip()
        if '@' not in s:
            continue
        # Clean Mg annotations
        s_clean = re.sub(r'\(?\s*Mg\s*\)?\s*', '', s)
        match = re.search(r'([\w.\-+]+@[\w.\-]+\.[a-zA-Z]{2,})', s_clean)
        if match:
            return match.group(1)
    return ""


def extract_phones(lines: list) -> list:
    phones = []
    for line in lines:
        for m in re.finditer(r'(0\d{1,4}[-\s]?\d{1,4}[-\s]?\d{3,4})', line):
            phone = re.sub(r'\s+', '', m.group(1))
            digits = phone.replace('-', '')
            if 10 <= len(digits) <= 11:
                phones.append(phone)
    return phones


def extract_company(lines: list) -> str:
    company_kws = [
        'Inc.', 'inc.', 'Ltd.', '事務所', 'MANAGEMENT', 'management',
        'P.I.C.S', 'ROBOT', 'TYO', 'DRAWING', 'MANUAL', 'KOO-K',
        'GUILD', 'EPOCH', 'CYAN', 'GLASSLOFT', 'SPEC', 'CINQ', 'VSQ',
        'CONNECTION', 'WASH', 'カントク', '太陽演出', '太陽企画',
        '博報堂プロダクツ', '電通クリエーティブ', 'ロボット', '東北新社',
        'ナガイホシ', 'ギークピクチュアズ', 'ギークピクチュアス',
        'キラメキ', 'ダダビ', 'ピラミッド', 'コトプロダクション',
        'ナイスレインボー', 'ONDO', 'TRACK', '親子社', 'SOURSOX',
        'FIELD', 'FMX', 'TOKYO', 'cobne', 'isai', 'BIS',
        'ENDOJI', 'I.TOON', '星野事務所', '館岡事務所', '伊達事務所',
        'C3Film', 'C3FILM',
    ]
    for line in lines:
        s = line.strip()
        for kw in company_kws:
            if kw in s:
                clean = re.sub(r'\(\s*Mg\s*[：:]\s*[^)]*\)', '', s).strip()
                clean = re.sub(r'\(\s*Mg\s*\)', '', clean).strip()
                return clean if len(clean) > 1 else s
    return ""


def extract_profile(lines: list) -> str:
    profile_parts = []
    profile_triggers = [
        '年生まれ', '出身', '卒業', '入社', '所属', '独立', '設立',
        'Award', '受賞', 'ACC', 'ADFEST', 'Cannes', 'One Show',
        'アワード', 'グランプリ', '大学', 'よろしく', '頑張',
        '得意', '活動', 'フリー', 'ディレクター', 'フリーランス',
        'スタート', '挑戦', '心がけ', '演出',
    ]
    skip_patterns = [
        r'^〒', r'^FAX', r'^https?://', r'^www\.',
        r'^\d{2,4}-\d{2,4}-\d{3,4}', r'@[\w.]',
        r'^東京都', r'^大阪', r'^神奈川', r'^福岡',
    ]

    collecting = False
    for line in lines:
        s = line.strip()
        if not s or len(s) < 4:
            continue
        if any(re.search(p, s) for p in skip_patterns):
            continue
        if any(kw in s for kw in profile_triggers):
            collecting = True
        if collecting:
            # Stop at work-like entries
            if re.search(r'(＋|\+).*\d{4}\s*$', s):
                break
            if re.match(r'^(19|20)\d{2}\s*$', s):
                break
            profile_parts.append(s)
    return '\n'.join(profile_parts)


def extract_works(lines: list, source_year: str) -> list:
    works = []
    seen = set()

    for i, line in enumerate(lines):
        s = normalize_spaced_text(line.strip())

        # Pattern: "Agency＋Production Year"
        match = re.match(r'^(.+(?:＋|\+).+?)\s+((?:19|20)\d{2})\s*$', s)
        if not match:
            # Also try: "AgencyYear" at end of line
            match = re.match(r'^(.+(?:＋|\+).+?)((?:19|20)\d{2})\s*$', s)
        if match:
            agency = match.group(1).strip()
            year = int(match.group(2))

            title = ""
            client = ""
            for j in range(i - 1, max(i - 5, -1), -1):
                prev = lines[j].strip()
                if not prev or len(prev) < 2:
                    continue
                if re.search(r'(＋|\+).*\d{4}', prev):
                    break
                if re.match(r'^(〒|\d{2,4}-\d{2,4}|FAX|https?://|www\.|.*@)', prev):
                    continue
                if any(kw in prev for kw in ['年生まれ', '卒業', '入社', 'よろしく', '得意']):
                    continue
                if re.match(r'^P\s*[＝=]', prev):
                    continue
                if not title:
                    title = prev
                elif not client:
                    client = prev
                    break

            if title:
                key = f"{title}|{client}|{year}"
                if key not in seen:
                    seen.add(key)
                    works.append({
                        "title": title,
                        "clientName": client or None,
                        "productName": title if '「' in title else None,
                        "agency": agency,
                        "year": year,
                        "sourceYear": source_year,
                    })

    return works


def parse_director_entry(lines: list, page_num: int, source_year: str) -> dict:
    if len(lines) < 3:
        return None

    name = lines[0].strip()
    # Find romaji line (may not be immediately after name due to OCR garbage)
    romaji = ""
    romaji_idx = 1
    for j in range(1, min(4, len(lines))):
        candidate = fix_romaji_ocr(lines[j].strip())
        candidate = split_camelcase_romaji(candidate)
        if is_romaji_person_name(lines[j].strip()):
            romaji = candidate
            romaji_idx = j
            break
    if not romaji and len(lines) > 1:
        romaji = fix_romaji_ocr(lines[1].strip())
        romaji = split_camelcase_romaji(romaji)
    remaining = lines[romaji_idx + 1:]

    phones = extract_phones(remaining)
    email = extract_email_clean(remaining)
    company = extract_company(remaining)
    profile = extract_profile(remaining)
    works = extract_works(remaining, source_year)

    return {
        "name": name,
        "nameRomaji": romaji,
        "phone": phones[0] if phones else "",
        "email": email,
        "company": company,
        "profile": profile,
        "works": works,
        "sourcePage": page_num,
        "sourceYear": source_year,
    }


def parse_year(year: str, limit: int = 0):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    raw_path = os.path.join(base_dir, "data", "raw", f"raw_{year}.json")

    if not os.path.exists(raw_path):
        print(f"Raw data not found: {raw_path}")
        sys.exit(1)

    with open(raw_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    all_lines = []
    page_map = {}

    for page_data in raw_data["pages"]:
        page_num = page_data["page_number"]
        text = clean_page_text(page_data["text"])
        for line in text.split('\n'):
            page_map[len(all_lines)] = page_num
            all_lines.append(line)

    boundaries = find_director_boundaries(all_lines)
    print(f"Found {len(boundaries)} director entries")

    all_directors = []
    for bi, start_idx in enumerate(boundaries):
        end_idx = boundaries[bi + 1] if bi + 1 < len(boundaries) else len(all_lines)
        entry_lines = all_lines[start_idx:end_idx]
        page_num = page_map.get(start_idx, 0)

        director = parse_director_entry(entry_lines, page_num, year)
        if director:
            all_directors.append(director)

        if limit > 0 and len(all_directors) >= limit:
            break

    output_dir = os.path.join(base_dir, "data", "intermediate")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"parsed_{year}.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "source_year": year,
            "total_directors": len(all_directors),
            "directors": all_directors
        }, f, ensure_ascii=False, indent=2)

    print(f"\nParsed {len(all_directors)} directors → {output_path}")
    print("\n--- Results ---")
    for i, d in enumerate(all_directors):
        w_count = len(d['works'])
        print(f"  {i+1:2d}. {d['name']:<10s} | {d['nameRomaji'][:22]:<22s} | {d['email'][:25] if d['email'] else '-':<25s} | {d['phone']:<15s} | {d['company'][:15] if d['company'] else '-':<15s} | works:{w_count}")

    return all_directors


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    parse_year(args.year, args.limit)
