import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Directors File DB",
  description: "CM・映像ディレクターズファイル検索サイト",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ja">
      <body className="bg-[#0a0a0a] text-white min-h-screen">
        <header className="bg-black/80 backdrop-blur-md border-b border-white/10 sticky top-0 z-50">
          <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
            <a href="/" className="text-xl font-bold tracking-[0.15em] uppercase text-white hover:text-white/80 transition-colors">
              Directors File DB
            </a>
            <span className="text-xs text-white/40 tracking-widest uppercase">Internal</span>
          </div>
        </header>
        <main className="max-w-7xl mx-auto px-4 py-8">{children}</main>
      </body>
    </html>
  );
}
