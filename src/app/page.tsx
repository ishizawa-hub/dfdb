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

export default function HomePage() {
  const [directors, setDirectors] = useState<Director[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [loading, setLoading] = useState(true);
  const limit = 100;

  const fetchDirectors = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: page.toString(),
        limit: limit.toString(),
      });
      if (query) params.set("q", query);

      const res = await fetch(`/api/search?${params}`);
      const data = await res.json();
      setDirectors(data.directors || []);
      setTotal(data.total || 0);
    } catch (e) {
      console.error("Search failed:", e);
    } finally {
      setLoading(false);
    }
  }, [page, query]);

  useEffect(() => {
    fetchDirectors();
  }, [fetchDirectors]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    setQuery(searchInput);
  };

  const totalPages = Math.ceil(total / limit);

  return (
    <div>
      {/* Search Bar */}
      <form onSubmit={handleSearch} className="mb-6">
        <div className="flex gap-2">
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="監督名・クライアント名・商品名・作品タイトルで検索..."
            className="flex-1 px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-lg"
          />
          <button
            type="submit"
            className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium"
          >
            検索
          </button>
          {query && (
            <button
              type="button"
              onClick={() => {
                setSearchInput("");
                setQuery("");
                setPage(1);
              }}
              className="px-4 py-3 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300"
            >
              クリア
            </button>
          )}
        </div>
      </form>

      {/* Results count */}
      <div className="mb-4 text-sm text-gray-600">
        {query && <span>「{query}」の検索結果: </span>}
        {total}人の監督 {totalPages > 1 && `(ページ ${page}/${totalPages})`}
      </div>

      {/* Director List */}
      {loading ? (
        <div className="text-center py-12 text-gray-500">読み込み中...</div>
      ) : directors.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          該当する監督が見つかりませんでした。
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {directors.map((d) => (
            <Link
              key={d.id}
              href={`/director/${d.id}`}
              className="block bg-white rounded-lg border border-gray-200 p-4 hover:shadow-md transition-shadow"
            >
              <div className="flex items-start gap-3">
                <div className="w-14 h-14 bg-gray-200 rounded-full flex items-center justify-center text-gray-500 text-xl shrink-0">
                  {d.portraitImagePath ? (
                    <img
                      src={d.portraitImagePath}
                      alt={d.name}
                      className="w-14 h-14 rounded-full object-cover"
                    />
                  ) : (
                    d.name[0]
                  )}
                </div>
                <div className="min-w-0">
                  <h2 className="font-bold text-lg leading-tight">
                    {d.name}
                  </h2>
                  {d.nameRomaji && (
                    <p className="text-xs text-gray-400 mt-0.5">
                      {d.nameRomaji}
                    </p>
                  )}
                  {d.company && (
                    <p className="text-sm text-gray-600 mt-1 truncate">
                      {d.company}
                    </p>
                  )}
                  <div className="mt-2 flex flex-wrap gap-2 text-xs text-gray-500">
                    {d.email && (
                      <span className="bg-gray-100 px-2 py-0.5 rounded">
                        {d.email}
                      </span>
                    )}
                    {d.phone && (
                      <span className="bg-gray-100 px-2 py-0.5 rounded">
                        {d.phone}
                      </span>
                    )}
                  </div>
                  {d.sourceYears && (
                    <div className="mt-2 flex gap-1">
                      {d.sourceYears.split(",").map((y) => (
                        <span
                          key={y}
                          className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded"
                        >
                          {y}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="mt-8 flex justify-center gap-2">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-4 py-2 border rounded disabled:opacity-50 hover:bg-gray-100"
          >
            前へ
          </button>
          {Array.from({ length: Math.min(totalPages, 10) }, (_, i) => {
            const p = i + 1;
            return (
              <button
                key={p}
                onClick={() => setPage(p)}
                className={`px-4 py-2 border rounded ${
                  p === page
                    ? "bg-blue-600 text-white border-blue-600"
                    : "hover:bg-gray-100"
                }`}
              >
                {p}
              </button>
            );
          })}
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="px-4 py-2 border rounded disabled:opacity-50 hover:bg-gray-100"
          >
            次へ
          </button>
        </div>
      )}
    </div>
  );
}
