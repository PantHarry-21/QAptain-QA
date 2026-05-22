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

    const offStep = socket.on('step_completed', (data) => {
      if (data.run_id !== runId) return;
      setSteps((prev) => prev.map((s, i) =>
        i === Number(data.step_index) ? { ...s, status: data.success ? (data.healing_used ? 'HEALED' : 'PASSED') : 'FAILED', duration_ms: Number(data.duration_ms) } : s
      ));
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

    return () => { offLog(); offStep(); offComplete(); };
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
        report ? <ReportPanel report={report} /> : (
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

function ReportPanel({ report }: { report: ExecutionReport }) {
  const riskColors: Record<string, string> = {
    LOW: 'text-green-400 bg-green-500/10 border-green-500/30',
    MEDIUM: 'text-amber-400 bg-amber-500/10 border-amber-500/30',
    HIGH: 'text-red-400 bg-red-500/10 border-red-500/30',
    CRITICAL: 'text-red-300 bg-red-500/20 border-red-500/50',
  };

  const summary = report.summary as Record<string, unknown>;

  return (
    <div className="space-y-4">
      {/* Quality Score */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-white">Execution Summary</h3>
          <div className={`text-sm px-3 py-1 rounded-full border ${riskColors[report.risk_level] || riskColors.LOW}`}>
            {report.risk_level} RISK
          </div>
        </div>
        <div className="grid grid-cols-3 gap-4 mb-4">
          <div>
            <div className="text-3xl font-bold text-white">{report.quality_score?.toFixed(0) || 'N/A'}</div>
            <div className="text-xs text-zinc-500">Quality Score</div>
          </div>
          <div>
            <div className="text-3xl font-bold text-white">{String(summary.pass_rate || 0)}%</div>
            <div className="text-xs text-zinc-500">Pass Rate</div>
          </div>
          <div>
            <div className="text-3xl font-bold text-white">{String(summary.duration_seconds ? Math.round(Number(summary.duration_seconds)) : 0)}s</div>
            <div className="text-xs text-zinc-500">Duration</div>
          </div>
        </div>
      </div>

      {/* AI Insights */}
      {report.insights.length > 0 && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
          <h3 className="font-semibold text-white mb-3">AI Insights</h3>
          <div className="space-y-2">
            {(report.insights as Array<{ type: string; message?: string; cause?: string; probability?: number }>).map((insight, i) => (
              <div key={i} className="flex gap-3 p-3 bg-zinc-800/50 rounded-lg">
                <span className="text-lg shrink-0">
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

      {/* Recommendations */}
      {report.recommendations.length > 0 && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
          <h3 className="font-semibold text-white mb-3">Recommendations</h3>
          <ul className="space-y-2">
            {report.recommendations.map((rec, i) => (
              <li key={i} className="flex gap-2 text-sm text-zinc-400">
                <span className="text-blue-400 shrink-0">→</span>
                {rec}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
