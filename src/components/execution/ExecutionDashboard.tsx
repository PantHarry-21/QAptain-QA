'use client';

import { useEffect, useRef, useState } from 'react';
import { executions as executionsApi, type ExecutionRun, type ExecutionStep, type ExecutionLog, type ExecutionReport } from '@/lib/api';
import { getSocket } from '@/lib/websocket';

interface ExecutionDashboardProps {
  runId: string;
}

const STATUS_CONFIG: Record<string, { label: string; dot: string; badge: string }> = {
  PENDING:   { label: 'Pending',   dot: 'bg-zinc-500',            badge: 'bg-zinc-800 text-zinc-400' },
  QUEUED:    { label: 'Queued',    dot: 'bg-zinc-400',            badge: 'bg-zinc-800 text-zinc-400' },
  RUNNING:   { label: 'Running',   dot: 'bg-blue-500 animate-pulse', badge: 'bg-blue-500/20 text-blue-300' },
  COMPLETED: { label: 'Completed', dot: 'bg-green-500',           badge: 'bg-green-500/20 text-green-300' },
  FAILED:    { label: 'Failed',    dot: 'bg-red-500',             badge: 'bg-red-500/20 text-red-300' },
  CANCELLED: { label: 'Cancelled', dot: 'bg-zinc-600',            badge: 'bg-zinc-800 text-zinc-500' },
  PARTIAL:   { label: 'Partial',   dot: 'bg-amber-500',           badge: 'bg-amber-500/20 text-amber-300' },
  HEALED:    { label: 'Healed',    dot: 'bg-amber-400',           badge: 'bg-amber-500/20 text-amber-300' },
  PASSED:    { label: 'Passed',    dot: 'bg-green-500',           badge: 'bg-green-500/20 text-green-300' },
  SKIPPED:   { label: 'Skipped',   dot: 'bg-zinc-600',            badge: 'bg-zinc-700 text-zinc-400' },
};

export function ExecutionDashboard({ runId }: ExecutionDashboardProps) {
  const [run, setRun] = useState<ExecutionRun | null>(null);
  const [steps, setSteps] = useState<ExecutionStep[]>([]);
  const [logs, setLogs] = useState<ExecutionLog[]>([]);
  const [report, setReport] = useState<ExecutionReport | null>(null);
  const [activeTab, setActiveTab] = useState<'steps' | 'logs' | 'report'>('steps');
  const [expandedStep, setExpandedStep] = useState<string | null>(null);
  const logsEndRef = useRef<HTMLDivElement>(null);
  const socket = getSocket();

  // Initial load
  useEffect(() => {
    const load = async () => {
      const [r, s, l] = await Promise.all([
        executionsApi.get(runId),
        executionsApi.getSteps(runId),
        executionsApi.getLogs(runId),
      ]);
      setRun(r);
      setSteps(s);
      setLogs(l);

      if (r.status === 'COMPLETED' || r.status === 'FAILED') {
        const rep = await executionsApi.getReport(runId);
        setReport(rep);
      }
    };
    load().catch(console.error);
  }, [runId]);

  // Poll every 4s while QUEUED or RUNNING — always refresh steps so live progress shows
  useEffect(() => {
    const poll = async () => {
      if (!run || run.status === 'COMPLETED' || run.status === 'FAILED' || run.status === 'CANCELLED') return;
      try {
        const [r, s] = await Promise.all([
          executionsApi.get(runId),
          executionsApi.getSteps(runId),
        ]);
        setRun(r);
        setSteps(s);
        if (r.status === 'COMPLETED' || r.status === 'FAILED') {
          const rep = await executionsApi.getReport(runId);
          setReport(rep);
        }
      } catch { /* ignore */ }
    };
    const timer = setInterval(poll, 3000);
    return () => clearInterval(timer);
  }, [runId, run?.status]);

  // Real-time
  useEffect(() => {
    socket.connect();
    socket.subscribe(runId);

    const offLog = socket.on('run_log', (data) => {
      if (data.run_id !== runId) return;
      setLogs((prev) => [...prev, {
        id: String(Date.now()),
        timestamp: new Date().toISOString(),
        level: String(data.level || 'INFO'),
        category: String(data.category || ''),
        message: String(data.message || ''),
        metadata: {},
      }]);
    });

    const offStepStarted = socket.on('step_started', (data) => {
      if (data.run_id !== runId) return;
      const idx = Number(data.step_num) - 1;
      setSteps((prev) => {
        if (idx < prev.length) {
          return prev.map((s, i) => i === idx ? { ...s, status: 'RUNNING' as ExecutionStep['status'] } : s);
        }
        const live: ExecutionStep = {
          id: `live-${idx}`,
          sequence: Number(data.step_num),
          action_type: String(data.action || ''),
          description: String(data.description || `Step ${data.step_num}`),
          status: 'RUNNING' as ExecutionStep['status'],
          healing_triggered: false,
          healing_attempts: [],
        };
        const updated = [...prev];
        updated[idx] = live;
        return updated;
      });
    });

    const offStep = socket.on('step_completed', (data) => {
      if (data.run_id !== runId) return;
      const idx = Number(data.step_index);
      const newStatus = data.success ? (data.healing_used ? 'HEALED' : 'PASSED') : 'FAILED';
      setSteps((prev) => {
        // If the step already exists in DB, update it in-place
        if (idx < prev.length) {
          return prev.map((s, i) => i === idx ? { ...s, status: newStatus as ExecutionStep['status'], duration_ms: Number(data.duration_ms) } : s);
        }
        // Otherwise synthesize a live step row so progress is visible before DB commit
        const synthetic: ExecutionStep = {
          id: `live-${idx}`,
          sequence: idx + 1,
          action_type: String(data.action || ''),
          description: String(data.description || `Step ${idx + 1}`),
          status: newStatus as ExecutionStep['status'],
          duration_ms: Number(data.duration_ms),
          healing_triggered: Boolean(data.healing_used),
          healing_attempts: [],
        };
        const updated = [...prev];
        updated[idx] = synthetic;
        return updated;
      });
    });

    const offStarted = socket.on('run_started', async (data) => {
      if (data.run_id !== runId) return;
      setRun((prev) => prev ? { ...prev, status: 'RUNNING' } : prev);
    });

    const offComplete = socket.on('run_completed', async (data) => {
      if (data.run_id !== runId) return;
      const [r, s] = await Promise.all([
        executionsApi.get(runId),
        executionsApi.getSteps(runId),
      ]);
      setRun(r);
      setSteps(s);
      const rep = await executionsApi.getReport(runId);
      setReport(rep);
    });

    const offFailed = socket.on('run_failed', async (data) => {
      if (data.run_id !== runId) return;
      const r = await executionsApi.get(runId);
      setRun(r);
    });

    return () => { offLog(); offStepStarted(); offStep(); offStarted(); offComplete(); offFailed(); };
  }, [runId, socket]);

  useEffect(() => {
    if (activeTab === 'logs') {
      logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, activeTab]);

  if (!run) {
    return (
      <div className="flex items-center justify-center h-64 text-zinc-500">
        <div className="animate-spin w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full mr-3" />
        Loading execution...
      </div>
    );
  }

  const status = STATUS_CONFIG[run.status] || STATUS_CONFIG.PENDING;
  const passRate = run.total_steps > 0 ? Math.round((run.passed_steps / run.total_steps) * 100) : 0;

  return (
    <div className="flex flex-col gap-5">
      {/* Run Header */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className={`w-3 h-3 rounded-full ${status.dot}`} />
            <h2 className="text-lg font-semibold text-white">Execution Run</h2>
            <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${status.badge}`}>
              {status.label}
            </span>
          </div>
          {(run.status === 'RUNNING' || run.status === 'QUEUED') && (
            <button
              onClick={() => executionsApi.cancel(runId)}
              className="text-xs text-red-400 hover:text-red-300 border border-red-500/30 px-3 py-1 rounded-lg"
            >
              Cancel
            </button>
          )}
        </div>

        {/* Metrics */}
        <div className="grid grid-cols-5 gap-4">
          <Metric label="Total Steps" value={run.total_steps} />
          <Metric label="Passed" value={run.passed_steps} color="text-green-400" />
          <Metric label="Failed" value={run.failed_steps} color="text-red-400" />
          <Metric label="Healed" value={run.healed_steps} color="text-amber-400" />
          <Metric label="Pass Rate" value={`${passRate}%`} color={passRate >= 80 ? 'text-green-400' : passRate >= 50 ? 'text-amber-400' : 'text-red-400'} />
        </div>

        {/* Progress Bar */}
        {run.status === 'RUNNING' && run.total_steps > 0 && (
          <div className="mt-4">
            <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 rounded-full transition-all duration-500"
                style={{ width: `${((run.passed_steps + run.failed_steps + run.healed_steps) / run.total_steps) * 100}%` }}
              />
            </div>
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-zinc-900 border border-zinc-800 rounded-lg p-1 w-fit">
        {(['steps', 'logs', 'report'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-1.5 text-sm rounded-md transition-colors ${
              activeTab === tab ? 'bg-zinc-700 text-white' : 'text-zinc-500 hover:text-zinc-300'
            }`}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
            {tab === 'steps' && ` (${steps.length})`}
            {tab === 'logs' && ` (${logs.length})`}
            {tab === 'report' && report ? ' ✓' : ''}
          </button>
        ))}
      </div>

      {/* Steps Panel */}
      {activeTab === 'steps' && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
          <div className="divide-y divide-zinc-800">
            {steps.length === 0 && (
              <div className="p-8 text-center text-zinc-600 text-sm">
                {run.status === 'QUEUED' ? 'Waiting for execution to start...' : 'No steps recorded'}
              </div>
            )}
            {steps.map((step) => (
              <StepRow
                key={step.id}
                step={step}
                expanded={expandedStep === step.id}
                onToggle={() => setExpandedStep((id) => id === step.id ? null : step.id)}
              />
            ))}
          </div>
        </div>
      )}

      {/* Logs Panel */}
      {activeTab === 'logs' && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
          <div className="max-h-[500px] overflow-y-auto p-4 space-y-1 font-mono text-xs">
            {logs.map((log) => (
              <div key={log.id} className="flex gap-3 items-start">
                <span className="text-zinc-600 w-20 shrink-0">{new Date(log.timestamp).toLocaleTimeString()}</span>
                <span className={`shrink-0 w-16 ${
                  log.level === 'SUCCESS' ? 'text-green-400' :
                  log.level === 'WARNING' ? 'text-amber-400' :
                  'text-blue-400'
                }`}>{log.level}</span>
                <span className="text-zinc-500 shrink-0 w-20">{log.category}</span>
                <span className="text-zinc-300">{log.message}</span>
              </div>
            ))}
            <div ref={logsEndRef} />
          </div>
        </div>
      )}

      {/* Report Panel */}
      {activeTab === 'report' && (
        report ? <ReportPanel report={report} steps={steps} /> : (
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-8 text-center text-zinc-500 text-sm">
            {run.status === 'RUNNING' ? 'Report will be generated after execution completes.' : 'No report available.'}
          </div>
        )
      )}
    </div>
  );
}

function Metric({ label, value, color = 'text-white' }: { label: string; value: number | string; color?: string }) {
  return (
    <div>
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
      <div className="text-xs text-zinc-500">{label}</div>
    </div>
  );
}

function StepRow({ step, expanded, onToggle }: { step: ExecutionStep; expanded: boolean; onToggle: () => void }) {
  const config = STATUS_CONFIG[step.status] || STATUS_CONFIG.PENDING;
  const hasDetails = step.healing_triggered || step.error_message || step.screenshot_path;

  return (
    <div>
      <button
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-zinc-800/50 transition-colors text-left"
        onClick={hasDetails ? onToggle : undefined}
      >
        <span className="text-zinc-500 text-xs w-6 shrink-0 text-right">{step.sequence}</span>
        <div className={`w-2 h-2 rounded-full shrink-0 ${config.dot}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-zinc-500 bg-zinc-800 px-1.5 py-0.5 rounded">
              {step.action_type}
            </span>
            <span className="text-sm text-zinc-300 truncate">{step.description}</span>
            {step.healing_triggered && (
              <span className="text-xs px-1.5 py-0.5 bg-amber-500/20 text-amber-400 rounded">healed</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {step.duration_ms && (
            <span className="text-xs text-zinc-600">{step.duration_ms}ms</span>
          )}
          <span className={`text-xs px-2 py-0.5 rounded-full ${config.badge}`}>{config.label}</span>
          {hasDetails && (
            <svg className={`w-4 h-4 text-zinc-600 transition-transform ${expanded ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          )}
        </div>
      </button>

      {expanded && hasDetails && (
        <div className="px-12 pb-4 space-y-2">
          {step.error_message && (
            <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-xs text-red-300">
              {step.error_message}
            </div>
          )}
          {step.healing_triggered && step.healing_attempts.length > 0 && (
            <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg text-xs text-amber-300 space-y-1">
              <div className="font-medium">Self-healing attempts:</div>
              {(step.healing_attempts as Array<{ strategy: string; success: boolean; reason: string }>).map((a, i) => (
                <div key={i} className="flex gap-2">
                  <span>{a.success ? '✓' : '✗'}</span>
                  <span className="text-zinc-400">{a.strategy}</span>
                  <span>{a.reason}</span>
                </div>
              ))}
            </div>
          )}
          {step.screenshot_path && (
            <div className="text-xs text-zinc-500">
              Screenshot: <a href={`/artifacts/${step.screenshot_path}`} target="_blank" className="text-blue-400 hover:underline">View</a>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ReportPanel({ report, steps }: { report: ExecutionReport; steps: ExecutionStep[] }) {
  const [showPassed, setShowPassed] = useState(false);

  const riskColors: Record<string, string> = {
    LOW: 'text-green-400 bg-green-500/10 border-green-500/30',
    MEDIUM: 'text-amber-400 bg-amber-500/10 border-amber-500/30',
    HIGH: 'text-red-400 bg-red-500/10 border-red-500/30',
    CRITICAL: 'text-red-300 bg-red-500/20 border-red-500/50',
  };

  const summary = report.summary as Record<string, unknown>;
  const failedSteps = steps.filter((s) => s.status === 'FAILED');
  const passedSteps = steps.filter((s) => s.status === 'PASSED' || s.status === 'HEALED');
  const skippedSteps = steps.filter((s) => s.status === 'SKIPPED');

  return (
    <div className="space-y-4">
      {/* ── Summary header ── */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
        <div className="flex items-center justify-between mb-5">
          <h3 className="font-semibold text-white text-lg">Test Execution Report</h3>
          <div className={`text-sm px-3 py-1 rounded-full border font-medium ${riskColors[report.risk_level] || riskColors.LOW}`}>
            {report.risk_level} RISK
          </div>
        </div>

        <div className="grid grid-cols-4 gap-4 mb-4">
          <div className="text-center p-3 bg-zinc-800/60 rounded-xl">
            <div className="text-3xl font-bold text-white">{report.quality_score?.toFixed(0) ?? '–'}</div>
            <div className="text-xs text-zinc-500 mt-1">Quality Score</div>
          </div>
          <div className="text-center p-3 bg-green-500/5 border border-green-500/20 rounded-xl">
            <div className="text-3xl font-bold text-green-400">{passedSteps.length}</div>
            <div className="text-xs text-zinc-500 mt-1">Passed</div>
          </div>
          <div className="text-center p-3 bg-red-500/5 border border-red-500/20 rounded-xl">
            <div className="text-3xl font-bold text-red-400">{failedSteps.length}</div>
            <div className="text-xs text-zinc-500 mt-1">Failed</div>
          </div>
          <div className="text-center p-3 bg-zinc-800/60 rounded-xl">
            <div className="text-3xl font-bold text-white">
              {String(summary.duration_seconds ? Math.round(Number(summary.duration_seconds)) : 0)}s
            </div>
            <div className="text-xs text-zinc-500 mt-1">Duration</div>
          </div>
        </div>

        {/* Pass/fail bar */}
        {steps.length > 0 && (
          <div className="h-2 bg-zinc-800 rounded-full overflow-hidden flex gap-0.5">
            <div
              className="bg-green-500 h-full transition-all"
              style={{ width: `${(passedSteps.length / steps.length) * 100}%` }}
            />
            <div
              className="bg-red-500 h-full transition-all"
              style={{ width: `${(failedSteps.length / steps.length) * 100}%` }}
            />
          </div>
        )}
      </div>

      {/* ── Failed Steps (Jira-style issues) ── */}
      {failedSteps.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center gap-2 px-1">
            <span className="w-2.5 h-2.5 rounded-full bg-red-500 shrink-0" />
            <h3 className="font-semibold text-white">Failed Tests ({failedSteps.length})</h3>
          </div>
          {failedSteps.map((step, i) => (
            <div key={step.id} className="bg-zinc-900 border border-red-500/30 rounded-xl overflow-hidden">
              {/* Issue header */}
              <div className="flex items-start gap-3 p-4 bg-red-500/5">
                <div className="flex items-center justify-center w-7 h-7 rounded-lg bg-red-500/20 text-red-400 text-xs font-bold shrink-0 mt-0.5">
                  F{i + 1}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-white">{step.description || `Step ${step.sequence}`}</span>
                    <span className="text-xs font-mono bg-zinc-800 text-zinc-400 px-2 py-0.5 rounded">{step.action_type}</span>
                    {step.healing_triggered && (
                      <span className="text-xs bg-amber-500/20 text-amber-400 px-2 py-0.5 rounded">Healing attempted</span>
                    )}
                  </div>
                  {step.duration_ms != null && (
                    <div className="text-xs text-zinc-500 mt-0.5">Step {step.sequence} · {step.duration_ms}ms</div>
                  )}
                </div>
                <span className="text-xs px-2 py-1 bg-red-500/20 text-red-400 rounded-full shrink-0 font-medium">FAILED</span>
              </div>

              {/* Error details */}
              {step.error_message && (
                <div className="px-4 py-3 border-t border-zinc-800">
                  <div className="text-xs font-medium text-zinc-400 mb-1.5 uppercase tracking-wide">Why it failed</div>
                  <pre className="text-xs text-red-300 bg-red-500/5 border border-red-500/20 rounded-lg p-3 whitespace-pre-wrap break-all font-mono leading-relaxed">
                    {step.error_message}
                  </pre>
                </div>
              )}

              {/* Healing attempts */}
              {step.healing_triggered && step.healing_attempts.length > 0 && (
                <div className="px-4 py-3 border-t border-zinc-800">
                  <div className="text-xs font-medium text-zinc-400 mb-2 uppercase tracking-wide">
                    Self-healing attempts ({step.healing_attempts.length})
                  </div>
                  <div className="space-y-1.5">
                    {(step.healing_attempts as Array<{ strategy: string; success: boolean; reason: string }>).map((a, hi) => (
                      <div key={hi} className="flex items-start gap-2 text-xs">
                        <span className={a.success ? 'text-green-400' : 'text-red-400'}>{a.success ? '✓' : '✗'}</span>
                        <span className="text-zinc-400 font-medium">{a.strategy}</span>
                        <span className="text-zinc-500">{a.reason}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Screenshot */}
              {step.screenshot_path && (
                <div className="px-4 py-3 border-t border-zinc-800 flex items-center gap-3">
                  <span className="text-xs font-medium text-zinc-400 uppercase tracking-wide">Screenshot</span>
                  <a
                    href={`/artifacts/${step.screenshot_path}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-blue-400 hover:text-blue-300 underline underline-offset-2"
                  >
                    View evidence →
                  </a>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── AI Root Cause Analysis ── */}
      {report.rca_analysis && Object.keys(report.rca_analysis).length > 0 && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
          <h3 className="font-semibold text-white mb-3 flex items-center gap-2">
            <span>🔍</span> Root Cause Analysis
          </h3>
          <div className="text-sm text-zinc-300 leading-relaxed whitespace-pre-wrap">
            {typeof report.rca_analysis === 'string'
              ? report.rca_analysis
              : JSON.stringify(report.rca_analysis, null, 2)}
          </div>
        </div>
      )}

      {/* ── AI Insights ── */}
      {report.insights.length > 0 && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
          <h3 className="font-semibold text-white mb-3 flex items-center gap-2">
            <span>💡</span> AI Insights
          </h3>
          <div className="space-y-2">
            {(report.insights as Array<{ type: string; message?: string; cause?: string; probability?: number }>).map((insight, i) => (
              <div key={i} className="flex gap-3 p-3 bg-zinc-800/50 rounded-lg">
                <span className="text-base shrink-0">
                  {insight.type === 'quality' ? '📊' : insight.type === 'root_cause' ? '🔍' : '💡'}
                </span>
                <div>
                  <div className="text-sm text-zinc-300">{insight.message || insight.cause}</div>
                  {insight.probability !== undefined && (
                    <div className="text-xs text-zinc-500 mt-0.5">
                      Confidence: {Math.round(Number(insight.probability) * 100)}%
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Recommendations ── */}
      {report.recommendations.length > 0 && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
          <h3 className="font-semibold text-white mb-3 flex items-center gap-2">
            <span>📋</span> Recommendations
          </h3>
          <ul className="space-y-2">
            {report.recommendations.map((rec, i) => (
              <li key={i} className="flex gap-2 text-sm text-zinc-400">
                <span className="text-blue-400 shrink-0">→</span>
                {String(rec)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ── Passed Steps (collapsible) ── */}
      {passedSteps.length > 0 && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
          <button
            onClick={() => setShowPassed((v) => !v)}
            className="w-full flex items-center justify-between px-5 py-3 hover:bg-zinc-800/50 transition-colors"
          >
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-green-500 shrink-0" />
              <span className="text-sm font-medium text-zinc-300">
                Passed Steps ({passedSteps.length})
              </span>
            </div>
            <svg className={`w-4 h-4 text-zinc-500 transition-transform ${showPassed ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
          {showPassed && (
            <div className="divide-y divide-zinc-800 border-t border-zinc-800">
              {passedSteps.map((step) => (
                <div key={step.id} className="flex items-center gap-3 px-5 py-2.5">
                  <span className="text-green-400 text-sm">✓</span>
                  <span className="text-xs font-mono text-zinc-600 bg-zinc-800 px-1.5 py-0.5 rounded">{step.action_type}</span>
                  <span className="text-sm text-zinc-400 flex-1 truncate">{step.description}</span>
                  {step.duration_ms != null && (
                    <span className="text-xs text-zinc-600 shrink-0">{step.duration_ms}ms</span>
                  )}
                  {step.screenshot_path && (
                    <a href={`/artifacts/${step.screenshot_path}`} target="_blank" rel="noopener noreferrer"
                       className="text-xs text-zinc-600 hover:text-blue-400 transition-colors shrink-0">
                      📷
                    </a>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
