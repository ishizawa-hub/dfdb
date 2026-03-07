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
        <div className="w-8 h-8 border-2 border-white/10 border-t-white/60 rounded-full animate-spin" />
      </div>
    );
  }

  if (!director) {
    return (
      <div className="text-center py-12">
        <p className="text-white/40 mb-4">監督が見つかりませんでした。</p>
        <Link href="/" className="text-white/60 hover:text-white transition-colors">
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
        className="text-white/30 hover:text-white/60 text-sm mb-6 inline-flex items-center gap-1.5 transition-colors"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
        一覧に戻る
      </Link>

      {/* Hero Card */}
      <div className="bg-[#141414] rounded-xl border border-white/5 overflow-hidden mb-8">
        <div className="bg-gradient-to-r from-[#1a1a1a] to-[#111] px-6 py-8 sm:px-8">
          <div className="flex items-start gap-6">
            <div className="w-28 h-28 rounded-lg overflow-hidden bg-[#222] shrink-0 border border-white/10">
              {director.portraitImagePath ? (
                <img
                  src={director.portraitImagePath}
                  alt={director.name}
                  className="w-full h-full object-cover"
                />
              ) : (
                <div className="w-full h-full flex items-center justify-center text-white/20 text-4xl font-bold">
                  {director.name[0]}
                </div>
              )}
            </div>
            <div className="min-w-0">
              <h1 className="text-3xl font-bold text-white tracking-tight">{director.name}</h1>
              {director.nameRomaji && (
                <p className="text-white/40 mt-1 text-lg tracking-wide">{director.nameRomaji}</p>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                {director.yearSources.map((ys) => (
                  <span
                    key={ys.sourceYear}
                    className="bg-white/8 text-white/60 px-3 py-0.5 rounded-full text-sm border border-white/5"
                  >
                    {ys.sourceYear}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Contact Info */}
        <div className="px-6 py-4 sm:px-8 grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm border-b border-white/5">
          {director.company && (
            <div>
              <div className="text-white/25 text-xs mb-0.5 uppercase tracking-wider">所属</div>
              <div className="font-medium text-white/80">{director.company}</div>
            </div>
          )}
          {director.email && (
            <div>
              <div className="text-white/25 text-xs mb-0.5 uppercase tracking-wider">Email</div>
              <a href={`mailto:${director.email}`} className="text-white/60 hover:text-white transition-colors break-all">
                {director.email}
              </a>
            </div>
          )}
          {director.phone && (
            <div>
              <div className="text-white/25 text-xs mb-0.5 uppercase tracking-wider">TEL</div>
              <a href={`tel:${director.phone}`} className="text-white/60 hover:text-white transition-colors">
                {director.phone}
              </a>
            </div>
          )}
          {director.website && (
            <div>
              <div className="text-white/25 text-xs mb-0.5 uppercase tracking-wider">Web</div>
              <a href={director.website} target="_blank" rel="noopener noreferrer" className="text-white/60 hover:text-white transition-colors break-all">
                {director.website.replace(/^https?:\/\//, '')}
              </a>
            </div>
          )}
        </div>

        {/* Profile */}
        {director.profile && (
          <div className="px-6 py-4 sm:px-8">
            <p className="text-white/50 whitespace-pre-line leading-relaxed text-sm">
              {director.profile}
            </p>
          </div>
        )}
      </div>

      {/* Works */}
      {director.works.length > 0 && (
        <div className="mb-8">
          <h2 className="text-xl font-bold mb-5 flex items-center gap-3 text-white/90">
            作品一覧
            <span className="text-sm font-normal text-white/30 bg-white/5 px-2.5 py-0.5 rounded-full">
              {director.works.length}件
            </span>
          </h2>

          {sortedYears.map((sourceYear) => (
            <div key={sourceYear} className="mb-10 last:mb-0">
              <h3 className="text-sm font-medium text-white/30 mb-4 uppercase tracking-widest border-b border-white/5 pb-2">
                {sourceYear}
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {worksByYear[sourceYear].map((work) => {
                  const ytId = work.youtubeUrl
                    ? getYouTubeId(work.youtubeUrl)
                    : null;
                  const searchUrl = youtubeSearchUrl(work, director.name);

                  const infoParts = [
                    work.clientName,
                    work.productName,
                    work.title,
                  ].filter(Boolean);
                  const infoLine = infoParts.join(" | ");

                  return (
                    <div
                      key={work.id}
                      className="bg-[#141414] rounded-lg border border-white/5 overflow-hidden hover:border-white/15 transition-all duration-300 group"
                    >
                      {/* Thumbnail */}
                      {work.thumbnailPath ? (
                        <div className="aspect-video bg-[#1a1a1a] overflow-hidden thumb-shine">
                          <img
                            src={work.thumbnailPath}
                            alt={work.title}
                            className="w-full h-full object-cover group-hover:scale-[1.03] transition-transform duration-500 ease-out"
                          />
                        </div>
                      ) : !ytId && (
                        <div className="aspect-video bg-[#111] flex items-center justify-center">
                          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" className="text-white/10">
                            <rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/>
                            <line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/>
                            <line x1="2" y1="12" x2="22" y2="12"/><line x1="2" y1="7" x2="22" y2="7"/>
                            <line x1="2" y1="17" x2="22" y2="17"/>
                          </svg>
                        </div>
                      )}

                      {/* YouTube embed */}
                      {ytId && (
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
                      )}

                      <div className="p-3">
                        <div className="font-medium text-sm leading-tight mb-1 line-clamp-2 text-white/80">
                          {infoLine}
                        </div>

                        {work.agency && (
                          <div className="text-xs text-white/30 truncate mb-1">
                            {work.agency}
                          </div>
                        )}

                        {work.year != null && work.year > 0 && (
                          <div className="text-xs text-white/20">{work.year}</div>
                        )}

                        {/* YouTube links */}
                        <div className="mt-2 flex gap-2 flex-wrap">
                          {work.youtubeUrl ? (
                            <a
                              href={work.youtubeUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-xs bg-red-500/10 text-red-400 px-2 py-1 rounded hover:bg-red-500/20 transition-colors"
                            >
                              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>
                              YouTube
                            </a>
                          ) : (
                            <a
                              href={searchUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-xs bg-white/5 text-white/30 px-2 py-1 rounded hover:bg-white/10 hover:text-white/50 transition-colors"
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
        <div className="bg-[#141414] rounded-lg border border-white/5 p-8 text-center text-white/20 mb-8">
          作品情報はまだ登録されていません
        </div>
      )}

      {/* Profile History */}
      {director.profileHistories.length > 1 && (
        <div className="bg-[#141414] rounded-xl border border-white/5 p-6 mb-8">
          <h2 className="text-lg font-bold mb-4 text-white/80">プロフィール履歴</h2>
          <div className="space-y-4">
            {director.profileHistories.map((ph) => (
              <div key={ph.sourceYear} className="border-l-2 border-white/10 pl-4">
                <div className="text-xs font-bold text-white/25 mb-1">{ph.sourceYear}</div>
                <p className="text-sm text-white/40 whitespace-pre-line leading-relaxed">
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
