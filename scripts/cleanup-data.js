/**
 * データ品質クリーンアップスクリプト
 * 1. 明らかに監督ではないエントリを削除
 * 2. OCR破損ローマ字を修正
 * 3. 壊れた作品データを修正/削除
 */
const Database = require('better-sqlite3');
const path = require('path');

const dbPath = path.resolve(__dirname, '..', 'prisma', 'dev.db');
const db = new Database(dbPath);

// ===== 1. FALSE POSITIVE DIRECTORS TO DELETE =====
// These are clearly not director names (companies, products, phrases, OCR garbage)
const FALSE_POSITIVE_IDS = [
  34,   // スクウェア・エニックス (game company)
  647,  // タカラトミーぷにるんす (toy company + product)
  666,  // 本田技研工業ヴｪゼﾙ (Honda Vezel)
  737,  // 四十住さくら / "Google LLC Google アプリ" (data completely mixed)
  746,  // 歌う (verb "to sing")
  759,  // トレーニング (word "training")
  760,  // ・ロ (OCR garbage)
  762,  // 恩返しです (phrase)
  764,  // 住友化学企業 (Sumitomo Chemical)
  769,  // 大滝詠一 (musician, not director)
  771,  // 天使のはね (product name)
  772,  // セザンヌ化粧品 (cosmetics company)
  774,  // ダイワポウ情報システム (IT company)
  789,  // このやまコーヒー (coffee brand)
  791,  // 首都医校 (school)
  792,  // お気軽にご相談ください (phrase)
  795,  // コーセー (Kosé cosmetics)
  798,  // 企業 (word "company")
  804,  // パルテラマ (brand name)
  810,  // ミュージック (word "music")
  821,  // 日本郵便 (Japan Post)
  824,  // テイレクターテビュー (OCR of "ディレクターデビュー")
  828,  // シグマ (SIGMA camera company)
  832,  // ・コーラ (fragment of Coca-Cola)
  838,  // ユニパーサルミュージック (Universal Music)
  848,  // 御幸毛織 (fabric company)
  850,  // ライトバブリシティ (Light Publicity company)
  858,  // 見る人の心に届くものを (phrase)
  860,  // 作品を観た人が笑顔になる (phrase)
  861,  // ネスカフェエクセラ (Nescafe product)
  865,  // 青・黄・赤 (colors "blue/yellow/red")
  867,  // アイダ設計 (construction company)
  873,  // ボラス / "ADK MS/navy" (agency data)
  874,  // 三井住友トラストクラプ (financial company)
  876,  // カネポウ化粧品 (Kanebo cosmetics)
  885,  // コースにしか入 (sentence fragment)
  888,  // ヒグチアイ / "DRAWING AND MANUAL" (singer, not director, wrong data)
  896,  // 女王蜂 / "Sony Moslc Labels" (band name)
  898,  // シナぷしゅ / "DRAWING AND MANUAL" (TV show)
  903,  // フレイアクリニック (clinic)
  907,  // グーグル (Google)
  908,  // 在宅自己注射がある日常 (phrase)
  910,  // おいおい追いがつお (product/catchphrase)
  913,  // 三和酒類 (alcohol company)
  915,  // 本田技研工業 (Honda Motor)
  920,  // キッズステーション (TV channel)
  923,  // 全力でがんばります (phrase)
  925,  // ウィルピークリニック (clinic)
];

console.log(`=== Deleting ${FALSE_POSITIVE_IDS.length} false positive directors ===`);
const deleteWork = db.prepare('DELETE FROM Work WHERE directorId = ?');
const deleteYearSource = db.prepare('DELETE FROM DirectorYearSource WHERE directorId = ?');
const deleteProfileHistory = db.prepare('DELETE FROM DirectorProfileHistory WHERE directorId = ?');
const deleteDirector = db.prepare('DELETE FROM Director WHERE id = ?');

let deleted = 0;
for (const id of FALSE_POSITIVE_IDS) {
  const d = db.prepare('SELECT name FROM Director WHERE id = ?').get(id);
  if (d) {
    deleteWork.run(id);
    deleteYearSource.run(id);
    deleteProfileHistory.run(id);
    deleteDirector.run(id);
    console.log(`  Deleted: ${id} ${d.name}`);
    deleted++;
  }
}
console.log(`Deleted ${deleted} false positive directors`);

// ===== 2. FIX OCR-DAMAGED ROMAJI =====
console.log('\n=== Fixing OCR-damaged romaji ===');

function fixRomaji(romaji) {
  if (!romaji) return romaji;
  let fixed = romaji;

  // Fix semicolons → 'i' (most common OCR error in this dataset)
  // Pattern: character followed by ; at word boundary or end
  fixed = fixed.replace(/;/g, 'i');

  // Fix trailing '1' → 'i' (e.g., "Natsuk1" → "Natsuki", "Masash1" → "Masashi")
  fixed = fixed.replace(/1(?=\s|$)/g, 'i');

  // Fix '9' in middle of name → 'g' (e.g., "Shin9u" → "Shingu")
  fixed = fixed.replace(/(?<=[a-zA-Z])9(?=[a-zA-Z])/g, 'g');

  // Fix fullwidth katakana middle dots → quotes for nicknames
  fixed = fixed.replace(/ｷ/g, '"');

  // Fix ',n' → 'in' at end of word
  fixed = fixed.replace(/,n(?=\s|$)/g, 'in');

  // Fix trailing ',' → 'i' (e.g., "Takesh," → "Takeshi")
  fixed = fixed.replace(/,(?=\s|$)/g, 'i');

  // Fix 'J,n' → 'Jin'
  fixed = fixed.replace(/J,n/g, 'Jin');

  // Fix 'Nacke' → 'Naoko' (specific known case)
  // Actually this is more complex, skip specific fixes

  // Fix 'h;' patterns already handled by semicolon fix

  // Fix 'Yudko' → 'Yuriko' - too specific, skip

  // Fix 'Edka' → 'Erika' - too specific

  // Fix common OCR patterns
  fixed = fixed.replace(/Hicoak/g, 'Hiroak');
  fixed = fixed.replace(/Hicotak/g, 'Hirotak');
  fixed = fixed.replace(/Hicosh/g, 'Hirosh');
  fixed = fixed.replace(/Yosh;h;co/g, 'Yoshihiro');
  fixed = fixed.replace(/Kucoda/g, 'Kuroda');
  fixed = fixed.replace(/Masahacu/g, 'Masaharu');
  fixed = fixed.replace(/Watacu/g, 'Wataru');
  fixed = fixed.replace(/Sugurn/g, 'Suguru');
  fixed = fixed.replace(/Tosh;co/g, 'Toshiro');
  fixed = fixed.replace(/Hicoshi/g, 'Hiroshi');
  fixed = fixed.replace(/Hoduch/g, 'Horiuch');
  fixed = fixed.replace(/Moduch/g, 'Moriuch');
  fixed = fixed.replace(/Modta/g, 'Morita');
  fixed = fixed.replace(/Modgak/g, 'Morigak');
  fixed = fixed.replace(/Imamuca/g, 'Imamura');
  fixed = fixed.replace(/Nomuca/g, 'Nomura');
  fixed = fixed.replace(/Tecuyo/g, 'Teruyo');
  fixed = fixed.replace(/Tecuom/g, 'Teruom');
  fixed = fixed.replace(/Nack/g, 'Naok');
  fixed = fixed.replace(/Kazunod/g, 'Kazunori');
  fixed = fixed.replace(/Yokobod/g, 'Yokobori');
  fixed = fixed.replace(/Kodam a/g, 'Kodama');
  fixed = fixed.replace(/Ko mod/g, 'Komori');
  fixed = fixed.replace(/Sh 』ngo/g, 'Shingo');
  fixed = fixed.replace(/Nodyoshi/g, 'Noriyoshi');
  fixed = fixed.replace(/Naka Iima/g, 'Nakajima');
  fixed = fixed.replace(/Ke;suke/g, 'Keisuke');
  fixed = fixed.replace(/Ha Jimex/g, 'Hajime');
  fixed = fixed.replace(/Shu he/g, 'Shuhe');
  fixed = fixed.replace(/Tai J,n/g, 'Taijin');
  fixed = fixed.replace(/Edko/g, 'Eriko');
  fixed = fixed.replace(/Kosa/g, 'Kosa');

  // Clean up double spaces
  fixed = fixed.replace(/\s+/g, ' ').trim();

  return fixed;
}

const allDirs = db.prepare('SELECT id, nameRomaji FROM Director WHERE nameRomaji IS NOT NULL').all();
const updateRomaji = db.prepare('UPDATE Director SET nameRomaji = ? WHERE id = ?');
let romajiFixed = 0;

for (const d of allDirs) {
  const fixed = fixRomaji(d.nameRomaji);
  if (fixed !== d.nameRomaji) {
    updateRomaji.run(fixed, d.id);
    console.log(`  ${d.id}: "${d.nameRomaji}" → "${fixed}"`);
    romajiFixed++;
  }
}
console.log(`Fixed ${romajiFixed} romaji entries`);

// ===== 3. FIX COMPANY FIELDS THAT CONTAIN ONLY EMAIL ADDRESSES =====
console.log('\n=== Fixing company fields with email addresses ===');

// For directors where company field looks like just an email, move it or clear it
const emailCompanyDirs = db.prepare(`
  SELECT id, name, company, email
  FROM Director
  WHERE company IS NOT NULL
    AND company LIKE '%@%'
    AND company NOT LIKE '%（%'
    AND company NOT LIKE '%(Mg%'
    AND length(company) < 50
`).all();

const updateCompany = db.prepare('UPDATE Director SET company = ? WHERE id = ?');
const updateEmail = db.prepare('UPDATE Director SET email = ? WHERE id = ?');

let companyFixed = 0;
for (const d of emailCompanyDirs) {
  // If company is purely an email, and director doesn't have email, use it as email
  const emailMatch = d.company.match(/^([a-zA-Z0-9._+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]+)$/);
  if (emailMatch) {
    if (!d.email) {
      updateEmail.run(emailMatch[1], d.id);
    }
    updateCompany.run(null, d.id);
    console.log(`  ${d.id} ${d.name}: company "${d.company}" → email`);
    companyFixed++;
  }
}
console.log(`Fixed ${companyFixed} company fields`);

// ===== 4. CLEAN UP GARBLED WORKS =====
console.log('\n=== Checking works with profile text in client/agency fields ===');

// Remove works where clientName contains profile-like text
const badWorks = db.prepare(`
  SELECT w.id, w.directorId, w.title, w.clientName, w.agency, d.name
  FROM Work w
  JOIN Director d ON d.id = w.directorId
  WHERE w.clientName LIKE '%ください%'
    OR w.clientName LIKE '%お待ち%'
    OR w.clientName LIKE '%大歓迎%'
    OR w.clientName LIKE '%お問い合わせ%'
    OR w.clientName LIKE '%心がけて%'
    OR w.clientName LIKE '%連絡ください%'
    OR w.clientName LIKE '%お任せ%'
    OR w.clientName LIKE '%民族音楽%'
`).all();

const updateWork = db.prepare('UPDATE Work SET clientName = NULL WHERE id = ?');
for (const w of badWorks) {
  console.log(`  Work ${w.id} (${w.name}): clearing garbled clientName "${w.clientName}"`);
  updateWork.run(w.id);
}
console.log(`Cleaned ${badWorks.length} works with garbled client names`);

// ===== 5. FIX HALF-WIDTH KATAKANA IN WORK TITLES =====
console.log('\n=== Fixing half-width katakana in work titles ===');

const hwKataMap = {
  'ｱ': 'ア', 'ｲ': 'イ', 'ｳ': 'ウ', 'ｴ': 'エ', 'ｵ': 'オ',
  'ｶ': 'カ', 'ｷ': 'キ', 'ｸ': 'ク', 'ｹ': 'ケ', 'ｺ': 'コ',
  'ｻ': 'サ', 'ｼ': 'シ', 'ｽ': 'ス', 'ｾ': 'セ', 'ｿ': 'ソ',
  'ﾀ': 'タ', 'ﾁ': 'チ', 'ﾂ': 'ツ', 'ﾃ': 'テ', 'ﾄ': 'ト',
  'ﾅ': 'ナ', 'ﾆ': 'ニ', 'ﾇ': 'ヌ', 'ﾈ': 'ネ', 'ﾉ': 'ノ',
  'ﾊ': 'ハ', 'ﾋ': 'ヒ', 'ﾌ': 'フ', 'ﾍ': 'ヘ', 'ﾎ': 'ホ',
  'ﾏ': 'マ', 'ﾐ': 'ミ', 'ﾑ': 'ム', 'ﾒ': 'メ', 'ﾓ': 'モ',
  'ﾔ': 'ヤ', 'ﾕ': 'ユ', 'ﾖ': 'ヨ',
  'ﾗ': 'ラ', 'ﾘ': 'リ', 'ﾙ': 'ル', 'ﾚ': 'レ', 'ﾛ': 'ロ',
  'ﾜ': 'ワ', 'ﾝ': 'ン',
  'ﾞ': '゛', 'ﾟ': '゜',
  'ﾞ': '゛',
  '｢': '「', '｣': '」',
  'ｰ': 'ー', '､': '、', '｡': '。',
  'ｯ': 'ッ', 'ｬ': 'ャ', 'ｭ': 'ュ', 'ｮ': 'ョ',
  'ﾟ': '゜', 'ﾞ': '゛',
  'ｧ': 'ァ', 'ｨ': 'ィ', 'ｩ': 'ゥ', 'ｪ': 'ェ', 'ｫ': 'ォ',
};

function fixHalfWidthKatakana(text) {
  if (!text) return text;
  let fixed = text;
  for (const [hw, fw] of Object.entries(hwKataMap)) {
    fixed = fixed.split(hw).join(fw);
  }
  // Fix dakuten combinations
  fixed = fixed.replace(/カ゛/g, 'ガ').replace(/キ゛/g, 'ギ').replace(/ク゛/g, 'グ')
    .replace(/ケ゛/g, 'ゲ').replace(/コ゛/g, 'ゴ')
    .replace(/サ゛/g, 'ザ').replace(/シ゛/g, 'ジ').replace(/ス゛/g, 'ズ')
    .replace(/セ゛/g, 'ゼ').replace(/ソ゛/g, 'ゾ')
    .replace(/タ゛/g, 'ダ').replace(/チ゛/g, 'ヂ').replace(/ツ゛/g, 'ヅ')
    .replace(/テ゛/g, 'デ').replace(/ト゛/g, 'ド')
    .replace(/ハ゛/g, 'バ').replace(/ヒ゛/g, 'ビ').replace(/フ゛/g, 'ブ')
    .replace(/ヘ゛/g, 'ベ').replace(/ホ゛/g, 'ボ')
    .replace(/パ゜/g, 'パ').replace(/ピ゜/g, 'ピ').replace(/プ゜/g, 'プ')
    .replace(/ペ゜/g, 'ペ').replace(/ポ゜/g, 'ポ');
  // Fix 'l' → 'I' in English words within titles (common OCR error)
  fixed = fixed.replace(/(?<=[A-Z])l(?=[A-Z])/g, 'I');
  return fixed;
}

const allWorks = db.prepare('SELECT id, title, clientName, agency FROM Work').all();
const updateWorkTitle = db.prepare('UPDATE Work SET title = ? WHERE id = ?');
const updateWorkClient = db.prepare('UPDATE Work SET clientName = ? WHERE id = ?');
const updateWorkAgency = db.prepare('UPDATE Work SET agency = ? WHERE id = ?');

let worksFixed = 0;
for (const w of allWorks) {
  let changed = false;
  const fixedTitle = fixHalfWidthKatakana(w.title);
  const fixedClient = fixHalfWidthKatakana(w.clientName);
  const fixedAgency = fixHalfWidthKatakana(w.agency);

  if (fixedTitle !== w.title) {
    updateWorkTitle.run(fixedTitle, w.id);
    changed = true;
  }
  if (fixedClient !== w.clientName) {
    updateWorkClient.run(fixedClient, w.id);
    changed = true;
  }
  if (fixedAgency !== w.agency) {
    updateWorkAgency.run(fixedAgency, w.id);
    changed = true;
  }
  if (changed) worksFixed++;
}
console.log(`Fixed half-width katakana in ${worksFixed} works`);

// ===== 6. ADDITIONAL SUSPICIOUS DIRECTORS FROM 2020-2021 =====
// Check for more false positives that slipped through
console.log('\n=== Additional suspicious entries ===');
const additionalSuspicious = db.prepare(`
  SELECT d.id, d.name, d.nameRomaji, d.email, d.phone
  FROM Director d
  WHERE d.email IS NULL AND d.phone IS NULL
    AND d.id NOT IN (${FALSE_POSITIVE_IDS.join(',')})
    AND (
      d.name LIKE '%化粧品%' OR d.name LIKE '%工業%' OR d.name LIKE '%企業%'
      OR d.name LIKE '%株式%' OR d.name LIKE '%クリニック%' OR d.name LIKE '%ステーション%'
    )
  ORDER BY d.id
`).all();
additionalSuspicious.forEach(d => console.log(`  ${d.id} ${d.name} | ${d.nameRomaji}`));

// ===== FINAL STATS =====
console.log('\n=== Final stats ===');
const finalCount = db.prepare('SELECT COUNT(*) as c FROM Director').get();
const finalWorks = db.prepare('SELECT COUNT(*) as c FROM Work').get();
console.log(`Directors: ${finalCount.c}`);
console.log(`Works: ${finalWorks.c}`);

db.close();
console.log('\nCleanup complete!');
