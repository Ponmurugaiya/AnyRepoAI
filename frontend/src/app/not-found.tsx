/**
 * 404 Not Found page.
 */
import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex min-h-[80vh] flex-col items-center justify-center p-8">
      <div className="text-center space-y-4">
        <p className="text-6xl font-bold text-brand-500" aria-hidden="true">404</p>
        <h1 className="text-2xl font-semibold text-white">Page not found</h1>
        <p className="text-gray-400">The page you are looking for does not exist.</p>
        <Link
          href="/"
          className="inline-block mt-4 rounded-lg bg-brand-500 px-5 py-2.5 text-sm font-semibold text-white hover:bg-brand-600 transition-colors focus:outline-none focus:ring-2 focus:ring-brand-500"
        >
          Back to home
        </Link>
      </div>
    </div>
  );
}
