import { NextRequest, NextResponse } from "next/server";
import Database from "better-sqlite3";
import path from "path";

export async function GET(request: NextRequest) {
  const q = request.nextUrl.searchParams.get("q") || "";
  const page = parseInt(request.nextUrl.searchParams.get("page") || "1");
  const limit = parseInt(request.nextUrl.searchParams.get("limit") || "100");
  const offset = (page - 1) * limit;

  const dbPath = path.resolve(process.cwd(), "prisma", "dev.db");
  const db = new Database(dbPath, { readonly: true });

  try {
    if (!q.trim()) {
      // Return all directors paginated
      const total = (db.prepare("SELECT COUNT(*) as count FROM Director").get() as any).count;
      const directors = db.prepare(
        "SELECT d.*, " +
        "(SELECT GROUP_CONCAT(DISTINCT dys.sourceYear) FROM DirectorYearSource dys WHERE dys.directorId = d.id) as sourceYears " +
        "FROM Director d ORDER BY d.name LIMIT ? OFFSET ?"
      ).all(limit, offset);

      return NextResponse.json({ directors, total, page, limit });
    }

    // FTS search
    const searchTerm = q.trim().split(/\s+/).map(t => `"${t}"`).join(" OR ");

    const ftsResults = db.prepare(
      "SELECT director_id FROM director_fts WHERE director_fts MATCH ? LIMIT 500"
    ).all(searchTerm) as any[];

    if (ftsResults.length === 0) {
      // Fallback: LIKE search
      const likePattern = `%${q.trim()}%`;
      const directors = db.prepare(
        "SELECT DISTINCT d.*, " +
        "(SELECT GROUP_CONCAT(DISTINCT dys.sourceYear) FROM DirectorYearSource dys WHERE dys.directorId = d.id) as sourceYears " +
        "FROM Director d LEFT JOIN Work w ON w.directorId = d.id " +
        "WHERE d.name LIKE ? OR d.nameRomaji LIKE ? OR d.profile LIKE ? " +
        "OR w.title LIKE ? OR w.clientName LIKE ? OR w.productName LIKE ? " +
        "ORDER BY d.name LIMIT ? OFFSET ?"
      ).all(likePattern, likePattern, likePattern, likePattern, likePattern, likePattern, limit, offset);

      return NextResponse.json({ directors, total: directors.length, page, limit });
    }

    const ids = ftsResults.map((r: any) => r.director_id);
    const placeholders = ids.map(() => "?").join(",");
    const total = ids.length;
    const pagedIds = ids.slice(offset, offset + limit);

    if (pagedIds.length === 0) {
      return NextResponse.json({ directors: [], total, page, limit });
    }

    const ph2 = pagedIds.map(() => "?").join(",");
    const directors = db.prepare(
      `SELECT d.*, ` +
      `(SELECT GROUP_CONCAT(DISTINCT dys.sourceYear) FROM DirectorYearSource dys WHERE dys.directorId = d.id) as sourceYears ` +
      `FROM Director d WHERE d.id IN (${ph2}) ORDER BY d.name`
    ).all(...pagedIds);

    return NextResponse.json({ directors, total, page, limit });
  } finally {
    db.close();
  }
}
