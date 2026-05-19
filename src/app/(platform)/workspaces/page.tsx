'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Plus, ChevronRight, MoreVertical, Edit, Trash2 } from 'lucide-react';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

type Ws = {
  id: string;
  name: string;
  description: string | null;
  readiness: number;
  _count: { modules: number; scenarios: number; executionRuns: number };
};

export default function WorkspacesPage() {
  const [list, setList] = useState<Ws[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/v1/workspaces')
      .then((r) => r.json())
      .then((d) => setList(d.workspaces || []))
      .finally(() => setLoading(false));
  }, []);

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.preventDefault();
    if (!confirm('Are you sure you want to delete this workspace?')) return;
    setList(list.filter((w) => w.id !== id));
    await fetch(`/api/v1/workspaces/${id}`, { method: 'DELETE' });
  };


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
        <p className="text-sm text-slate-400 animate-pulse">Loading secure environment…</p>
      ) : list.length === 0 ? (
        <Card className="border-dashed border-slate-800 bg-slate-900/40 backdrop-blur-xl">
          <CardHeader>
            <CardTitle className="text-white">No workspaces yet</CardTitle>
            <CardDescription className="text-slate-400">Create your first workspace to configure URL, authentication, and discovery.</CardDescription>
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
                  <div className="flex items-center gap-1" onClick={(e) => e.preventDefault()}>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0 hover:bg-slate-800 text-slate-400 hover:text-white">
                          <MoreVertical className="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="bg-slate-900 border-slate-800 text-slate-300">
                        <DropdownMenuItem asChild className="hover:bg-slate-800 hover:text-white focus:bg-slate-800 focus:text-white">
                          <Link href={`/workspaces/${w.id}?tab=settings`} className="cursor-pointer">
                            <Edit className="mr-2 h-4 w-4" /> Edit
                          </Link>
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={(e: any) => handleDelete(e, w.id)} className="cursor-pointer text-red-400 hover:bg-slate-800 focus:bg-slate-800 focus:text-red-400">
                          <Trash2 className="mr-2 h-4 w-4" /> Delete
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                    <ChevronRight className="h-5 w-5 text-slate-500 transition-transform group-hover:translate-x-1 group-hover:text-violet-400" />
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex flex-wrap gap-2 text-xs">
                    <Badge variant="secondary" className="bg-slate-800 text-slate-300 hover:bg-slate-700">{w._count.modules} modules</Badge>
                    <Badge variant="secondary" className="bg-slate-800 text-slate-300 hover:bg-slate-700">{w._count.scenarios} scenarios</Badge>
                    <Badge variant="secondary" className="bg-slate-800 text-slate-300 hover:bg-slate-700">{w._count.executionRuns} runs</Badge>
                  </div>
                  <div>
                    <div className="mb-1 flex justify-between text-xs text-slate-400">
                      <span>Readiness</span>
                      <span className="text-violet-400 font-medium">{w.readiness}%</span>
                    </div>
                    <Progress value={w.readiness} className="h-2 bg-slate-800 [&>div]:bg-violet-500" />
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
