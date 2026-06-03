'use client';

import { useEffect, useRef, useState } from 'react';
import { executions as executionsApi, type ExecutionRun, type ExecutionReport } from '@/lib/api';
import { getSocket } from '@/lib/websocket';

interface ExecutionDashboardProps {
  runId: string;
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface TimelineEntry {
  id: string;
  ts: string;          // ISO timestamp
  kind: 'log' | 'step_start' | 'step_done';
  level: 'INFO' | 'SUCCESS' | 'WARNING' | 'ERROR' | 'RUNNING';
  category: string;
  message: string;
  // step-specific
  stepNum?: number;
  action?: string;
  durationMs?: number;
  healing?: boolean;
}

// ── Config ────────────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<string, { label: string; dot: string; badge: string }> = {
  PENDING:   { label: 'Pending',   dot: 'bg-zinc-500',                badge: 'bg-zinc-800 text-zinc-400' },
  QUEUED:    { label: 'Queued',    dot: 'bg-zinc-400 animate-pulse',  badge: 'bg-zinc-800 text-zinc-400' },
  RUNNING:   { label: 'Running',   dot: 'bg-blue-500 animate-pulse',  badge: 'bg-blue-500/20 text-blue-300' },
  COMPLETED: { label: 'Passed',    dot: 'bg-green-500',               badge: 'bg-green-500/20 text-green-300' },
  FAILED:    { label: 'Failed',    dot: 'bg-red-500',                 badge: 'bg-red-500/20 text-red-300' },
  CANCELLED: { label: 'Cancelled', dot: 'bg-zinc-600',                badge: 'bg-zinc-800 text-zinc-500' },
};

const LEVEL_STYLES: Record<string, { dot: string; text: string }> = {
  INFO:    { dot: 'bg-blue-500/70',   text: 'text-zinc-400' },
  SUCCESS: { dot: 'bg-green-500',     text: 'text-green-300' },
  WARNING: { dot: 'bg-amber-500',     text: 'text-amber-300' },
  ERROR:   { dot: 'bg-red-500',       text: 'text-red-300' },
  RUNNING: { dot: 'bg-blue-500 animate-pulse', text: 'text-blue-300' },
};

const CATEGORY_ICONS: Record<string, string> = {
  login:     '🔐',
  batch:     '📦',
  execution: '⚡',
  step:      '▶',
  plan:      '📋',
  ai:        '🤖',
  network:   '🌐',
  system:    '⚙',
  report:    '📊',
};

function categoryIcon(cat: string): string {
  return CATEGORY_ICONS[cat?.toLowerCase()] || '·';
}

function tsToTime(iso: string): string {
  const raw = iso && !iso.endsWith('Z') && !iso.includes('+') ? iso + 'Z' : iso;
  try { return new Date(raw).toLocaleTimeString(); } catch { return '—'; }
}

// ── Main Component ────────────────────────────────────────────────────────────

export function ExecutionDashboard({ runId }: ExecutionDashboardProps) {
  const [run, setRun] = useState<ExecutionRun | null>(null);
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [report, setReport] = useState<ExecutionReport | null>(null);
  const [showReport, setShowReport] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  // Track the last DB log id for incremental polling — avoids re-fetching the entire log list
  const [lastLogId, setLastLogId] = useState<string | undefined>(undefined);
  const lastLogIdRef = useRef<string | undefined>(undefined);
  lastLogIdRef.current = lastLogId;
  const feedRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const socket = getSocket();

  // Merge log entries, deduplicating by id (handles WS + poll overlap)
  function mergeLogEntries(prev: TimelineEntry[], newEntries: TimelineEntry[]): TimelineEntry[] {
    if (newEntries.length === 0) return prev;
    const existingIds = new Set(prev.map((e) => e.id));
    const fresh = newEntries.filter((e) => !existingIds.has(e.id));
    return fresh.length > 0 ? [...prev, ...fresh] : prev;
  }

  // Add a client-side entry (WS step events that don't come through run_log)
  const addEntry = (entry: Omit<TimelineEntry, 'id'>) => {
    const id = `client-${Date.now()}-${Math.random()}`;
    setTimeline((prev) => [...prev, { ...entry, id }]);
  };

  // ── Initial load ─────────────────────────────────────────────────────────

  useEffect(() => {
    const load = async () => {
      const [r, logs] = await Promise.all([
        executionsApi.get(runId),
        executionsApi.getLogs(runId),
      ]);
      setRun(r);

      const seeded: TimelineEntry[] = logs.map((l) => ({
        id: l.id,
        ts: l.timestamp,
        kind: 'log' as const,
        level: (l.level || 'INFO') as TimelineEntry['level'],
        category: l.category || '',
        message: l.message || '',
      }));
      setTimeline(seeded);
      if (logs.length > 0) {
        const last = logs[logs.length - 1].id;
        setLastLogId(last);
        lastLogIdRef.current = last;
      }

      if (r.status === 'COMPLETED' || r.status === 'FAILED') {
        const rep = await executionsApi.getReport(runId);
        setReport(rep);
      }
    };
    load().catch(console.error);
  }, [runId]);

  // ── Poll run + logs (incremental via since_id) while active ──────────────

  useEffect(() => {
    if (!run) return;
    if (run.status === 'COMPLETED' || run.status === 'FAILED' || run.status === 'CANCELLED') return;

    const poll = async () => {
      try {
        // Fetch only logs newer than what we already have
        const [r, freshLogs] = await Promise.all([
          executionsApi.get(runId),
          executionsApi.getLogs(runId, lastLogIdRef.current),
        ]);
        setRun(r);

        if (freshLogs.length > 0) {
          const newEntries: TimelineEntry[] = freshLogs.map((l) => ({
            id: l.id,
            ts: l.timestamp,
            kind: 'log' as const,
            level: (l.level || 'INFO') as TimelineEntry['level'],
            category: l.category || '',
            message: l.message || '',
          }));
          setTimeline((prev) => mergeLogEntries(prev, newEntries));
          const newLastId = freshLogs[freshLogs.length - 1].id;
          setLastLogId(newLastId);
          lastLogIdRef.current = newLastId;
        }

        if (r.status === 'COMPLETED' || r.status === 'FAILED') {
          const rep = await executionsApi.getReport(runId);
          setReport(rep);
        }
      } catch { /* ignore poll errors */ }
    };

    const t = setInterval(poll, 2500);
    return () => clearInterval(t);
  }, [runId, run?.status]);

  // ── WebSocket real-time ──────────────────────────────────────────────────

  useEffect(() => {
    socket.connect();
    socket.subscribe(runId);

    const offLog = socket.on('run_log', (data) => {
      if (data.run_id !== runId) return;
      // Use server-provided id so polling deduplication works correctly.
      // If id is absent (old server), fall back to a random id.
      const entryId = data.id ? String(data.id) : `ws-${Date.now()}-${Math.random()}`;
      const ts = data.timestamp ? String(data.timestamp) : new Date().toISOString();
      setTimeline((prev) => {
        if (prev.some((e) => e.id === entryId)) return prev;  // already have it
        return [...prev, {
          id: entryId,
          ts,
          kind: 'log' as const,
          level: (data.level || 'INFO') as TimelineEntry['level'],
          category: String(data.category || ''),
          message: String(data.message || ''),
        }];
      });
      // Advance the incremental poll cursor so we don't re-fetch what WS delivered
      if (data.id) {
        lastLogIdRef.current = String(data.id);
        setLastLogId(String(data.id));
      }
    });

    const offStepStarted = socket.on('step_started', (data) => {
      if (data.run_id !== runId) return;
      addEntry({
        ts: new Date().toISOString(),
        kind: 'step_start',
        level: 'RUNNING',
        category: 'step',
        message: String(data.description || `Step ${data.step_num}`),
        stepNum: Number(data.step_num),
        action: String(data.action || ''),
      });
    });

    const offStepDone = socket.on('step_completed', (data) => {
      if (data.run_id !== runId) return;
      const ok = Boolean(data.success);
      addEntry({
        ts: new Date().toISOString(),
        kind: 'step_done',
        level: ok ? (data.healing_used ? 'WARNING' : 'SUCCESS') : 'ERROR',
        category: 'step',
        message: String(data.description || `Step ${Number(data.step_index) + 1}`),
        stepNum: Number(data.step_index) + 1,
        action: String(data.action || ''),
        durationMs: data.duration_ms ? Number(data.duration_ms) : undefined,
        healing: Boolean(data.healing_used),
      });
    });

    const offStarted = socket.on('run_started', (data) => {
      if (data.run_id !== runId) return;
      setRun((r) => r ? { ...r, status: 'RUNNING' } : r);
      addEntry({
        ts: new Date().toISOString(), kind: 'log', level: 'INFO',
        category: 'system', message: 'Execution started',
      });
    });

    const offComplete = socket.on('run_completed', async (data) => {
      if (data.run_id !== runId) return;
      const r = await executionsApi.get(runId);
      setRun(r);
      const rep = await executionsApi.getReport(runId);
      setReport(rep);
      addEntry({
        ts: new Date().toISOString(), kind: 'log', level: 'SUCCESS',
        category: 'system',
        message: `Execution complete — ${data.passed ?? 0}/${data.total ?? 0} steps passed`,
      });
    });

    const offFailed = socket.on('run_failed', async (data) => {
      if (data.run_id !== runId) return;
      const r = await executionsApi.get(runId);
      setRun(r);
      addEntry({
        ts: new Date().toISOString(), kind: 'log', level: 'ERROR',
        category: 'system', message: `Execution failed: ${data.reason || 'unknown error'}`,
      });
    });

    return () => { offLog(); offStepStarted(); offStepDone(); offStarted(); offComplete(); offFailed(); };
  }, [runId, socket]);

  // ── Auto-scroll ──────────────────────────────────────────────────────────

  useEffect(() => {
    if (autoScroll) bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [timeline, autoScroll]);

  const handleFeedScroll = () => {
    const el = feedRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    setAutoScroll(atBottom);
  };

  // ── Loading state ────────────────────────────────────────────────────────

  if (!run) {
    return (
      <div className="flex items-center justify-center h-64 text-zinc-500">
        <div className="animate-spin w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full mr-3" />
        Loading execution...
      </div>
    );
  }

  const status = STATUS_CONFIG[run.status] || STATUS_CONFIG.PENDING;
  const isActive = run.status === 'RUNNING' || run.status === 'QUEUED';
  const isDone = run.status === 'COMPLETED' || run.status === 'FAILED';
  const passRate = run.total_steps > 0 ? Math.round((run.passed_steps / run.total_steps) * 100) : 0;
  const progressPct = run.total_steps > 0
    ? ((run.passed_steps + run.failed_steps + run.healed_steps) / run.total_steps) * 100
    : 0;

  const stepsComplete = run.passed_steps + run.failed_steps + run.healed_steps;

  return (
    <div className="flex flex-col gap-4">

      {/* ── Header ── */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className={`w-2.5 h-2.5 rounded-full ${status.dot}`} />
            <h2 className="text-base font-semibold text-white">Execution Run</h2>
            <span className={`text-xs px-2.5 py-0.5 rounded-full font-medium ${status.badge}`}>
              {status.label}
            </span>
            {run.status === 'RUNNING' && run.total_steps > 0 && (
              <span className="text-xs text-zinc-500">
                {stepsComplete} / {run.total_steps} steps
              </span>
            )}
          </div>
          <div className="flex items-center gap-3">
            {isDone && report && (
              <button
                onClick={() => setShowReport((v) => !v)}
                className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                  showReport
                    ? 'bg-zinc-700 border-zinc-600 text-white'
                    : 'border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-600'
                }`}
              >
                {showReport ? 'Hide Report' : 'View Report'}
              </button>
            )}
            {isActive && (
              <button
                onClick={() => executionsApi.cancel(runId)}
                className="text-xs text-red-400 hover:text-red-300 border border-red-500/30 hover:border-red-500/50 px-3 py-1.5 rounded-lg transition-colors"
              >
                ■ Cancel
              </button>
            )}
          </div>
        </div>

        {/* Metrics row */}
        <div className="flex items-center gap-6">
          <StatChip label="Total" value={run.total_steps} />
          <StatChip label="Passed" value={run.passed_steps} color="text-green-400" />
          <StatChip label="Failed" value={run.failed_steps} color="text-red-400" />
          {run.healed_steps > 0 && <StatChip label="Healed" value={run.healed_steps} color="text-amber-400" />}
          {isDone && <StatChip label="Pass Rate" value={`${passRate}%`} color={passRate >= 80 ? 'text-green-400' : passRate >= 50 ? 'text-amber-400' : 'text-red-400'} />}
        </div>

        {/* Progress bar */}
        {run.total_steps > 0 && (
          <div className="mt-3 h-1 bg-zinc-800 rounded-full overflow-hidden flex gap-px">
            <div
              className="bg-green-500 h-full transition-all duration-500 rounded-l-full"
              style={{ width: `${(run.passed_steps / run.total_steps) * 100}%` }}
            />
            {run.healed_steps > 0 && (
              <div
                className="bg-amber-500 h-full transition-all duration-500"
                style={{ width: `${(run.healed_steps / run.total_steps) * 100}%` }}
              />
            )}
            {run.failed_steps > 0 && (
              <div
                className="bg-red-500 h-full transition-all duration-500 rounded-r-full"
                style={{ width: `${(run.failed_steps / run.total_steps) * 100}%` }}
              />
            )}
            {isActive && (
              <div
                className="bg-blue-500/40 h-full transition-all duration-500 rounded-r-full"
                style={{ width: `${Math.max(0, 100 - progressPct)}%` }}
              />
            )}
          </div>
        )}
      </div>

      {/* ── Live Execution Timeline ── */}
      <div className="bg-zinc-900/60 border border-zinc-800 rounded-xl overflow-hidden flex flex-col"
           style={{ minHeight: '420px', maxHeight: '65vh' }}>

        <div className="px-4 py-3 border-b border-zinc-800 flex items-center gap-2 shrink-0">
          {isActive
            ? <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
            : <div className={`w-2 h-2 rounded-full ${run.status === 'COMPLETED' ? 'bg-green-500' : 'bg-red-500'}`} />
          }
          <span className="text-sm font-medium text-zinc-300">
            {isActive ? 'Live Execution Log' : 'Execution Log'}
          </span>
          <span className="ml-auto text-xs text-zinc-600">{timeline.length} events</span>
          {!autoScroll && (
            <button
              onClick={() => { setAutoScroll(true); bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }}
              className="text-xs text-blue-400 hover:text-blue-300 ml-2"
            >
              ↓ scroll to bottom
            </button>
          )}
        </div>

        <div
          ref={feedRef}
          onScroll={handleFeedScroll}
          className="flex-1 overflow-y-auto p-4 space-y-0.5 font-mono text-xs"
        >
          {timeline.length === 0 && (
            <div className="text-center text-zinc-600 py-12">
              {run.status === 'QUEUED' ? (
                <div className="flex flex-col items-center gap-2">
                  <div className="w-4 h-4 border border-zinc-600 border-t-zinc-400 rounded-full animate-spin" />
                  <span>Waiting in queue...</span>
                </div>
              ) : 'No log entries yet.'}
            </div>
          )}

          {timeline.map((entry) => (
            <TimelineRow key={entry.id} entry={entry} />
          ))}

          {isActive && (
            <div className="flex items-center gap-3 pt-1 opacity-40">
              <span className="text-zinc-700 w-16 shrink-0" />
              <div className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse shrink-0" />
              <span className="text-zinc-600">·</span>
              <span className="text-zinc-600 italic">executing...</span>
            </div>
          )}

          <div ref={bottomRef} />
        </div>
      </div>

      {/* ── Report (inline, after completion) ── */}
      {isDone && report && showReport && (
        <ReportPanel report={report} />
      )}

      {/* ── Completion summary banner ── */}
      {isDone && !showReport && (
        <div className={`rounded-xl border p-4 flex items-center justify-between ${
          run.status === 'COMPLETED'
            ? 'bg-green-500/5 border-green-500/25'
            : 'bg-red-500/5 border-red-500/25'
        }`}>
          <div className="flex items-center gap-3">
            <span className="text-lg">{run.status === 'COMPLETED' ? '✓' : '✕'}</span>
            <div>
              <div className={`text-sm font-medium ${run.status === 'COMPLETED' ? 'text-green-300' : 'text-red-300'}`}>
                {run.status === 'COMPLETED'
                  ? `All ${run.total_steps} steps passed`
                  : `${run.failed_steps} of ${run.total_steps} steps failed`
                }
              </div>
              {report && (
                <div className="text-xs text-zinc-500 mt-0.5">
                  Quality score: {report.quality_score?.toFixed(0) ?? '—'} · Risk: {report.risk_level}
                </div>
              )}
            </div>
          </div>
          {report && (
            <button
              onClick={() => setShowReport(true)}
              className="text-xs text-zinc-400 hover:text-white border border-zinc-700 hover:border-zinc-600 px-3 py-1.5 rounded-lg transition-colors"
            >
              View Full Report →
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── Timeline Row ──────────────────────────────────────────────────────────────

function TimelineRow({ entry }: { entry: TimelineEntry }) {
  const style = LEVEL_STYLES[entry.level] || LEVEL_STYLES.INFO;
  const isStep = entry.kind === 'step_start' || entry.kind === 'step_done';

  if (isStep) {
    const success = entry.level === 'SUCCESS';
    const failed  = entry.level === 'ERROR';
    const running = entry.level === 'RUNNING';
    const healed  = entry.level === 'WARNING';

    return (
      <div className={`flex items-start gap-3 py-0.5 ${isStep ? 'pl-0' : ''}`}>
        <span className="text-zinc-600 text-[10px] pt-0.5 w-16 shrink-0">{tsToTime(entry.ts)}</span>
        <div className={`w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 ${style.dot}`} />
        <span className="text-zinc-600 shrink-0 w-4">▶</span>
        <span className={`font-mono text-[10px] px-1.5 py-0 rounded shrink-0 ${
          running ? 'bg-blue-500/15 text-blue-400' :
          success ? 'bg-green-500/15 text-green-400' :
          healed  ? 'bg-amber-500/15 text-amber-400' :
          failed  ? 'bg-red-500/15 text-red-400' :
          'bg-zinc-800 text-zinc-500'
        }`}>
          {entry.action || 'step'}
        </span>
        <span className={`flex-1 ${style.text}`}>
          {running ? '' : (success ? '✓ ' : healed ? '⚡ ' : failed ? '✗ ' : '')}
          {entry.stepNum && <span className="text-zinc-600 mr-1">#{entry.stepNum}</span>}
          {entry.message}
          {entry.durationMs !== undefined && (
            <span className="text-zinc-600 ml-1.5">{entry.durationMs}ms</span>
          )}
          {healed && <span className="text-amber-500 ml-1.5 text-[10px]">[self-healed]</span>}
        </span>
      </div>
    );
  }

  const icon = categoryIcon(entry.category);

  return (
    <div className="flex items-start gap-3 py-0.5">
      <span className="text-zinc-600 text-[10px] pt-0.5 w-16 shrink-0">{tsToTime(entry.ts)}</span>
      <div className={`w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 ${style.dot}`} />
      <span className="text-zinc-600 shrink-0 w-4">{icon}</span>
      <span className={`flex-1 ${style.text} break-words`}>{entry.message}</span>
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function StatChip({ label, value, color = 'text-white' }: { label: string; value: number | string; color?: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className={`text-xl font-bold ${color}`}>{value}</span>
      <span className="text-xs text-zinc-600">{label}</span>
    </div>
  );
}

// ── Report Panel ──────────────────────────────────────────────────────────────

function ReportPanel({ report }: { report: ExecutionReport }) {
  const [showPassed, setShowPassed] = useState(false);

  const riskColors: Record<string, string> = {
    LOW:      'text-green-400 bg-green-500/10 border-green-500/30',
    MEDIUM:   'text-amber-400 bg-amber-500/10 border-amber-500/30',
    HIGH:     'text-red-400 bg-red-500/10 border-red-500/30',
    CRITICAL: 'text-red-300 bg-red-500/20 border-red-500/50',
  };

  const summary = report.summary as Record<string, unknown>;
  const passedSteps = (summary.passed as number) ?? 0;
  const failedSteps = (summary.failed as number) ?? 0;
  const totalSteps  = (summary.total as number) ?? 0;

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-white">Test Execution Report</h3>
          <span className={`text-xs px-3 py-1 rounded-full border font-medium ${riskColors[report.risk_level] || riskColors.LOW}`}>
            {report.risk_level} RISK
          </span>
        </div>

        <div className="grid grid-cols-4 gap-3 mb-4">
          <div className="text-center p-3 bg-zinc-800/60 rounded-xl">
            <div className="text-3xl font-bold text-white">{report.quality_score?.toFixed(0) ?? '—'}</div>
            <div className="text-xs text-zinc-500 mt-1">Quality Score</div>
          </div>
          <div className="text-center p-3 bg-green-500/5 border border-green-500/20 rounded-xl">
            <div className="text-3xl font-bold text-green-400">{passedSteps}</div>
            <div className="text-xs text-zinc-500 mt-1">Passed</div>
          </div>
          <div className="text-center p-3 bg-red-500/5 border border-red-500/20 rounded-xl">
            <div className="text-3xl font-bold text-red-400">{failedSteps}</div>
            <div className="text-xs text-zinc-500 mt-1">Failed</div>
          </div>
          <div className="text-center p-3 bg-zinc-800/60 rounded-xl">
            <div className="text-3xl font-bold text-white">
              {summary.duration_seconds ? Math.round(Number(summary.duration_seconds)) : 0}s
            </div>
            <div className="text-xs text-zinc-500 mt-1">Duration</div>
          </div>
        </div>

        {totalSteps > 0 && (
          <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden flex gap-px">
            <div className="bg-green-500 h-full" style={{ width: `${(passedSteps / totalSteps) * 100}%` }} />
            <div className="bg-red-500 h-full" style={{ width: `${(failedSteps / totalSteps) * 100}%` }} />
          </div>
        )}
      </div>

      {/* AI Root Cause Analysis */}
      {report.rca_analysis && Object.keys(report.rca_analysis).length > 0 && (
        <RCAPanel rca={report.rca_analysis as Record<string, unknown>} />
      )}

      {/* AI Insights */}
      {report.insights.length > 0 && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
          <h3 className="font-semibold text-white mb-3 text-sm">AI Insights</h3>
          <div className="space-y-2">
            {(report.insights as Array<{ type: string; message?: string; cause?: string; probability?: number }>).map((ins, i) => (
              <div key={i} className="flex gap-3 p-3 bg-zinc-800/50 rounded-lg">
                <span className="shrink-0">
                  {ins.type === 'root_cause' ? '🔍' : '💡'}
                </span>
                <div>
                  <div className="text-sm text-zinc-300">{ins.message || ins.cause}</div>
                  {ins.probability !== undefined && (
                    <div className="text-xs text-zinc-500 mt-0.5">
                      Confidence: {Math.round(Number(ins.probability) * 100)}%
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recommendations */}
      {report.recommendations.length > 0 && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
          <h3 className="font-semibold text-white mb-3 text-sm">Recommendations</h3>
          <ul className="space-y-1.5">
            {report.recommendations.map((rec, i) => (
              <li key={i} className="flex gap-2 text-sm text-zinc-400">
                <span className="text-blue-400 shrink-0">→</span>
                {String(rec)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Passed steps collapsible */}
      {passedSteps > 0 && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
          <button
            onClick={() => setShowPassed((v) => !v)}
            className="w-full flex items-center justify-between px-5 py-3 hover:bg-zinc-800/50 transition-colors"
          >
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-green-500 shrink-0" />
              <span className="text-sm text-zinc-300">Passed Steps ({passedSteps})</span>
            </div>
            <svg className={`w-4 h-4 text-zinc-500 transition-transform ${showPassed ? 'rotate-180' : ''}`}
                 fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
          {showPassed && (
            <div className="px-5 pb-4 pt-2 space-y-1 border-t border-zinc-800">
              {/* Passed steps come from report summary since we removed the steps state */}
              <p className="text-xs text-zinc-600">See the live log above for step-by-step detail.</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── RCA Panel ─────────────────────────────────────────────────────────────────

function RCAPanel({ rca }: { rca: Record<string, unknown> }) {
  const health = rca.overall_health as string | undefined;
  const criticalFailures = (rca.critical_failures as string[] | undefined) ?? [];
  const rootCauses = (rca.root_causes as Array<{ cause: string; probability: number; category: string }> | undefined) ?? [];
  const workflowAnalysis = rca.workflow_analysis as Record<string, unknown> | undefined;
  const checkpointSummary = rca.checkpoint_summary as string | undefined;
  const patterns = (rca.patterns as string[] | undefined) ?? [];
  const businessImpact = rca.business_impact as string | undefined;
  const recommendations = (rca.recommendations as string[] | undefined) ?? [];

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-4">
      <h3 className="font-semibold text-white text-sm flex items-center gap-2">
        🔍 Root Cause Analysis
      </h3>

      {health && (
        <div className="bg-zinc-800/50 rounded-lg px-4 py-3 text-sm text-zinc-300 leading-relaxed">
          {health}
        </div>
      )}

      {workflowAnalysis && (
        <div className="grid grid-cols-2 gap-3">
          {(workflowAnalysis.phases_completed as string[] | undefined)?.length ? (
            <div>
              <div className="text-xs font-medium text-zinc-500 uppercase tracking-wide mb-1.5">Phases Completed</div>
              <div className="flex flex-wrap gap-1.5">
                {(workflowAnalysis.phases_completed as string[]).map((p, i) => (
                  <span key={i} className="text-xs px-2 py-0.5 bg-green-500/15 text-green-400 rounded-full">{p}</span>
                ))}
              </div>
            </div>
          ) : null}
          {(workflowAnalysis.phases_failed as string[] | undefined)?.length ? (
            <div>
              <div className="text-xs font-medium text-zinc-500 uppercase tracking-wide mb-1.5">Phases Failed</div>
              <div className="flex flex-wrap gap-1.5">
                {(workflowAnalysis.phases_failed as string[]).map((p, i) => (
                  <span key={i} className="text-xs px-2 py-0.5 bg-red-500/15 text-red-400 rounded-full">{p}</span>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      )}

      {checkpointSummary && (
        <div>
          <div className="text-xs font-medium text-zinc-500 uppercase tracking-wide mb-1">AI Checkpoint Validation</div>
          <div className="text-sm text-zinc-400 leading-relaxed">{checkpointSummary}</div>
        </div>
      )}

      {criticalFailures.length > 0 && (
        <div>
          <div className="text-xs font-medium text-zinc-500 uppercase tracking-wide mb-1.5">Critical Failures</div>
          <div className="space-y-1.5">
            {criticalFailures.map((f, i) => (
              <div key={i} className="flex gap-2 text-sm text-red-300 bg-red-500/5 border border-red-500/15 rounded-lg px-3 py-2">
                <span className="text-red-500 shrink-0">✕</span>{f}
              </div>
            ))}
          </div>
        </div>
      )}

      {rootCauses.length > 0 && (
        <div>
          <div className="text-xs font-medium text-zinc-500 uppercase tracking-wide mb-1.5">Root Causes</div>
          <div className="space-y-2">
            {rootCauses.map((rc, i) => (
              <div key={i} className="flex items-start gap-3 bg-zinc-800/40 rounded-lg px-3 py-2.5">
                <div className="w-9 text-center shrink-0">
                  <div className={`text-xs font-bold ${rc.probability >= 0.7 ? 'text-red-400' : rc.probability >= 0.4 ? 'text-amber-400' : 'text-zinc-400'}`}>
                    {Math.round(rc.probability * 100)}%
                  </div>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-zinc-300">{rc.cause}</div>
                  <div className="text-xs text-zinc-600 mt-0.5">{rc.category}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {patterns.length > 0 && (
        <div>
          <div className="text-xs font-medium text-zinc-500 uppercase tracking-wide mb-1.5">Failure Patterns</div>
          {patterns.map((p, i) => (
            <div key={i} className="text-sm text-zinc-400 flex gap-2 mb-1">
              <span className="text-zinc-600 shrink-0">◆</span>{p}
            </div>
          ))}
        </div>
      )}

      {businessImpact && (
        <div className="bg-amber-500/5 border border-amber-500/20 rounded-lg px-4 py-3">
          <div className="text-xs font-medium text-amber-500/80 uppercase tracking-wide mb-1">Business Impact</div>
          <div className="text-sm text-amber-300/90">{businessImpact}</div>
        </div>
      )}

      {recommendations.length > 0 && (
        <div>
          <div className="text-xs font-medium text-zinc-500 uppercase tracking-wide mb-1.5">Recommendations</div>
          <ul className="space-y-1.5">
            {recommendations.map((r, i) => (
              <li key={i} className="flex gap-2 text-sm text-zinc-400">
                <span className="text-blue-400 shrink-0">→</span>{r}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
