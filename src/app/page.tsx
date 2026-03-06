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
      <form onSubmit={handleSearch} className="mb-6">
        <div className="flex gap-2">
          <div className="flex-1 relative">
            <svg className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="監督名・クライアント名・作品名で検索..."
              className="w-full pl-10 pr-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-base"
            />
          </div>
          <button
            type="submit"
            className="px-6 py-3 bg-gray-800 text-white rounded-lg hover:bg-gray-700 transition-colors font-medium"
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
              className="px-4 py-3 bg-gray-100 text-gray-600 rounded-lg hover:bg-gray-200 transition-colors"
            >
              クリア
            </button>
          )}
        </div>
      </form>

      {/* Results info */}
      {data && (
        <div className="flex items-center justify-between mb-4">
          <div className="text-sm text-gray-500">
            {query ? (
              <span>「{query}」の検索結果: <b>{data.total}件</b></span>
            ) : (
              <span>全 <b>{data.total}名</b> のディレクター</span>
            )}
          </div>
          {totalPages > 1 && (
            <div className="text-sm text-gray-400">
              {page} / {totalPages} ページ
            </div>
          )}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex justify-center py-12">
          <div className="w-8 h-8 border-4 border-gray-300 border-t-blue-500 rounded-full animate-spin" />
        </div>
      )}

      {/* Director Grid */}
      {data && !loading && (
        <>
          {data.directors.length === 0 ? (
            <div className="text-center py-12 text-gray-400">
              該当する監督が見つかりませんでした。
            </div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
              {data.directors.map((d) => {
                const years = d.sourceYears?.split(",") || [];
                return (
                  <Link
                    key={d.id}
                    href={`/director/${d.id}`}
                    className="bg-white rounded-lg border border-gray-200 overflow-hidden hover:shadow-lg hover:border-gray-300 transition-all group"
                  >
                    <div className="aspect-square bg-gray-100 overflow-hidden">
                      {d.portraitImagePath ? (
                        <img
                          src={d.portraitImagePath}
                          alt={d.name}
                          className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
                        />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-gray-300 text-4xl font-bold">
                          {d.name[0]}
                        </div>
                      )}
                    </div>
                    <div className="p-2.5">
                      <div className="font-bold text-sm leading-tight">{d.name}</div>
                      {d.nameRomaji && (
                        <div className="text-xs text-gray-400 truncate mt-0.5">
                          {d.nameRomaji}
                        </div>
                      )}
                      {d.company && (
                        <div className="text-xs text-gray-500 truncate mt-1">
                          {d.company}
                        </div>
                      )}
                      <div className="flex flex-wrap gap-1 mt-1.5">
                        {years.map((y) => (
                          <span
                            key={y}
                            className="text-[10px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded"
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
        <div className="flex justify-center items-center gap-2 mt-8">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-3 py-2 rounded-lg border border-gray-300 text-sm disabled:opacity-30 hover:bg-gray-50"
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
                className={`w-9 h-9 rounded-lg text-sm ${
                  p === page
                    ? "bg-gray-800 text-white"
                    : "border border-gray-300 hover:bg-gray-50"
                }`}
              >
                {p}
              </button>
            );
          })}
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="px-3 py-2 rounded-lg border border-gray-300 text-sm disabled:opacity-30 hover:bg-gray-50"
          >
            次へ
          </button>
        </div>
      )}
    </div>
  );
}
