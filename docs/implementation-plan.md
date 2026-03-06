# ディレクターズファイル検索サイト 実装計画

## 1. プロジェクト概要

「CM・映像ディレクターズファイル」PDFから監督情報を抽出し、
社内限定の検索可能なWebサイトを構築する。

### 入力データ
| ファイル | ページ数 | 監督データ開始 | 備考 |
|---------|---------|-------------|------|
| CM・映像ディレクターズファイル2023-2024.pdf | 372p | 19p〜 | 最新版、PoC対象 |
| CM・映像ディレクターズファイル2021-2022.pdf | 380p | 18p〜 | 追加対象 |
| CM・映像ディレクターズファイル2020-2021.pdf | 359p | 18p〜 | 追加対象 |

### PDF構造分析結果
各ページに1〜2人の監督情報が含まれる。1監督あたりの構造：

```
監督名（日本語）
ローマ字名
電話番号 (Mg) ← マネジメント電話の場合
所属会社名 (Mg：担当者名)
〒郵便番号
住所
メールアドレス (Mg)
WebサイトURL
プロフィール文（経歴・受賞歴・自己PR）
─── 作品ブロック ───
クライアント名
商品名/作品タイトル
「作品サブタイトル」篇
広告代理店＋制作会社
制作年
（複数作品が続く）
```

### OCR品質
- 2023-2024: 良好（一部文字化けあり）
- 2021-2022: やや粗い（改行位置ずれ多い）
- 2020-2021: やや粗い

---

## 2. データモデル設計

### テーブル構成

```prisma
model Director {
  id                 Int      @id @default(autoincrement())
  name               String   // 監督名（日本語）
  nameRomaji         String?  // ローマ字名
  email              String?  // メールアドレス
  phone              String?  // 電話番号
  company            String?  // 所属会社
  profile            String?  // 最新プロフィール
  portraitImagePath   String?  // 写真パス
  createdAt          DateTime @default(now())
  updatedAt          DateTime @updatedAt
  works              Work[]
  yearSources        DirectorYearSource[]
  profileHistories   DirectorProfileHistory[]
}

model Work {
  id            Int      @id @default(autoincrement())
  directorId    Int
  title         String   // 作品タイトル
  clientName    String?  // クライアント名
  productName   String?  // 商品名
  agency        String?  // 広告代理店＋制作会社
  year          Int?     // 制作年
  sourceYear    String   // 掲載年度 (e.g. "2023-2024")
  youtubeUrl    String?  // YouTube URL
  thumbnailPath String?  // サムネイル画像パス
  director      Director @relation(fields: [directorId], references: [id])
}

model DirectorYearSource {
  id          Int      @id @default(autoincrement())
  directorId  Int
  sourceYear  String   // "2023-2024"
  sourcePage  Int?     // PDFページ番号
  director    Director @relation(fields: [directorId], references: [id])
  @@unique([directorId, sourceYear])
}

model DirectorProfileHistory {
  id          Int      @id @default(autoincrement())
  directorId  Int
  sourceYear  String
  profile     String
  director    Director @relation(fields: [directorId], references: [id])
  @@unique([directorId, sourceYear])
}

model ImportBatch {
  id          Int      @id @default(autoincrement())
  sourceYear  String
  status      String   // "dry-run" | "applied" | "rolled-back"
  inserted    Int      @default(0)
  updated     Int      @default(0)
  skipped     Int      @default(0)
  reviewCount Int      @default(0)
  createdAt   DateTime @default(now())
}

// FTS用仮想テーブル（SQL直接作成）
// director_fts(name, profile, work_titles, client_names, product_names)
```

---

## 3. 抽出ルール設計

### Phase 1: テキスト抽出（PyMuPDF）
- PDFからページ単位でテキスト抽出
- ノイズ除去（ヘッダ/フッタ/ページ番号/サイドバー文字）

### Phase 2: 監督ブロック分割
正規表現で監督エントリを検出：
1. 日本語名（漢字/ひらがな/カタカナ 2〜10文字）
2. 直後にローマ字名（英字 + スペース）
3. 電話番号パターン（0XX-XXXX-XXXX）

### Phase 3: フィールド抽出
各ブロックから以下を正規表現で抽出：
- **名前**: ブロック先頭の日本語文字列
- **ローマ字**: 英字名パターン
- **電話番号**: `\d{2,4}-\d{3,4}-\d{4}` パターン
- **メール**: `[\w.-]+@[\w.-]+` パターン
- **住所**: `〒` で始まる行 + 続く住所行
- **会社**: 電話番号の次の行（会社名パターン）
- **プロフィール**: 住所/URL後の文章ブロック
- **作品**: クライアント名 + タイトル + 代理店 + 年

### Phase 4: 正規化
- 電話番号フォーマット統一
- メールアドレスクリーニング
- 年度情報付与

---

## 4. 処理パイプライン

```
[PDF] → extract-text.py → data/raw/
      → parse-directors.py → data/intermediate/
      → normalize-data.py → data/normalized/
      → import (dry-run) → レビュー
      → import (apply) → SQLite DB
      → extract-images.py → public/portraits/
      → fetch-youtube.ts → YouTube URL更新
```

各ステップは独立実行可能。
中間データはJSON形式で保存。

---

## 5. 技術スタック

| 項目 | 技術 |
|------|------|
| フロントエンド | Next.js 14 + TypeScript + Tailwind CSS |
| DB | SQLite + Prisma ORM |
| 全文検索 | SQLite FTS5 |
| PDF処理 | PyMuPDF (Python) |
| 画像処理 | PyMuPDF + Pillow (WebP変換) |
| YouTube | YouTube Data API v3 |

---

## 6. 実装フェーズ

### Phase 1: PoC（20人）
1. 2023-2024 PDFから最初の20人を抽出
2. JSON形式で保存
3. DB投入
4. 検索UI構築
5. 精度検証

### Phase 2: 2023-2024 全件
1. 全ページ処理
2. 画像抽出
3. YouTube取得
4. レビュー

### Phase 3: 年度追加
1. 2021-2022 インポート
2. 同一監督マージ
3. 2020-2021 インポート

---

## 7. 同一監督マージロジック

```
confidence判定:
  名前完全一致 + メール一致 → high (自動マージ)
  名前完全一致 + 電話一致 → high (自動マージ)
  名前完全一致 + 会社一致 → medium (レビュー推奨)
  名前完全一致のみ → low (要レビュー)
```

medium以下は `data/review/` にCSV出力。

---

## 8. インポートコマンド

```bash
# テキスト抽出
python scripts/extract-text.py --year 2023-2024

# パース
python scripts/parse-directors.py --year 2023-2024

# 正規化
python scripts/normalize-data.py --year 2023-2024

# dry-run（DBに書き込まない）
npx ts-node scripts/import-db.ts --year 2023-2024 --dry-run

# 本番適用
npx ts-node scripts/import-db.ts --year 2023-2024 --apply

# 画像抽出
python scripts/extract-images.py --year 2023-2024

# YouTube取得
npx ts-node scripts/fetch-youtube.ts --year 2023-2024
```

---

## 9. UI仕様

### トップページ `/`
- 検索バー（リアルタイム検索）
- 監督カード一覧（写真・名前・メール・連絡先）
- アルファベット/五十音順
- 100件/ページ、ページネーション

### 詳細ページ `/director/[id]`
- 監督情報（名前、連絡先、プロフィール）
- 掲載年度バッジ
- 作品一覧（年度別）
- YouTube埋め込み or サムネイル+リンク

### 検索 `/api/search?q=`
- FTS5による全文検索
- 監督名、プロフィール、作品名、クライアント名、商品名を横断検索

---

## 10. ディレクトリ構成

```
dfdb/
├── .env.example
├── README.md
├── docs/
│   ├── implementation-plan.md
│   └── data-model.md
├── scripts/
│   ├── extract-text.py
│   ├── parse-directors.py
│   ├── normalize-data.py
│   ├── import-db.ts
│   ├── extract-images.py
│   └── fetch-youtube.ts
├── data/
│   ├── raw/
│   ├── intermediate/
│   ├── normalized/
│   ├── final/
│   └── review/
├── source/           # PDFs (gitignored)
├── prisma/
│   └── schema.prisma
├── src/
│   └── app/
│       ├── page.tsx
│       ├── director/[id]/page.tsx
│       ├── api/search/route.ts
│       └── api/directors/route.ts
├── public/
│   └── portraits/
└── package.json
```

---

## 11. 安全運用方針

- 長時間処理は分割実行
- 中間データはすべてファイル保存
- dry-run → レビュー → apply の3段階
- ImportBatchでロールバック可能
- 原本PDFは `source/` に保全（gitignored）
