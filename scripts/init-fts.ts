import Database from "better-sqlite3";
import path from "path";

const dbPath = path.join(__dirname, "..", "prisma", "dev.db");
const db = new Database(dbPath);

// Create FTS5 virtual table for full-text search
db.exec(`
  CREATE VIRTUAL TABLE IF NOT EXISTS director_fts USING fts5(
    director_id UNINDEXED,
    name,
    name_romaji,
    profile,
    work_titles,
    client_names,
    product_names,
    tokenize='unicode61'
  );
`);

console.log("FTS5 table created successfully.");
db.close();
