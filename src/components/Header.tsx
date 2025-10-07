'use client';

import Link from 'next/link';
import Image from 'next/image';

export default function Header() {
  return (
    <header className="bg-white dark:bg-slate-900 shadow-md">
      <div className="container mx-auto px-4 py-3">
        <div className="flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <Image src="/logo.png" alt="QAptain Logo" width={35} height={25} />
            <span className="text-2xl font-bold text-slate-900 dark:text-slate-100">QAptain</span>
          </Link>
          <nav>
            <ul className="flex items-center gap-6">
              <li>
                <Link href="/scenarios" className="text-lg font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-slate-100 transition-colors">
                  Scenarios
                </Link>
              </li>
              <li>
                <Link href="/history" className="text-lg font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-slate-100 transition-colors">
                  History
                </Link>
              </li>
            </ul>
          </nav>
          {/* Navigation links can be added here later */}
        </div>
      </div>
    </header>
  );
}
