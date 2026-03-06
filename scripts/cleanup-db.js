#!/usr/bin/env node
/**
 * DB内のゴミデータを削除・修正
 */
const Database = require('better-sqlite3');
const path = require('path');

const DB_PATH = path.join(__dirname, '..', 'prisma', 'dev.db');
const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');

let deleted = 0;
let fixed = 0;

// 1. Delete garbage directors
const garbageIds = [];
const dirs = db.prepare('SELECT id, name, nameRomaji FROM Director').all();

for (const d of dirs) {
  const name = d.name;
  // Starts with special chars (not CJK, not alpha)
  if (/^["\=\(\)\[\]①②③④⑤⑥⑦⑧⑨⑩\+\-\.\,\;\:\!\?\~\#\@\$\%\&\*\^\_\|\\\/0-9]/.test(name)) {
    garbageIds.push(d.id);
    console.log(`DELETE: ID=${d.id} name=[${name}]`);
  } else if (name.length <= 1) {
    garbageIds.push(d.id);
    console.log(`DELETE: ID=${d.id} name=[${name}]`);
  }
}

if (garbageIds.length > 0) {
  const ph = garbageIds.map(() => '?').join(',');
  db.prepare(`DELETE FROM Work WHERE directorId IN (${ph})`).run(...garbageIds);
  db.prepare(`DELETE FROM DirectorYearSource WHERE directorId IN (${ph})`).run(...garbageIds);
  db.prepare(`DELETE FROM DirectorProfileHistory WHERE directorId IN (${ph})`).run(...garbageIds);
  db.prepare(`DELETE FROM Director WHERE id IN (${ph})`).run(...garbageIds);
  deleted = garbageIds.length;
}

// 2. Fix romaji spacing issues (e.g., "A i e s s a n d r o" -> "Alessandro")
const updateRomaji = db.prepare('UPDATE Director SET nameRomaji = ? WHERE id = ?');
const allDirs = db.prepare('SELECT id, name, nameRomaji FROM Director WHERE nameRomaji IS NOT NULL').all();

for (const d of allDirs) {
  let r = d.nameRomaji;
  if (!r) continue;

  let newR = r;

  // Fix spaced-out romaji: "A l e s s a n d r o P a c c i a n i" -> "AlessandroPacciani"
  // Check if most characters are single with spaces
  const chars = r.split('');
  const singleCharSpacePattern = chars.filter((c, i) => c !== ' ' && i + 2 < chars.length && chars[i + 1] === ' ' && chars[i + 2] !== ' ');
  const nonSpace = chars.filter(c => c !== ' ');
  if (nonSpace.length > 3 && singleCharSpacePattern.length / nonSpace.length > 0.4) {
    // Collapse spaces but keep word boundaries (uppercase after lowercase)
    const collapsed = r.replace(/ /g, '');
    // Re-insert space before uppercase that follows lowercase
    newR = collapsed.replace(/([a-z])([A-Z])/g, '$1 $2');
  }

  // Fix common OCR in romaji: l -> I at start of word, 1 -> I at start
  newR = newR.replace(/\bl([a-z])/g, 'I$1');
  newR = newR.replace(/\b1([a-z])/g, 'I$1');
  // Fix ;i -> i (common OCR)
  newR = newR.replace(/;/g, 'i');
  // Fix ,, -> ji
  newR = newR.replace(/,,/g, 'ji');
  // Fix trailing 1 after alpha
  newR = newR.replace(/([a-z])1\b/g, '$1i');

  if (newR !== r) {
    updateRomaji.run(newR, d.id);
    fixed++;
    if (fixed <= 20) {
      console.log(`FIX ROMAJI: [${r}] -> [${newR}]`);
    }
  }
}

// 3. Fix work titles that are actually agency+year (title should be something meaningful)
// Check works where title looks like "agency+year" pattern
const works = db.prepare('SELECT id, title, clientName, agency, year FROM Work').all();
let workFixed = 0;
const updateWork = db.prepare('UPDATE Work SET title = ?, clientName = ?, agency = ? WHERE id = ?');

for (const w of works) {
  let { title, clientName, agency } = w;
  if (!title) continue;

  // If title matches "XXX+YYY YYYY" (agency+production year), it's misidentified
  const agencyYearMatch = title.match(/^(.+[+].+)\s+((?:19|20)\d{2})\s*$/);
  if (agencyYearMatch && !agency) {
    // Title is actually the agency line - swap with client
    const newAgency = agencyYearMatch[1];
    const newTitle = clientName || title;
    if (clientName) {
      updateWork.run(newTitle, null, newAgency, w.id);
      workFixed++;
    }
  }
}

// 4. Rebuild FTS
console.log('\nRebuilding FTS5...');
db.exec("INSERT INTO director_fts(director_fts) VALUES('rebuild');");

// Stats
const dirCount = db.prepare('SELECT COUNT(*) as c FROM Director').get().c;
const workCount = db.prepare('SELECT COUNT(*) as c FROM Work').get().c;
console.log(`\nDeleted: ${deleted} garbage directors`);
console.log(`Fixed romaji: ${fixed}`);
console.log(`Fixed works: ${workFixed}`);
console.log(`Remaining: ${dirCount} directors, ${workCount} works`);

db.close();
