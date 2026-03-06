/**
 * DBインポートスクリプト
 * Usage:
 *   npx tsx scripts/import-db.ts --year 2023-2024 --dry-run
 *   npx tsx scripts/import-db.ts --year 2023-2024 --apply
 */
import { PrismaClient } from "@prisma/client";
import Database from "better-sqlite3";
import * as fs from "fs";
import * as path from "path";

const prisma = new PrismaClient();

interface ParsedWork {
  title: string;
  clientName: string | null;
  productName: string | null;
  agency: string | null;
  year: number | null;
  sourceYear: string;
}

interface ParsedDirector {
  name: string;
  nameRomaji: string;
  phone: string;
  email: string;
  company: string;
  profile: string;
  works: ParsedWork[];
  sourcePage: number;
  sourceYear: string;
}

interface ParsedData {
  source_year: string;
  total_directors: number;
  directors: ParsedDirector[];
}

async function findExistingDirector(
  name: string,
  email: string,
  phone: string
): Promise<{ id: number; confidence: string } | null> {
  // Priority 1: name + email
  if (email) {
    const match = await prisma.director.findFirst({
      where: { name, email },
    });
    if (match) return { id: match.id, confidence: "high" };
  }

  // Priority 2: name + phone
  if (phone) {
    const match = await prisma.director.findFirst({
      where: { name, phone },
    });
    if (match) return { id: match.id, confidence: "high" };
  }

  // Priority 3: name only
  const nameMatch = await prisma.director.findFirst({
    where: { name },
  });
  if (nameMatch) return { id: nameMatch.id, confidence: "medium" };

  return null;
}

async function importData(year: string, dryRun: boolean) {
  const baseDir = path.resolve(__dirname, "..");
  const dataPath = path.join(
    baseDir,
    "data",
    "intermediate",
    `parsed_${year}.json`
  );

  if (!fs.existsSync(dataPath)) {
    console.error(`Data file not found: ${dataPath}`);
    console.error(
      `Run parse-directors.py first: python scripts/parse-directors.py --year ${year}`
    );
    process.exit(1);
  }

  const rawData = fs.readFileSync(dataPath, "utf-8");
  const data: ParsedData = JSON.parse(rawData);

  console.log(`\n=== Import ${dryRun ? "(DRY RUN)" : "(APPLY)"} ===`);
  console.log(`Source Year: ${year}`);
  console.log(`Directors: ${data.total_directors}`);
  console.log("");

  let inserted = 0;
  let updated = 0;
  let skipped = 0;
  let reviewNeeded = 0;
  const reviewItems: string[] = [];

  for (const dir of data.directors) {
    if (!dir.name || dir.name.length < 2) {
      skipped++;
      continue;
    }

    const existing = await findExistingDirector(
      dir.name,
      dir.email,
      dir.phone
    );

    if (existing) {
      // Auto-merge for both high and medium confidence
      if (!dryRun) {
        // Check if this year is newer than existing data
        const existingSources = await prisma.directorYearSource.findMany({
          where: { directorId: existing.id },
          select: { sourceYear: true },
        });
        const existingYears = existingSources.map((s) => s.sourceYear);
        const isNewer = !existingYears.some((ey) => ey > year);

        // Only update main Director fields if this data is newer
        if (isNewer) {
          await prisma.director.update({
            where: { id: existing.id },
            data: {
              email: dir.email || undefined,
              phone: dir.phone || undefined,
              company: dir.company || undefined,
              profile: dir.profile || undefined,
              nameRomaji: dir.nameRomaji || undefined,
            },
          });
        }

        // Add year source
        await prisma.directorYearSource.upsert({
          where: {
            directorId_sourceYear: {
              directorId: existing.id,
              sourceYear: year,
            },
          },
          create: {
            directorId: existing.id,
            sourceYear: year,
            sourcePage: dir.sourcePage,
          },
          update: { sourcePage: dir.sourcePage },
        });

        // Add profile history
        if (dir.profile) {
          await prisma.directorProfileHistory.upsert({
            where: {
              directorId_sourceYear: {
                directorId: existing.id,
                sourceYear: year,
              },
            },
            create: {
              directorId: existing.id,
              sourceYear: year,
              profile: dir.profile,
            },
            update: { profile: dir.profile },
          });
        }

        // Add works
        for (const work of dir.works) {
          const existingWork = await prisma.work.findFirst({
            where: {
              directorId: existing.id,
              title: work.title,
              year: work.year,
            },
          });
          if (!existingWork) {
            await prisma.work.create({
              data: {
                directorId: existing.id,
                title: work.title,
                clientName: work.clientName,
                productName: work.productName,
                agency: work.agency,
                year: work.year,
                sourceYear: work.sourceYear,
              },
            });
          }
        }
      }
      updated++;
      if (existing.confidence === "medium") {
        reviewNeeded++;
        reviewItems.push(
          `${dir.name},${dir.email},${dir.phone},${existing.confidence},existing_id=${existing.id}`
        );
      }
      console.log(`  UPDATE: ${dir.name} (confidence: ${existing.confidence})`);
    } else {
      // New director
      if (!dryRun) {
        const created = await prisma.director.create({
          data: {
            name: dir.name,
            nameRomaji: dir.nameRomaji || null,
            email: dir.email || null,
            phone: dir.phone || null,
            company: dir.company || null,
            profile: dir.profile || null,
            yearSources: {
              create: {
                sourceYear: year,
                sourcePage: dir.sourcePage,
              },
            },
            profileHistories: dir.profile
              ? {
                  create: {
                    sourceYear: year,
                    profile: dir.profile,
                  },
                }
              : undefined,
            works: {
              create: dir.works.map((w) => ({
                title: w.title,
                clientName: w.clientName,
                productName: w.productName,
                agency: w.agency,
                year: w.year,
                sourceYear: w.sourceYear,
              })),
            },
          },
        });
      }
      inserted++;
      console.log(`  INSERT: ${dir.name}`);
    }
  }

  // Record import batch
  if (!dryRun) {
    await prisma.importBatch.create({
      data: {
        sourceYear: year,
        status: "applied",
        inserted,
        updated,
        skipped,
        reviewCount: reviewNeeded,
      },
    });

    // Update FTS index
    await updateFTS();
  } else {
    console.log(`\n--- DRY RUN Summary ---`);
  }

  console.log(`\n=== Summary ===`);
  console.log(`Inserted:  ${inserted}`);
  console.log(`Updated:   ${updated}`);
  console.log(`Skipped:   ${skipped}`);
  console.log(`Review:    ${reviewNeeded}`);

  // Save review items
  if (reviewItems.length > 0) {
    const reviewDir = path.join(baseDir, "data", "review");
    fs.mkdirSync(reviewDir, { recursive: true });
    const reviewPath = path.join(reviewDir, `review_${year}.csv`);
    fs.writeFileSync(
      reviewPath,
      "name,email,phone,confidence,note\n" + reviewItems.join("\n")
    );
    console.log(`\nReview file: ${reviewPath}`);
  }
}

async function updateFTS() {
  const baseDir = path.resolve(__dirname, "..");
  const dbPath = path.join(baseDir, "prisma", "dev.db");
  const db = new Database(dbPath);

  // Clear and rebuild FTS
  db.exec("DELETE FROM director_fts");

  const directors = db
    .prepare(
      `
    SELECT d.id, d.name, d.nameRomaji, d.profile,
           GROUP_CONCAT(DISTINCT w.title) as work_titles,
           GROUP_CONCAT(DISTINCT w.clientName) as client_names,
           GROUP_CONCAT(DISTINCT w.productName) as product_names
    FROM Director d
    LEFT JOIN Work w ON w.directorId = d.id
    GROUP BY d.id
  `
    )
    .all();

  const insert = db.prepare(
    "INSERT INTO director_fts(director_id, name, name_romaji, profile, work_titles, client_names, product_names) VALUES (?, ?, ?, ?, ?, ?, ?)"
  );

  for (const d of directors as any[]) {
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

  console.log(`FTS index updated: ${directors.length} directors`);
  db.close();
}

// Parse args
const args = process.argv.slice(2);
let year = "";
let dryRun = true;

for (let i = 0; i < args.length; i++) {
  if (args[i] === "--year" && args[i + 1]) {
    year = args[i + 1];
    i++;
  } else if (args[i] === "--dry-run") {
    dryRun = true;
  } else if (args[i] === "--apply") {
    dryRun = false;
  }
}

if (!year) {
  console.error("Usage: npx tsx scripts/import-db.ts --year 2023-2024 [--dry-run|--apply]");
  process.exit(1);
}

importData(year, dryRun)
  .then(() => prisma.$disconnect())
  .catch((e) => {
    console.error(e);
    prisma.$disconnect();
    process.exit(1);
  });
