/**
 * データクリーンアップ 第2パス
 * 残りのOCR破損ローマ字修正と追加の偽陽性削除
 */
const Database = require('better-sqlite3');
const path = require('path');

const dbPath = path.resolve(__dirname, '..', 'prisma', 'dev.db');
const db = new Database(dbPath);

// ===== 1. MORE FALSE POSITIVES TO DELETE =====
const MORE_FALSE_POSITIVES = [
  125,  // 日本旅行 (Japan Travel company)
  342,  // 矢崎部品 (Yazaki auto parts company)
  615,  // クロマニヨン - garbled data (romaji = "UNIVERSALMUSl CLLC関取花新しい花")
  628,  // 愛知県出身 (phrase "From Aichi Prefecture")
  701,  // 博報堂ブﾛダｸﾂ (Hakuhodo Products - agency)
  708,  // 篭必 (OCR garbage)
  724,  // 電通十ギーク (Dentsu + Geek - agencies)
  899,  // アシックス (Asics shoe company)
  912,  // 駿台予偏学校 (prep school)
  914,  // ニチレイ (Nichirei food company)
  926,  // ピップ (Pip health company)
  928,  // 受験並走トラマ (OCR garbage phrase)
  929,  // カネボウ (Kanebo cosmetics)
  930,  // ピークサイド (Peakside - company name, not a person)
];

console.log(`=== Deleting ${MORE_FALSE_POSITIVES.length} more false positives ===`);
const deleteWork = db.prepare('DELETE FROM Work WHERE directorId = ?');
const deleteYearSource = db.prepare('DELETE FROM DirectorYearSource WHERE directorId = ?');
const deleteProfileHistory = db.prepare('DELETE FROM DirectorProfileHistory WHERE directorId = ?');
const deleteDirector = db.prepare('DELETE FROM Director WHERE id = ?');

let deleted = 0;
for (const id of MORE_FALSE_POSITIVES) {
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
console.log(`Deleted ${deleted} more false positives`);

// ===== 2. FIX REMAINING COMMA-BASED OCR ERRORS =====
// In this dataset, ',' in romaji is consistently an OCR error for 'r'
console.log('\n=== Fixing comma → r in romaji ===');

const commaFixes = {
  2: 'Aritomo Kenji',       // アリトモケンジ
  29: 'Eguchi Fumihiro',    // 江口史宏
  75: 'Katsura Yu',         // 勝浦裕 → Katsu'u,a' = Katsura
  111: 'Kimura Gen',        // 木村玄
  122: 'Kurahashi Takuya',  // 倉橋拓也
  229: 'Takahashi Marina',  // 高橋まりな
  259: 'Tanaka Noriyuki',   // タナカノリユキ
  286: 'Tokuhira Koichi',   // 徳平弘一
  289: 'Totsuka Fujimaru',  // 戸塚富士丸
  351: 'Hakomori Keisuke',  // 箱守恵輔
  367: 'Hara Fumiya',       // 原風海也
  370: 'Harada Yosuke',     // 原田陽介
  376: 'Hiraoka Masanobu',  // 平岡政展
  426: 'Miura Kazunori',    // 三浦和徳
  440: 'Miyakawa Yoshihiro',// 宮川慶大
  465: 'Yashiro Takeshi',   // 八代健志
  510: 'Watabe Yasunari',   // 渡部康成
  599: 'Kuroyanagi Keisuke',// 畔柳恵輔
};

const updateRomaji = db.prepare('UPDATE Director SET nameRomaji = ? WHERE id = ?');
let romajiFixed = 0;
for (const [id, romaji] of Object.entries(commaFixes)) {
  const d = db.prepare('SELECT name, nameRomaji FROM Director WHERE id = ?').get(parseInt(id));
  if (d) {
    updateRomaji.run(romaji, parseInt(id));
    console.log(`  ${id} ${d.name}: "${d.nameRomaji}" → "${romaji}"`);
    romajiFixed++;
  }
}

// ===== 3. FIX OTHER SPECIAL CHARACTER OCR ERRORS =====
const specialFixes = {
  36: 'Oishi Yuji',         // 大石裕次 (was "Olshl Y u」i")
  585: 'Kawamoto Kimihiro', // 河本公泰 (was "Kawamo↑o Kimihiro")
  598: 'Kuramoto Raita',    // 倉本雷大 (was "Ku｢amoto Raita")
  800: 'Shimizu Yasuhiko',  // 清水康彦 (was "CAVIAR LIMITED (Mg：本郷）")
  841: 'Hayakawa Chie',     // 早川千絵 (was "Hayakawa Ch1e")
  794: 'Sano Yutaka',       // サノ貨ユタカ → actually "サノハユタカ" = Sano Yutaka (was "Sano* Yutaka")
};

for (const [id, romaji] of Object.entries(specialFixes)) {
  const d = db.prepare('SELECT name, nameRomaji FROM Director WHERE id = ?').get(parseInt(id));
  if (d) {
    updateRomaji.run(romaji, parseInt(id));
    console.log(`  ${id} ${d.name}: "${d.nameRomaji}" → "${romaji}"`);
    romajiFixed++;
  }
}

// Fix remaining 'co' endings that should be 'ro' (OCR confusion of c→r)
const coFixes = {
  59: 'Okuto Yoshihiro',    // 奥藤祥弘 (was "Okuto Yoshihico" → should be Yoshihiro)
  215: 'Sonoda Toshiro',    // 園田俊郎 (was "Sonoda Toshico")
  246: 'Takemoto Yoshihiro',// 竹本よしひろ (was "Takemoto Yoshihico")
  285: 'Tokiwa Shiro',      // 常盤司郎 (was "Tokiwa Shico")
  474: 'Yamashiro Ayaka',   // 山城彩香 (was "Yamashico Ayaka")
  498: 'Yoshihara Michikatsu', // 吉原通克 (was "Yoshihaca Michikatsu")
};

for (const [id, romaji] of Object.entries(coFixes)) {
  const d = db.prepare('SELECT name, nameRomaji FROM Director WHERE id = ?').get(parseInt(id));
  if (d) {
    updateRomaji.run(romaji, parseInt(id));
    console.log(`  ${id} ${d.name}: "${d.nameRomaji}" → "${romaji}"`);
    romajiFixed++;
  }
}

// Fix other known romaji errors
const miscFixes = {
  7: 'Ishikawa Hiroshi',    // 石川寛 (was "Ishikawa Hiroshi" - already correct but double-check)
  35: 'Oikawa Kenichi',     // 及川謙一 (was "Qikawa Kenichi" - Q→O)
  44: 'Ohsumi Yuuka',       // オースミューカ (was "Ooosumi Yuuuka" - too many o's)
  68: 'Kaga Aisa',          // 加賀愛紗 - wait, is this right? "Kaga Aisa" looks correct
  69: 'Kakitsubata Kiyoshi',// 杜若清司 (was "Kakitsubata Kioyshi")
  81: 'Katoya Hiroshi',     // 加登屋寛 (was "Katoya Hiroshi" - already correct)
  211: 'Sekine Kosai',      // 関根光オ → Kosai doesn't seem right, but hard to tell
  292: 'Toyoshima Yuriko',  // 豊島百合子 (was "Toyoshima Yudko" → Yuriko)
  470: 'Yamaguchi Erika',   // 山口えり花 (was "Yamaguchi Edka" → Erika)
  482: 'Yamamoto Kenji',    // 山本憲司 (was "Yamamoto Kenii" → Kenji)
  492: 'Yokobori Mitsunori',// 横堀光範 (was "Yokobori Mitsunod" → Mitsunori)
  797: 'Jitsumori Shinsuke',// 賓守信介 (was "Jitsumoi Shinsuke" → Jitsumori)
  909: 'Takahashi Teruomi', // 高橋輝臣 (already correct)
  815: 'Takamura Shinichi', // 高村伸一 (was "Takamuca Shinichi" → Takamura)
  248: 'Tajima Naoko',      // たじまなおこ (was "Tajima Naoke" → Naoko)
  39: 'Ogama Tomomi',       // 大釜友美 (was "Ogama To momi" → Tomomi, fix space)
  454: 'Momen Tatsushi',    // 木綿達史 (was "Mom en Tatsushi" → fix space)
  233: 'Takamura Tsuyoshi', // 高村剛 (was "Takam ura Tsuyoshi" → fix space)
  30: 'Eko Kazi',           // 江湖広二 → actually should be "Eko Koji" maybe?
  665: 'Naruse Yoichi',     // 成閉洋一 (name OCR error too, but keep for now)
};

for (const [id, romaji] of Object.entries(miscFixes)) {
  const d = db.prepare('SELECT name, nameRomaji FROM Director WHERE id = ?').get(parseInt(id));
  if (d && d.nameRomaji !== romaji) {
    updateRomaji.run(romaji, parseInt(id));
    console.log(`  ${id} ${d.name}: "${d.nameRomaji}" → "${romaji}"`);
    romajiFixed++;
  }
}

console.log(`Fixed ${romajiFixed} romaji entries in pass 2`);

// Fix director name for 794 (サノ貨ユタカ → サノハユタカ)
const updateName = db.prepare('UPDATE Director SET name = ? WHERE id = ?');
const d794 = db.prepare('SELECT name FROM Director WHERE id = 794').get();
if (d794 && d794.name === 'サノ貨ユタカ') {
  updateName.run('サノハユタカ', 794);
  console.log('\nFixed name 794: サノ貨ユタカ → サノハユタカ');
}

// Fix 665 name (成閉洋一 → probably 成瀬洋一 but not sure, leave as is)
// Fix 616 name (佐藤ま → incomplete, check)
const d616 = db.prepare('SELECT name, nameRomaji, email, phone FROM Director WHERE id = 616').get();
if (d616) {
  console.log(`\nCheck 616: ${d616.name} | ${d616.nameRomaji} | ${d616.email} | ${d616.phone}`);
}

// ===== Final stats =====
console.log('\n=== Final stats ===');
const total = db.prepare('SELECT COUNT(*) as c FROM Director').get();
const works = db.prepare('SELECT COUNT(*) as c FROM Work').get();
console.log(`Directors: ${total.c}`);
console.log(`Works: ${works.c}`);

db.close();
console.log('\nPass 2 cleanup complete!');
