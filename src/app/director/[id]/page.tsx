"use client";

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";

interface Work {
  id: number;
  title: string;
  clientName: string | null;
  productName: string | null;
  agency: string | null;
  year: number | null;
  sourceYear: string;
  youtubeUrl: string | null;
  thumbnailPath: string | null;
}

interface YearSource {
  sourceYear: string;
  sourcePage: number | null;
}

interface ProfileHistory {
  sourceYear: string;
  profile: string;
}

interface DirectorDetail {
  id: number;
  name: string;
  nameRomaji: string | null;
  email: string | null;
  phone: string | null;
  company: string | null;
  profile: string | null;
  portraitImagePath: string | null;
  works: Work[];
  yearSources: YearSource[];
  profileHistories: ProfileHistory[];
}

function getYouTubeId(url: string): string | null {
  const match = url.match(
    /(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})/
  );
  return match ? match[1] : null;
}

export default function DirectorPage() {
  const params = useParams();
  const [director, setDirector] = useState<DirectorDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchDirector() {
      try {
        const res = await fetch(`/api/directors/${params.id}`);
        if (res.ok) {
          setDirector(await res.json());
        }
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    }
    fetchDirector();
  }, [params.id]);

  if (loading) {
    return <div className="text-center py-12 text-gray-500">読み込み中...</div>;
  }

  if (!director) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500 mb-4">監督が見つかりませんでした。</p>
        <Link href="/" className="text-blue-600 hover:underline">
          一覧に戻る
        </Link>
      </div>
    );
  }

  // Group works by year
  const worksByYear = director.works.reduce((acc, w) => {
    const y = w.year?.toString() || "不明";
    if (!acc[y]) acc[y] = [];
    acc[y].push(w);
    return acc;
  }, {} as Record<string, Work[]>);

  const sortedYears = Object.keys(worksByYear).sort((a, b) =>
    b.localeCompare(a)
  );

  return (
    <div>
      <Link
        href="/"
        className="text-blue-600 hover:underline text-sm mb-4 inline-block"
      >
        &larr; 一覧に戻る
      </Link>

      <div className="bg-white rounded-lg border border-gray-200 p-6 mb-6">
        <div className="flex items-start gap-6">
          <div className="w-24 h-24 bg-gray-200 rounded-full flex items-center justify-center text-gray-500 text-3xl shrink-0">
            {director.portraitImagePath ? (
              <img
                src={director.portraitImagePath}
                alt={director.name}
                className="w-24 h-24 rounded-full object-cover"
              />
            ) : (
              director.name[0]
            )}
          </div>
          <div>
            <h1 className="text-3xl font-bold">{director.name}</h1>
            {director.nameRomaji && (
              <p className="text-gray-500 mt-1">{director.nameRomaji}</p>
            )}

            <div className="mt-3 flex flex-wrap gap-2">
              {director.yearSources.map((ys) => (
                <span
                  key={ys.sourceYear}
                  className="bg-blue-100 text-blue-700 px-3 py-1 rounded text-sm"
                >
                  {ys.sourceYear}
                  {ys.sourcePage && ` (p.${ys.sourcePage})`}
                </span>
              ))}
            </div>

            <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
              {director.company && (
                <div>
                  <span className="text-gray-500">所属:</span>{" "}
                  <span className="font-medium">{director.company}</span>
                </div>
              )}
              {director.email && (
                <div>
                  <span className="text-gray-500">Email:</span>{" "}
                  <a
                    href={`mailto:${director.email}`}
                    className="text-blue-600 hover:underline"
                  >
                    {director.email}
                  </a>
                </div>
              )}
              {director.phone && (
                <div>
                  <span className="text-gray-500">TEL:</span>{" "}
                  <a
                    href={`tel:${director.phone}`}
                    className="text-blue-600 hover:underline"
                  >
                    {director.phone}
                  </a>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Profile */}
      {director.profile && (
        <div className="bg-white rounded-lg border border-gray-200 p-6 mb-6">
          <h2 className="text-lg font-bold mb-3">プロフィール</h2>
          <p className="text-gray-700 whitespace-pre-line leading-relaxed">
            {director.profile}
          </p>
        </div>
      )}

      {/* Works */}
      {director.works.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 p-6 mb-6">
          <h2 className="text-lg font-bold mb-4">
            作品一覧 ({director.works.length}件)
          </h2>
          {sortedYears.map((year) => (
            <div key={year} className="mb-6 last:mb-0">
              <h3 className="text-sm font-bold text-gray-500 mb-2 border-b pb-1">
                {year}年
              </h3>
              <div className="space-y-3">
                {worksByYear[year].map((work) => {
                  const ytId = work.youtubeUrl
                    ? getYouTubeId(work.youtubeUrl)
                    : null;
                  return (
                    <div
                      key={work.id}
                      className="border-l-4 border-gray-200 pl-4"
                    >
                      <div className="font-medium">{work.title}</div>
                      {work.clientName && (
                        <div className="text-sm text-gray-600">
                          クライアント: {work.clientName}
                        </div>
                      )}
                      {work.agency && (
                        <div className="text-sm text-gray-500">
                          {work.agency}
                        </div>
                      )}
                      {ytId && (
                        <div className="mt-2">
                          <iframe
                            width="320"
                            height="180"
                            src={`https://www.youtube.com/embed/${ytId}`}
                            title={work.title}
                            allowFullScreen
                            className="rounded"
                          />
                        </div>
                      )}
                      {work.youtubeUrl && !ytId && (
                        <a
                          href={work.youtubeUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-sm text-blue-600 hover:underline mt-1 inline-block"
                        >
                          YouTube で見る
                        </a>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Profile History */}
      {director.profileHistories.length > 1 && (
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h2 className="text-lg font-bold mb-3">プロフィール履歴</h2>
          {director.profileHistories.map((ph) => (
            <div key={ph.sourceYear} className="mb-4 last:mb-0">
              <h3 className="text-sm font-bold text-gray-500 mb-1">
                {ph.sourceYear}
              </h3>
              <p className="text-sm text-gray-600 whitespace-pre-line">
                {ph.profile}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
