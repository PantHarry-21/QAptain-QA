'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { ArrowRight, PlayCircle, Radar, Brain, CheckCircle2, XCircle, Clock, TrendingUp } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { workspaces as workspacesApi, type Workspace } from '@/lib/api';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

interface Stats {
  workspaces: number;
  totalApps: number;
  runs: number;
  userName: string;
  avgReadiness: number;
}

const READINESS_COLORS = ['#ef4444', '#f97316', '#eab308', '#22c55e', '#10b981'];

function getReadinessColor(pct: number) {
  if (pct >= 80) return '#10b981';
  if (pct >= 60) return '#22c55e';
  if (pct >= 40) return '#eab308';
  if (pct >= 20) return '#f97316';
  return '#ef4444';
}

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats>({ workspaces: 0, totalApps: 0, runs: 0, userName: '', avgReadiness: 0 });
  const [workspaceList, setWorkspaceList] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('qaptain_token');
    if (!token) return;

    const headers = { Authorization: `Bearer ${token}` };

    Promise.all([
      fetch(`${API_URL}/auth/me`, { headers }).then((r) => r.json()).catch(() => ({})),
      workspacesApi.list().catch(() => []),
    ]).then(([user, wsData]) => {
      const list: Workspace[] = Array.isArray(wsData) ? wsData : [];
      const totalApps = list.reduce((sum, w) => sum + (w.application_count ?? 0), 0);
      const avgReadiness = list.length > 0
        ? Math.round(list.reduce((sum, w) => sum + (w.readiness ?? 0), 0) / list.length)
        : 0;
      setStats({
        workspaces: list.length,
        totalApps,
        runs: 0,
        userName: user?.full_name ?? user?.email ?? '',
        avgReadiness,
      });
      setWorkspaceList(list);
    }).catch(() => {}).finally(() => setLoading(false));
  }, []);

  const firstName = stats.userName.split(' ')[0] || stats.userName.split('@')[0];

  const chartData = workspaceList.map((w) => ({
    name: w.name.length > 14 ? w.name.slice(0, 14) + '…' : w.name,
    readiness: w.readiness ?? 0,
  }));

  return (
    <div className="mx-auto max-w-6xl space-y-8 p-6 lg:p-10">
      {/* Header */}
      <div className="space-y-1">
        <h1 className="text-3xl font-semibold tracking-tight text-white">
          Welcome back{firstName ? `, ${firstName}` : ''}
        </h1>
        <p className="max-w-2xl text-slate-400">
          QAptain explores your applications, builds a semantic knowledge graph, and executes intelligent test scenarios with self-healing selectors.
        </p>
      </div>

      {/* KPI cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-xl shadow-sm">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-slate-300">Workspaces</CardTitle>
            <Radar className="h-4 w-4 text-violet-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-white">{loading ? '—' : stats.workspaces}</div>
            <p className="text-xs text-slate-500 mt-1">Applications under test</p>
          </CardContent>
        </Card>

        <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-xl shadow-sm">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-slate-300">Applications</CardTitle>
            <Brain className="h-4 w-4 text-indigo-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-white">{loading ? '—' : stats.totalApps}</div>
            <p className="text-xs text-slate-500 mt-1">Across all workspaces</p>
          </CardContent>
        </Card>

        <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-xl shadow-sm">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-slate-300">Avg. Readiness</CardTitle>
            <TrendingUp className="h-4 w-4 text-emerald-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-white">{loading ? '—' : `${stats.avgReadiness}%`}</div>
            <Progress
              value={stats.avgReadiness}
              className="h-1.5 mt-2 bg-slate-800 [&>div]:bg-emerald-500"
            />
          </CardContent>
        </Card>

        <Card className="border-slate-800 bg-gradient-to-br from-violet-600 to-indigo-700 text-white shadow-md">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-violet-100">Quick Start</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <Button asChild variant="secondary" size="sm" className="w-full gap-2 text-xs">
              <Link href="/workspaces/new">
                New workspace <ArrowRight className="h-3 w-3" />
              </Link>
            </Button>
            {stats.workspaces > 0 && (
              <Button asChild variant="ghost" size="sm" className="w-full gap-2 text-xs text-violet-200 hover:text-white hover:bg-violet-500/20">
                <Link href="/workspaces">
                  View workspaces <ArrowRight className="h-3 w-3" />
                </Link>
              </Button>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Workspace readiness chart */}
      {!loading && workspaceList.length > 0 && (
        <div className="grid gap-6 lg:grid-cols-3">
          {/* Bar chart */}
          <Card className="lg:col-span-2 border-slate-800 bg-slate-900/60 backdrop-blur-xl shadow-sm">
            <CardHeader>
              <CardTitle className="text-sm font-medium text-white">Workspace Readiness</CardTitle>
              <CardDescription className="text-slate-400 text-xs">
                KG coverage & exploration completeness per workspace
              </CardDescription>
            </CardHeader>
            <CardContent>
              {chartData.length > 0 ? (
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={chartData} margin={{ top: 4, right: 8, left: -16, bottom: 4 }}>
                    <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} />
                    <YAxis domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} unit="%" />
                    <Tooltip
                      contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
                      labelStyle={{ color: '#f1f5f9' }}
                      itemStyle={{ color: '#94a3b8' }}
                      formatter={(v: number) => [`${v}%`, 'Readiness']}
                    />
                    <Bar dataKey="readiness" radius={[4, 4, 0, 0]}>
                      {chartData.map((entry, i) => (
                        <Cell key={i} fill={getReadinessColor(entry.readiness)} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-[180px] flex items-center justify-center text-slate-500 text-sm">
                  No workspaces yet
                </div>
              )}
            </CardContent>
          </Card>

          {/* Workspace list */}
          <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-xl shadow-sm">
            <CardHeader>
              <CardTitle className="text-sm font-medium text-white">Workspaces</CardTitle>
              <CardDescription className="text-slate-400 text-xs">
                {stats.workspaces} workspace{stats.workspaces !== 1 ? 's' : ''}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {workspaceList.slice(0, 5).map((w) => (
                <Link key={w.id} href={`/workspaces/${w.id}`} className="block group">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="text-sm text-slate-200 group-hover:text-violet-300 transition-colors truncate">{w.name}</div>
                      <div className="text-xs text-slate-500">{w.application_count ?? 0} app{(w.application_count ?? 0) !== 1 ? 's' : ''}</div>
                    </div>
                    <div className="shrink-0 text-right">
                      <div className="text-xs font-medium" style={{ color: getReadinessColor(w.readiness ?? 0) }}>
                        {w.readiness ?? 0}%
                      </div>
                    </div>
                  </div>
                  <Progress
                    value={w.readiness ?? 0}
                    className="h-1 mt-1.5 bg-slate-800"
                    style={{ '--progress-color': getReadinessColor(w.readiness ?? 0) } as React.CSSProperties}
                  />
                </Link>
              ))}
              {workspaceList.length > 5 && (
                <Link href="/workspaces" className="text-xs text-violet-400 hover:text-violet-300 transition-colors">
                  +{workspaceList.length - 5} more →
                </Link>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* How it works */}
      <Card className="border-slate-800 bg-slate-900/40 backdrop-blur-xl shadow-sm">
        <CardHeader>
          <CardTitle className="text-sm font-medium text-white">How QAptain works</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-4">
            {[
              { icon: <Radar className="h-5 w-5 text-violet-400" />, title: '1. Connect', desc: 'Add your app URL and credentials' },
              { icon: <Brain className="h-5 w-5 text-indigo-400" />, title: '2. Explore', desc: 'AI maps UI and builds a Knowledge Graph' },
              { icon: <PlayCircle className="h-5 w-5 text-emerald-400" />, title: '3. Execute', desc: 'Run generated scenarios against your app' },
              { icon: <TrendingUp className="h-5 w-5 text-blue-400" />, title: '4. Report', desc: 'Get quality scores and fix insights' },
            ].map((step) => (
              <div key={step.title} className="flex flex-col gap-2">
                <div className="w-9 h-9 rounded-lg bg-slate-800 flex items-center justify-center">
                  {step.icon}
                </div>
                <div className="text-sm font-medium text-slate-200">{step.title}</div>
                <div className="text-xs text-slate-500">{step.desc}</div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
