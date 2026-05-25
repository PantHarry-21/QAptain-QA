'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Plus, ChevronRight } from 'lucide-react';
import { api, type Workspace } from '@/lib/api';

export default function WorkspacesPage() {
  const [list, setList] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.workspaces.list()
      .then((data) => setList(Array.isArray(data) ? data : []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="mx-auto max-w-5xl space-y-8 p-6 lg:p-10 relative z-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-white">Workspaces</h1>
          <p className="mt-1 text-slate-400">One workspace per application under test.</p>
        </div>
        <Button asChild className="gap-2 bg-violet-600 hover:bg-violet-700 text-white shadow-lg shadow-violet-600/20">
          <Link href="/workspaces/new">
            <Plus className="h-4 w-4" />
            Add workspace
          </Link>
        </Button>
      </div>

      {loading ? (
        <p className="text-sm text-slate-400 animate-pulse">Loading workspaces…</p>
      ) : list.length === 0 ? (
        <Card className="border-dashed border-slate-800 bg-slate-900/40 backdrop-blur-xl">
          <CardHeader>
            <CardTitle className="text-white">No workspaces yet</CardTitle>
            <CardDescription className="text-slate-400">
              Create your first workspace to configure a URL, credentials, and run AI exploration.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button asChild className="bg-violet-600 hover:bg-violet-700 text-white shadow-md shadow-violet-600/20">
              <Link href="/workspaces/new">Create workspace</Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {list.map((w) => (
            <Link key={w.id} href={`/workspaces/${w.id}`} className="group block">
              <Card className="h-full border-slate-800 bg-slate-900/60 backdrop-blur-xl shadow-lg transition-all hover:shadow-violet-900/20 hover:border-violet-500/50 hover:-translate-y-1">
                <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
                  <div className="flex-1">
                    <CardTitle className="text-lg text-white group-hover:text-violet-300 transition-colors">{w.name}</CardTitle>
                    <CardDescription className="line-clamp-2 text-slate-400">{w.description || '—'}</CardDescription>
                  </div>
                  <ChevronRight className="h-5 w-5 text-slate-500 transition-transform group-hover:translate-x-1 group-hover:text-violet-400 shrink-0" />
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex flex-wrap gap-2 text-xs">
                    <Badge variant="secondary" className="bg-slate-800 text-slate-300">{w.application_count ?? 0} apps</Badge>
                  </div>
                  <div>
                    <div className="mb-1 flex justify-between text-xs text-slate-400">
                      <span>Readiness</span>
                      <span className="text-violet-400 font-medium">{w.readiness ?? 0}%</span>
                    </div>
                    <Progress value={w.readiness ?? 0} className="h-2 bg-slate-800 [&>div]:bg-violet-500" />
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
