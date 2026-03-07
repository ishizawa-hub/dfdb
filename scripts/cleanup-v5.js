#!/usr/bin/env node
/**
 * v5 DB cleanup: remove garbage directors and fix data issues
 */
const Database = require('better-sqlite3');
const path = require('path');

const DB_PATH = path.join(__dirname, '..', 'prisma', 'dev.db');
const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');

let deleted = 0;

// 1. Delete clearly garbage directors
const garbageIds = [];
const dirs = db.prepare('SELECT id, name, nameRomaji FROM Director').all();

for (const d of dirs) {
  const name = d.name;
  let isGarbage = false;

  // Starts with special chars (not CJK, not alpha, not katakana)
  if (/^["\=\(\)\[\]①②③④⑤⑥⑦⑧⑨⑩\+\-\.\,\;\:\!\?\~\#\@\$\%\&\*\^\_\|\\\/]/.test(name)) {
    isGarbage = true;
  }
  // Contains non-CJK garbage characters mixed with text
  if (/[IlL1]{3,}|[0-9:，『』]+/.test(name) && name.length > 3) {
    isGarbage = true;
  }
  // Contains embedded digits (like 春山11デビw祥一)
  if (/\d{2,}/.test(name) && !/^TAKCOM/.test(name)) {
    isGarbage = true;
  }
  // Single character names
  if (name.length <= 1) {
    isGarbage = true;
  }
  // OCR garbage patterns
  if (/^[軽拓曼句謹].$/.test(name)) {
    // Check if romaji is also suspicious
    const romaji = d.nameRomaji || '';
    if (!romaji || /UNl|Dark Knigh|IN FOCUS|Mivakoshi/.test(romaji)) {
      isGarbage = true;
    }
  }

  if (isGarbage) {
    garbageIds.push(d.id);
    console.log(`DELETE: ID=${d.id} name=[${name}] romaji=[${d.nameRomaji || ''}]`);
  }
}

if (garbageIds.length > 0) {
  const ph = garbageIds.map(() => '?').join(',');
  const worksDel = db.prepare(`DELETE FROM Work WHERE directorId IN (${ph})`).run(...garbageIds);
  db.prepare(`DELETE FROM DirectorYearSource WHERE directorId IN (${ph})`).run(...garbageIds);
  db.prepare(`DELETE FROM DirectorProfileHistory WHERE directorId IN (${ph})`).run(...garbageIds);
  const dirsDel = db.prepare(`DELETE FROM Director WHERE id IN (${ph})`).run(...garbageIds);
  deleted = dirsDel.changes;
  console.log(`\nDeleted ${deleted} garbage directors (${worksDel.changes} works)`);
}

// 2. Rebuild FTS
console.log('\nRebuilding FTS5...');
db.exec("INSERT INTO director_fts(director_fts) VALUES('rebuild');");

// Stats
const dirCount = db.prepare('SELECT COUNT(*) as c FROM Director').get().c;
const workCount = db.prepare('SELECT COUNT(*) as c FROM Work').get().c;
const withPortrait = db.prepare("SELECT COUNT(*) as c FROM Director WHERE portraitImagePath IS NOT NULL AND portraitImagePath != ''").get().c;
const withThumb = db.prepare("SELECT COUNT(*) as c FROM Work WHERE thumbnailPath IS NOT NULL AND thumbnailPath != ''").get().c;
const withYt = db.prepare("SELECT COUNT(*) as c FROM Work WHERE youtubeUrl IS NOT NULL AND youtubeUrl != ''").get().c;

console.log(`\n--- Stats ---`);
console.log(`Directors: ${dirCount} (with portrait: ${withPortrait})`);
console.log(`Works: ${workCount} (with thumb: ${withThumb}, with YouTube: ${withYt})`);

db.close();
