const Database = require('better-sqlite3');
const path = require('path');
const db = new Database(path.join(__dirname, '..', 'prisma', 'dev.db'), { readonly: true });

const dirs = db.prepare('SELECT id, name, nameRomaji, company FROM Director WHERE nameRomaji IS NOT NULL ORDER BY nameRomaji').all();

const companyKw = ['FILM', 'GLASS', 'DRAW', 'MANUAL', 'CINQ', 'PICS', 'ROBOT', 'GUILD',
  'TYO', 'STINK', 'SPEC', 'AOI', 'TRACK', 'VSQ', 'ONDO', 'CYAN', 'BIS', 'FMX',
  'LAB', 'ENDOJI', 'SOURSOX', 'CONNECTION', 'MANAGEMENT', 'FIELD', 'EPOCH', 'EXPAND',
  'VILLAGE', 'PRODUCTION', 'INC', 'LTD', 'CREATIVE'];

const bad = dirs.filter(d => {
  const r = (d.nameRomaji || '').toUpperCase();
  return companyKw.some(kw => r.includes(kw)) || r.includes('（') || r.includes('代表');
});

console.log('Company-like romaji (' + bad.length + '):');
for (const d of bad) {
  console.log(`  ID=${d.id} name=[${d.name}] romaji=[${d.nameRomaji}] company=[${d.company}]`);
}

// Also fix: set romaji to NULL for these
console.log('\n--- Will clear romaji for these directors ---');

db.close();
