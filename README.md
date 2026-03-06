# Directors File DB (dfdb)

CM・映像ディレクターズファイルの検索サイト。PDFの年鑑データからディレクター情報を抽出し、検索可能なWebアプリとして提供する社内ツール。

## 技術スタック

- **Frontend**: Next.js 16 / React 19 / Tailwind CSS 4
- **Backend**: Next.js App Router API Routes
- **DB**: SQLite (Prisma 5 + better-sqlite3) / FTS5全文検索
- **データ抽出**: Python (PyMuPDF + Pillow)
- **認証**: Basic Auth (パスワード: dfdb)

## データ概要

| 年度 | ディレクター数 | 作品数 |
|------|--------------|--------|
| 2023-2024 | 603 | 139 |
| 2021-2022 | 510 | 204 |
| 2020-2021 | 607 | 81 |
| **合計(重複除外)** | **863** | **416** |

## セットアップ

```bash
npm install
cp .env.example .env
npx prisma generate
npm run dev
# http://localhost:3000 (パスワード: dfdb)
```

## デプロイ (Render.com)

1. [Render.com](https://render.com) にGitHubアカウントでサインアップ
2. Dashboard → **New** → **Web Service**
3. GitHub リポジトリ `ishizawa-hub/dfdb` を接続
4. 設定:
   - **Runtime**: Docker
   - **Environment Variables**: `BASIC_AUTH_PASSWORD` = `dfdb`
5. **Create Web Service** をクリック

デプロイ完了後、発行されたURLにアクセスするとBasic Auth認証画面が表示されます。
ユーザー名は任意、パスワードは `dfdb` です。

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

# 5. 作品サムネイル抽出
python scripts/extract-work-thumbnails.py --year 2023-2024

# 6. FTSインデックス更新
npx tsx scripts/update-fts.ts

# 7. YouTube URL取得 (オプション、API KEY必要)
npx tsx scripts/fetch-youtube.ts --year 2023-2024
```

## 主要スクリプト

| コマンド | 説明 |
|----------|------|
| `npm run dev` | 開発サーバー起動 |
| `npm run build` | プロダクションビルド |
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
│   ├── middleware.ts              # Basic Auth
│   └── lib/db.ts                 # Prismaクライアント
├── scripts/
│   ├── extract-text.py           # PDF→テキスト
│   ├── parse-directors.py        # テキスト→構造化データ
│   ├── import-db.ts              # 構造化データ→DB
│   ├── extract-images.py         # PDF→写真(WebP)
│   ├── extract-work-thumbnails.py # PDF→作品サムネイル
│   ├── cleanup-data.js           # データクリーンアップ
│   ├── fetch-youtube.ts          # YouTube URL取得
│   ├── update-fts.ts             # FTSインデックス再構築
│   └── init-fts.ts               # FTS5テーブル初期化
├── prisma/
│   ├── schema.prisma             # データモデル
│   └── dev.db                    # SQLiteデータベース
├── public/
│   ├── portraits/                # 監督写真(WebP)
│   └── thumbnails/               # 作品サムネイル(WebP)
├── Dockerfile                    # Docker デプロイ用
└── render.yaml                   # Render.com デプロイ設定
```

## 新年度追加手順

1. PDFを親ディレクトリに配置
2. `extract-text.py`の`PDF_MAP`に追加
3. パイプライン実行: extract → parse → import:dry → import:apply → extract-images
4. 既存ディレクターは自動マージ（名前+メール/電話で同定）
5. `cleanup-data.js` でデータ品質チェック
6. `update-fts.ts` でFTSインデックス再構築
