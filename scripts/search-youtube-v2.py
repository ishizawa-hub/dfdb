#!/usr/bin/env python3
"""
v2 YouTube動画URL検索 - 高速 + 厳格マッチング
- yt-dlp による高速検索
- スコアベースの検証で誤マッチ防止
- 危険なフォールバック完全排除
- 最適化されたクエリ戦略（1-2クエリ/作品）

Usage: python scripts/search-youtube-v2.py [--limit N] [--offset N] [--dry-run] [--reset]
"""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'prisma', 'dev.db')

YTDLP_PATH = os.path.join(
    os.path.expanduser('~'),
    'AppData', 'Local', 'Packages',
    'PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0',
    'LocalCache', 'local-packages', 'Python313', 'Scripts', 'yt-dlp.exe'
)
if not os.path.exists(YTDLP_PATH):
    YTDLP_PATH = 'yt-dlp'


def clean_for_search(text):
    """Clean text for YouTube search query."""
    if not text:
        return ''
    text = re.sub(r'[「」『』（）\(\)\[\]]', ' ', text)
    text = re.sub(r'[©®™＇\'"=\-_~#@$%&*^|\\/:;!?.,<>{}]+', ' ', text)
    text = re.sub(r'\b[a-zA-Z]\b', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def build_query(work, director_name):
    """Build single best search query for a work."""
    client = clean_for_search(work['clientName'] or '')
    title = clean_for_search(work['title'] or '')
    product = clean_for_search(work['productName'] or '')

    # Extract bracket content
    bracket = ''
    if work['title']:
        m = re.search(r'[「『](.+?)[」』]', work['title'])
        if m:
            bracket = m.group(1)

    # Build the best query
    parts = []
    if client and len(client) > 2:
        parts.append(client)
    if bracket:
        parts.append(bracket)
    elif product and len(product) > 2:
        parts.append(product)
    elif title and title != client and len(title) > 2:
        parts.append(title)

    if parts:
        parts.append('CM')

    query = ' '.join(parts)
    if len(query) < 5:
        return None
    if len(query) > 80:
        query = query[:80]
    return query


def search_youtube(query, max_results=3):
    """Search YouTube using yt-dlp subprocess."""
    try:
        cmd = [
            YTDLP_PATH,
            f'ytsearch{max_results}:{query}',
            '--dump-json', '--flat-playlist',
            '--no-download', '--quiet', '--no-warnings',
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=15, encoding='utf-8',
        )
        if result.returncode != 0:
            return []
        videos = []
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            try:
                data = json.loads(line)
                videos.append({
                    'id': data.get('id', ''),
                    'title': data.get('title', ''),
                    'channel': data.get('channel', '') or data.get('uploader', ''),
                    'duration': data.get('duration', 0),
                })
            except json.JSONDecodeError:
                continue
        return videos
    except (subprocess.TimeoutExpired, Exception):
        return []


def extract_words(text):
    """Extract meaningful words from text for matching."""
    if not text:
        return set()
    jp = set(re.findall(r'[\u3040-\u9fff]{2,}', text.lower()))
    en = set(w.lower() for w in re.findall(r'[a-zA-Z]{3,}', text))
    return jp | en


def validate_match(video, work):
    """Score-based validation. Returns score.
    Requires multiple matching signals to avoid false positives.
    """
    vt = video['title'].lower()

    client = work['clientName'] or ''
    product = work['productName'] or ''
    title = work['title'] or ''

    bracket = ''
    if title:
        m = re.search(r'[「『](.+?)[」』]', title)
        if m:
            bracket = m.group(1)

    client_matched = False
    bracket_matched = False
    product_matched = False
    title_matched = False
    cm_matched = False

    # Client name match
    for w in extract_words(client):
        if len(w) >= 2 and w in vt:
            client_matched = True
            break

    # Bracket title match
    if bracket:
        for w in extract_words(bracket):
            if len(w) >= 2 and w in vt:
                bracket_matched = True
                break

    # Product match
    for w in extract_words(product):
        if len(w) >= 2 and w in vt:
            product_matched = True
            break

    # Title words match (1+ meaningful word)
    title_words = extract_words(title)
    matching_title_words = sum(1 for w in title_words if len(w) >= 2 and w in vt)
    if matching_title_words >= 1:
        title_matched = True

    # CM keyword
    if any(p in vt for p in ['cm', 'tvcm', 'コマーシャル']):
        cm_matched = True

    # Calculate score
    score = 0
    if client_matched:
        score += 3
    if bracket_matched:
        score += 3
    if product_matched:
        score += 2
    if title_matched:
        score += (2 if matching_title_words >= 2 else 1)
    if cm_matched:
        score += 1

    # Too long = not a CM (-2)
    dur = video.get('duration', 0)
    if dur and dur > 300:
        score -= 2

    # Key rule: client-only match is not enough
    # Must have at least one other signal (title, bracket, product, or CM)
    content_matched = bracket_matched or product_matched or title_matched
    if client_matched and not content_matched and not cm_matched:
        score = min(score, 2)  # Cap at 2 (below threshold)

    return score


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--batch', type=int, default=100)
    parser.add_argument('--reset', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if args.reset:
        print("Resetting all YouTube URLs...")
        cur.execute("UPDATE Work SET youtubeUrl = NULL")
        conn.commit()

    cur.execute("""
        SELECT w.id, w.title, w.clientName, w.productName, w.agency,
               w.sourceYear, d.name as directorName
        FROM Work w
        JOIN Director d ON w.directorId = d.id
        WHERE (w.youtubeUrl IS NULL OR w.youtubeUrl = '')
        ORDER BY w.id
    """)
    works = [dict(row) for row in cur.fetchall()]

    if args.offset:
        works = works[args.offset:]
    if args.limit:
        works = works[:args.limit]

    print(f"Processing {len(works)} works...")
    found = 0
    skipped = 0
    no_match = 0
    cache_hits = 0

    THRESHOLD = 3
    search_cache = {}  # query -> results

    for i, work in enumerate(works):
        # Skip placeholders and garbage
        if work['title'] and re.match(r'^作品\d+$', work['title']):
            skipped += 1
            continue

        all_text = (work['clientName'] or '') + (work['title'] or '')
        jp_chars = len(re.findall(r'[\u3040-\u9fff]', all_text))
        en_chars = len(re.findall(r'[a-zA-Z]', all_text))
        if jp_chars + en_chars < 4:
            skipped += 1
            continue

        query = build_query(work, work['directorName'])
        if not query:
            skipped += 1
            continue

        if args.dry_run:
            print(f"[{i+1}] {work['clientName']} / {work['title']} → {query}")
            continue

        # Use cache if available
        if query in search_cache:
            results = search_cache[query]
            cache_hits += 1
        else:
            results = search_youtube(query)
            search_cache[query] = results
            time.sleep(0.3)  # Rate limiting

        best_url = None
        best_score = 0
        for video in results:
            score = validate_match(video, work)
            if score >= THRESHOLD and score > best_score:
                best_score = score
                best_url = f"https://www.youtube.com/watch?v={video['id']}"

        if best_url:
            cur.execute('UPDATE Work SET youtubeUrl = ? WHERE id = ?', (best_url, work['id']))
            found += 1
            if args.verbose:
                print(f"  ✓ [{work['id']}] score={best_score} | {work['clientName']} / {work['title']}")
        else:
            no_match += 1

        if (i + 1) % 50 == 0:
            print(f"[{i+1}/{len(works)}] Found: {found}, No match: {no_match}, Skipped: {skipped}, Cache: {cache_hits}")

        if (i + 1) % args.batch == 0:
            conn.commit()

    conn.commit()

    total_yt = cur.execute("SELECT COUNT(*) FROM Work WHERE youtubeUrl IS NOT NULL AND youtubeUrl != ''").fetchone()[0]
    total = cur.execute("SELECT COUNT(*) FROM Work").fetchone()[0]

    print(f"\n{'='*50}")
    print(f"Processed: {len(works)}")
    print(f"Found: {found}, No match: {no_match}, Skipped: {skipped}")
    print(f"Total with YouTube: {total_yt}/{total} ({total_yt/total*100:.1f}%)")

    conn.close()


if __name__ == '__main__':
    main()
