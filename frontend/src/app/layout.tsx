import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Codebase Intelligence Platform",
  description: "AI-powered codebase analysis and retrieval platform",
};

/**
 * Root layout component.
 *
 * Wraps all pages with the shared HTML shell, fonts, and global styles.
 */
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-gray-950 text-gray-100 antialiased">
        {children}
      </body>
    </html>
  );
}
