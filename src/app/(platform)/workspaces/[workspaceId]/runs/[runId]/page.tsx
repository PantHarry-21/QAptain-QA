'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { io, type Socket } from 'socket.io-client';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

type RunDetail = {
  id: string;
  status: string;
  executionMode?: string;
  plan?: { plan: unknown };
  steps: {
    stepOrder: number;
    action: string;
    status: string;
    error: string | null;
    recoveryLog?: unknown;
    rcaAnalysis?: {
      category: string;
      summary: string;
      rootCause: string;
      impact: string;
      remediation: string;
      isHealable: boolean;
      confidence: number;
    } | null;
    screenshotPath?: string | null;
  }[];
  logs: { level: string; message: string; createdAt: string }[];
  report?: {
    summary: string;
    riskLevel: string | null;
    aiSummary?: string | null;
    fieldValidationSummary?: unknown;
    selectorDiagnostics?: unknown;
    recoverySummary?: unknown;
    timeline?: unknown;
    generatedDataLog?: unknown;
  };
};

function JsonBlock({ title, data }: { title: string; data: unknown }) {
  if (data === undefined || data === null) return null;
  const text = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
  if (!text || text === '{}' || text === '[]') return null;
  return (
    <div className="space-y-1">
      <div className="text-xs font-medium text-muted-foreground">{title}</div>
      <pre className="max-h-[280px] overflow-auto rounded-md border bg-slate-50 p-3 text-xs dark:bg-slate-900">{text}</pre>
    </div>
  );
}

export default function RunDetailPage() {
  const params = useParams();
  const workspaceId = String(params.workspaceId || '');
  const runId = String(params.runId || '');
  const [run, setRun] = useState<RunDetail | null>(null);

  const load = async () => {
    const r = await fetch(`/api/v1/workspaces/${workspaceId}/runs/${runId}`);
    const j = await r.json();
    setRun(j.run);
  };

  useEffect(() => {
    void load();
  }, [workspaceId, runId]);

  useEffect(() => {
    const origin = typeof window !== 'undefined' ? window.location.origin : '';
    const s = io(origin, { path: '/api/socketio' });
    s.emit('join-run', { runId });
    const onLog = () => void load();
    s.on('run-log', onLog);
    s.on('run-status', onLog);
    s.on('run-completed', onLog);
    const iv = setInterval(() => void load(), 3000);
    return () => {
      s.off('run-log', onLog);
      s.off('run-status', onLog);
      s.off('run-completed', onLog);
      s.disconnect();
      clearInterval(iv);
    };
  }, [runId, workspaceId]);

  const stop = async () => {
    await fetch(`/api/v1/workspaces/${workspaceId}/runs/${runId}/stop`, { method: 'POST' });
  };

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6 lg:p-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Execution run</h1>
          <p className="font-mono text-xs text-muted-foreground">{runId}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {run && <Badge variant="outline">{run.status}</Badge>}
          {run?.executionMode && (
            <Badge variant="secondary" className="capitalize">
              {run.executionMode.replace(/_/g, ' ')}
            </Badge>
          )}
          <Button variant="outline" size="sm" onClick={stop}>
            Request stop
          </Button>
          <Button variant="ghost" size="sm" asChild>
            <a href={`/workspaces/${workspaceId}`}>← Workspace</a>
          </Button>
        </div>
      </div>

      {run?.report && (
        <Card>
          <CardHeader>
            <CardTitle>Report</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 text-sm">
            <div className="text-muted-foreground">Risk: {run.report.riskLevel}</div>
            <p>{run.report.summary}</p>
            {run.report.aiSummary ? (
              <div className="space-y-1 border-t pt-3">
                <div className="text-xs font-medium text-muted-foreground">AI reasoning summary</div>
                <p className="whitespace-pre-wrap">{run.report.aiSummary}</p>
              </div>
            ) : null}
            <div className="grid gap-4 border-t pt-3 md:grid-cols-2">
              <JsonBlock title="Field validation" data={run.report.fieldValidationSummary} />
              <JsonBlock title="Selector diagnostics" data={run.report.selectorDiagnostics} />
              <JsonBlock title="Recovery summary" data={run.report.recoverySummary} />
              <JsonBlock title="Generated data log" data={run.report.generatedDataLog} />
            </div>
            <JsonBlock title="Execution timeline" data={run.report.timeline} />
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Steps</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm font-mono">
          {(run?.steps || []).map((s) => (
            <div key={s.stepOrder} className="space-y-1 border-b border-dashed py-2 last:border-0">
              <div className="flex justify-between gap-2">
                <span>
                  {s.stepOrder + 1}. {s.action}
                </span>
                <span className={s.status === 'failed' ? 'text-red-600' : 'text-emerald-600'}>{s.status}</span>
              </div>
              {s.error && <div className="text-xs text-red-600">{s.error}</div>}
              {s.recoveryLog && (
                <pre className="max-h-[200px] overflow-auto rounded-md border bg-slate-50 p-2 text-[11px] dark:bg-slate-900">
                  {typeof s.recoveryLog === 'string' ? s.recoveryLog : JSON.stringify(s.recoveryLog, null, 2)}
                </pre>
              )}
              {s.rcaAnalysis && (
                <div className="mt-2 space-y-2 rounded-lg border border-red-100 bg-red-50/50 p-3 dark:border-red-900/30 dark:bg-red-950/20">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-bold uppercase tracking-wider text-red-600 dark:text-red-400">
                      AI Root Cause Analysis
                    </span>
                    <Badge variant="outline" className="bg-white dark:bg-slate-900">
                      {s.rcaAnalysis.category}
                    </Badge>
                  </div>
                  <div className="text-sm font-medium">{s.rcaAnalysis.summary}</div>
                  <div className="text-xs text-muted-foreground">
                    <span className="font-semibold">Reason:</span> {s.rcaAnalysis.rootCause}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    <span className="font-semibold">Remediation:</span> {s.rcaAnalysis.remediation}
                  </div>
                  <div className="flex items-center gap-3 pt-1 text-[10px] font-medium uppercase text-muted-foreground">
                    <span>Confidence: {Math.round(s.rcaAnalysis.confidence * 100)}%</span>
                    {s.rcaAnalysis.isHealable && (
                      <span className="text-emerald-600 dark:text-emerald-400">✓ Auto-Healable</span>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Live log</CardTitle>
        </CardHeader>
        <CardContent className="max-h-[420px] space-y-1 overflow-auto text-xs font-mono">
          {(run?.logs || []).map((l, i) => (
            <div key={i} className="whitespace-pre-wrap">
              <span className="text-muted-foreground">{new Date(l.createdAt).toLocaleTimeString()}</span>{' '}
              <span className="uppercase">{l.level}</span> {l.message}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
