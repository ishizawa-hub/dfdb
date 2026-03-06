# Directors File DB (dfdb)

CM・映像ディレクターズファイルの検索サイト。PDFの年鑑データからディレクター情報を抽出し、検索可能なWebアプリとして提供する社内ツール。

## 技術スタック

- **Frontend**: Next.js 16 / React 19 / Tailwind CSS 4
- **Backend**: Next.js App Router API Routes
- **DB**: SQLite (Prisma 5 + better-sqlite3) / FTS5全文検索
- **データ抽出**: Python (PyMuPDF + Pillow)

## セットアップ

```bash
# 依存インストール
npm install

# .env作成
cp .env.example .env

# DB初期化
npx prisma generate
npx prisma db push

# FTS5テーブル作成
npx tsx scripts/init-fts.ts
```

## データパイプライン

PDFからの全処理フロー:

```bash
# 1. テキスト抽出 (Python + PyMuPDF)
python scripts/extract-text.py --year 2023-2024

# 2. ディレクター情報パース
python scripts/parse-directors.py --year 2023-2024

# 3. DBインポート (dry-runで確認→apply)
npx tsx scripts/import-db.ts --year 2023-2024 --dry-run
npx tsx scripts/import-db.ts --year 2023-2024 --apply

# 4. 写真抽出 (PDFからクロップ→WebP)
python scripts/extract-images.py --year 2023-2024

# 5. YouTube URL取得 (オプション、API KEY必要)
npx tsx scripts/fetch-youtube.ts --year 2023-2024
```

### 処理済み年度

| 年度 | ディレクター数 | 作品数 |
|------|--------------|--------|
| 2023-2024 | 609 | 139 |
| 2021-2022 | 510 | 204 |
| 2020-2021 | 609 | 81 |
| **合計(重複除外)** | **932** | **424** |

## 開発サーバー

```bash
npm run dev
# http://localhost:3000
```

## 主要スクリプト

| コマンド | 説明 |
|----------|------|
| `npm run dev` | 開発サーバー起動 |
| `npm run build` | プロダクションビルド |
| `npm run extract` | PDFテキスト抽出 |
| `npm run parse` | ディレクター情報パース |
| `npm run import:dry` | DBインポート (dry-run) |
| `npm run import:apply` | DBインポート (適用) |
| `npm run fts:update` | FTSインデックス更新 |

## ディレクトリ構造

```
dfdb/
├── src/
│   ├── app/
│   │   ├── page.tsx              # トップページ（検索・一覧）
│   │   ├── director/[id]/page.tsx # ディレクター詳細
│   │   ├── api/search/route.ts   # 検索API
│   │   └── api/directors/[id]/route.ts  # 詳細API
│   └── lib/db.ts                 # Prismaクライアント
├── scripts/
│   ├── extract-text.py           # PDF→テキスト
│   ├── parse-directors.py        # テキスト→構造化データ
│   ├── import-db.ts              # 構造化データ→DB
│   ├── extract-images.py         # PDF→写真(WebP)
│   ├── fetch-youtube.ts          # YouTube URL取得
│   ├── update-fts.ts             # FTSインデックス再構築
│   └── init-fts.ts               # FTS5テーブル初期化
├── prisma/schema.prisma          # データモデル
├── data/                         # 中間データ（git除外）
└── public/portraits/             # 写真（git除外）
```

## 新年度追加手順

1. PDFを親ディレクトリに配置
2. `extract-text.py`の`PDF_MAP`に追加
3. パイプライン実行: extract → parse → import:dry → import:apply → extract-images
4. 既存ディレクターは自動マージ（名前+メール/電話で同定）

## 注意事項

- PDFと抽出データ、DBファイルはgit管理外
- `data/review/`にマージ確信度が中程度のケースが出力される
- YouTube取得には`YOUTUBE_API_KEY`環境変数が必要
