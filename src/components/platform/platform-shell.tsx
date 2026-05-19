'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { signOut, useSession } from 'next-auth/react';
import {
  LayoutDashboard,
  Building2,
  LogOut,
  Settings,
  Sparkles,
} from 'lucide-react';
import { cn } from '@/lib/utils.client';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';

const mainNav = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/workspaces', label: 'Workspaces', icon: Building2 },
  { href: '/settings', label: 'Settings', icon: Settings },
];

export function PlatformShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { data: session } = useSession();

  return (
    <div className="flex min-h-screen w-full bg-slate-950 text-slate-50 font-sans selection:bg-violet-500/30">
      {/* Ambient background for the shell */}
      <div className="fixed inset-0 z-0 overflow-hidden pointer-events-none">
        <div className="absolute top-[0%] left-[0%] h-[50%] w-[30%] rounded-full bg-violet-600/5 blur-[120px]" />
        <div className="absolute bottom-[0%] right-[0%] h-[40%] w-[30%] rounded-full bg-indigo-600/5 blur-[120px]" />
        <div className="absolute inset-0 bg-[url('/grid.svg')] bg-center opacity-30 [mask-image:linear-gradient(180deg,white,rgba(255,255,255,0))]" />
      </div>

      <aside className="relative z-20 hidden w-64 shrink-0 border-r border-slate-800 bg-slate-900/60 backdrop-blur-xl md:flex md:flex-col">
        <div className="flex h-16 items-center gap-2 border-b border-slate-800 px-6">
          <Link href="/" className="flex items-center gap-2 group">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-violet-600 to-indigo-600 text-white shadow-lg shadow-violet-600/20 transition-transform group-hover:scale-105">
              <Sparkles className="h-5 w-5" />
            </div>
            <div className="leading-tight">
              <div className="text-sm font-semibold tracking-tight text-white group-hover:text-violet-300 transition-colors">QAPtain</div>
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
        </ScrollArea>
        <div className="border-t border-slate-800 p-4 bg-slate-950/40">
          <div className="mb-3 truncate text-xs text-slate-400 font-medium px-1">{session?.user?.email}</div>
          <Button
            variant="outline"
            size="sm"
            className="w-full justify-start gap-2 border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800 hover:text-white"
            onClick={() => signOut({ callbackUrl: '/login' })}
          >
            <LogOut className="h-4 w-4" />
            Sign out
          </Button>
        </div>
      </aside>
      
      <div className="relative z-10 flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center border-b border-slate-800 bg-slate-900/60 px-4 backdrop-blur-xl md:hidden">
          <div className="flex items-center gap-2 font-semibold text-white">
            <Sparkles className="h-5 w-5 text-violet-500" />
            QAPtain
          </div>
        </header>
        <main className="flex-1 overflow-auto p-6 md:p-8">{children}</main>
      </div>
    </div>
  );
}
