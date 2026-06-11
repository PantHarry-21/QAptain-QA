import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Sparkles, ArrowRight, ShieldCheck, Zap, Activity } from 'lucide-react';

export default function HomePage() {
  return (
    <div className="relative min-h-screen bg-slate-950 font-sans text-slate-50 selection:bg-violet-500/30">
      <div className="absolute inset-0 z-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-[20%] -left-[10%] h-[70%] w-[50%] rounded-full bg-violet-600/20 blur-[120px]" />
        <div className="absolute top-[20%] -right-[10%] h-[60%] w-[40%] rounded-full bg-indigo-600/20 blur-[100px]" />
        <div className="absolute -bottom-[20%] left-[20%] h-[50%] w-[60%] rounded-full bg-fuchsia-600/10 blur-[120px]" />
      </div>

      <header className="relative z-20 flex items-center justify-between px-6 py-6 lg:px-12">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-indigo-600 shadow-lg shadow-violet-500/30">
            <Sparkles className="h-4 w-4 text-white" />
          </div>
          <span className="text-xl font-bold tracking-tight text-white">QAptain</span>
        </div>
        <div className="flex items-center gap-4">
          <Link href="/login" className="text-sm font-medium text-slate-300 transition-colors hover:text-white">
            Log in
          </Link>
          <Button asChild className="bg-violet-600 text-white hover:bg-violet-700 shadow-lg shadow-violet-600/20 transition-all hover:scale-105">
            <Link href="/signup">Get Started</Link>
          </Button>
        </div>
      </header>

      <main className="relative z-10 flex flex-col items-center justify-center px-6 pt-20 pb-32 text-center lg:pt-32">
        <div className="inline-flex items-center rounded-full border border-violet-500/30 bg-violet-500/10 px-3 py-1 text-sm font-medium text-violet-300 backdrop-blur-md">
          <span className="flex h-2 w-2 rounded-full bg-violet-500 mr-2 animate-pulse"></span>
          AI-native Enterprise Quality Engineering
        </div>

        <h1 className="mt-8 max-w-4xl bg-gradient-to-br from-white via-slate-200 to-slate-400 bg-clip-text text-5xl font-extrabold tracking-tight text-transparent sm:text-7xl">
          Ship software with <br className="hidden sm:block" />
          <span className="bg-gradient-to-r from-violet-400 to-fuchsia-400 bg-clip-text text-transparent">Zero Friction.</span>
        </h1>

        <p className="mt-6 max-w-2xl text-lg text-slate-400 sm:text-xl">
          QAptain is an AI-native autonomous testing platform. It explores your app, learns how it works, then executes intelligent scenarios via Selenium — self-healing on every run.
        </p>

        <div className="mt-10 flex flex-col items-center justify-center gap-4 sm:flex-row sm:gap-6">
          <Button asChild size="lg" className="h-14 px-8 rounded-full bg-gradient-to-r from-violet-600 to-indigo-600 text-white shadow-xl shadow-violet-600/20 transition-all hover:scale-105 hover:shadow-violet-600/40 text-lg">
            <Link href="/signup">
              Start Free Trial <ArrowRight className="ml-2 h-5 w-5" />
            </Link>
          </Button>
          <Button asChild size="lg" variant="outline" className="h-14 px-8 rounded-full border-slate-700 bg-slate-900/50 text-slate-200 backdrop-blur-md transition-all hover:bg-slate-800 hover:text-white text-lg">
            <Link href="/login">Sign In</Link>
          </Button>
        </div>

        <div className="mt-32 grid w-full max-w-5xl grid-cols-1 gap-8 sm:grid-cols-3">
          <div className="flex flex-col items-center rounded-2xl border border-slate-800 bg-slate-900/40 p-8 backdrop-blur-sm transition-transform hover:-translate-y-2 hover:border-violet-500/50">
            <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-indigo-500/20 text-indigo-400">
              <Zap className="h-6 w-6" />
            </div>
            <h3 className="text-xl font-semibold text-slate-200">Autonomous Exploration</h3>
            <p className="mt-2 text-center text-sm text-slate-400">Explore engine learns every module, page, and workflow — building a semantic knowledge graph of your app.</p>
          </div>
          <div className="flex flex-col items-center rounded-2xl border border-slate-800 bg-slate-900/40 p-8 backdrop-blur-sm transition-transform hover:-translate-y-2 hover:border-fuchsia-500/50">
            <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-fuchsia-500/20 text-fuchsia-400">
              <Activity className="h-6 w-6" />
            </div>
            <h3 className="text-xl font-semibold text-slate-200">Self-Healing Execution</h3>
            <p className="mt-2 text-center text-sm text-slate-400">8 ranked healing strategies. aria-label → label → placeholder → text → role. Never a flaky test again.</p>
          </div>
          <div className="flex flex-col items-center rounded-2xl border border-slate-800 bg-slate-900/40 p-8 backdrop-blur-sm transition-transform hover:-translate-y-2 hover:border-violet-500/50">
            <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-violet-500/20 text-violet-400">
              <ShieldCheck className="h-6 w-6" />
            </div>
            <h3 className="text-xl font-semibold text-slate-200">Memory That Grows</h3>
            <p className="mt-2 text-center text-sm text-slate-400">ChromaDB vector memory improves with every execution. The more it runs, the smarter it gets.</p>
          </div>
        </div>
      </main>

      <footer className="relative z-10 border-t border-slate-800 bg-slate-950/80 py-8 text-center backdrop-blur-lg">
        <p className="text-sm text-slate-500">© {new Date().getFullYear()} QAptain AI. All rights reserved.</p>
      </footer>
    </div>
  );
}
