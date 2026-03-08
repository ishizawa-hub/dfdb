#!/usr/bin/env python3
"""
import-v8.py - v8抽出データをSQLiteにインポート
=================================================
directors_v8.json から Prisma スキーマに準拠した SQLite DB に直接インポート。
年度間の重複監督を統合し、FTS5インデックスを再構築する。
"""

import json
import sqlite3
import sys
import os
import re
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_FILE = BASE_DIR / "extracted_data" / "directors_v8.json"
DB_FILE = BASE_DIR / "prisma" / "dev.db"

# 年度の新しさ順（新しいほど優先）
YEAR_PRIORITY = {"2023-2024": 3, "2021-2022": 2, "2020-2021": 1}


def log(msg, level="INFO"):
    print(f"[{level}] {msg}", flush=True)


def reset_database(conn):
    """全テーブルをリセット"""
    cur = conn.cursor()

    # 既存データを削除
    tables = [
        "Work", "DirectorYearSource", "DirectorProfileHistory",
        "ImportBatch", "Director",
    ]
    for table in tables:
        try:
            cur.execute(f"DELETE FROM {table}")
        except sqlite3.OperationalError:
            pass

    # director_fts テーブルもクリア
    try:
        cur.execute("DELETE FROM director_fts")
    except sqlite3.OperationalError:
        pass

    # auto-increment カウンターをリセット
    try:
        cur.execute("DELETE FROM sqlite_sequence")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    log("Database reset complete")


def ensure_tables(conn):
    """テーブルが存在しない場合は作成"""
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS Director (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        nameRomaji TEXT,
        email TEXT,
        phone TEXT,
        company TEXT,
        website TEXT,
        profile TEXT,
        portraitImagePath TEXT,
        createdAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        updatedAt DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS Work (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        directorId INTEGER NOT NULL,
        title TEXT NOT NULL,
        clientName TEXT,
        productName TEXT,
        agency TEXT,
        year INTEGER,
        sourceYear TEXT NOT NULL,
        youtubeUrl TEXT,
        thumbnailPath TEXT,
        FOREIGN KEY (directorId) REFERENCES Director(id) ON DELETE CASCADE
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS DirectorYearSource (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        directorId INTEGER NOT NULL,
        sourceYear TEXT NOT NULL,
        sourcePage INTEGER,
        FOREIGN KEY (directorId) REFERENCES Director(id) ON DELETE CASCADE,
        UNIQUE(directorId, sourceYear)
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS DirectorProfileHistory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        directorId INTEGER NOT NULL,
        sourceYear TEXT NOT NULL,
        profile TEXT NOT NULL,
        FOREIGN KEY (directorId) REFERENCES Director(id) ON DELETE CASCADE,
        UNIQUE(directorId, sourceYear)
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ImportBatch (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sourceYear TEXT NOT NULL,
        status TEXT NOT NULL,
        inserted INTEGER DEFAULT 0,
        updated INTEGER DEFAULT 0,
        skipped INTEGER DEFAULT 0,
        reviewCount INTEGER DEFAULT 0,
        createdAt DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")

    conn.commit()


def ensure_fts(conn):
    """FTS5テーブルの作成"""
    cur = conn.cursor()
    try:
        cur.execute("DROP TABLE IF EXISTS director_fts")
    except:
        pass

    cur.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS director_fts USING fts5(
        director_id UNINDEXED,
        name,
        name_romaji,
        profile,
        work_titles,
        client_names,
        product_names,
        tokenize='unicode61'
    )""")
    conn.commit()


def normalize_name(name):
    """名前を正規化して比較用のキーを作成"""
    if not name:
        return ""
    # 全角スペースを半角に
    n = name.replace("\u3000", " ").strip()
    # 余分な空白を除去
    n = re.sub(r'\s+', '', n)
    return n


def deduplicate_directors(all_data):
    """
    年度間の重複監督を統合する。

    マッチング戦略:
    1. 名前の正規化比較（空白除去後の完全一致）
    2. 複数年度に出現する監督は1レコードに統合
    3. 連絡先等は最新年度のデータを優先
    """
    # 全監督を名前でグルーピング
    name_groups = {}  # normalized_name -> [{year, director_data}, ...]

    for year in ["2023-2024", "2021-2022", "2020-2021"]:
        if year not in all_data:
            continue
        for d in all_data[year]:
            norm = normalize_name(d.get("name", ""))
            if not norm:
                continue
            if norm not in name_groups:
                name_groups[norm] = []
            name_groups[norm].append({"year": year, "data": d})

    # 統合
    merged_directors = []
    for norm_name, appearances in name_groups.items():
        # 年度順にソート（新しいものが後 → 最新をベースに）
        appearances.sort(key=lambda a: YEAR_PRIORITY.get(a["year"], 0))

        # 最新年度のデータをベースにする
        latest = appearances[-1]["data"]

        merged = {
            "name": latest.get("name", ""),
            "nameRomaji": "",
            "email": "",
            "phone": "",
            "company": "",
            "website": "",
            "profile": "",
            "portraitImagePath": "",
            "appearances": [],  # [{year, data}]
        }

        # 各年度のデータをマージ（最新優先）
        for app in reversed(appearances):
            d = app["data"]
            year = app["year"]

            # 空でないフィールドのみ上書き（最新優先）
            if d.get("nameRomaji") and not merged["nameRomaji"]:
                merged["nameRomaji"] = d["nameRomaji"]
            if d.get("email") and not merged["email"]:
                merged["email"] = d["email"]
            if d.get("phone") and not merged["phone"]:
                merged["phone"] = d["phone"]
            if d.get("company") and not merged["company"]:
                merged["company"] = d["company"]
            if d.get("website") and not merged["website"]:
                merged["website"] = d["website"]
            if d.get("profile") and not merged["profile"]:
                merged["profile"] = d["profile"]
            if d.get("portraitPath") and not merged["portraitImagePath"]:
                merged["portraitImagePath"] = d["portraitPath"]

            merged["appearances"].append(app)

        merged_directors.append(merged)

    return merged_directors


def import_directors(conn, merged_directors):
    """統合された監督データをDBにインポート"""
    cur = conn.cursor()
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    total_directors = 0
    total_works = 0
    total_year_sources = 0

    for md in merged_directors:
        # Director挿入
        cur.execute("""
        INSERT INTO Director (name, nameRomaji, email, phone, company, website,
                              profile, portraitImagePath, createdAt, updatedAt)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            md["name"],
            md["nameRomaji"],
            md["email"],
            md["phone"],
            md["company"],
            md["website"],
            md["profile"],
            md["portraitImagePath"],
            now, now,
        ))
        director_id = cur.lastrowid
        total_directors += 1

        # 各年度のデータ
        for app in md["appearances"]:
            year = app["year"]
            d = app["data"]

            # DirectorYearSource
            try:
                cur.execute("""
                INSERT INTO DirectorYearSource (directorId, sourceYear, sourcePage)
                VALUES (?, ?, ?)
                """, (director_id, year, d.get("_page")))
                total_year_sources += 1
            except sqlite3.IntegrityError:
                pass  # 重複は無視

            # DirectorProfileHistory
            profile = d.get("profile", "")
            if profile:
                try:
                    cur.execute("""
                    INSERT INTO DirectorProfileHistory (directorId, sourceYear, profile)
                    VALUES (?, ?, ?)
                    """, (director_id, year, profile))
                except sqlite3.IntegrityError:
                    pass

            # Works
            for w in d.get("works", []):
                title = w.get("title", "")
                if not title or len(title) < 3:
                    continue

                cur.execute("""
                INSERT INTO Work (directorId, title, clientName, productName,
                                  agency, year, sourceYear, thumbnailPath)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    director_id,
                    title,
                    w.get("clientName", ""),
                    w.get("productName", ""),
                    w.get("agency", ""),
                    w.get("year"),
                    year,
                    w.get("thumbnailPath", ""),
                ))
                total_works += 1

    conn.commit()

    log(f"Imported: {total_directors} directors, {total_works} works, "
        f"{total_year_sources} year sources")

    return total_directors, total_works


def rebuild_fts(conn):
    """FTS5インデックスの再構築"""
    cur = conn.cursor()

    # FTSテーブルをクリア
    try:
        cur.execute("DELETE FROM director_fts")
    except:
        pass

    # 各監督のデータを集約してFTSに挿入
    cur.execute("""
    SELECT
        d.id,
        d.name,
        COALESCE(d.nameRomaji, '') as nameRomaji,
        COALESCE(d.profile, '') as profile,
        COALESCE(GROUP_CONCAT(DISTINCT w.title), '') as work_titles,
        COALESCE(GROUP_CONCAT(DISTINCT w.clientName), '') as client_names,
        COALESCE(GROUP_CONCAT(DISTINCT w.productName), '') as product_names
    FROM Director d
    LEFT JOIN Work w ON w.directorId = d.id
    GROUP BY d.id
    """)

    rows = cur.fetchall()
    for row in rows:
        cur.execute("""
        INSERT INTO director_fts (director_id, name, name_romaji, profile,
                                   work_titles, client_names, product_names)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, row)

    conn.commit()
    log(f"FTS5 index rebuilt: {len(rows)} entries")


def record_import_batch(conn, source_year, inserted, updated):
    """ImportBatchに記録"""
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO ImportBatch (sourceYear, status, inserted, updated, skipped, reviewCount)
    VALUES (?, 'applied', ?, ?, 0, 0)
    """, (source_year, inserted, updated))
    conn.commit()


def main():
    # データ読み込み
    log(f"Loading {INPUT_FILE}...")
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        all_data = json.load(f)

    # 統計表示
    for year in ["2023-2024", "2021-2022", "2020-2021"]:
        dirs = all_data.get(year, [])
        works = sum(len(d.get("works", [])) for d in dirs)
        log(f"  {year}: {len(dirs)} directors, {works} works")

    total_raw = sum(len(all_data.get(y, [])) for y in all_data)
    log(f"  Total (raw): {total_raw} director entries")

    # 重複統合
    log("\nDeduplicating across years...")
    merged = deduplicate_directors(all_data)
    multi_year = sum(1 for m in merged if len(m["appearances"]) > 1)
    log(f"  Unique directors: {len(merged)} (multi-year: {multi_year})")

    # DB接続・リセット
    log(f"\nConnecting to {DB_FILE}...")
    conn = sqlite3.connect(str(DB_FILE))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    ensure_tables(conn)
    reset_database(conn)
    ensure_fts(conn)

    # インポート
    log("\nImporting to database...")
    n_dirs, n_works = import_directors(conn, merged)

    # FTS再構築
    log("\nRebuilding FTS5 index...")
    rebuild_fts(conn)

    # ImportBatch記録
    record_import_batch(conn, "v8-all", n_dirs, 0)

    # 検証
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM Director")
    db_dirs = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM Work")
    db_works = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM DirectorYearSource")
    db_ys = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM director_fts")
    db_fts = cur.fetchone()[0]

    conn.close()

    log(f"\n=== Import Complete ===")
    log(f"  Directors: {db_dirs}")
    log(f"  Works: {db_works}")
    log(f"  Year Sources: {db_ys}")
    log(f"  FTS entries: {db_fts}")


if __name__ == "__main__":
    main()
