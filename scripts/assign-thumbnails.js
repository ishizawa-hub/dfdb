#!/usr/bin/env node
/**
 * サムネイル画像をDBの作品に紐付ける
 *
 * v4データのsourcePage情報とDB内の監督順序を使い、
 * 同一ページの1番目=左カラム、2番目=右カラムと推定する。
 * 各カラムの作品1=上段(slot_1)、作品2=下段(slot_2)に対応。
 */
const Database = require('better-sqlite3');
const fs = require('fs');
const path = require('path');

const DB_PATH = path.join(__dirname, '..', 'prisma', 'dev.db');
const THUMB_BASE = path.join(__dirname, '..', 'public', 'thumbnails');
const YEARS = ['2023-2024', '2021-2022', '2020-2021'];

function main() {
  const db = new Database(DB_PATH);
  db.pragma('journal_mode = WAL');

  // Get all directors with their source pages and works
  const directors = db.prepare(`
    SELECT d.id, d.name, dys.sourceYear, dys.sourcePage
    FROM Director d
    JOIN DirectorYearSource dys ON dys.directorId = d.id
    ORDER BY dys.sourceYear, dys.sourcePage, d.id
  `).all();

  // Group directors by (year, page)
  const pageGroups = {};
  for (const d of directors) {
    const key = `${d.sourceYear}|${d.sourcePage}`;
    if (!pageGroups[key]) pageGroups[key] = [];
    pageGroups[key].push(d);
  }

  const updateWork = db.prepare('UPDATE Work SET thumbnailPath = ? WHERE id = ?');

  let assigned = 0;
  let checked = 0;

  const assignAll = db.transaction(() => {
    for (const [key, dirs] of Object.entries(pageGroups)) {
      const [year, pageStr] = key.split('|');
      const page = parseInt(pageStr);

      // First director on page = left column, second = right column
      for (let di = 0; di < dirs.length && di < 2; di++) {
        const side = di === 0 ? 'left' : 'right';
        const dirId = dirs[di].id;

        // Get works for this director from this sourceYear, ordered by id (insertion order = PDF order)
        const works = db.prepare(
          'SELECT id FROM Work WHERE directorId = ? AND sourceYear = ? ORDER BY id'
        ).all(dirId, year);

        for (let wi = 0; wi < works.length && wi < 2; wi++) {
          const slot = wi + 1;
          const thumbFile = `p${page}_${side}_${slot}.jpg`;
          const thumbPath = path.join(THUMB_BASE, year, thumbFile);
          checked++;

          if (fs.existsSync(thumbPath)) {
            const webPath = `/thumbnails/${year}/${thumbFile}`;
            updateWork.run(webPath, works[wi].id);
            assigned++;
          }
        }
      }
    }
  });

  assignAll();

  // Stats
  const totalWorks = db.prepare('SELECT COUNT(*) as c FROM Work').get().c;
  const withThumb = db.prepare("SELECT COUNT(*) as c FROM Work WHERE thumbnailPath IS NOT NULL AND thumbnailPath != ''").get().c;

  console.log(`Checked: ${checked} work-thumbnail pairs`);
  console.log(`Assigned: ${assigned} thumbnails`);
  console.log(`Total works: ${totalWorks}, with thumbnails: ${withThumb} (${((withThumb/totalWorks)*100).toFixed(1)}%)`);

  db.close();
}

main();
