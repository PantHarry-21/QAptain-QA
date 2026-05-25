'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { explore as exploreApi, ApiError, type ExploreSession, type ExploreLog, type HumanDecision } from '@/lib/api';
import { getSocket } from '@/lib/websocket';
import { useAppToast } from '@/components/ui/app-notifications';

interface ExploreSessionViewerProps {
  sessionId: string;
  applicationId: string;
}

const LEVEL_STYLES: Record<string, { dot: string; text: string }> = {
  INFO:      { dot: 'bg-blue-500',  text: 'text-zinc-300' },
  SUCCESS:   { dot: 'bg-green-500', text: 'text-green-300' },
  WARNING:   { dot: 'bg-amber-500', text: 'text-amber-300' },
  MILESTONE: { dot: 'bg-purple-500', text: 'text-purple-300 font-medium' },
};

const CATEGORY_ICONS: Record<string, string> = {
  login:      '🔐',
  navigation: '🗺',
  exploration: '🔍',
  knowledge:  '🧠',
  system:     '⚙',
  module:     '📦',
  form:       '📝',
  workflow:   '⚡',
};

export function ExploreSessionViewer({ sessionId, applicationId }: ExploreSessionViewerProps) {
  const router = useRouter();
  const pathname = usePathname();
  const toast = useAppToast();
  const [session, setSession] = useState<ExploreSession | null>(null);
  const [logs, setLogs] = useState<ExploreLog[]>([]);
  const [pendingDecision, setPendingDecision] = useState<HumanDecision | null>(null);
  const [knowledge, setKnowledge] = useState<{ modules: number; pages: number; workflows: number } | null>(null);
  const [lastLogId, setLastLogId] = useState<string | undefined>();
  const logsEndRef = useRef<HTMLDivElement>(null);
  const socket = getSocket();

  // Load initial data
  useEffect(() => {
    const load = async () => {
      const [s, initialLogs] = await Promise.all([
        exploreApi.getSession(sessionId),
        exploreApi.getLogs(sessionId),
      ]);
      setSession(s);
      setLogs(initialLogs);
      if (initialLogs.length > 0) {
        setLastLogId(initialLogs[initialLogs.length - 1].id);
      }
    };
    load().catch(console.error);
  }, [sessionId]);

  // Real-time updates via WebSocket
  useEffect(() => {
    socket.connect();
    socket.subscribe(sessionId);

    const offLog = socket.on('explore_log', (data) => {
      if (data.session_id !== sessionId) return;
      // Use server-provided UTC timestamp if available, otherwise fall back to client time.
      // Server sends ISO 8601 with explicit Z suffix so JS parses it as UTC correctly.
      const ts = data.timestamp ? String(data.timestamp) : new Date().toISOString();
      const log: ExploreLog = {
        id: String(data.id || Date.now()),
        timestamp: ts,
        level: (data.level || 'INFO') as ExploreLog['level'],
        category: String(data.category || ''),
        message: String(data.message || ''),
        metadata: {},
      };
      setLogs((prev) => [...prev, log]);
    });

    const offStatus = socket.on('explore_completed', (data) => {
      if (data.session_id !== sessionId) return;
      setSession((s) => s ? { ...s, status: 'COMPLETED', modules_discovered: Number(data.modules || 0), pages_discovered: Number(data.pages || 0), workflows_discovered: Number(data.workflows || 0) } : s);
      setKnowledge({ modules: Number(data.modules || 0), pages: Number(data.pages || 0), workflows: Number(data.workflows || 0) });
    });

    const offDecision = socket.on('human_decision_required', (data) => {
      if (data.session_id !== sessionId) return;
      setPendingDecision({
        id: String(data.decision_id),
        question: String(data.question),
        options: Array.isArray(data.options) ? data.options as HumanDecision['options'] : [],
        is_saved_as_preference: true,
      });
      setDecisionScreenshot(data.screenshot_url ? String(data.screenshot_url) : null);
      setSession((s) => s ? { ...s, status: 'WAITING_HUMAN' } : s);
    });

    return () => {
      offLog();
      offStatus();
      offDecision();
    };
  }, [sessionId, socket]);

  // Auto-scroll to bottom
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  const [decidingOption, setDecidingOption] = useState<string | null>(null);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [decisionScreenshot, setDecisionScreenshot] = useState<string | null>(null);
  const [textInputValue, setTextInputValue] = useState('');
  const [stopping, setStopping] = useState(false);
  const [restarting, setRestarting] = useState(false);

  const handleStop = useCallback(async () => {
    if (!session || stopping) return;
    setStopping(true);
    try {
      await exploreApi.cancelSession(session.id);
      setSession((s) => s ? { ...s, status: 'CANCELLED' as ExploreSession['status'] } : s);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'Failed to stop session');
    } finally {
      setStopping(false);
    }
  }, [session, stopping, toast]);

  const handleRestart = useCallback(async () => {
    if (!session || restarting) return;
    setRestarting(true);
    try {
      const newSession = await exploreApi.start({ application_id: applicationId, mode: session.mode });
      // Navigate to the new session — replace current explore path segment
      const newPath = pathname.replace(/\/explore\/[^/]+$/, `/explore/${newSession.id}`);
      router.push(newPath);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'Failed to restart exploration');
      setRestarting(false);
    }
  }, [session, restarting, applicationId, pathname, router, toast]);

  const handleDecision = useCallback(async (option: { label: string; value: string }) => {
    if (!pendingDecision || decidingOption) return;
    setDecidingOption(option.value);
    setDecisionError(null);
    try {
      await exploreApi.resolveDecision(sessionId, {
        decision_id: pendingDecision.id,
        selected_option: option,
        save_as_preference: true,
      });
      setPendingDecision(null);
      setTextInputValue('');
      setDecisionScreenshot(null);
      setSession((s) => s ? { ...s, status: 'RUNNING' } : s);
    } catch (e) {
      setDecisionError(e instanceof Error ? e.message : 'Failed to submit decision');
    } finally {
      setDecidingOption(null);
    }
  }, [pendingDecision, decidingOption, sessionId]);

  const statusColor = session?.status === 'COMPLETED' ? 'text-green-400' :
                     session?.status === 'FAILED' ? 'text-red-400' :
                     session?.status === 'CANCELLED' ? 'text-zinc-400' :
                     session?.status === 'WAITING_HUMAN' ? 'text-amber-400' :
                     'text-blue-400';

  const statusDot = session?.status === 'COMPLETED' ? 'bg-green-500' :
                   session?.status === 'FAILED' ? 'bg-red-500' :
                   session?.status === 'CANCELLED' ? 'bg-zinc-500' :
                   session?.status === 'WAITING_HUMAN' ? 'bg-amber-500' :
                   'bg-blue-500 animate-pulse';

  return (
    <div className="flex flex-col h-full gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={`w-2.5 h-2.5 rounded-full ${statusDot}`} />
          <h2 className="text-lg font-semibold text-white">Application Exploration</h2>
          <span className={`text-sm font-medium ${statusColor}`}>
            {session?.status?.replace('_', ' ') || 'Loading...'}
          </span>
        </div>

        <div className="flex items-center gap-3">
          {session && session.status === 'COMPLETED' && (
            <div className="flex gap-4 text-sm text-zinc-400">
              <span><span className="text-white font-medium">{session.modules_discovered}</span> modules</span>
              <span><span className="text-white font-medium">{session.pages_discovered}</span> pages</span>
              <span><span className="text-white font-medium">{session.workflows_discovered}</span> workflows</span>
            </div>
          )}
          {session && ['RUNNING', 'WAITING_HUMAN', 'PENDING'].includes(session.status) && (
            <button
              onClick={handleStop}
              disabled={stopping}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 text-red-400 rounded-lg transition-colors disabled:opacity-50"
            >
              {stopping
                ? <><div className="w-3 h-3 border border-red-400 border-t-transparent rounded-full animate-spin" /> Stopping...</>
                : <>■ Stop</>}
            </button>
          )}
          {session && ['COMPLETED', 'FAILED', 'CANCELLED'].includes(session.status) && (
            <button
              onClick={handleRestart}
              disabled={restarting}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/30 text-blue-400 rounded-lg transition-colors disabled:opacity-50"
            >
              {restarting
                ? <><div className="w-3 h-3 border border-blue-400 border-t-transparent rounded-full animate-spin" /> Starting...</>
                : <>↺ Restart Exploration</>}
            </button>
          )}
        </div>
      </div>

      {/* Human-in-loop Decision Panel */}
      {pendingDecision && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-5">
          <div className="flex items-start gap-3">
            <span className="text-2xl">🤔</span>
            <div className="flex-1">
              <h3 className="font-semibold text-amber-300 mb-1">AI needs your input</h3>
              <p className="text-sm text-zinc-300 mb-1">{pendingDecision.question}</p>
              {pendingDecision.context && (
                <p className="text-xs text-zinc-500 mb-3">{pendingDecision.context}</p>
              )}
              {decisionScreenshot && (
                <div className="mb-3 rounded-lg overflow-hidden border border-amber-500/20">
                  <p className="text-xs text-zinc-500 px-2 py-1 bg-zinc-800/60">Current browser state:</p>
                  <img
                    src={`http://localhost:8000${decisionScreenshot}`}
                    alt="Browser screenshot"
                    className="w-full max-h-64 object-contain object-top bg-zinc-900"
                  />
                </div>
              )}
              {(pendingDecision.options[0] as { type?: string } | undefined)?.type === 'text_input' ? (
                <div className="flex gap-2 mt-3">
                  <input
                    type="text"
                    value={textInputValue}
                    onChange={(e) => setTextInputValue(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && textInputValue.trim() && !decidingOption) {
                        handleDecision({ label: textInputValue.trim(), value: textInputValue.trim() });
                      }
                    }}
                    placeholder={(pendingDecision.options[0] as { placeholder?: string }).placeholder || 'Type your answer...'}
                    disabled={!!decidingOption}
                    className="flex-1 px-3 py-2 bg-zinc-800 border border-amber-500/40 text-zinc-100 text-sm rounded-lg placeholder-zinc-500 focus:outline-none focus:border-amber-400 disabled:opacity-50"
                    autoFocus
                  />
                  <button
                    onClick={() => {
                      if (textInputValue.trim()) {
                        handleDecision({ label: textInputValue.trim(), value: textInputValue.trim() });
                      }
                    }}
                    disabled={!!decidingOption || !textInputValue.trim()}
                    className="px-4 py-2 bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-200 text-sm rounded-lg transition-colors disabled:opacity-50 flex items-center gap-2 shrink-0"
                  >
                    {decidingOption && (
                      <div className="w-3 h-3 border border-amber-400 border-t-transparent rounded-full animate-spin" />
                    )}
                    Submit
                  </button>
                </div>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {pendingDecision.options.map((opt) => (
                    <button
                      key={opt.value}
                      onClick={() => handleDecision(opt)}
                      disabled={!!decidingOption}
                      className="px-4 py-2 bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-200 text-sm rounded-lg transition-colors disabled:opacity-50 flex items-center gap-2"
                    >
                      {decidingOption === opt.value && (
                        <div className="w-3 h-3 border border-amber-400 border-t-transparent rounded-full animate-spin" />
                      )}
                      {opt.label}
                    </button>
                  ))}
                </div>
              )}
              {decisionError && (
                <p className="text-xs text-red-400 mt-2">Error: {decisionError}</p>
              )}
              <p className="text-xs text-zinc-500 mt-2">
                Your selection will be saved as the default for all future executions.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Live Semantic Timeline */}
      <div className="flex-1 bg-zinc-900/50 border border-zinc-800 rounded-xl overflow-hidden flex flex-col">
        <div className="px-4 py-3 border-b border-zinc-800 flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
          <span className="text-sm font-medium text-zinc-300">Live Exploration Timeline</span>
          <span className="ml-auto text-xs text-zinc-600">{logs.length} events</span>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-1.5 font-mono text-xs">
          {logs.length === 0 && (
            <div className="text-center text-zinc-600 py-8">
              Exploration initializing...
            </div>
          )}

          {logs.map((log) => {
            const style = LEVEL_STYLES[log.level] || LEVEL_STYLES.INFO;
            const icon = CATEGORY_ICONS[log.category || ''] || '•';
            // DB timestamps have no timezone suffix — treat them as UTC by appending Z.
            // WebSocket timestamps already include Z from the server.
            const rawTs = log.timestamp || '';
            const ts = rawTs && !rawTs.endsWith('Z') && !rawTs.includes('+') ? rawTs + 'Z' : rawTs;
            const time = ts ? new Date(ts).toLocaleTimeString() : '—';

            return (
              <div key={log.id} className="flex items-start gap-3 group">
                <span className="text-zinc-600 text-[10px] pt-0.5 w-16 shrink-0">{time}</span>
                <div className={`w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 ${style.dot}`} />
                <span className="text-zinc-600 shrink-0">{icon}</span>
                <span className={style.text}>{log.message}</span>
              </div>
            );
          })}
          <div ref={logsEndRef} />
        </div>
      </div>

      {/* Knowledge Summary (shown when completed) */}
      {session?.status === 'COMPLETED' && (
        <div className="grid grid-cols-3 gap-3">
          <KnowledgeCard
            icon="📦"
            label="Modules Discovered"
            value={session.modules_discovered}
            color="blue"
          />
          <KnowledgeCard
            icon="📄"
            label="Pages Mapped"
            value={session.pages_discovered}
            color="purple"
          />
          <KnowledgeCard
            icon="⚡"
            label="Workflows Found"
            value={session.workflows_discovered}
            color="green"
          />
        </div>
      )}
    </div>
  );
}

function KnowledgeCard({ icon, label, value, color }: {
  icon: string; label: string; value: number;
  color: 'blue' | 'purple' | 'green';
}) {
  const colors = {
    blue: 'border-blue-500/30 bg-blue-500/10',
    purple: 'border-purple-500/30 bg-purple-500/10',
    green: 'border-green-500/30 bg-green-500/10',
  };

  return (
    <div className={`border rounded-lg p-4 ${colors[color]}`}>
      <div className="text-2xl mb-1">{icon}</div>
      <div className="text-2xl font-bold text-white">{value}</div>
      <div className="text-xs text-zinc-400">{label}</div>
    </div>
  );
}
