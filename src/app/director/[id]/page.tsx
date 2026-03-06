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
  website: string | null;
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

function youtubeSearchUrl(work: Work, directorName: string): string {
  const parts = [
    work.clientName || "",
    work.title,
    directorName,
    "CM",
  ].filter(Boolean);
  return `https://www.youtube.com/results?search_query=${encodeURIComponent(parts.join(" "))}`;
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
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-8 h-8 border-4 border-gray-300 border-t-blue-500 rounded-full animate-spin" />
      </div>
    );
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

  // Group works by sourceYear
  const worksByYear = director.works.reduce(
    (acc, w) => {
      const key = w.sourceYear;
      if (!acc[key]) acc[key] = [];
      acc[key].push(w);
      return acc;
    },
    {} as Record<string, Work[]>
  );

  const sortedYears = Object.keys(worksByYear).sort((a, b) =>
    b.localeCompare(a)
  );

  return (
    <div className="max-w-5xl mx-auto">
      <Link
        href="/"
        className="text-gray-500 hover:text-gray-800 text-sm mb-4 inline-flex items-center gap-1"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
        一覧に戻る
      </Link>

      {/* Hero Card */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden mb-6">
        <div className="bg-gradient-to-r from-gray-800 to-gray-700 px-6 py-8 sm:px-8">
          <div className="flex items-start gap-5">
            <div className="w-28 h-28 rounded-lg overflow-hidden bg-gray-600 shrink-0 border-2 border-white/20">
              {director.portraitImagePath ? (
                <img
                  src={director.portraitImagePath}
                  alt={director.name}
                  className="w-full h-full object-cover"
                />
              ) : (
                <div className="w-full h-full flex items-center justify-center text-white/60 text-4xl font-bold">
                  {director.name[0]}
                </div>
              )}
            </div>
            <div className="min-w-0">
              <h1 className="text-3xl font-bold text-white">{director.name}</h1>
              {director.nameRomaji && (
                <p className="text-gray-300 mt-1 text-lg">{director.nameRomaji}</p>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                {director.yearSources.map((ys) => (
                  <span
                    key={ys.sourceYear}
                    className="bg-white/15 text-white px-3 py-0.5 rounded-full text-sm backdrop-blur-sm"
                  >
                    {ys.sourceYear}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Contact Info */}
        <div className="px-6 py-4 sm:px-8 grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm border-b border-gray-100">
          {director.company && (
            <div>
              <div className="text-gray-400 text-xs mb-0.5">所属</div>
              <div className="font-medium">{director.company}</div>
            </div>
          )}
          {director.email && (
            <div>
              <div className="text-gray-400 text-xs mb-0.5">Email</div>
              <a href={`mailto:${director.email}`} className="text-blue-600 hover:underline break-all">
                {director.email}
              </a>
            </div>
          )}
          {director.phone && (
            <div>
              <div className="text-gray-400 text-xs mb-0.5">TEL</div>
              <a href={`tel:${director.phone}`} className="text-blue-600 hover:underline">
                {director.phone}
              </a>
            </div>
          )}
          {director.website && (
            <div>
              <div className="text-gray-400 text-xs mb-0.5">Webサイト</div>
              <a href={director.website} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline break-all">
                {director.website.replace(/^https?:\/\//, '')}
              </a>
            </div>
          )}
        </div>

        {/* Profile */}
        {director.profile && (
          <div className="px-6 py-4 sm:px-8">
            <p className="text-gray-700 whitespace-pre-line leading-relaxed text-sm">
              {director.profile}
            </p>
          </div>
        )}
      </div>

      {/* Works */}
      {director.works.length > 0 && (
        <div className="mb-6">
          <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
            作品一覧
            <span className="text-sm font-normal text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full">
              {director.works.length}件
            </span>
          </h2>

          {sortedYears.map((sourceYear) => (
            <div key={sourceYear} className="mb-8 last:mb-0">
              <h3 className="text-sm font-bold text-gray-500 mb-3 uppercase tracking-wider border-b border-gray-200 pb-2">
                {sourceYear}
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {worksByYear[sourceYear].map((work) => {
                  const ytId = work.youtubeUrl
                    ? getYouTubeId(work.youtubeUrl)
                    : null;
                  const searchUrl = youtubeSearchUrl(work, director.name);

                  return (
                    <div
                      key={work.id}
                      className="bg-white rounded-lg border border-gray-200 overflow-hidden hover:shadow-md transition-shadow"
                    >
                      {/* Thumbnail */}
                      {work.thumbnailPath ? (
                        <div className="aspect-video bg-gray-100 overflow-hidden">
                          <img
                            src={work.thumbnailPath}
                            alt={work.title}
                            className="w-full h-full object-cover"
                          />
                        </div>
                      ) : ytId ? (
                        <div className="aspect-video">
                          <iframe
                            width="100%"
                            height="100%"
                            src={`https://www.youtube.com/embed/${ytId}`}
                            title={work.title}
                            allowFullScreen
                            className="w-full h-full"
                          />
                        </div>
                      ) : (
                        <div className="aspect-video bg-gray-50 flex items-center justify-center">
                          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" className="text-gray-300">
                            <rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/>
                            <line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/>
                            <line x1="2" y1="12" x2="22" y2="12"/><line x1="2" y1="7" x2="22" y2="7"/>
                            <line x1="2" y1="17" x2="22" y2="17"/>
                          </svg>
                        </div>
                      )}

                      <div className="p-3">
                        <div className="font-medium text-sm leading-tight mb-1 line-clamp-2">
                          {work.title}
                        </div>
                        {work.clientName && (
                          <div className="text-xs text-gray-500 mb-1">
                            {work.clientName}
                          </div>
                        )}
                        {work.agency && (
                          <div className="text-xs text-gray-400 truncate">
                            {work.agency}
                          </div>
                        )}
                        {work.year != null && work.year > 0 && (
                          <div className="text-xs text-gray-400 mt-1">{work.year}</div>
                        )}

                        {/* YouTube links */}
                        <div className="mt-2 flex gap-2 flex-wrap">
                          {work.youtubeUrl ? (
                            <a
                              href={work.youtubeUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-xs bg-red-50 text-red-600 px-2 py-1 rounded hover:bg-red-100 transition-colors"
                            >
                              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>
                              YouTube
                            </a>
                          ) : (
                            <a
                              href={searchUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-xs bg-gray-50 text-gray-500 px-2 py-1 rounded hover:bg-gray-100 transition-colors"
                            >
                              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
                              YouTube検索
                            </a>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* No works message */}
      {director.works.length === 0 && (
        <div className="bg-white rounded-lg border border-gray-200 p-8 text-center text-gray-400 mb-6">
          作品情報はまだ登録されていません
        </div>
      )}

      {/* Profile History */}
      {director.profileHistories.length > 1 && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
          <h2 className="text-lg font-bold mb-4">プロフィール履歴</h2>
          <div className="space-y-4">
            {director.profileHistories.map((ph) => (
              <div key={ph.sourceYear} className="border-l-2 border-gray-200 pl-4">
                <div className="text-xs font-bold text-gray-400 mb-1">{ph.sourceYear}</div>
                <p className="text-sm text-gray-600 whitespace-pre-line leading-relaxed">
                  {ph.profile}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
