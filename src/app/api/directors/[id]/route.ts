import { NextRequest, NextResponse } from "next/server";
import Database from "better-sqlite3";
import path from "path";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const directorId = parseInt(id);

  if (isNaN(directorId)) {
    return NextResponse.json({ error: "Invalid ID" }, { status: 400 });
  }

  const dbPath = path.resolve(process.cwd(), "prisma", "dev.db");
  const db = new Database(dbPath, { readonly: true });

  try {
    const director = db.prepare("SELECT * FROM Director WHERE id = ?").get(directorId);

    if (!director) {
      return NextResponse.json({ error: "Not found" }, { status: 404 });
    }

    const works = db.prepare(
      "SELECT * FROM Work WHERE directorId = ? ORDER BY year DESC, title"
    ).all(directorId);

    const yearSources = db.prepare(
      "SELECT * FROM DirectorYearSource WHERE directorId = ? ORDER BY sourceYear DESC"
    ).all(directorId);

    const profileHistories = db.prepare(
      "SELECT * FROM DirectorProfileHistory WHERE directorId = ? ORDER BY sourceYear DESC"
    ).all(directorId);

    return NextResponse.json({
      ...(director as any),
      works,
      yearSources,
      profileHistories,
    });
  } finally {
    db.close();
  }
}
