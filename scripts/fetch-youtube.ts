/**
 * YouTube URL取得スクリプト
 * Usage: npx tsx scripts/fetch-youtube.ts --year 2023-2024
 *
 * YOUTUBE_API_KEY が未設定の場合は構造だけ作成してスキップ。
 * 後から再取得可能。
 */
import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

const API_KEY = process.env.YOUTUBE_API_KEY;

interface YouTubeSearchResult {
  items?: Array<{
    id: { videoId: string };
    snippet: { title: string; thumbnails: { medium: { url: string } } };
  }>;
}

async function searchYouTube(query: string): Promise<string | null> {
  if (!API_KEY) return null;

  const url = `https://www.googleapis.com/youtube/v3/search?part=snippet&q=${encodeURIComponent(
    query
  )}&type=video&maxResults=1&key=${API_KEY}`;

  try {
    const res = await fetch(url);
    if (!res.ok) {
      console.error(`YouTube API error: ${res.status}`);
      return null;
    }
    const data: YouTubeSearchResult = await res.json();
    if (data.items && data.items.length > 0) {
      const videoId = data.items[0].id.videoId;
      return `https://www.youtube.com/watch?v=${videoId}`;
    }
  } catch (e) {
    console.error(`YouTube search failed: ${e}`);
  }
  return null;
}

async function fetchYouTubeUrls(year: string) {
  if (!API_KEY) {
    console.log("YOUTUBE_API_KEY not set. Skipping YouTube fetch.");
    console.log("Set YOUTUBE_API_KEY in .env and re-run to fetch YouTube URLs.");
    return;
  }

  const works = await prisma.work.findMany({
    where: {
      sourceYear: year,
      youtubeUrl: null,
    },
    include: {
      director: { select: { name: true } },
    },
  });

  console.log(`Found ${works.length} works without YouTube URLs`);

  let found = 0;
  let notFound = 0;

  for (const work of works) {
    // Search priority:
    // 1. title + director name
    // 2. title + client
    // 3. title only
    const queries = [
      `${work.title} ${work.director.name} CM`,
      work.clientName ? `${work.title} ${work.clientName} CM` : null,
      `${work.title} CM`,
    ].filter(Boolean) as string[];

    let url: string | null = null;
    for (const q of queries) {
      url = await searchYouTube(q);
      if (url) break;
      // Rate limit
      await new Promise((r) => setTimeout(r, 200));
    }

    if (url) {
      await prisma.work.update({
        where: { id: work.id },
        data: { youtubeUrl: url },
      });
      found++;
      console.log(`  Found: ${work.title} → ${url}`);
    } else {
      notFound++;
    }

    // Rate limit between works
    await new Promise((r) => setTimeout(r, 300));
  }

  console.log(`\nResults: ${found} found, ${notFound} not found`);
}

// Parse args
const args = process.argv.slice(2);
let year = "";
for (let i = 0; i < args.length; i++) {
  if (args[i] === "--year" && args[i + 1]) {
    year = args[i + 1];
    break;
  }
}

if (!year) {
  console.error("Usage: npx tsx scripts/fetch-youtube.ts --year 2023-2024");
  process.exit(1);
}

fetchYouTubeUrls(year)
  .then(() => prisma.$disconnect())
  .catch((e) => {
    console.error(e);
    prisma.$disconnect();
    process.exit(1);
  });
