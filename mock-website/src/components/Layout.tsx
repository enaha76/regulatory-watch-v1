import { Link } from 'react-router-dom';
import { ReactNode } from 'react';

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="bg-[#003366] text-white shadow-md">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div>
            <Link to="/" className="font-serif text-xl font-bold">
              ATCA Admin
            </Link>
            <p className="text-[11px] uppercase tracking-widest opacity-80">
              Regulation Management
            </p>
          </div>
          <nav className="flex space-x-4 text-sm">
            <Link to="/" className="hover:underline">
              All Regulations
            </Link>
            <a href="/" className="hover:underline">
              View Public Site →
            </a>
          </nav>
        </div>
      </header>
      <main className="max-w-6xl mx-auto px-6 py-8">{children}</main>
    </div>
  );
}
