'use client';

import Link from 'next/link';
import Image from 'next/image';
import { ThemeToggle } from "@/components/ThemeToggle";

export default function Header() {
  return (
    <header className="bg-transparent">
      <div className="container mx-auto px-4 py-3">
        <div className="flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <Image src="/logo.png" alt="QAptain Logo" width={35} height={25} />
            <span className="text-2xl font-bold">QAptain</span>
          </Link>
          <div className="flex items-center gap-4">
            <nav>
              <ul className="flex items-center gap-6">
                <li>
                  <Link href="/saved-scenarios" className="text-base font-medium text-slate-300 hover:text-white transition-colors">
                    Saved Scenarios
                  </Link>
                </li>
                <li>
                  <Link href="/history" className="text-base font-medium text-slate-300 hover:text-white transition-colors">
                    History
                  </Link>
                </li>
              </ul>
            </nav>
            <ThemeToggle />
          </div>
        </div>
      </div>
    </header>
  );
}
