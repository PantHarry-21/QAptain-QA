'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Plus, ChevronRight } from 'lucide-react';

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

  return (
    <div className="mx-auto max-w-5xl space-y-8 p-6 lg:p-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Workspaces</h1>
          <p className="mt-1 text-muted-foreground">One workspace per application under test.</p>
        </div>
        <Button asChild className="gap-2">
          <Link href="/workspaces/new">
            <Plus className="h-4 w-4" />
            Add workspace
          </Link>
        </Button>
      </div>

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : list.length === 0 ? (
        <Card className="border-dashed">
          <CardHeader>
            <CardTitle>No workspaces yet</CardTitle>
            <CardDescription>Create your first workspace to configure URL, authentication, and discovery.</CardDescription>
          </CardHeader>
          <CardContent>
            <Button asChild>
              <Link href="/workspaces/new">Create workspace</Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {list.map((w) => (
            <Link key={w.id} href={`/workspaces/${w.id}`} className="group block">
              <Card className="h-full border-slate-200/80 shadow-sm transition-shadow hover:shadow-md dark:border-slate-800">
                <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
                  <div>
                    <CardTitle className="text-lg">{w.name}</CardTitle>
                    <CardDescription className="line-clamp-2">{w.description || '—'}</CardDescription>
                  </div>
                  <ChevronRight className="h-5 w-5 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex flex-wrap gap-2 text-xs">
                    <Badge variant="secondary">{w._count.modules} modules</Badge>
                    <Badge variant="secondary">{w._count.scenarios} scenarios</Badge>
                    <Badge variant="secondary">{w._count.executionRuns} runs</Badge>
                  </div>
                  <div>
                    <div className="mb-1 flex justify-between text-xs text-muted-foreground">
                      <span>Readiness</span>
                      <span>{w.readiness}%</span>
                    </div>
                    <Progress value={w.readiness} className="h-2" />
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
