'use client';

import Link from 'next/link';

export default function Footer() {
  return (
    <footer className="bg-slate-100 dark:bg-slate-800 border-t border-slate-200 dark:border-slate-700">
      <div className="container mx-auto px-4 py-6">
        <div className="text-center text-sm text-slate-600 dark:text-slate-400">
          <p className="font-semibold">Sponsored by TYNYBAY Pvt. Ltd.</p>
          <p>Your one-stop solution for Automation Testing</p>
          <div className="mt-2 space-x-4">
            <p className="font-bold">Write less. Test more. Ship faster with QAptain.</p>
           
          </div>
          <p className="mt-4 text-xs">&copy; {new Date().getFullYear()} Crafted with 🤖 + ❤️ by QAptain</p>
        </div>
      </div>
    </footer>
  );
}
