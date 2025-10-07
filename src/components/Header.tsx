'use client';

import Link from 'next/link';
import Image from 'next/image';

export default function Header() {
  return (
    <header className="bg-white dark:bg-slate-900 shadow-md">
      <div className="container mx-auto px-4 py-3">
        <div className="flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <Image src="/logo.png" alt="QAptain Logo" width={75} height={75} />
            <span className="text-3xl font-bold text-slate-900 dark:text-slate-100">QAptain</span>
          </Link>
          {/* Navigation links can be added here later */}
        </div>
      </div>
    </header>
  );
}
