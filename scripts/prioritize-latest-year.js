/**
 * 最新年度のデータを優先して連絡先・所属・プロフィールを更新する
 * ProfileHistoryから最新年度のプロフィールをDirector.profileに設定
 * DirectorYearSourceの最新年度に基づいてデータを確認
 */
const Database = require('better-sqlite3');
const path = require('path');

const dbPath = path.resolve(__dirname, '..', 'prisma', 'dev.db');
const db = new Database(dbPath);

console.log('=== Prioritizing latest year data for profiles ===');

// Get all directors with profile histories
const directors = db.prepare(`
  SELECT d.id, d.name, d.profile,
    (SELECT MAX(dys.sourceYear) FROM DirectorYearSource dys WHERE dys.directorId = d.id) as latestYear
  FROM Director d
`).all();

const updateProfile = db.prepare('UPDATE Director SET profile = ? WHERE id = ?');

let profileUpdated = 0;
for (const d of directors) {
  if (!d.latestYear) continue;

  // Get the latest profile history
  const latestProfile = db.prepare(`
    SELECT profile FROM DirectorProfileHistory
    WHERE directorId = ? AND sourceYear = ?
  `).get(d.id, d.latestYear);

  if (latestProfile && latestProfile.profile) {
    // Check if current profile differs from latest
    if (d.profile !== latestProfile.profile) {
      updateProfile.run(latestProfile.profile, d.id);
      profileUpdated++;
    }
  }
}
console.log(`Updated ${profileUpdated} profiles to latest year version`);

// Check which directors have data from multiple years
console.log('\n=== Directors with multiple year sources ===');
const multiYear = db.prepare(`
  SELECT d.id, d.name,
    GROUP_CONCAT(dys.sourceYear ORDER BY dys.sourceYear DESC) as years
  FROM Director d
  JOIN DirectorYearSource dys ON dys.directorId = d.id
  GROUP BY d.id
  HAVING COUNT(DISTINCT dys.sourceYear) > 1
  LIMIT 10
`).all();
console.log(`${multiYear.length > 0 ? 'Sample:' : 'None'}`);
multiYear.forEach(d => console.log(`  ${d.id} ${d.name}: ${d.years}`));

// Get total count of multi-year directors
const multiYearCount = db.prepare(`
  SELECT COUNT(*) as c FROM (
    SELECT directorId FROM DirectorYearSource
    GROUP BY directorId HAVING COUNT(DISTINCT sourceYear) > 1
  )
`).get();
console.log(`Total directors with multiple years: ${multiYearCount.c}`);

// Final stats
const total = db.prepare('SELECT COUNT(*) as c FROM Director').get();
const withProfile = db.prepare("SELECT COUNT(*) as c FROM Director WHERE profile IS NOT NULL AND profile != ''").get();
const withContact = db.prepare('SELECT COUNT(*) as c FROM Director WHERE email IS NOT NULL OR phone IS NOT NULL').get();
console.log(`\nFinal: ${total.c} directors, ${withProfile.c} with profile, ${withContact.c} with contact`);

db.close();
console.log('Done!');
