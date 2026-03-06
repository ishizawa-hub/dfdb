#!/usr/bin/env node
/**
 * v4データをSQLiteにインポート
 * - 3年分をマージ（同名監督を統合）
 * - FTS5再構築
 */
const Database = require('better-sqlite3');
const fs = require('fs');
const path = require('path');

const DB_PATH = path.join(__dirname, '..', 'prisma', 'dev.db');
const DATA_DIR = path.join(__dirname, '..', 'data', 'v4');

const YEARS = ['2023-2024', '2021-2022', '2020-2021'];

function normalizeForMatch(name) {
  return name.replace(/[\s　・]/g, '').toLowerCase();
}

function main() {
  const db = new Database(DB_PATH);
  db.pragma('journal_mode = WAL');
  db.pragma('foreign_keys = ON');

  // Drop and recreate tables
  console.log('Resetting database...');
  db.exec(`
    DROP TABLE IF EXISTS DirectorProfileHistory;
    DROP TABLE IF EXISTS DirectorYearSource;
    DROP TABLE IF EXISTS Work;
    DROP TABLE IF EXISTS Director;
    DROP TABLE IF EXISTS ImportBatch;
    DROP TABLE IF EXISTS director_fts;
  `);

  db.exec(`
    CREATE TABLE Director (
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
    );
    CREATE TABLE Work (
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
    );
    CREATE TABLE DirectorYearSource (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      directorId INTEGER NOT NULL,
      sourceYear TEXT NOT NULL,
      sourcePage INTEGER,
      FOREIGN KEY (directorId) REFERENCES Director(id) ON DELETE CASCADE,
      UNIQUE(directorId, sourceYear)
    );
    CREATE TABLE DirectorProfileHistory (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      directorId INTEGER NOT NULL,
      sourceYear TEXT NOT NULL,
      profile TEXT NOT NULL,
      FOREIGN KEY (directorId) REFERENCES Director(id) ON DELETE CASCADE,
      UNIQUE(directorId, sourceYear)
    );
    CREATE TABLE ImportBatch (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      sourceYear TEXT NOT NULL,
      status TEXT NOT NULL,
      inserted INTEGER DEFAULT 0,
      updated INTEGER DEFAULT 0,
      skipped INTEGER DEFAULT 0,
      reviewCount INTEGER DEFAULT 0,
      createdAt DATETIME DEFAULT CURRENT_TIMESTAMP
    );
  `);

  // Merge directors across years
  // Key: normalized Japanese name
  const dirMap = new Map(); // normName -> { director data, works[], years[] }

  for (const year of YEARS) {
    const jsonPath = path.join(DATA_DIR, `v4_${year}.json`);
    if (!fs.existsSync(jsonPath)) {
      console.log(`Skip: ${jsonPath} not found`);
      continue;
    }
    const raw = JSON.parse(fs.readFileSync(jsonPath, 'utf-8'));
    const dirs = raw.directors;
    console.log(`Loading ${year}: ${dirs.length} directors`);

    for (const d of dirs) {
      const key = normalizeForMatch(d.name);
      if (!key) continue;

      if (dirMap.has(key)) {
        const existing = dirMap.get(key);
        // Merge: prefer newer data (2023 > 2021 > 2020)
        if (!existing.nameRomaji && d.nameRomaji) existing.nameRomaji = d.nameRomaji;
        if (!existing.email && d.email) existing.email = d.email;
        if (!existing.phone && d.phone) existing.phone = d.phone;
        if (!existing.company && d.company) existing.company = d.company;
        if (!existing.website && d.website) existing.website = d.website;
        if (!existing.profile && d.profile) existing.profile = d.profile;

        // Add works (avoid exact duplicates)
        for (const w of d.works) {
          const dupKey = `${normalizeForMatch(w.title || '')}|${w.year || 0}`;
          if (!existing.workKeys.has(dupKey)) {
            existing.works.push({ ...w, sourceYear: year });
            existing.workKeys.add(dupKey);
          }
        }

        existing.years.push({ year, page: d.sourcePage });
        if (d.profile) {
          existing.profiles.push({ year, profile: d.profile });
        }
      } else {
        const workKeys = new Set();
        const works = [];
        for (const w of d.works) {
          const dupKey = `${normalizeForMatch(w.title || '')}|${w.year || 0}`;
          if (!workKeys.has(dupKey)) {
            works.push({ ...w, sourceYear: year });
            workKeys.add(dupKey);
          }
        }

        dirMap.set(key, {
          name: d.name,
          nameRomaji: d.nameRomaji || '',
          email: d.email || '',
          phone: d.phone || '',
          company: d.company || '',
          website: d.website || '',
          profile: d.profile || '',
          works,
          workKeys,
          years: [{ year, page: d.sourcePage }],
          profiles: d.profile ? [{ year, profile: d.profile }] : [],
        });
      }
    }
  }

  console.log(`\nMerged: ${dirMap.size} unique directors`);

  // Sort by romaji (alphabetical)
  const sorted = [...dirMap.values()].sort((a, b) => {
    const ra = (a.nameRomaji || '').toLowerCase();
    const rb = (b.nameRomaji || '').toLowerCase();
    if (!ra && !rb) return a.name.localeCompare(b.name, 'ja');
    if (!ra) return 1;
    if (!rb) return -1;
    return ra.localeCompare(rb);
  });

  // Insert
  const insertDir = db.prepare(`
    INSERT INTO Director (name, nameRomaji, email, phone, company, website, profile, portraitImagePath)
    VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
  `);
  const insertWork = db.prepare(`
    INSERT INTO Work (directorId, title, clientName, productName, agency, year, sourceYear, youtubeUrl, thumbnailPath)
    VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)
  `);
  const insertYearSource = db.prepare(`
    INSERT OR IGNORE INTO DirectorYearSource (directorId, sourceYear, sourcePage)
    VALUES (?, ?, ?)
  `);
  const insertProfile = db.prepare(`
    INSERT OR IGNORE INTO DirectorProfileHistory (directorId, sourceYear, profile)
    VALUES (?, ?, ?)
  `);

  const insertAll = db.transaction(() => {
    let totalWorks = 0;
    for (const d of sorted) {
      const info = insertDir.run(
        d.name, d.nameRomaji || null, d.email || null, d.phone || null,
        d.company || null, d.website || null, d.profile || null
      );
      const dirId = info.lastInsertRowid;

      for (const w of d.works) {
        insertWork.run(
          dirId, w.title, w.clientName || null, w.productName || null,
          w.agency || null, w.year || null, w.sourceYear
        );
        totalWorks++;
      }

      for (const ys of d.years) {
        insertYearSource.run(dirId, ys.year, ys.page);
      }

      for (const ph of d.profiles) {
        insertProfile.run(dirId, ph.year, ph.profile);
      }
    }
    return totalWorks;
  });

  const totalWorks = insertAll();
  console.log(`Inserted: ${sorted.length} directors, ${totalWorks} works`);

  // Build FTS5
  console.log('Building FTS5 index...');
  db.exec(`
    CREATE VIRTUAL TABLE IF NOT EXISTS director_fts USING fts5(
      name, nameRomaji, company, profile,
      content='Director', content_rowid='id',
      tokenize='unicode61'
    );
  `);
  db.exec(`INSERT INTO director_fts(director_fts) VALUES('rebuild');`);
  console.log('FTS5 index built.');

  // Stats
  const dirCount = db.prepare('SELECT COUNT(*) as c FROM Director').get().c;
  const workCount = db.prepare('SELECT COUNT(*) as c FROM Work').get().c;
  const withWorks = db.prepare('SELECT COUNT(DISTINCT directorId) as c FROM Work').get().c;
  const withWebsite = db.prepare("SELECT COUNT(*) as c FROM Director WHERE website IS NOT NULL AND website != ''").get().c;
  const withCompany = db.prepare("SELECT COUNT(*) as c FROM Director WHERE company IS NOT NULL AND company != ''").get().c;
  const withEmail = db.prepare("SELECT COUNT(*) as c FROM Director WHERE email IS NOT NULL AND email != ''").get().c;

  console.log(`\n=== Final DB Stats ===`);
  console.log(`Directors: ${dirCount}`);
  console.log(`Works: ${workCount}`);
  console.log(`Directors with works: ${withWorks}`);
  console.log(`Directors with website: ${withWebsite}`);
  console.log(`Directors with company: ${withCompany}`);
  console.log(`Directors with email: ${withEmail}`);

  db.close();
  console.log('\nDone!');
}

main();
