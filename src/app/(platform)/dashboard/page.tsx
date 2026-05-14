import Link from 'next/link';
import { getServerSession } from 'next-auth/next';
import { getAuthOptions } from '@/lib/auth';
import { prisma } from '@/lib/prisma';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { ArrowRight, PlayCircle, Radar } from 'lucide-react';

export default async function DashboardPage() {
  const session = await getServerSession(getAuthOptions());
  const userId = session?.user && 'id' in session.user ? (session.user as { id: string }).id : null;

  let workspaceCount = 0;
  let runCount = 0;
  if (userId) {
    workspaceCount = await prisma.workspace.count({
      where: { OR: [{ ownerId: userId }, { members: { some: { userId } } }] },
    });
    runCount = await prisma.executionRun.count({
      where: {
        workspace: { OR: [{ ownerId: userId }, { members: { some: { userId } } }] },
      },
    });
  }

  return (
    <div className="mx-auto max-w-6xl space-y-8 p-6 lg:p-10">
      <div className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight text-slate-900 dark:text-slate-50">
          Welcome back{session?.user?.name ? `, ${session.user.name.split(' ')[0]}` : ''}
        </h1>
        <p className="max-w-2xl text-muted-foreground">
          QAPtain maps your applications, expands scenarios with AI, and executes structured Playwright plans with
          self-healing selectors — all scoped per workspace.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card className="border-slate-200/80 shadow-sm dark:border-slate-800">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Workspaces</CardTitle>
            <Radar className="h-4 w-4 text-violet-600" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{workspaceCount}</div>
            <p className="text-xs text-muted-foreground">Applications under test</p>
          </CardContent>
        </Card>
        <Card className="border-slate-200/80 shadow-sm dark:border-slate-800">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Execution runs</CardTitle>
            <PlayCircle className="h-4 w-4 text-emerald-600" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{runCount}</div>
            <p className="text-xs text-muted-foreground">Recorded in PostgreSQL</p>
          </CardContent>
        </Card>
        <Card className="border-slate-200/80 bg-gradient-to-br from-violet-600 to-indigo-700 text-white shadow-md dark:from-violet-700 dark:to-indigo-900">
          <CardHeader>
            <CardTitle className="text-lg">Start here</CardTitle>
            <CardDescription className="text-violet-100">
              Create a workspace, attach credentials, run lightweight discovery, then execute scenarios.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button asChild variant="secondary" className="gap-2">
              <Link href="/workspaces/new">
                New workspace <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
