import { redirect } from 'next/navigation';
import { getServerSession } from 'next-auth/next';
import Link from 'next/link';
import { getAuthOptions } from '@/lib/auth';
import { Button } from '@/components/ui/button';
import { Sparkles } from 'lucide-react';

export default async function HomePage() {
  const session = await getServerSession(getAuthOptions());
  if (session) redirect('/dashboard');

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-slate-950 px-6 text-slate-50">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-violet-600/40 via-slate-950 to-slate-950" />
      <div className="relative z-10 max-w-xl text-center">
        <div className="mx-auto mb-6 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-500 to-indigo-600 shadow-lg shadow-violet-500/30">
          <Sparkles className="h-8 w-8 text-white" />
        </div>
        <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">QAPtain</h1>
        <p className="mt-4 text-lg text-slate-300">
          AI-native quality engineering: progressive discovery, scenario intelligence, structured Playwright execution,
          and workspace-scoped memory.
        </p>
        <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
          <Button asChild size="lg" className="bg-white text-slate-900 hover:bg-slate-100">
            <Link href="/login">Sign in</Link>
          </Button>
          <Button asChild size="lg" variant="outline" className="border-slate-600 text-slate-100 hover:bg-slate-800">
            <Link href="/signup">Create account</Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
