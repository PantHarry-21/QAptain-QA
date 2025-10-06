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
            <Link href="#" className="hover:underline">Learn More</Link>
            <Link href="#" className="hover:underline">Our Products</Link>
            <Link href="#" className="hover:underline">Contact Us</Link>
          </div>
          <p className="mt-4 text-xs">&copy; {new Date().getFullYear()} QAptain. All rights reserved.</p>
        </div>
      </div>
    </footer>
  );
}
