const Database = require('better-sqlite3');
const path = require('path');
const dbPath = path.resolve(__dirname, '..', 'prisma', 'dev.db');
const db = new Database(dbPath, { readonly: true });

// 1. Remaining directors without contact, only in 2020-2021
console.log('=== Remaining no-contact directors only in 2020-2021 ===');
const noContact = db.prepare(`
  SELECT d.id, d.name, d.nameRomaji, d.company
  FROM Director d
  WHERE d.email IS NULL AND d.phone IS NULL
    AND d.id IN (SELECT directorId FROM DirectorYearSource WHERE sourceYear = '2020-2021')
    AND d.id NOT IN (SELECT directorId FROM DirectorYearSource WHERE sourceYear != '2020-2021')
  ORDER BY d.id
`).all();
noContact.forEach(d => console.log(d.id + '|' + d.name + '|' + (d.nameRomaji||'') + '|' + (d.company||'')));
console.log('Count:', noContact.length);

// 2. Remaining romaji with non-alpha chars
console.log('\n=== Remaining romaji issues ===');
const all = db.prepare('SELECT id, name, nameRomaji FROM Director WHERE nameRomaji IS NOT NULL').all();
const bad = all.filter(d => {
  if (!d.nameRomaji) return false;
  // Allow: A-Z, a-z, spaces, periods, hyphens, quotes, apostrophes
  return /[^A-Za-z\s.\-'"]/i.test(d.nameRomaji);
});
bad.forEach(d => console.log(d.id + '|' + d.name + '|' + d.nameRomaji));
console.log('Count:', bad.length);

// 3. Overall stats
console.log('\n=== Final stats ===');
const total = db.prepare('SELECT COUNT(*) as c FROM Director').get();
const works = db.prepare('SELECT COUNT(*) as c FROM Work').get();
const withEmail = db.prepare('SELECT COUNT(*) as c FROM Director WHERE email IS NOT NULL').get();
const withPhone = db.prepare('SELECT COUNT(*) as c FROM Director WHERE phone IS NOT NULL').get();
const withProfile = db.prepare("SELECT COUNT(*) as c FROM Director WHERE profile IS NOT NULL AND profile != ''").get();
const withPortrait = db.prepare("SELECT COUNT(*) as c FROM Director WHERE portraitImagePath IS NOT NULL").get();
console.log(`Directors: ${total.c}`);
console.log(`Works: ${works.c}`);
console.log(`With email: ${withEmail.c}`);
console.log(`With phone: ${withPhone.c}`);
console.log(`With profile: ${withProfile.c}`);
console.log(`With portrait: ${withPortrait.c}`);

db.close();
