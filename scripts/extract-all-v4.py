#!/usr/bin/env python3
"""
PDFから全監督データを高精度で抽出 (v4)
- LINE単位の座標ベース抽出で左右カラムを正確に分離
- フォントサイズで名前を識別
- Y座標クラスタリングで作品を漏れなく検出（年号がない作品も検出）
- URL, メール, 電話, 所属, Webサイトを正確にパース

Usage: python scripts/extract-all-v4.py --all
"""
import argparse
import csv
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

import fitz

PDF_MAP = {
    "2023-2024": "CM・映像ディレクターズファイル2023-2024.pdf",
    "2021-2022": "CM・映像ディレクターズファイル2021-2022.pdf",
    "2020-2021": "CM・映像ディレクターズファイル2020-2021.pdf",
}

START_PAGE = {"2023-2024": 18, "2021-2022": 17, "2020-2021": 17}
END_PAGE = {"2023-2024": 367, "2021-2022": 375, "2020-2021": 355}

SIDEBAR_X = 340
WORK_ZONE_Y = 230  # Works start below this y
CLUSTER_GAP = 50   # Y-gap > this = new work cluster


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


def fix_ocr(text):
    return hw2fw_katakana(text).replace('十', '+').replace('＋', '+').replace('＝', '=').replace('：', ':')


def get_page_lines(page):
    """ページから全行を座標・フォントサイズ付きで抽出"""
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
    """左右カラムに分離"""
    mid = page_width / 2
    left, right = [], []
    for l in lines:
        # Filter garbage
        if l['fs'] > 15 and len(l['text']) <= 3:
            continue  # Large font garbage
        if l['fs'] < 1.5:
            continue  # Tiny font garbage
        if l['x0'] > SIDEBAR_X and len(l['text']) <= 3:
            continue  # Sidebar navigation
        if re.match(r'^0?\d{2,3}\s*[\'"]?\s*$', l['text']):
            continue  # Page numbers
        if len(l['text']) <= 1:
            continue  # Single char garbage

        if l['cx'] < mid:
            left.append(l)
        else:
            right.append(l)
    left.sort(key=lambda l: l['y0'])
    right.sort(key=lambda l: l['y0'])
    return left, right


def find_name(col):
    """監督名（日本語）をフォントサイズで検出"""
    for i, l in enumerate(col):
        if l['fs'] >= 9.5 and len(l['text']) >= 2 and len(l['text']) <= 15:
            cjk = sum(1 for c in l['text'] if is_cjk(c))
            if cjk >= 2:
                return i, l['text'].strip()
    return -1, ""


def find_romaji(col, after_idx):
    """ローマ字名を検出"""
    for i in range(after_idx + 1, min(after_idx + 5, len(col))):
        text = col[i]['text'].strip()
        text = re.sub(r'^[|｜\[\]]+\s*', '', text)
        if len(text) < 3 or len(text) > 40:
            continue
        alpha = sum(1 for c in text if c.isalpha() and ord(c) < 128)
        total = len(text.replace(' ', ''))
        if total == 0 or alpha / total < 0.6:
            continue
        split = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
        parts = split.split()
        if len(parts) >= 2:
            upper = sum(1 for p in parts if p and p[0].isupper())
            if upper >= 2:
                lower = text.lower()
                if not any(kw in lower for kw in [
                    'inc.', 'ltd.', 'management', 'studio', 'project', 'expand',
                    'epoch', 'field', 'guild', 'stink', 'robot', 'drawing',
                    'manual', 'p.i.c.s', 'tyo', 'aoi', 'track', 'films',
                    'pictures', 'village', 'connection', 'soursox', 'wash',
                    'creative', 'production', 'entertainment', 'pictures',
                ]):
                    return i, text
    return -1, ""


def fix_romaji_name(text):
    s = re.sub(r'^[|｜\[\]]+\s*', '', text.strip())
    if s and s[0] == 'l' and len(s) > 1 and s[1].islower():
        s = 'I' + s[1:]
    if s and s[0] == '1' and len(s) > 1 and s[1].islower():
        s = 'I' + s[1:]
    s = s.replace(',,', 'ji').replace(';', 'i')
    if s.endswith('1') and len(s) > 2 and s[-2].isalpha():
        s = s[:-1] + 'i'
    return re.sub(r'([a-z])([A-Z])', r'\1 \2', s)


def merge_same_y(lines, y_threshold=3):
    """同じy座標の行をマージ"""
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


def extract_contact(merged_lines):
    """連絡先情報を抽出"""
    phones, emails, urls, company = [], [], [], ""

    company_kws = [
        'Inc.', 'inc.', 'Ltd.', 'P.I.C.S', 'ROBOT', 'TYO', 'DRAWING',
        'MANUAL', 'KOO-KI', 'GUILD', 'EPOCH', 'CYAN', 'GLASSLOFT',
        'SPEC', 'CINQ', 'VSQ', 'CONNECTION', 'WASH', '太陽企画',
        '博報堂プロダクツ', '電通クリエーティブ', 'ロボット', '東北新社',
        'ギークピクチュアズ', 'ダダビ', 'ピラミッドフィルム', 'ONDO',
        'FIELD', 'FMX', 'cobne', 'isai', 'BIS', 'ENDOJI', 'I.TOON',
        '星野事務所', '館岡事務所', '伊達事務所', 'C3Film', 'STINK',
        '事務所', 'MANAGEMENT', 'キラメキ', '親子社', 'ナガイホシ',
        'ナイスレインボー', 'コトプロダクション', 'AOI Pro', 'PICS',
        'TRACK', 'SOURSOX', 'Village', 'パラゴン', 'トリガー', 'エンジン',
    ]

    for ml in merged_lines:
        s = fix_ocr(ml['text'])

        # Phones
        ns = norm_spaced(s)
        for m in re.finditer(r'(0\d{1,4}[\-\s]?\d{1,4}[\-\s]?\d{3,4})', ns):
            ph = re.sub(r'\s+', '', m.group(1))
            if 10 <= len(ph.replace('-','')) <= 11 and ph not in phones:
                phones.append(ph)

        # Emails
        cl = re.sub(r'\(?\s*Mg\s*\)?\s*', '', s)
        for m in re.finditer(r'([\w.\-+]+@[\w.\-]+\.[a-zA-Z]{2,})', cl):
            em = m.group(1).replace(',lp','.jp').replace('･lp','.jp')
            em = em.replace('.ne.Jp','.ne.jp').replace('.co.Jp','.co.jp')
            if em not in emails:
                emails.append(em)

        # URLs
        for m in re.finditer(r'(https?://[\w.\-/~?=&%#+:]+)', s):
            u = m.group(1).rstrip('.')
            if u not in urls:
                urls.append(u)
        for m in re.finditer(r'(?<![/@\w])(www\.[\w.\-/~?=&%#+:]+)', s):
            u = 'https://' + m.group(1).rstrip('.')
            if u not in urls:
                urls.append(u)
        # Reconstruct fragmented URLs (e.g., "vi" + "meo.com/showcase/a" + "ri" + "ken")
        # Look for domain patterns
        for m in re.finditer(r'(?<![/@\w])((?:vimeo|youtube|instagram)\.com[\w.\-/~]*)', s):
            u = 'https://' + m.group(1).rstrip('.')
            if u not in urls:
                urls.append(u)

        # Company (first match)
        if not company:
            # Skip non-company lines
            if re.search(r'(〒|@|FAX|https?://|www\.|年生まれ|卒業|入社|得意|受賞)', s):
                continue
            for kw in company_kws:
                if kw.lower() in s.lower():
                    c = re.sub(r'\(\s*Mg\s*[:：]?\s*[^)]*\)', '', s).strip()
                    c = re.sub(r'（\s*Mg\s*[:：]?\s*[^）]*）', '', c).strip()
                    c = re.sub(r'\(\s*担当\s*[:：]\s*[^)]*\)', '', c).strip()
                    c = re.sub(r'（\s*担当\s*[:：]\s*[^）]*）', '', c).strip()
                    c = re.sub(r'\s*\d{4}\s*$', '', c).strip()
                    c = re.sub(r'\s*P\s*[=＝]\s*.*$', '', c).strip()
                    c = c.replace('十', '+').replace('＋', '+')
                    if 2 <= len(c) <= 40:
                        company = c
                    break

    return phones, emails, urls, company


def extract_profile(merged_lines):
    """プロフィール文を抽出"""
    parts = []
    triggers = ['年生まれ','出身','卒業','入社','所属','独立','設立',
                'Award','受賞','ACC','Cannes','アワード','グランプリ',
                '大学','活動','フリー','ディレクター','スタート','演出',
                '得意','頑張','よろしく','学校','専門','生まれ']
    skip = [r'^〒', r'^FAX', r'^https?://', r'^www\.', r'@[\w.]', r'^\d{2,4}-\d{2,4}']
    collecting = False
    for ml in merged_lines:
        s = ml['text'].strip()
        if not s or len(s) < 3:
            continue
        if any(re.search(p, s) for p in skip):
            continue
        if any(kw in s for kw in triggers):
            collecting = True
        if collecting:
            if re.search(r'[+＋].+(?:19|20)\d{2}\s*$', s):
                break
            parts.append(s)
    return '\n'.join(parts)


def cluster_work_lines(work_lines):
    """Y座標でクラスタリング → 各クラスタ = 1作品"""
    if not work_lines:
        return []
    clusters = []
    current = [work_lines[0]]
    for wl in work_lines[1:]:
        if wl['y'] - current[-1]['y'] > CLUSTER_GAP:
            clusters.append(current)
            current = [wl]
        else:
            current.append(wl)
    clusters.append(current)
    return clusters


def is_garbage_text(text):
    """ゴミテキストを判定"""
    s = text.strip()
    if len(s) <= 2:
        return True
    # Common OCR garbage patterns
    if re.match(r'^[Ii1l_\-\.\'\"\`\^]+$', s):
        return True
    if re.match(r'^[` つJ\'\"\^ー]+$', s):
        return True
    # Page number fragments
    if re.match(r'^0?\d{2,3}[\'\"e]?$', s):
        return True
    return False


def parse_work_cluster(cluster, source_year):
    """1つの作品クラスタからタイトル・クライアント・制作・年を抽出"""
    # Filter garbage lines first
    raw_lines = [fix_ocr(cl['text']) for cl in cluster]
    lines = [l for l in raw_lines if not is_garbage_text(l)]
    if not lines:
        return None

    # Find year (search all lines)
    year = None
    agency = ""
    year_line_idx = -1
    agency_line_idx = -1

    for i, line in enumerate(lines):
        # Pattern: "agency+production year" or "agency year"
        m = re.search(r'((?:19|20)\d{2})\s*$', line)
        if m:
            year = int(m.group(1))
            before_year = line[:m.start()].strip()
            if before_year:
                agency = before_year
            year_line_idx = i
            break

    # If year found on standalone line, look for agency on adjacent lines
    if year and not agency:
        # Check line AFTER year
        if year_line_idx + 1 < len(lines):
            next_line = lines[year_line_idx + 1]
            if '+' in next_line or re.search(r'[A-Za-zぁ-ん].*[+]', next_line):
                agency = next_line
                agency_line_idx = year_line_idx + 1
        # Check line BEFORE year
        if not agency and year_line_idx > 0:
            prev_line = lines[year_line_idx - 1]
            if '+' in prev_line or re.search(r'[A-Za-z]', prev_line):
                agency = prev_line
                agency_line_idx = year_line_idx - 1

    # Collect title/client lines (everything except year and agency lines)
    skip_indices = set()
    if year_line_idx >= 0:
        skip_indices.add(year_line_idx)
    if agency_line_idx >= 0:
        skip_indices.add(agency_line_idx)

    title_lines = []
    for i, line in enumerate(lines):
        if i in skip_indices:
            continue
        if re.match(r'^P\s*[=]', line):
            continue
        if line.strip():
            title_lines.append(line.strip())

    # Parse: first line = client (company name), remaining = title/product
    client = ""
    title = ""
    if len(title_lines) >= 2:
        client = title_lines[0]
        title = ' '.join(title_lines[1:])
    elif len(title_lines) == 1:
        title = title_lines[0]

    if not title and not client:
        return None

    return {
        "title": title or client,
        "clientName": client if title else None,
        "productName": None,
        "agency": agency or None,
        "year": year or 0,
        "sourceYear": source_year,
    }


def parse_column(col, page_num, source_year):
    """カラムから監督データを抽出"""
    if len(col) < 3:
        return None

    # 1. Find name
    name_idx, name = find_name(col)
    if name_idx < 0:
        return None

    # 2. Find romaji
    romaji_idx, romaji_raw = find_romaji(col, name_idx)
    romaji = fix_romaji_name(romaji_raw) if romaji_raw else ""

    # 3. Split into info zone and work zone
    info_start = (romaji_idx + 1) if romaji_idx > 0 else (name_idx + 1)

    info_lines_raw = [l for l in col[info_start:] if l['y0'] < WORK_ZONE_Y]
    work_lines_raw = [l for l in col[info_start:] if l['y0'] >= WORK_ZONE_Y]

    # Merge same-y lines for info zone
    info_merged = merge_same_y(info_lines_raw)

    # 4. Contact info
    phones, emails, urls, company = extract_contact(info_merged)

    # 5. Profile
    profile = extract_profile(info_merged)

    # 6. Works: merge same-y lines, then cluster
    work_merged = merge_same_y(work_lines_raw)
    clusters = cluster_work_lines(work_merged)

    works = []
    for cluster in clusters:
        w = parse_work_cluster(cluster, source_year)
        if w:
            works.append(w)

    email = emails[0] if emails else ""
    website = ""
    for u in urls:
        if '@' not in u:
            website = u
            break

    return {
        "name": name,
        "nameRomaji": romaji,
        "phone": phones[0] if phones else "",
        "email": email,
        "company": company,
        "profile": profile,
        "website": website,
        "works": works,
        "sourcePage": page_num,
        "sourceYear": source_year,
    }


def process_pdf(year, source_dir, output_dir):
    pdf_name = PDF_MAP.get(year)
    if not pdf_name:
        return []
    pdf_path = os.path.join(source_dir, pdf_name)
    if not os.path.exists(pdf_path):
        print(f"PDF not found: {pdf_path}")
        return []

    print(f"\n{'='*60}")
    print(f"Processing: {pdf_name}")
    print(f"{'='*60}")

    doc = fitz.open(pdf_path)
    start = START_PAGE.get(year, 0)
    end = min(END_PAGE.get(year, doc.page_count), doc.page_count)
    all_dirs = []

    for pi in range(start, end):
        page = doc[pi]
        lines = get_page_lines(page)
        left, right = split_columns(lines, page.rect.width)

        for col in [left, right]:
            if col:
                d = parse_column(col, pi + 1, year)
                if d:
                    all_dirs.append(d)

        if (pi - start) % 50 == 0:
            print(f"  Page {pi+1}/{end} ... ({len(all_dirs)} directors)")

    doc.close()

    # Stats
    ww = sum(1 for d in all_dirs if d['works'])
    tw = sum(len(d['works']) for d in all_dirs)
    print(f"\n--- {year} ---")
    print(f"  Directors: {len(all_dirs)}")
    print(f"  With works: {ww} ({tw} total)")
    print(f"  With email: {sum(1 for d in all_dirs if d['email'])}")
    print(f"  With phone: {sum(1 for d in all_dirs if d['phone'])}")
    print(f"  With company: {sum(1 for d in all_dirs if d['company'])}")
    print(f"  With website: {sum(1 for d in all_dirs if d['website'])}")
    print(f"  With profile: {sum(1 for d in all_dirs if d['profile'])}")

    return all_dirs


def save_all(data, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    total_d, total_w = 0, 0

    for year, dirs in data.items():
        # JSON
        jp = os.path.join(output_dir, f"v4_{year}.json")
        with open(jp, "w", encoding="utf-8") as f:
            json.dump({"source_year": year, "total_directors": len(dirs), "directors": dirs},
                      f, ensure_ascii=False, indent=2)
        print(f"Saved: {jp}")

        # CSV
        cp = os.path.join(output_dir, f"v4_{year}.csv")
        with open(cp, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ID","名前","ローマ字","電話","メール","所属","Webサイト",
                        "プロフィール","作品数","作品一覧","ページ"])
            for i, d in enumerate(dirs, 1):
                ws = " / ".join([f"{wk['title']}({wk.get('clientName','')},{wk.get('agency','')},{wk['year']})"
                                 for wk in d['works']])
                w.writerow([i, d['name'], d['nameRomaji'], d['phone'], d['email'],
                            d['company'], d['website'], d['profile'][:300].replace('\n',' '),
                            len(d['works']), ws, d['sourcePage']])
        print(f"Saved: {cp}")

        tw = sum(len(d['works']) for d in dirs)
        total_d += len(dirs)
        total_w += tw

    print(f"\n{'='*60}")
    print(f"TOTAL: {total_d} directors, {total_w} works")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", help="Specific year")
    parser.add_argument("--all", action="store_true", help="All years")
    args = parser.parse_args()

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = os.path.dirname(base)
    out = os.path.join(base, "data", "v4")

    years = ["2023-2024", "2021-2022", "2020-2021"] if args.all else [args.year or "2023-2024"]

    data = {}
    for y in years:
        data[y] = process_pdf(y, src, out)

    save_all(data, out)
