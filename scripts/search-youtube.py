#!/usr/bin/env python3
"""
YouTube動画URLを自動検索してDBに登録するスクリプト。
各作品のタイトル・クライアント名・監督名からYouTube検索し、
最も関連性の高い動画URLを取得する。

Usage: python scripts/search-youtube.py [--limit N] [--offset N] [--dry-run]
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')

from youtubesearchpython import VideosSearch

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'prisma', 'dev.db')


def clean_title(text):
    """OCRゴミや不要部分を除去して検索用テキストを作る"""
    if not text:
        return ''
    # Remove year patterns like "2020", "2023"
    text = re.sub(r'\b(19|20)\d{2}\b', '', text)
    # Remove agency patterns like "電通+太陽企画"
    text = re.sub(r'[\w\u3000-\u9fff]+\+[\w\u3000-\u9fff]+', '', text)
    # Remove "DIRECTOR'S FILE" etc
    text = re.sub(r"DIRECTOR['']?S?\s*\d{4}[-/]\d{4}\s*/?\s*FILE", '', text, flags=re.IGNORECASE)
    # Remove OCR garbage: sequences of punctuation/special chars
    text = re.sub(r'[©®™＇\'"=\-_~#@$%&*^|\\/:;!?.,<>(){}\[\]]+', ' ', text)
    # Remove single chars that are likely OCR errors
    text = re.sub(r'\b[a-zA-Z]\b', '', text)
    # Remove P= producer credits
    text = re.sub(r'P\s*[=＝]\s*\S+', '', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def build_search_query(work, director_name):
    """作品情報から最適なYouTube検索クエリを構築"""
    title = work['title'] or ''
    client = work['clientName'] or ''
    product = work['productName'] or ''
    agency = work['agency'] or ''

    # Detect if title is actually an agency+year line (messy data)
    has_agency_in_title = bool(re.search(r'(電通|博報堂|ADK|読売|東急|大広)\+', title))
    has_year_prefix = bool(re.match(r'^\s*(19|20)\d{2}\s', title))

    if has_agency_in_title or has_year_prefix:
        # Title is garbage - use clientName as main search term
        main_text = clean_title(client)
        sub_text = clean_title(product)
    else:
        # Title looks clean
        main_text = clean_title(title)
        sub_text = clean_title(client) if client else clean_title(product)

    # Build query parts
    parts = []
    if main_text and len(main_text) > 2:
        parts.append(main_text)
    if sub_text and len(sub_text) > 2 and sub_text != main_text:
        parts.append(sub_text)

    # Add CM keyword for commercial works
    if parts:
        parts.append('CM')

    query = ' '.join(parts)

    # If query is too short or empty, try a broader search with director name
    if len(query) < 5:
        query = f"{director_name} CM"

    # Truncate very long queries (YouTube search works better with shorter queries)
    if len(query) > 100:
        query = query[:100]

    return query


def is_likely_match(video_title, work_title, client_name, director_name):
    """検索結果が本当にその作品か簡易判定"""
    vt = video_title.lower()
    # Check if any significant word from work/client matches
    check_texts = [work_title, client_name]
    for text in check_texts:
        if not text:
            continue
        # Extract Japanese/meaningful words (3+ chars)
        words = re.findall(r'[\u3040-\u9fff]{2,}', text)
        for word in words:
            if word.lower() in vt:
                return True
        # Also check romaji/brand names
        words_en = re.findall(r'[a-zA-Z]{3,}', text)
        for word in words_en:
            if word.lower() in vt:
                return True
    return False


def search_youtube(query, max_retries=3):
    """YouTube検索を実行（リトライ付き）"""
    for attempt in range(max_retries):
        try:
            search = VideosSearch(query, limit=3)
            result = search.result()
            return result.get('result', [])
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"  Search error: {e}")
                return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=0, help='Max works to process (0=all)')
    parser.add_argument('--offset', type=int, default=0, help='Skip first N works')
    parser.add_argument('--dry-run', action='store_true', help='Show queries without searching')
    parser.add_argument('--batch', type=int, default=50, help='Save every N works')
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Get all works without YouTube URLs
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
    errors = 0

    for i, work in enumerate(works):
        query = build_search_query(work, work['directorName'])

        if args.dry_run:
            print(f"[{i+1}/{len(works)}] ID={work['id']}: {query}")
            continue

        if len(query.strip()) < 5:
            skipped += 1
            continue

        results = search_youtube(query)

        youtube_url = None
        for video in results:
            # Basic relevance check
            if is_likely_match(video.get('title', ''), work['title'], work['clientName'], work['directorName']):
                youtube_url = f"https://www.youtube.com/watch?v={video['id']}"
                break

        # If no strict match, take first result if query was specific enough
        if not youtube_url and results and len(query) > 10:
            # Take first result as best guess
            youtube_url = f"https://www.youtube.com/watch?v={results[0]['id']}"

        if youtube_url:
            cur.execute('UPDATE Work SET youtubeUrl = ? WHERE id = ?', (youtube_url, work['id']))
            found += 1

        # Progress
        if (i + 1) % 10 == 0:
            print(f"[{i+1}/{len(works)}] Found: {found}, Skipped: {skipped}, Errors: {errors}")

        # Batch save
        if (i + 1) % args.batch == 0:
            conn.commit()
            print(f"  Saved batch at {i+1}")

        # Rate limiting - be gentle
        time.sleep(0.5)

    conn.commit()

    # Final stats
    total_with_yt = cur.execute("SELECT COUNT(*) FROM Work WHERE youtubeUrl IS NOT NULL AND youtubeUrl != ''").fetchone()[0]
    total_works = cur.execute("SELECT COUNT(*) FROM Work").fetchone()[0]

    print(f"\n=== Results ===")
    print(f"Processed: {len(works)}")
    print(f"Found YouTube URLs: {found}")
    print(f"Skipped (bad query): {skipped}")
    print(f"Total works with YouTube: {total_with_yt}/{total_works} ({total_with_yt/total_works*100:.1f}%)")

    conn.close()


if __name__ == '__main__':
    main()
