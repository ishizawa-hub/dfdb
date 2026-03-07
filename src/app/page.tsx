"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";

interface Director {
  id: number;
  name: string;
  nameRomaji: string | null;
  email: string | null;
  phone: string | null;
  company: string | null;
  portraitImagePath: string | null;
  sourceYears: string | null;
}

interface SearchResponse {
  directors: Director[];
  total: number;
  page: number;
  limit: number;
}

export default function HomePage() {
  const [query, setQuery] = useState("");
  const [data, setData] = useState<SearchResponse | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const limit = 60;

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (query) params.set("q", query);
      params.set("page", page.toString());
      params.set("limit", limit.toString());
      const res = await fetch(`/api/search?${params}`);
      if (res.ok) setData(await res.json());
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [query, page]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
  };

  const totalPages = data ? Math.ceil(data.total / limit) : 0;

  return (
    <div>
      {/* Search Bar */}
      <form onSubmit={handleSearch} className="mb-8">
        <div className="flex gap-2">
          <div className="flex-1 relative">
            <svg className="absolute left-4 top-1/2 -translate-y-1/2 text-white/30" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="監督名・クライアント名・作品名で検索..."
              className="w-full pl-11 pr-4 py-3.5 bg-[#141414] border border-white/10 rounded-lg focus:outline-none focus:ring-1 focus:ring-white/30 focus:border-white/30 text-white placeholder-white/30 text-base transition-all"
            />
          </div>
          <button
            type="submit"
            className="px-7 py-3.5 bg-white text-black rounded-lg hover:bg-white/90 transition-all font-medium tracking-wide"
          >
            検索
          </button>
          {query && (
            <button
              type="button"
              onClick={() => {
                setQuery("");
                setPage(1);
              }}
              className="px-5 py-3.5 bg-white/5 text-white/60 rounded-lg hover:bg-white/10 transition-all border border-white/10"
            >
              クリア
            </button>
          )}
        </div>
      </form>

      {/* Results info */}
      {data && (
        <div className="flex items-center justify-between mb-6">
          <div className="text-sm text-white/40">
            {query ? (
              <span>&ldquo;{query}&rdquo; の検索結果: <span className="text-white/70 font-medium">{data.total}件</span></span>
            ) : (
              <span>全 <span className="text-white/70 font-medium">{data.total}名</span> のディレクター</span>
            )}
          </div>
          {totalPages > 1 && (
            <div className="text-sm text-white/30">
              {page} / {totalPages}
            </div>
          )}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex justify-center py-20">
          <div className="w-8 h-8 border-2 border-white/10 border-t-white/60 rounded-full animate-spin" />
        </div>
      )}

      {/* Director Grid */}
      {data && !loading && (
        <>
          {data.directors.length === 0 ? (
            <div className="text-center py-20 text-white/30">
              該当する監督が見つかりませんでした。
            </div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
              {data.directors.map((d) => {
                const years = d.sourceYears?.split(",") || [];
                return (
                  <Link
                    key={d.id}
                    href={`/director/${d.id}`}
                    className="group bg-[#141414] rounded-lg border border-white/5 overflow-hidden hover:border-white/15 transition-all duration-300 hover:scale-[1.02] hover:shadow-2xl hover:shadow-black/50"
                  >
                    <div className="aspect-square bg-[#1a1a1a] overflow-hidden">
                      {d.portraitImagePath ? (
                        <img
                          src={d.portraitImagePath}
                          alt={d.name}
                          className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500 ease-out"
                        />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-white/15 text-4xl font-bold">
                          {d.name[0]}
                        </div>
                      )}
                    </div>
                    <div className="p-3">
                      <div className="font-bold text-sm leading-tight text-white/90">{d.name}</div>
                      {d.nameRomaji && (
                        <div className="text-xs text-white/30 truncate mt-0.5">
                          {d.nameRomaji}
                        </div>
                      )}
                      {d.company && (
                        <div className="text-xs text-white/40 truncate mt-1">
                          {d.company}
                        </div>
                      )}
                      <div className="flex flex-wrap gap-1 mt-2">
                        {years.map((y) => (
                          <span
                            key={y}
                            className="text-[10px] bg-white/5 text-white/40 px-1.5 py-0.5 rounded"
                          >
                            {y}
                          </span>
                        ))}
                      </div>
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex justify-center items-center gap-2 mt-10">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-4 py-2 rounded-lg border border-white/10 text-sm text-white/60 disabled:opacity-20 hover:bg-white/5 transition-all"
          >
            前へ
          </button>
          {Array.from({ length: Math.min(totalPages, 10) }, (_, i) => {
            const start = Math.max(1, Math.min(page - 4, totalPages - 9));
            const p = start + i;
            if (p > totalPages) return null;
            return (
              <button
                key={p}
                onClick={() => setPage(p)}
                className={`w-9 h-9 rounded-lg text-sm transition-all ${
                  p === page
                    ? "bg-white text-black font-medium"
                    : "border border-white/10 text-white/50 hover:bg-white/5"
                }`}
              >
                {p}
              </button>
            );
          })}
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="px-4 py-2 rounded-lg border border-white/10 text-sm text-white/60 disabled:opacity-20 hover:bg-white/5 transition-all"
          >
            次へ
          </button>
        </div>
      )}
    </div>
  );
}
