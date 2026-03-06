const Database = require('better-sqlite3');
const path = require('path');
const db = new Database(path.join(__dirname, '..', 'prisma', 'dev.db'));
db.pragma('journal_mode = WAL');

const update = db.prepare('UPDATE Director SET nameRomaji = ?, company = COALESCE(company, ?) WHERE id = ?');
const clearRomaji = db.prepare('UPDATE Director SET nameRomaji = NULL WHERE id = ?');

// Specific fixes for known misidentified romaji
const fixes = [
  // ID, correct romaji, company from romaji if useful
  [18, 'Adachi Kotaro', 'C3FILM'],
  [28, 'Ono Toshitsugu', 'COLORS Inc'],
  [29, 'Inagaki Satomi', 'CONNECTION Inc.'],
  [34, 'Tauchi Kenya', 'DASH The Lab'],
  [31, 'Ikemune Kiyoshi', 'DRAWING AND MANUAL'],
  [32, 'Tsujimoto Kazuo', 'DRAWING AND MANUAL'],
  [69, 'Iseda Sezan', 'GLASSLOFT'],
  [645, null, 'SPIRITS Inc.'],  // Clear romaji, set company
  [866, 'Takano Isao', 'ZEN creative'],
];

let count = 0;
for (const [id, romaji, company] of fixes) {
  if (romaji) {
    update.run(romaji, company || null, id);
  } else {
    clearRomaji.run(id);
    if (company) {
      db.prepare('UPDATE Director SET company = COALESCE(company, ?) WHERE id = ?').run(company, id);
    }
  }
  count++;
  console.log(`Fixed ID=${id}: romaji=${romaji}, company=${company}`);
}

// Fix near-dupe: ID 279 has company = "kondo Hlroshi" (which is the romaji)
db.prepare('UPDATE Director SET company = NULL WHERE id = 279').run();
console.log('Fixed ID=279: cleared garbage company');

// Fix ID 399 (モンドウユウキ) - duplicate of 338? Check
const d338 = db.prepare('SELECT * FROM Director WHERE id = 338').get();
const d399 = db.prepare('SELECT * FROM Director WHERE id = 399').get();
console.log(`\nID 338: ${d338.name} / ${d338.nameRomaji}`);
console.log(`ID 399: ${d399.name} / ${d399.nameRomaji}`);

// Rebuild FTS
console.log('\nRebuilding FTS5...');
db.exec("INSERT INTO director_fts(director_fts) VALUES('rebuild');");

console.log(`\nFixed: ${count} entries`);
db.close();
