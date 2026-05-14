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
    <div className="flex min-h-screen w-full bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-50">
      <aside className="hidden w-64 shrink-0 border-r border-slate-200/80 bg-white dark:border-slate-800 dark:bg-slate-900 md:flex md:flex-col">
        <div className="flex h-16 items-center gap-2 border-b border-slate-200/80 px-6 dark:border-slate-800">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-violet-600 to-indigo-600 text-white shadow-sm">
            <Sparkles className="h-5 w-5" />
          </div>
          <div className="leading-tight">
            <div className="text-sm font-semibold tracking-tight">QAPtain</div>
            <div className="text-[11px] text-muted-foreground">AI-native automation</div>
          </div>
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
                    'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                    active
                      ? 'bg-violet-600/10 text-violet-700 dark:bg-violet-500/15 dark:text-violet-200'
                      : 'text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800/80',
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0 opacity-80" />
                  {label}
                </Link>
              );
            })}
          </nav>
        </ScrollArea>
        <div className="border-t border-slate-200/80 p-4 dark:border-slate-800">
          <div className="mb-3 truncate text-xs text-muted-foreground">{session?.user?.email}</div>
          <Button
            variant="outline"
            size="sm"
            className="w-full justify-start gap-2"
            onClick={() => signOut({ callbackUrl: '/login' })}
          >
            <LogOut className="h-4 w-4" />
            Sign out
          </Button>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex h-14 items-center border-b border-slate-200/80 bg-white/90 px-4 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90 md:hidden">
          <div className="flex items-center gap-2 font-semibold">
            <Sparkles className="h-5 w-5 text-violet-600" />
            QAPtain
          </div>
        </header>
        <main className="flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
