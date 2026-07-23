import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Codebase Intelligence Platform",
  description: "AI-powered codebase analysis and retrieval platform",
};

/**
 * Root layout — shared HTML shell, global styles, and nav bar.
 */
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-gray-950 text-gray-100 antialiased">

        {/* Top navigation bar */}
        <nav className="border-b border-gray-800 bg-gray-950 sticky top-0 z-10">
          <div className="max-w-5xl mx-auto px-4 h-12 flex items-center justify-between">
            <a href="/" className="flex items-center gap-2 group">
              <div className="w-6 h-6 rounded bg-brand-500 flex items-center justify-center">
                <span className="text-white font-bold text-xs select-none">CI</span>
              </div>
              <span className="text-sm font-semibold text-white group-hover:text-brand-500 transition-colors">
                Codebase Intelligence
              </span>
            </a>
            <a
              href="http://localhost:8000/api/docs"
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
            >
              API docs ↗
            </a>
          </div>
        </nav>

        <main className="relative z-0">{children}</main>
      </body>
    </html>
  );
}
