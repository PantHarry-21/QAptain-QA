'use client';

import { useEffect, useState } from 'react';
import { executions as executionsApi, type ExecutionRun } from '@/lib/api';
import { getSocket } from '@/lib/websocket';
import { ExecutionDashboard } from './ExecutionDashboard';

export interface BatchItem {
  run_id: string;
  title: string;
}

interface BatchExecutionDashboardProps {
  items: BatchItem[];
}

const STATUS_CONFIG: Record<string, { label: string; dot: string; badge: string }> = {
  PENDING:   { label: 'Pending',   dot: 'bg-zinc-500',                  badge: 'bg-zinc-800 text-zinc-400' },
  QUEUED:    { label: 'Queued',    dot: 'bg-zinc-400',                  badge: 'bg-zinc-800 text-zinc-400' },
  RUNNING:   { label: 'Running',   dot: 'bg-blue-500 animate-pulse',    badge: 'bg-blue-500/20 text-blue-300' },
  COMPLETED: { label: 'Passed',    dot: 'bg-green-500',                 badge: 'bg-green-500/20 text-green-300' },
  FAILED:    { label: 'Failed',    dot: 'bg-red-500',                   badge: 'bg-red-500/20 text-red-300' },
  CANCELLED: { label: 'Cancelled', dot: 'bg-zinc-600',                  badge: 'bg-zinc-800 text-zinc-500' },
};

function isActive(status?: string) {
  return !status || status === 'RUNNING' || status === 'QUEUED' || status === 'PENDING';
}

export function BatchExecutionDashboard({ items }: BatchExecutionDashboardProps) {
  const [runs, setRuns] = useState<Record<string, ExecutionRun>>({});
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [batchError, setBatchError] = useState<string | null>(null);
  const socket = getSocket();

  // Initial load
  useEffect(() => {
    const loadAll = async () => {
      const results = await Promise.allSettled(items.map(i => executionsApi.get(i.run_id)));
      setRuns(prev => {
        const updated = { ...prev };
        results.forEach((r, idx) => {
          if (r.status === 'fulfilled') updated[items[idx].run_id] = r.value;
        });
        return updated;
      });
    };
    loadAll();
  }, []);

  // Poll active runs every 3s
  useEffect(() => {
    const poll = async () => {
      const activeIds = items.filter(i => isActive(runs[i.run_id]?.status)).map(i => i.run_id);
      if (activeIds.length === 0) return;
      const results = await Promise.allSettled(activeIds.map(id => executionsApi.get(id)));
      setRuns(prev => {
        const updated = { ...prev };
        results.forEach((r, idx) => {
          if (r.status === 'fulfilled') updated[activeIds[idx]] = r.value;
        });
        return updated;
      });
    };
    const timer = setInterval(poll, 3000);
    return () => clearInterval(timer);
  }, [runs, items]);

  // WebSocket updates
  useEffect(() => {
    socket.connect();
    const runIds = new Set(items.map(i => i.run_id));

    const offStarted = socket.on('run_started', (data) => {
      const id = data.run_id as string;
      if (!runIds.has(id)) return;
      setRuns(prev => prev[id]
        ? { ...prev, [id]: { ...prev[id], status: 'RUNNING' } }
        : prev);
    });

    const offCompleted = socket.on('run_completed', async (data) => {
      const id = data.run_id as string;
      if (!runIds.has(id)) return;
      try {
        const r = await executionsApi.get(id);
        setRuns(prev => ({ ...prev, [id]: r }));
      } catch { /* ignore */ }
    });

    const offFailed = socket.on('run_failed', async (data) => {
      const id = data.run_id as string;
      if (!runIds.has(id)) return;
      try {
        const r = await executionsApi.get(id);
        setRuns(prev => ({ ...prev, [id]: r }));
      } catch { /* ignore */ }
    });

    const offBatchFailed = socket.on('batch_failed', (data) => {
      const reason = data.reason as string | undefined;
      setBatchError(reason ?? 'Batch execution failed before any scenarios could run.');
      // Refresh all run statuses
      items.forEach(async (item) => {
        try {
          const r = await executionsApi.get(item.run_id);
          setRuns(prev => ({ ...prev, [item.run_id]: r }));
        } catch { /* ignore */ }
      });
    });

    return () => { offStarted(); offCompleted(); offFailed(); offBatchFailed(); };
  }, [items, socket]);

  const totalCount = items.length;
  const passedCount = Object.values(runs).filter(r => r.status === 'COMPLETED').length;
  const failedCount = Object.values(runs).filter(r => r.status === 'FAILED').length;
  const doneCount = passedCount + failedCount;
  const runningCount = Object.values(runs).filter(r => r.status === 'RUNNING').length;
  const isAllDone = doneCount === totalCount && totalCount > 0;

  return (
    <div className="flex flex-col gap-5">
      {/* Batch-level error banner (e.g. login failed before scenarios ran) */}
      {batchError && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl px-5 py-4 flex items-start gap-3">
          <div className="w-5 h-5 rounded-full bg-red-500 flex items-center justify-center shrink-0 mt-0.5">
            <span className="text-white text-xs font-bold">!</span>
          </div>
          <div>
            <p className="text-sm font-medium text-red-300">Batch execution stopped</p>
            <p className="text-xs text-red-400/80 mt-0.5">{batchError}</p>
          </div>
        </div>
      )}

      {/* Summary header */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className={`w-3 h-3 rounded-full ${
              isAllDone
                ? (failedCount > 0 ? 'bg-red-500' : 'bg-green-500')
                : 'bg-blue-500 animate-pulse'
            }`} />
            <h2 className="text-lg font-semibold text-white">Batch Execution</h2>
            <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${
              isAllDone
                ? (failedCount > 0 ? 'bg-red-500/20 text-red-300' : 'bg-green-500/20 text-green-300')
                : 'bg-blue-500/20 text-blue-300'
            }`}>
              {isAllDone
                ? (failedCount > 0 ? 'Completed with failures' : 'All passed')
                : `Running${runningCount > 0 ? ` (${runningCount} active)` : ''}`}
            </span>
          </div>
          <span className="text-sm text-zinc-500">{totalCount} scenarios</span>
        </div>

        <div className="grid grid-cols-4 gap-4 mb-4">
          <div>
            <div className="text-2xl font-bold text-white">{totalCount}</div>
            <div className="text-xs text-zinc-500">Total</div>
          </div>
          <div>
            <div className="text-2xl font-bold text-green-400">{passedCount}</div>
            <div className="text-xs text-zinc-500">Passed</div>
          </div>
          <div>
            <div className="text-2xl font-bold text-red-400">{failedCount}</div>
            <div className="text-xs text-zinc-500">Failed</div>
          </div>
          <div>
            <div className="text-2xl font-bold text-zinc-400">{totalCount - doneCount}</div>
            <div className="text-xs text-zinc-500">Pending / Running</div>
          </div>
        </div>

        <div>
          <div className="flex justify-between text-xs text-zinc-500 mb-1.5">
            <span>{doneCount} / {totalCount} completed</span>
            <span>{totalCount > 0 ? Math.round((doneCount / totalCount) * 100) : 0}%</span>
          </div>
          <div className="h-2 bg-zinc-800 rounded-full overflow-hidden flex">
            <div
              className="bg-green-500 h-full transition-all duration-500"
              style={{ width: `${totalCount > 0 ? (passedCount / totalCount) * 100 : 0}%` }}
            />
            <div
              className="bg-red-500 h-full transition-all duration-500"
              style={{ width: `${totalCount > 0 ? (failedCount / totalCount) * 100 : 0}%` }}
            />
          </div>
        </div>
      </div>

      {/* Scenario list */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden divide-y divide-zinc-800">
        {items.map((item, idx) => {
          const run = runs[item.run_id];
          const cfg = STATUS_CONFIG[run?.status ?? 'PENDING'];
          const isExpanded = expandedId === item.run_id;
          const passRate = run && run.total_steps > 0
            ? Math.round((run.passed_steps / run.total_steps) * 100)
            : null;

          return (
            <div key={item.run_id}>
              <button
                className="w-full flex items-center gap-4 px-5 py-4 hover:bg-zinc-800/50 transition-colors text-left"
                onClick={() => setExpandedId(id => id === item.run_id ? null : item.run_id)}
              >
                <span className="text-zinc-600 text-sm w-5 shrink-0 text-right">{idx + 1}</span>
                <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${cfg.dot}`} />
                <div className="flex-1 min-w-0">
                  <span className="text-sm text-zinc-200 font-medium block truncate">{item.title}</span>
                  {run && run.total_steps > 0 && (
                    <span className="text-xs text-zinc-500">
                      {run.passed_steps}/{run.total_steps} steps passed
                      {run.failed_steps > 0 ? ` · ${run.failed_steps} failed` : ''}
                      {run.healed_steps > 0 ? ` · ${run.healed_steps} healed` : ''}
                    </span>
                  )}
                  {run?.total_steps === 0 && run.status === 'RUNNING' && (
                    <span className="text-xs text-zinc-500">Executing…</span>
                  )}
                  {run?.total_steps === 0 && run.status === 'FAILED' && (
                    <span className="text-xs text-red-400/70">Failed before execution — check batch error above</span>
                  )}
                  {(!run || !run.status) && (
                    <span className="text-xs text-zinc-600">Waiting to start…</span>
                  )}
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  {passRate !== null && (
                    <span className={`text-xs font-medium tabular-nums ${
                      passRate === 100 ? 'text-green-400' : passRate >= 50 ? 'text-amber-400' : 'text-red-400'
                    }`}>
                      {passRate}%
                    </span>
                  )}
                  <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${cfg.badge}`}>
                    {cfg.label}
                  </span>
                  <svg
                    className={`w-4 h-4 text-zinc-600 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                    fill="none" viewBox="0 0 24 24" stroke="currentColor"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </div>
              </button>

              {isExpanded && (
                <div className="border-t border-zinc-800 px-5 py-5 bg-zinc-950/60">
                  <ExecutionDashboard runId={item.run_id} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
