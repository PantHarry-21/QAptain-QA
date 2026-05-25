'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { ArrowRight, PlayCircle, Radar, Brain } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

export default function DashboardPage() {
  const [stats, setStats] = useState({ workspaces: 0, runs: 0, userName: '' });

  useEffect(() => {
    const token = localStorage.getItem('qaptain_token');
    if (!token) return;

    Promise.all([
      fetch(`${API_URL}/auth/me`, { headers: { Authorization: `Bearer ${token}` } }).then((r) => r.json()),
      fetch(`${API_URL}/workspaces`, { headers: { Authorization: `Bearer ${token}` } }).then((r) => r.json()),
    ]).then(([user, workspaceData]) => {
      setStats({
        workspaces: workspaceData?.total ?? 0,
        runs: 0,
        userName: user?.full_name ?? user?.email ?? '',
      });
    }).catch(() => {});
  }, []);

  const firstName = stats.userName.split(' ')[0];

  return (
    <div className="mx-auto max-w-6xl space-y-8 p-6 lg:p-10">
      <div className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight text-white">
          Welcome back{firstName ? `, ${firstName}` : ''}
        </h1>
        <p className="max-w-2xl text-slate-400">
          QAptain explores your applications, builds a semantic knowledge graph, and executes intelligent test scenarios via Selenium with self-healing selectors.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-xl shadow-sm">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-slate-300">Workspaces</CardTitle>
            <Radar className="h-4 w-4 text-violet-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-white">{stats.workspaces}</div>
            <p className="text-xs text-slate-400">Applications under test</p>
          </CardContent>
        </Card>
        <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-xl shadow-sm">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-slate-300">Execution Runs</CardTitle>
            <PlayCircle className="h-4 w-4 text-emerald-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-white">{stats.runs}</div>
            <p className="text-xs text-slate-400">Selenium runs recorded</p>
          </CardContent>
        </Card>
        <Card className="border-slate-800 bg-gradient-to-br from-violet-600 to-indigo-700 text-white shadow-md">
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Brain className="h-5 w-5" /> Start here
            </CardTitle>
            <CardDescription className="text-violet-100">
              Create a workspace, configure credentials, run explore, then execute scenarios.
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
