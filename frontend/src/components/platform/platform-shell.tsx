'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import {
  LayoutDashboard,
  Building2,
  LogOut,
  Settings,
  Sparkles,
  Play,
  Search,
  X,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { AppNotificationsProvider } from '@/components/ui/app-notifications';
import { getSocket } from '@/lib/websocket';

const mainNav = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/workspaces', label: 'Workspaces', icon: Building2 },
  { href: '/settings', label: 'Settings', icon: Settings },
];

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

interface ActiveRun {
  runId: string | null;
  batchId?: string | null;
  workspaceId: string;
  title: string;
}

interface ActiveExplore {
  sessionId: string;
  workspaceId: string;
  appName: string;
}

export function PlatformShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);

  const [activeRun, setActiveRun] = useState<ActiveRun | null>(null);
  const [activeExplore, setActiveExplore] = useState<ActiveExplore | null>(null);

  const activeRunRef = useRef(activeRun);
  activeRunRef.current = activeRun;
  const activeExploreRef = useRef(activeExplore);
  activeExploreRef.current = activeExplore;

  // Load persisted active sessions from sessionStorage on mount
  useEffect(() => {
    try {
      const runData = sessionStorage.getItem('qaptain_active_run');
      if (runData) setActiveRun(JSON.parse(runData));
    } catch {}
    try {
      const exploreData = sessionStorage.getItem('qaptain_active_explore');
      if (exploreData) setActiveExplore(JSON.parse(exploreData));
    } catch {}
  }, []);

  // WebSocket: clear banners when runs/explores complete
  useEffect(() => {
    const socket = getSocket();
    socket.connect();

    const offRunCompleted = socket.on('run_completed', (data) => {
      const current = activeRunRef.current;
      if (current && (data.run_id === current.runId || !current.runId)) {
        sessionStorage.removeItem('qaptain_active_run');
        setActiveRun(null);
      }
    });

    const offRunFailed = socket.on('run_failed', (data) => {
      const current = activeRunRef.current;
      if (current && (data.run_id === current.runId || !current.runId)) {
        sessionStorage.removeItem('qaptain_active_run');
        setActiveRun(null);
      }
    });

    const offRunCancelled = socket.on('run_cancelled', (data) => {
      const current = activeRunRef.current;
      if (current && (data.run_id === current.runId || !current.runId)) {
        sessionStorage.removeItem('qaptain_active_run');
        setActiveRun(null);
      }
    });

    const offExploreCompleted = socket.on('explore_completed', () => {
      sessionStorage.removeItem('qaptain_active_explore');
      setActiveExplore(null);
    });

    const offExploreFailed = socket.on('explore_failed', () => {
      sessionStorage.removeItem('qaptain_active_explore');
      setActiveExplore(null);
    });

    const offExploreCancelled = socket.on('explore_cancelled', () => {
      sessionStorage.removeItem('qaptain_active_explore');
      setActiveExplore(null);
    });

    return () => {
      offRunCompleted();
      offRunFailed();
      offRunCancelled();
      offExploreCompleted();
      offExploreFailed();
      offExploreCancelled();
    };
  }, []);

  useEffect(() => {
    const token = localStorage.getItem('qaptain_token');
    if (!token) {
      router.push('/login');
      return;
    }
    fetch(`${API_URL}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((user) => {
        if (!user) {
          localStorage.removeItem('qaptain_token');
          router.push('/login');
        } else {
          setEmail(user.email);
        }
      })
      .catch(() => {
        router.push('/login');
      });
  }, [router]);

  const handleSignOut = () => {
    localStorage.removeItem('qaptain_token');
    router.push('/login');
  };

  const dismissRun = () => {
    sessionStorage.removeItem('qaptain_active_run');
    setActiveRun(null);
  };

  const dismissExplore = () => {
    sessionStorage.removeItem('qaptain_active_explore');
    setActiveExplore(null);
  };

  const runHref = activeRun
    ? activeRun.runId
      ? `/workspaces/${activeRun.workspaceId}/executions/${activeRun.runId}`
      : activeRun.batchId
        ? `/workspaces/${activeRun.workspaceId}/executions/batch?batch_id=${activeRun.batchId}`
        : null
    : null;

  const exploreHref = activeExplore
    ? `/workspaces/${activeExplore.workspaceId}/explore/${activeExplore.sessionId}`
    : null;

  // Don't show banner if already on that page
  const showRunBanner = activeRun && runHref && !pathname.includes('/executions/');
  const showExploreBanner = activeExplore && exploreHref && !pathname.includes('/explore/');

  return (
    <AppNotificationsProvider>
    <div className="flex min-h-screen w-full bg-slate-950 text-slate-50 font-sans selection:bg-violet-500/30">
      <div className="fixed inset-0 z-0 overflow-hidden pointer-events-none">
        <div className="absolute top-[0%] left-[0%] h-[50%] w-[30%] rounded-full bg-violet-600/5 blur-[120px]" />
        <div className="absolute bottom-[0%] right-[0%] h-[40%] w-[30%] rounded-full bg-indigo-600/5 blur-[120px]" />
      </div>

      <aside className="relative z-20 hidden w-64 shrink-0 border-r border-slate-800 bg-slate-900/60 backdrop-blur-xl md:flex md:flex-col">
        <div className="flex h-16 items-center gap-2 border-b border-slate-800 px-6">
          <Link href="/" className="flex items-center gap-2 group">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-violet-600 to-indigo-600 text-white shadow-lg shadow-violet-600/20 transition-transform group-hover:scale-105">
              <Sparkles className="h-5 w-5" />
            </div>
            <div className="leading-tight">
              <div className="text-sm font-semibold tracking-tight text-white group-hover:text-violet-300 transition-colors">QAptain</div>
              <div className="text-[11px] text-slate-400">AI-native automation</div>
            </div>
          </Link>
        </div>
        <ScrollArea className="flex-1 px-3 py-4">
          <nav className="space-y-1">
            {mainNav.map(({ href, label, icon: Icon }) => {
              const active = pathname === href || pathname.startsWith(`${href}/`);
              return (
                <Link
                  key={href}
                  href={href}
                  className={cn(
                    'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all',
                    active
                      ? 'bg-violet-600/20 text-violet-300 shadow-sm border border-violet-500/20'
                      : 'text-slate-400 hover:bg-slate-800/80 hover:text-slate-200 border border-transparent',
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  {label}
                </Link>
              );
            })}
          </nav>

          {/* Active session indicators in sidebar */}
          <div className="mt-6 space-y-2">
            {showRunBanner && (
              <Link href={runHref!} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20 hover:bg-emerald-500/15 transition-colors group">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-medium text-emerald-300">Execution running</div>
                  <div className="text-[10px] text-emerald-400/70 truncate">{activeRun?.title}</div>
                </div>
                <Play className="h-3 w-3 text-emerald-400 shrink-0" />
              </Link>
            )}
            {showExploreBanner && (
              <Link href={exploreHref!} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-blue-500/10 border border-blue-500/20 hover:bg-blue-500/15 transition-colors group">
                <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-medium text-blue-300">Exploring app</div>
                  <div className="text-[10px] text-blue-400/70 truncate">{activeExplore?.appName}</div>
                </div>
                <Search className="h-3 w-3 text-blue-400 shrink-0" />
              </Link>
            )}
          </div>
        </ScrollArea>
        <div className="border-t border-slate-800 p-4 bg-slate-950/40">
          {email && (
            <div className="mb-3 truncate text-xs text-slate-400 font-medium px-1">{email}</div>
          )}
          <Button
            variant="outline"
            size="sm"
            className="w-full justify-start gap-2 border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800 hover:text-white"
            onClick={handleSignOut}
          >
            <LogOut className="h-4 w-4" />
            Sign out
          </Button>
        </div>
      </aside>

      <div className="relative z-10 flex min-w-0 flex-1 flex-col">
        {/* Mobile header */}
        <header className="sticky top-0 z-30 flex h-14 items-center border-b border-slate-800 bg-slate-900/60 px-4 backdrop-blur-xl md:hidden">
          <div className="flex items-center gap-2 font-semibold text-white">
            <Sparkles className="h-5 w-5 text-violet-500" />
            QAptain
          </div>
        </header>

        {/* Active execution top banner — shown across all pages when execution is running */}
        {showRunBanner && (
          <div className="sticky top-0 z-20 flex items-center gap-3 bg-emerald-950/80 border-b border-emerald-500/20 px-4 py-2.5 backdrop-blur-sm">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse shrink-0" />
            <Play className="h-3.5 w-3.5 text-emerald-400 shrink-0" />
            <span className="text-sm text-emerald-300 font-medium">
              Execution in progress
            </span>
            <span className="text-xs text-emerald-400/60 truncate">{activeRun?.title}</span>
            <div className="flex-1" />
            <Link
              href={runHref!}
              className="text-xs px-3 py-1 bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/30 rounded-md transition-colors font-medium"
            >
              View execution →
            </Link>
            <button onClick={dismissRun} className="text-emerald-400/60 hover:text-emerald-300 transition-colors ml-1">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}

        {/* Active exploration top banner */}
        {showExploreBanner && (
          <div className="sticky top-0 z-20 flex items-center gap-3 bg-blue-950/80 border-b border-blue-500/20 px-4 py-2.5 backdrop-blur-sm">
            <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse shrink-0" />
            <Search className="h-3.5 w-3.5 text-blue-400 shrink-0" />
            <span className="text-sm text-blue-300 font-medium">
              Exploration in progress
            </span>
            <span className="text-xs text-blue-400/60 truncate">{activeExplore?.appName}</span>
            <div className="flex-1" />
            <Link
              href={exploreHref!}
              className="text-xs px-3 py-1 bg-blue-500/20 hover:bg-blue-500/30 text-blue-300 border border-blue-500/30 rounded-md transition-colors font-medium"
            >
              View exploration →
            </Link>
            <button onClick={dismissExplore} className="text-blue-400/60 hover:text-blue-300 transition-colors ml-1">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}

        <main className="flex-1 overflow-auto p-6 md:p-8">{children}</main>
      </div>
    </div>
    </AppNotificationsProvider>
  );
}
