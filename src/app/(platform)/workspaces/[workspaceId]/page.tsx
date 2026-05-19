'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams, useSearchParams } from 'next/navigation';
import { io, type Socket } from 'socket.io-client';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { EXECUTION_MODES, type ExecutionMode } from '@/lib/execution-modes';

const EXECUTION_MODE_LABEL: Record<ExecutionMode, string> = {
  smoke: 'Smoke',
  functional: 'Functional',
  validation_heavy: 'Validation heavy',
  regression: 'Regression',
  deep_validation: 'Deep validation',
};

type HubData = {
  workspace: { id: string; name: string; description: string | null };
  environments: { id: string; name: string; baseUrl: string }[];
  authProfiles: { id: string; name: string }[];
  modules: {
    id: string;
    name: string;
    routePattern: string | null;
    routes: { path: string; title: string | null; discoveryMeta?: unknown }[];
  }[];
  lastDiscovery: { id: string; status: string; progress: number; summary: unknown } | null;
  scenarioCount: number;
  readiness: number;
};

type FieldRow = {
  id: string;
  fieldKey: string;
  label: string | null;
  fieldType: string;
  semanticClass: string | null;
  semanticMeaning: string | null;
  required: boolean;
  minLength: number | null;
  maxLength: number | null;
  testPriority: number;
  routeFingerprint: string;
  _count?: { validations: number };
};

function routePageType(routes: { discoveryMeta?: unknown }[]): string {
  for (const r of routes) {
    const meta = r.discoveryMeta as { pageType?: string } | null | undefined;
    if (meta?.pageType) return meta.pageType;
  }
  return '—';
}

type IntelBundle = {
  navigationGraph: {
    confidence: number | null;
    graph: { nodes?: unknown[]; edges?: unknown[]; version?: number; generatedAt?: string };
    updatedAt: string;
  } | null;
  workflows: { workflowKey: string; displayName: string | null; confidence: number; source: string }[];
  apiEndpoints: {
    pathPattern: string;
    method: string;
    sampleCount: number;
    lastStatusCode?: number | null;
    module: { name: string } | null;
  }[];
};

export default function WorkspaceHubPage() {
  const params = useParams();
  const workspaceId = String(params.workspaceId || '');
  const searchParams = useSearchParams();
  const discoveryParam = searchParams.get('discovery');

  const [data, setData] = useState<HubData | null>(null);
  const [insights, setInsights] = useState<Record<string, unknown> | null>(null);
  const [scenarios, setScenarios] = useState<{ id: string; title: string; steps: string[]; riskScore: number | null }[]>(
    [],
  );
  const [runs, setRuns] = useState<
    {
      id: string;
      status: string;
      createdAt: string;
      passedSteps: number;
      failedSteps: number;
      executionMode?: string;
    }[]
  >([]);
  const [fields, setFields] = useState<FieldRow[]>([]);
  const [validationRuleCount, setValidationRuleCount] = useState(0);
  const [expandMode, setExpandMode] = useState<ExecutionMode>('functional');
  const [runMode, setRunMode] = useState<ExecutionMode>('functional');
  const [intel, setIntel] = useState<IntelBundle | null>(null);
  const [socket, setSocket] = useState<Socket | null>(null);
  const [live, setLive] = useState<{ progress?: number; status?: string; log?: string }>({});
  const [boot, setBoot] = useState(true);

  // Settings tab state
  const [editName, setEditName] = useState('');
  const [editDesc, setEditDesc] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  const refresh = useCallback(async () => {
    if (!workspaceId) return;
    try {
      const [w, s, r, ins, fld, intelRes] = await Promise.all([
        fetch(`/api/v1/workspaces/${workspaceId}`).then((x) => x.json()),
        fetch(`/api/v1/workspaces/${workspaceId}/scenarios`).then((x) => x.json()),
        fetch(`/api/v1/workspaces/${workspaceId}/runs`).then((x) => x.json()),
        fetch(`/api/v1/workspaces/${workspaceId}/insights`).then((x) => x.json()),
        fetch(`/api/v1/workspaces/${workspaceId}/fields`).then((x) => x.json()),
        fetch(`/api/v1/workspaces/${workspaceId}/intel`).then((x) => x.json()),
      ]);
      setData({
        workspace: w.workspace,
        environments: w.environments || [],
        authProfiles: w.authProfiles || [],
        modules: w.modules || [],
        lastDiscovery: w.lastDiscovery || null,
        scenarioCount: w.scenarioCount ?? 0,
        readiness: w.readiness ?? 0,
      });
      if (w.workspace) {
        setEditName(w.workspace.name || '');
        setEditDesc(w.workspace.description || '');
      }
      setScenarios(s.scenarios || []);
      setRuns(r.runs || []);
      setInsights(ins);
      setFields(fld.fields || []);
      setValidationRuleCount(Number(fld.validationRuleCount) || 0);
      if (intelRes && !intelRes.error) {
        setIntel({
          navigationGraph: intelRes.navigationGraph
            ? {
                confidence: intelRes.navigationGraph.confidence,
                graph: (intelRes.navigationGraph.graph || {}) as {
                  nodes?: unknown[];
                  edges?: unknown[];
                  version?: number;
                  generatedAt?: string;
                },
                updatedAt: intelRes.navigationGraph.updatedAt,
              }
            : null,
          workflows: intelRes.workflows || [],
          apiEndpoints: intelRes.apiEndpoints || [],
        });
      } else {
        setIntel(null);
      }
    } finally {
      setBoot(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const origin = typeof window !== 'undefined' ? window.location.origin : '';
    const s = io(origin, { path: '/api/socketio' });
    setSocket(s);
    return () => {
      s.disconnect();
    };
  }, []);

  useEffect(() => {
    if (!socket || !discoveryParam) return;
    socket.emit('join-run', { runId: discoveryParam });
    const onStatus = (payload: { status?: string }) =>
      setLive((prev) => ({ ...prev, status: payload?.status }));
    const onLog = (payload: { message?: string }) =>
      setLive((prev) => ({ ...prev, log: payload?.message }));
    socket.on('discovery-status', onStatus);
    socket.on('run-log', onLog);
    const iv = setInterval(() => void refresh(), 4000);
    return () => {
      socket.off('discovery-status', onStatus);
      socket.off('run-log', onLog);
      clearInterval(iv);
    };
  }, [socket, discoveryParam, refresh]);

  const [newTitle, setNewTitle] = useState('');
  const [newSteps, setNewSteps] = useState('');

  const addScenario = async () => {
    if (!newTitle.trim()) return;
    const steps = newSteps
      .split(/\n+/)
      .map((l) => l.trim())
      .filter(Boolean);
    await fetch(`/api/v1/workspaces/${workspaceId}/scenarios`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: newTitle, steps }),
    });
    setNewTitle('');
    setNewSteps('');
    void refresh();
  };

  const expandScenario = async (id: string) => {
    await fetch(`/api/v1/workspaces/${workspaceId}/scenarios/${id}/expand`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ executionMode: expandMode }),
    });
    void refresh();
  };

  const runScenario = async (scenarioId: string) => {
    const r = await fetch(`/api/v1/workspaces/${workspaceId}/runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenarioId, executionMode: runMode }),
    });
    const j = await r.json();
    if (j.run?.id) {
      window.location.href = `/workspaces/${workspaceId}/runs/${j.run.id}`;
    }
  };

  const saveWorkspace = async () => {
    setIsSaving(true);
    try {
      await fetch(`/api/v1/workspaces/${workspaceId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: editName, description: editDesc }),
      });
      void refresh();
    } finally {
      setIsSaving(false);
    }
  };

  const deleteWorkspace = async () => {
    if (!confirm('Are you sure you want to delete this workspace? This cannot be undone.')) return;
    await fetch(`/api/v1/workspaces/${workspaceId}`, {
      method: 'DELETE',
    });
    window.location.href = '/workspaces';
  };

  const header = useMemo(
    () => (
      <div className="space-y-1 border-b border-slate-800 bg-slate-900/40 px-6 py-6 backdrop-blur-xl lg:px-10">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight text-white">{data?.workspace.name || '…'}</h1>
          {data && <Badge variant="outline" className="border-violet-500/30 text-violet-300">Readiness {data.readiness}%</Badge>}
        </div>
        <p className="max-w-3xl text-sm text-slate-400">{data?.workspace.description || '—'}</p>
        {data && (
          <div className="max-w-md pt-2">
            <Progress value={data.readiness} className="h-2 bg-slate-800 [&>div]:bg-violet-500" />
          </div>
        )}
      </div>
    ),
    [data],
  );

  if (boot && !data) {
    return <div className="flex min-h-[40vh] items-center justify-center text-slate-400 animate-pulse">Loading workspace…</div>;
  }

  if (!data) return null;

  return (
    <div className="min-h-screen bg-transparent relative z-10">
      {header}
      <div className="mx-auto max-w-6xl px-4 py-6 lg:px-8">
        <Tabs defaultValue={searchParams.get('tab') || 'overview'} className="space-y-6">
          <TabsList className="flex flex-wrap gap-1 bg-slate-900/60 backdrop-blur-xl border border-slate-800 p-1">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="discovery">Discovery</TabsTrigger>
            <TabsTrigger value="modules">Modules</TabsTrigger>
            <TabsTrigger value="fields">Fields</TabsTrigger>
            <TabsTrigger value="scenarios">Scenarios</TabsTrigger>
            <TabsTrigger value="runs">Executions</TabsTrigger>
            <TabsTrigger value="reports">Reports</TabsTrigger>
            <TabsTrigger value="intel">Intel</TabsTrigger>
            <TabsTrigger value="requirements">Requirements</TabsTrigger>
            <TabsTrigger value="insights">AI insights</TabsTrigger>
            <TabsTrigger value="settings">Settings</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="space-y-4">
            <div className="grid gap-4 md:grid-cols-3">
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Environments</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2 text-sm">
                  {data?.environments.map((e) => (
                    <div key={e.id} className="rounded-md border border-slate-200/80 p-2 dark:border-slate-800">
                      <div className="font-medium">{e.name}</div>
                      <div className="break-all text-muted-foreground">{e.baseUrl}</div>
                    </div>
                  ))}
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Auth profiles</CardTitle>
                </CardHeader>
                <CardContent className="text-sm">
                  {(data?.authProfiles.length || 0) === 0 ? (
                    <p className="text-muted-foreground">Add credentials via the wizard or API.</p>
                  ) : (
                    <ul className="list-disc space-y-1 pl-4">
                      {data?.authProfiles.map((a) => (
                        <li key={a.id}>{a.name}</li>
                      ))}
                    </ul>
                  )}
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Last discovery</CardTitle>
                </CardHeader>
                <CardContent className="text-sm">
                  {data?.lastDiscovery ? (
                    <div className="space-y-1">
                      <Badge>{data.lastDiscovery.status}</Badge>
                      <div>Progress: {data.lastDiscovery.progress}%</div>
                    </div>
                  ) : (
                    <p className="text-muted-foreground">No runs yet.</p>
                  )}
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          <TabsContent value="discovery">
            <Card>
              <CardHeader>
                <CardTitle>Discovery</CardTitle>
                <CardDescription>
                  Lightweight Playwright crawl: routes, forms, API samples, and page-type hints (Phase 2). Jobs run in
                  the worker (Redis + BullMQ).
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {discoveryParam && (
                  <div className="rounded-lg border border-violet-200 bg-violet-50/80 p-4 text-sm dark:border-violet-900 dark:bg-violet-950/40">
                    <div className="font-medium">Tracking run {discoveryParam}</div>
                    <div>Socket status: {live.status || '—'}</div>
                    {live.log && <div className="mt-2 text-muted-foreground">{live.log}</div>}
                  </div>
                )}
                <Button
                  onClick={async () => {
                    const env = data?.environments[0];
                    const auth = data?.authProfiles[0];
                    if (!env || !auth) return;
                    const r = await fetch(`/api/v1/workspaces/${workspaceId}/discovery`, {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ environmentId: env.id, authProfileId: auth.id }),
                    });
                    const j = await r.json();
                    if (j.discoveryRun?.id) {
                      window.location.search = `?discovery=${j.discoveryRun.id}`;
                    }
                    void refresh();
                  }}
                >
                  Queue discovery job
                </Button>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="modules">
            <Card>
              <CardHeader>
                <CardTitle>Application map</CardTitle>
                <CardDescription>Modules and routes captured from lightweight discovery.</CardDescription>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Module</TableHead>
                      <TableHead>Route</TableHead>
                      <TableHead>Page type</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(data?.modules || []).map((m) => (
                      <TableRow key={m.id}>
                        <TableCell className="font-medium">{m.name}</TableCell>
                        <TableCell className="text-muted-foreground">{m.routePattern || m.routes[0]?.path}</TableCell>
                        <TableCell className="text-xs capitalize text-muted-foreground">{routePageType(m.routes)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="fields">
            <Card>
              <CardHeader>
                <CardTitle>Field intelligence</CardTitle>
                <CardDescription>
                  Inferred from discovery DOM, labels, HTML constraints, and validation rules. Workspace rules:{' '}
                  <span className="font-medium text-foreground">{validationRuleCount}</span>.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {fields.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Run discovery to populate fields.</p>
                ) : (
                  <div className="max-h-[560px] overflow-auto rounded-md border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Key</TableHead>
                          <TableHead>Label</TableHead>
                          <TableHead>Type</TableHead>
                          <TableHead>Semantic</TableHead>
                          <TableHead>Req</TableHead>
                          <TableHead>Priority</TableHead>
                          <TableHead>Rules</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {fields.map((f) => (
                          <TableRow key={f.id}>
                            <TableCell className="max-w-[140px] truncate font-mono text-xs">{f.fieldKey}</TableCell>
                            <TableCell className="max-w-[160px] truncate text-sm">{f.label || '—'}</TableCell>
                            <TableCell className="text-xs">{f.fieldType}</TableCell>
                            <TableCell className="text-xs">
                              {f.semanticClass || '—'}
                              {f.semanticMeaning ? (
                                <span className="block text-muted-foreground">{f.semanticMeaning}</span>
                              ) : null}
                            </TableCell>
                            <TableCell>{f.required ? 'Yes' : '—'}</TableCell>
                            <TableCell>{f.testPriority}</TableCell>
                            <TableCell>{f._count?.validations ?? 0}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="scenarios" className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>Add scenario</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <Input placeholder="Title" value={newTitle} onChange={(e) => setNewTitle(e.target.value)} />
                <Textarea
                  placeholder="One step per line (natural language)"
                  value={newSteps}
                  onChange={(e) => setNewSteps(e.target.value)}
                  rows={4}
                />
                <Button onClick={addScenario}>Save scenario</Button>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Library</CardTitle>
                <CardDescription>
                  Expansion depth and data profiles follow the selected execution mode (caps avoid combinatorial
                  explosion).
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex flex-wrap items-end gap-4 rounded-lg border border-slate-200/80 bg-slate-50/80 p-4 dark:border-slate-800 dark:bg-slate-900/40">
                  <div className="space-y-2">
                    <Label htmlFor="expand-mode">AI expand mode</Label>
                    <Select value={expandMode} onValueChange={(v) => setExpandMode(v as ExecutionMode)}>
                      <SelectTrigger id="expand-mode" className="w-[200px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {EXECUTION_MODES.map((m) => (
                          <SelectItem key={m} value={m}>
                            {EXECUTION_MODE_LABEL[m]}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="run-mode">Run mode</Label>
                    <Select value={runMode} onValueChange={(v) => setRunMode(v as ExecutionMode)}>
                      <SelectTrigger id="run-mode" className="w-[200px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {EXECUTION_MODES.map((m) => (
                          <SelectItem key={m} value={m}>
                            {EXECUTION_MODE_LABEL[m]}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                {scenarios.map((s) => (
                  <div
                    key={s.id}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200/80 p-3 dark:border-slate-800"
                  >
                    <div>
                      <div className="font-medium">{s.title}</div>
                      <div className="text-xs text-muted-foreground">{s.steps.length} step(s)</div>
                      {s.riskScore != null && <Badge variant="secondary">Risk {s.riskScore}</Badge>}
                    </div>
                    <div className="flex gap-2">
                      <Button size="sm" variant="outline" onClick={() => expandScenario(s.id)}>
                        AI expand
                      </Button>
                      <Button size="sm" onClick={() => runScenario(s.id)}>
                        Run
                      </Button>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="runs">
            <Card>
              <CardHeader>
                <CardTitle>Execution history</CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Run</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Mode</TableHead>
                      <TableHead>Steps</TableHead>
                      <TableHead />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {runs.map((r) => (
                      <TableRow key={r.id}>
                        <TableCell className="font-mono text-xs">{r.id.slice(0, 8)}…</TableCell>
                        <TableCell>
                          <Badge variant="outline">{r.status}</Badge>
                        </TableCell>
                        <TableCell className="text-xs capitalize text-muted-foreground">
                          {r.executionMode ? EXECUTION_MODE_LABEL[r.executionMode as ExecutionMode] || r.executionMode : '—'}
                        </TableCell>
                        <TableCell>
                          {r.passedSteps}/{r.passedSteps + r.failedSteps}
                        </TableCell>
                        <TableCell>
                          <Button size="sm" variant="ghost" asChild>
                            <a href={`/workspaces/${workspaceId}/runs/${r.id}`}>Open</a>
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="reports">
            <Card>
              <CardHeader>
                <CardTitle>Reports</CardTitle>
                <CardDescription>Per-run summaries are stored with each execution.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                {runs.slice(0, 10).map((r) => (
                  <div key={r.id} className="flex justify-between rounded-md border p-2">
                    <span className="font-mono text-xs">{r.id}</span>
                    <a className="text-violet-600 hover:underline" href={`/workspaces/${workspaceId}/runs/${r.id}`}>
                      View run & report
                    </a>
                  </div>
                ))}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="intel" className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>Application graph</CardTitle>
                <CardDescription>
                  Deterministic navigation graph and API surface from the last successful discovery (Phase 3
                  foundation).
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                {!intel?.navigationGraph ? (
                  <p className="text-muted-foreground">Run discovery to generate a navigation graph and API rollup.</p>
                ) : (
                  <>
                    <div className="flex flex-wrap gap-3">
                      <Badge variant="outline">
                        Confidence {intel.navigationGraph.confidence != null ? intel.navigationGraph.confidence : '—'}
                      </Badge>
                      <span className="text-muted-foreground">
                        Nodes: {intel.navigationGraph.graph.nodes?.length ?? 0} · Edges:{' '}
                        {intel.navigationGraph.graph.edges?.length ?? 0}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        Updated {new Date(intel.navigationGraph.updatedAt).toLocaleString()}
                      </span>
                    </div>
                    <details className="rounded-md border p-2">
                      <summary className="cursor-pointer text-xs font-medium">Raw graph JSON</summary>
                      <pre className="mt-2 max-h-64 overflow-auto text-xs">
                        {JSON.stringify(intel.navigationGraph.graph, null, 2)}
                      </pre>
                    </details>
                  </>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Workflow intelligence</CardTitle>
                <CardDescription>Stored workflow hypotheses (deterministic surface until full inference ships).</CardDescription>
              </CardHeader>
              <CardContent>
                {!intel?.workflows?.length ? (
                  <p className="text-sm text-muted-foreground">No workflows yet.</p>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Key</TableHead>
                        <TableHead>Name</TableHead>
                        <TableHead>Confidence</TableHead>
                        <TableHead>Source</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {intel.workflows.map((w) => (
                        <TableRow key={w.workflowKey}>
                          <TableCell className="font-mono text-xs">{w.workflowKey}</TableCell>
                          <TableCell>{w.displayName || '—'}</TableCell>
                          <TableCell>{w.confidence}</TableCell>
                          <TableCell className="text-xs text-muted-foreground">{w.source}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>API intelligence</CardTitle>
                <CardDescription>Observed API paths (rollup; method defaults to GET until response capture expands).</CardDescription>
              </CardHeader>
              <CardContent>
                {!intel?.apiEndpoints?.length ? (
                  <p className="text-sm text-muted-foreground">No API observations yet.</p>
                ) : (
                  <div className="max-h-[360px] overflow-auto rounded-md border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Path</TableHead>
                          <TableHead>Method</TableHead>
                          <TableHead>Last status</TableHead>
                          <TableHead>Samples</TableHead>
                          <TableHead>Module hint</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {intel.apiEndpoints.map((a) => (
                          <TableRow key={`${a.method}:${a.pathPattern}`}>
                            <TableCell className="max-w-[280px] truncate font-mono text-xs">{a.pathPattern}</TableCell>
                            <TableCell className="text-xs">{a.method}</TableCell>
                            <TableCell className="text-xs">{a.lastStatusCode ?? '—'}</TableCell>
                            <TableCell>{a.sampleCount}</TableCell>
                            <TableCell className="text-xs">{a.module?.name || '—'}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>
          <TabsContent value="requirements" className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>Requirement Intelligence</CardTitle>
                <CardDescription>
                  Paste your PRD, User Story, or requirement text below. QAPtain will analyze the workflows and generate a
                  comprehensive testing strategy.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div
                  className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-slate-200 p-8 transition-colors hover:border-violet-400 dark:border-slate-800"
                  onDragOver={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                  }}
                  onDrop={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const file = e.dataTransfer.files[0];
                    if (file) {
                      const reader = new FileReader();
                      reader.onload = (re) => {
                        const text = re.target?.result as string;
                        (document.getElementById('requirement-text') as HTMLTextAreaElement).value = text;
                      };
                      reader.readAsText(file);
                    }
                  }}
                >
                  <Label htmlFor="requirement-file" className="mb-2 cursor-pointer text-sm text-muted-foreground">
                    Drag and drop a PRD (.txt, .md, .json) or
                  </Label>
                  <Input
                    id="requirement-file"
                    type="file"
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) {
                        const reader = new FileReader();
                        reader.onload = (re) => {
                          const text = re.target?.result as string;
                          (document.getElementById('requirement-text') as HTMLTextAreaElement).value = text;
                        };
                        reader.readAsText(file);
                      }
                    }}
                  />
                  <Button variant="outline" size="sm" onClick={() => document.getElementById('requirement-file')?.click()}>
                    Choose file
                  </Button>
                </div>
                <div className="text-xs font-medium text-muted-foreground">OR PASTE TEXT</div>
                <Textarea
                  placeholder="Paste PRD or User Story here..."
                  className="min-h-[200px] font-mono text-sm"
                  id="requirement-text"
                />
                <div className="flex gap-2">
                  <Button
                    onClick={async () => {
                      const text = (document.getElementById('requirement-text') as HTMLTextAreaElement).value;
                      if (!text) return;
                      setLive((prev) => ({ ...prev, status: 'Analyzing requirement...' }));
                      const r = await fetch(`/api/v1/workspaces/${workspaceId}/analyze-requirement`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ text }),
                      });
                      const j = await r.json();
                      if (j.result) {
                        setInsights((prev) => ({ ...prev, requirementAnalysis: j.result }));
                      }
                      setLive((prev) => ({ ...prev, status: 'Analysis complete.' }));
                    }}
                  >
                    Analyze with AI
                  </Button>
                </div>
              </CardContent>
            </Card>

            {insights?.requirementAnalysis && (
              <div className="grid gap-4 lg:grid-cols-2">
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base text-violet-600">Testing Map & Workflows</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div>
                      <div className="text-xs font-bold uppercase text-muted-foreground">Workflows</div>
                      <div className="mt-2 space-y-2">
                        {(insights.requirementAnalysis as any).workflows.map((w: any, idx: number) => (
                          <div key={idx} className="rounded-md border p-2 text-sm">
                            <div className="font-medium">{w.name}</div>
                            <div className="text-xs text-muted-foreground">{w.steps.join(' → ')}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs font-bold uppercase text-muted-foreground">Validation Rules</div>
                      <ul className="mt-2 list-inside list-disc text-xs text-muted-foreground">
                        {(insights.requirementAnalysis as any).validationRules.map((r: any, idx: number) => (
                          <li key={idx}>
                            <span className="font-medium text-foreground">{r.field}:</span> {r.rule}
                          </li>
                        ))}
                      </ul>
                    </div>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle className="text-base text-emerald-600">Generated Scenarios</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="space-y-3">
                      {(insights.requirementAnalysis as any).scenarios.map((s: any, idx: number) => (
                        <div key={idx} className="group relative rounded-lg border p-3">
                          <div className="flex items-center justify-between">
                            <div className="font-medium">{s.title}</div>
                            <Badge variant="outline" className="capitalize">
                              {s.type}
                            </Badge>
                          </div>
                          <div className="mt-2 max-h-24 overflow-auto text-xs text-muted-foreground">
                            {s.steps.map((step: string, sIdx: number) => (
                              <div key={sIdx}>
                                {sIdx + 1}. {step}
                              </div>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                    <Button
                      className="w-full bg-emerald-600 hover:bg-emerald-700"
                      onClick={async () => {
                        setLive((prev) => ({ ...prev, status: 'Committing to library...' }));
                        await fetch(`/api/v1/workspaces/${workspaceId}/analyze-requirement`, {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({
                            text: (document.getElementById('requirement-text') as HTMLTextAreaElement).value,
                            commit: true,
                          }),
                        });
                        setLive((prev) => ({ ...prev, status: 'Scenarios saved.' }));
                        void refresh();
                      }}
                    >
                      Commit scenarios to library
                    </Button>
                  </CardContent>
                </Card>
              </div>
            )}
          </TabsContent>

          <TabsContent value="insights">
            <Card>
              <CardHeader>
                <CardTitle>Workspace intelligence</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-4 sm:grid-cols-2">
                <div>
                  <div className="text-sm text-muted-foreground">Modules</div>
                  <div className="text-2xl font-semibold">{String(insights?.modules ?? '—')}</div>
                </div>
                <div>
                  <div className="text-sm text-muted-foreground">Field definitions</div>
                  <div className="text-2xl font-semibold">{String(insights?.fields ?? '—')}</div>
                </div>
                <div>
                  <div className="text-sm text-muted-foreground">Avg. scenario risk score</div>
                  <div className="text-2xl font-semibold">
                    {insights?.avgRiskScore != null ? Number(insights.avgRiskScore).toFixed(1) : '—'}
                  </div>
                </div>
                <div>
                  <div className="text-sm text-muted-foreground">Runs by status</div>
                  <pre className="mt-1 rounded-md bg-slate-100 p-2 text-xs dark:bg-slate-900">
                    {JSON.stringify(insights?.runsByStatus || {}, null, 2)}
                  </pre>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="settings">
            <div className="grid gap-4 md:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle>Edit workspace</CardTitle>
                  <CardDescription>Update the name and description of this workspace.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="ws-name">Name</Label>
                    <Input id="ws-name" value={editName} onChange={(e) => setEditName(e.target.value)} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="ws-desc">Description</Label>
                    <Textarea
                      id="ws-desc"
                      value={editDesc}
                      onChange={(e) => setEditDesc(e.target.value)}
                      rows={3}
                    />
                  </div>
                  <Button onClick={saveWorkspace} disabled={isSaving}>
                    {isSaving ? 'Saving...' : 'Save changes'}
                  </Button>
                </CardContent>
              </Card>

              <Card className="border-red-200 dark:border-red-900">
                <CardHeader>
                  <CardTitle className="text-red-600 dark:text-red-400">Danger zone</CardTitle>
                  <CardDescription>Permanently delete this workspace and all associated data (modules, scenarios, runs).</CardDescription>
                </CardHeader>
                <CardContent>
                  <Button variant="destructive" onClick={deleteWorkspace}>
                    Delete workspace
                  </Button>
                </CardContent>
              </Card>
            </div>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
