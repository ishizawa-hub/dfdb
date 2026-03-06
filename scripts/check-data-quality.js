const Database = require('better-sqlite3');
const db = new Database('prisma/dev.db', { readonly: true });

// Get all directors from 2020-2021 without email/phone
console.log('=== 2020-2021 directors without contact info ===');
const dirs2020 = db.prepare(`
  SELECT d.id, d.name, d.nameRomaji, d.company, d.email, d.phone
  FROM Director d
  JOIN DirectorYearSource dys ON dys.directorId = d.id
  WHERE dys.sourceYear = '2020-2021'
    AND d.email IS NULL
    AND d.phone IS NULL
  ORDER BY d.id
`).all();
dirs2020.forEach(d => console.log(d.id + '|' + d.name + '|' + (d.nameRomaji||'') + '|' + (d.company||'')));
console.log('Count:', dirs2020.length);

console.log('\n=== ALL directors with OCR damaged romaji (semicolons, numbers) ===');
const allDirs = db.prepare('SELECT id, name, nameRomaji, email, phone, company FROM Director WHERE nameRomaji IS NOT NULL ORDER BY id').all();
const ocrDamaged = [];
allDirs.forEach(d => {
  const r = d.nameRomaji;
  if (r.includes(';') || r.match(/[0-9]/) || r.includes('ｷ') || r.includes('|')) {
    ocrDamaged.push(d);
  }
});
ocrDamaged.forEach(d => console.log(d.id + '|' + d.name + '|' + d.nameRomaji + '|' + (d.email||'') + '|' + (d.phone||'')));
console.log('Count:', ocrDamaged.length);

console.log('\n=== Directors ONLY in 2020-2021 (not in other years) ===');
const only2020 = db.prepare(`
  SELECT d.id, d.name, d.nameRomaji, d.company, d.email, d.phone,
    (SELECT COUNT(*) FROM DirectorYearSource dys WHERE dys.directorId = d.id) as yearCount,
    (SELECT GROUP_CONCAT(dys.sourceYear) FROM DirectorYearSource dys WHERE dys.directorId = d.id) as years
  FROM Director d
  WHERE d.id IN (
    SELECT directorId FROM DirectorYearSource WHERE sourceYear = '2020-2021'
  )
  AND d.id NOT IN (
    SELECT directorId FROM DirectorYearSource WHERE sourceYear != '2020-2021'
  )
  AND d.email IS NULL AND d.phone IS NULL
  ORDER BY d.id
`).all();
only2020.forEach(d => console.log(d.id + '|' + d.name + '|' + (d.nameRomaji||'') + '|' + (d.company||'')));
console.log('Count:', only2020.length);

console.log('\n=== Works with garbled data ===');
const works = db.prepare(`
  SELECT w.id, w.directorId, w.title, w.clientName, w.agency, w.sourceYear, d.name as directorName
  FROM Work w
  JOIN Director d ON d.id = w.directorId
  WHERE w.title LIKE '%|%' OR w.title LIKE '%ﾉ%' OR w.title LIKE '%ﾎ%'
    OR w.clientName LIKE '%連絡%' OR w.clientName LIKE '%ください%'
    OR length(w.title) > 80
  ORDER BY w.id
`).all();
works.forEach(w => console.log(w.id + '|' + w.directorName + '|' + w.title + '|' + (w.clientName||'')));
console.log('Count:', works.length);

db.close();
