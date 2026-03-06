import Database from "better-sqlite3";
import path from "path";

const dbPath = path.resolve(__dirname, "..", "prisma", "dev.db");
const db = new Database(dbPath);

db.exec("DELETE FROM director_fts");

const directors = db
  .prepare(
    "SELECT d.id, d.name, d.nameRomaji, d.profile, " +
    "GROUP_CONCAT(DISTINCT w.title) as work_titles, " +
    "GROUP_CONCAT(DISTINCT w.clientName) as client_names, " +
    "GROUP_CONCAT(DISTINCT w.productName) as product_names " +
    "FROM Director d LEFT JOIN Work w ON w.directorId = d.id GROUP BY d.id"
  )
  .all() as any[];

const insert = db.prepare(
  "INSERT INTO director_fts(director_id, name, name_romaji, profile, work_titles, client_names, product_names) VALUES (?, ?, ?, ?, ?, ?, ?)"
);

for (const d of directors) {
  insert.run(
    d.id,
    d.name || "",
    d.nameRomaji || "",
    d.profile || "",
    d.work_titles || "",
    d.client_names || "",
    d.product_names || ""
  );
}

console.log("FTS updated:", directors.length, "directors");
db.close();
