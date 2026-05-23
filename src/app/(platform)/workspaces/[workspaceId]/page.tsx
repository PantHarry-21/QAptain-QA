'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import {
  workspaces as workspaceApi,
  applications as appApi,
  scenarios as scenariosApi,
  explore as exploreApi,
  reports as reportsApi,
  type Application,
  type Scenario,
  type ExploreSession,
  type ReportSummary,
} from '@/lib/api';
import { getSocket } from '@/lib/websocket';

type ActiveTab = 'overview' | 'explore' | 'scenarios' | 'reports' | 'settings';

export default function WorkspacePage() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const workspaceId = params.workspaceId as string;

  const [tab, setTab] = useState<ActiveTab>('overview');
  const [apps, setApps] = useState<Application[]>([]);
  const [selectedApp, setSelectedApp] = useState<Application | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [exploreSessions, setExploreSessions] = useState<ExploreSession[]>([]);
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [loading, setLoading] = useState(true);

  // Scenario creation
  const [newScenarioTitle, setNewScenarioTitle] = useState('');
  const [newScenarioPriority, setNewScenarioPriority] = useState('MEDIUM');
  const [creatingScenario, setCreatingScenario] = useState(false);
  const [selectedScenarioId, setSelectedScenarioId] = useState<string | null>(null);
  const [generatingPlan, setGeneratingPlan] = useState(false);
  const [executionMode, setExecutionMode] = useState('functional');

  // Explore
  const [startingExplore, setStartingExplore] = useState(false);
  const [exploreMode, setExploreMode] = useState<'FULL' | 'SMART' | 'SKIP'>('SMART');

  // Settings
  const [settingsDesc, setSettingsDesc] = useState('');
  const [settingsUsername, setSettingsUsername] = useState('');
  const [settingsPassword, setSettingsPassword] = useState('');
  const [savingSettings, setSavingSettings] = useState(false);
  const [settingsSaved, setSettingsSaved] = useState(false);

  const socket = getSocket();

  useEffect(() => {
    const appId = searchParams.get('app');
    loadData(appId);
  }, [workspaceId]);

  useEffect(() => {
    socket.connect();
    const off = socket.on('run_completed', () => {
      if (selectedApp) loadReports(selectedApp.id);
    });
    return () => off();
  }, [selectedApp]);

  useEffect(() => {
    if (selectedApp) {
      setSettingsDesc(selectedApp.description || '');
      setSettingsUsername('');
      setSettingsPassword('');
      setSettingsSaved(false);
    }
  }, [selectedApp?.id]);

  const loadData = async (preferredAppId?: string | null) => {
    setLoading(true);
    try {
      const appList = await workspaceApi.listApplications(workspaceId);
      setApps(appList);

      const target = preferredAppId
        ? appList.find((a) => a.id === preferredAppId) || appList[0]
        : appList[0];

      if (target) {
        setSelectedApp(target);
        await Promise.all([
          loadScenarios(target.id),
          loadReports(target.id),
        ]);
      }
    } catch (e) {
      console.error('Failed to load workspace data', e);
    } finally {
      setLoading(false);
    }
  };

  const loadScenarios = async (appId: string) => {
    try {
      const s = await scenariosApi.list(appId);
      setScenarios(s);
    } catch { setScenarios([]); }
  };

  const loadReports = async (appId: string) => {
    try {
      const r = await reportsApi.listForApplication(appId, 10);
      setReports(r);
    } catch { setReports([]); }
  };

  const handleCreateScenario = async () => {
    if (!selectedApp || !newScenarioTitle.trim()) return;
    setCreatingScenario(true);
    try {
      const scenario = await scenariosApi.create({
        application_id: selectedApp.id,
        title: newScenarioTitle.trim(),
        priority: newScenarioPriority as Scenario['priority'],
      });
      setScenarios((s) => [scenario, ...s]);
      setNewScenarioTitle('');
    } catch (e) {
      console.error('Failed to create scenario', e);
    } finally {
      setCreatingScenario(false);
    }
  };

  const handleGenerateAndRun = async (scenarioId: string) => {
    if (!selectedApp) return;
    setGeneratingPlan(true);
    setSelectedScenarioId(scenarioId);
    try {
      const plan = await scenariosApi.generatePlan(scenarioId, executionMode);
      // Get default environment
      const envs = await appApi.listEnvironments(selectedApp.id);
      const env = envs.find((e) => e.is_default) || envs[0];
      if (!env) throw new Error('No environment configured');

      const run = await scenariosApi.triggerExecution(scenarioId, {
        plan_id: plan.id,
        environment_id: env.id,
      });
      router.push(`/workspaces/${workspaceId}/executions/${run.id}`);
    } catch (e) {
      console.error('Failed to start execution', e);
      alert(e instanceof Error ? e.message : 'Failed to start execution');
    } finally {
      setGeneratingPlan(false);
      setSelectedScenarioId(null);
    }
  };

  const handleStartExplore = async () => {
    if (!selectedApp) return;
    setStartingExplore(true);
    try {
      const session = await exploreApi.start({
        application_id: selectedApp.id,
        mode: exploreMode,
      });
      router.push(`/workspaces/${workspaceId}/explore/${session.id}`);
    } catch (e) {
      // If a session is already running, navigate to it instead of showing an error
      if (e instanceof Error && e.message.includes('already running')) {
        try {
          const active = await exploreApi.getActiveSession(selectedApp.id);
          if (active) {
            router.push(`/workspaces/${workspaceId}/explore/${active.id}`);
            return;
          }
        } catch { /* fall through to alert */ }
      }
      console.error('Failed to start exploration', e);
      alert(e instanceof Error ? e.message : 'Exploration failed to start');
    } finally {
      setStartingExplore(false);
    }
  };

  const handleSaveSettings = async () => {
    if (!selectedApp) return;
    setSavingSettings(true);
    setSettingsSaved(false);
    try {
      await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/applications/${selectedApp.id}/settings`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          ...(localStorage.getItem('qaptain_token') ? { Authorization: `Bearer ${localStorage.getItem('qaptain_token')}` } : {}),
        },
        body: JSON.stringify({
          description: settingsDesc || undefined,
          username: settingsUsername || undefined,
          password: settingsPassword || undefined,
        }),
      });
      setSettingsSaved(true);
      setSettingsPassword('');
      setTimeout(() => setSettingsSaved(false), 3000);
    } catch (e) {
      console.error('Failed to save settings', e);
      alert('Failed to save settings');
    } finally {
      setSavingSettings(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-zinc-950 text-zinc-500">
        <div className="animate-spin w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full mr-3" />
        Loading workspace...
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-zinc-950">
      {/* Sidebar */}
      <div className="flex h-screen">
        <aside className="w-64 bg-zinc-900 border-r border-zinc-800 flex flex-col">
          <div className="p-4 border-b border-zinc-800">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-7 h-7 bg-blue-600 rounded-lg flex items-center justify-center">
                <span className="text-white font-bold text-xs">Q</span>
              </div>
              <span className="text-white font-semibold text-sm">QAptain</span>
            </div>
            <Link
              href="/workspaces"
              className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
            >
              ← All Workspaces
            </Link>
          </div>

          {/* Application Selector */}
          <div className="p-3 border-b border-zinc-800">
            <div className="text-xs text-zinc-500 mb-2 px-1">APPLICATION</div>
            {apps.map((app) => (
              <button
                key={app.id}
                onClick={() => {
                  setSelectedApp(app);
                  loadScenarios(app.id);
                  loadReports(app.id);
                }}
                className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                  selectedApp?.id === app.id
                    ? 'bg-blue-600/20 text-blue-300 border border-blue-600/30'
                    : 'text-zinc-400 hover:bg-zinc-800 hover:text-zinc-300'
                }`}
              >
                <div className="font-medium truncate">{app.name}</div>
                <div className="text-xs text-zinc-600 truncate">{app.base_url}</div>
              </button>
            ))}
            <Link
              href={`/workspaces/new`}
              className="flex items-center gap-1 mt-2 px-3 py-2 text-xs text-zinc-600 hover:text-zinc-400 transition-colors"
            >
              + Add Application
            </Link>
          </div>

          {/* Navigation */}
          <nav className="flex-1 p-3 space-y-1">
            {(
              [
                { id: 'overview', label: 'Overview', icon: '📊' },
                { id: 'explore', label: 'Explore', icon: '🔍' },
                { id: 'scenarios', label: 'Scenarios', icon: '📋' },
                { id: 'reports', label: 'Reports', icon: '📈' },
                { id: 'settings', label: 'Settings', icon: '⚙️' },
              ] as const
            ).map((item) => (
              <button
                key={item.id}
                onClick={() => setTab(item.id)}
                className={`w-full text-left flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
                  tab === item.id
                    ? 'bg-zinc-800 text-white'
                    : 'text-zinc-500 hover:bg-zinc-800/60 hover:text-zinc-300'
                }`}
              >
                <span>{item.icon}</span>
                {item.label}
              </button>
            ))}
          </nav>
        </aside>

        {/* Main Content */}
        <main className="flex-1 overflow-y-auto p-6">
          {!selectedApp ? (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div className="text-4xl mb-4">🚀</div>
              <h2 className="text-xl font-semibold text-white mb-2">No applications yet</h2>
              <p className="text-zinc-500 mb-6 max-w-sm">
                Create your first application to start semantic test automation.
              </p>
              <Link
                href="/workspaces/new"
                className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition-colors"
              >
                Create Application
              </Link>
            </div>
          ) : (
            <>
              {tab === 'overview' && (
                <OverviewTab
                  app={selectedApp}
                  scenarios={scenarios}
                  reports={reports}
                  onRunScenario={handleGenerateAndRun}
                  onExploreClick={() => setTab('explore')}
                  onScenariosClick={() => setTab('scenarios')}
                />
              )}
              {tab === 'explore' && (
                <ExploreTab
                  app={selectedApp}
                  exploreMode={exploreMode}
                  setExploreMode={setExploreMode}
                  onStart={handleStartExplore}
                  loading={startingExplore}
                />
              )}
              {tab === 'scenarios' && (
                <ScenariosTab
                  app={selectedApp}
                  scenarios={scenarios}
                  newTitle={newScenarioTitle}
                  setNewTitle={setNewScenarioTitle}
                  priority={newScenarioPriority}
                  setPriority={setNewScenarioPriority}
                  executionMode={executionMode}
                  setExecutionMode={setExecutionMode}
                  onCreateScenario={handleCreateScenario}
                  onRunScenario={handleGenerateAndRun}
                  creating={creatingScenario}
                  runningId={generatingPlan ? selectedScenarioId : null}
                />
              )}
              {tab === 'reports' && (
                <ReportsTab
                  reports={reports}
                  workspaceId={workspaceId}
                />
              )}
              {tab === 'settings' && selectedApp && (
                <div className="max-w-2xl space-y-6">
                  <div>
                    <h2 className="text-xl font-semibold text-white mb-1">Application Settings</h2>
                    <p className="text-sm text-zinc-500">Update description and credentials for {selectedApp.name}</p>
                  </div>

                  <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-4">
                    <h3 className="text-sm font-medium text-zinc-300">General</h3>
                    <div>
                      <label className="block text-xs text-zinc-500 mb-1">Description</label>
                      <textarea
                        value={settingsDesc}
                        onChange={(e) => setSettingsDesc(e.target.value)}
                        rows={3}
                        className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-blue-500"
                        placeholder="What does this application do?"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-zinc-500 mb-1">Base URL</label>
                      <input
                        value={selectedApp.base_url}
                        disabled
                        className="w-full bg-zinc-800/50 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-400 cursor-not-allowed"
                      />
                    </div>
                  </div>

                  <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-4">
                    <h3 className="text-sm font-medium text-zinc-300">Credentials</h3>
                    <p className="text-xs text-zinc-500">Leave password blank to keep the existing one.</p>
                    <div>
                      <label className="block text-xs text-zinc-500 mb-1">Username / Email</label>
                      <input
                        type="text"
                        value={settingsUsername}
                        onChange={(e) => setSettingsUsername(e.target.value)}
                        className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-blue-500"
                        placeholder="username or email"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-zinc-500 mb-1">New Password</label>
                      <input
                        type="password"
                        value={settingsPassword}
                        onChange={(e) => setSettingsPassword(e.target.value)}
                        className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-blue-500"
                        placeholder="leave blank to keep existing"
                      />
                    </div>
                  </div>

                  <div className="flex items-center gap-3">
                    <button
                      onClick={handleSaveSettings}
                      disabled={savingSettings}
                      className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
                    >
                      {savingSettings ? 'Saving...' : 'Save Changes'}
                    </button>
                    {settingsSaved && (
                      <span className="text-sm text-green-400">✓ Saved successfully</span>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}

function OverviewTab({ app, scenarios, reports, onRunScenario, onExploreClick, onScenariosClick }: {
  app: Application;
  scenarios: Scenario[];
  reports: ReportSummary[];
  onRunScenario: (id: string) => void;
  onExploreClick: () => void;
  onScenariosClick: () => void;
}) {
  const recentReports = reports.slice(0, 5);
  const passRate = recentReports.length > 0
    ? Math.round(recentReports.filter((r) => r.run_status === 'COMPLETED').length / recentReports.length * 100)
    : 0;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">{app.name}</h1>
        <p className="text-zinc-500 text-sm mt-1">{app.base_url}</p>
      </div>

      {/* Status Cards */}
      <div className="grid grid-cols-4 gap-4 mb-8">
        <StatCard icon="📦" label="Modules" value={app.modules_count} color="blue" />
        <StatCard icon="📋" label="Scenarios" value={scenarios.length} color="purple" />
        <StatCard icon="📊" label="Executions" value={reports.length} color="green" />
        <StatCard icon="✓" label="Pass Rate" value={`${passRate}%`} color={passRate >= 80 ? 'green' : passRate >= 50 ? 'amber' : 'red'} />
      </div>

      {/* Application Knowledge Status */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 mb-6">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="font-semibold text-white mb-1">Application Knowledge</h3>
            <p className="text-sm text-zinc-500">
              {app.has_knowledge
                ? `Knowledge graph built. ${app.modules_count} modules discovered.`
                : 'No knowledge graph yet. Run exploration to help AI understand your application.'}
            </p>
          </div>
          <button
            onClick={onExploreClick}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition-colors"
          >
            {app.has_knowledge ? 'Re-explore' : 'Start Explore'}
          </button>
        </div>
      </div>

      {/* Quick Execute */}
      {scenarios.length > 0 && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 mb-6">
          <h3 className="font-semibold text-white mb-3">Quick Execute</h3>
          <div className="space-y-2">
            {scenarios.slice(0, 5).map((s) => (
              <div key={s.id} className="flex items-center justify-between p-3 bg-zinc-800/50 rounded-lg">
                <div>
                  <span className="text-sm text-zinc-300">{s.title}</span>
                  <PriorityBadge priority={s.priority} />
                </div>
                <button
                  onClick={() => onRunScenario(s.id)}
                  className="text-xs px-3 py-1 bg-green-600/20 hover:bg-green-600/30 text-green-400 border border-green-600/30 rounded-lg transition-colors"
                >
                  Run
                </button>
              </div>
            ))}
          </div>
          {scenarios.length > 5 && (
            <button onClick={onScenariosClick} className="mt-2 text-xs text-zinc-500 hover:text-zinc-300">
              View all {scenarios.length} scenarios →
            </button>
          )}
        </div>
      )}

      {/* Recent Executions */}
      {recentReports.length > 0 && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
          <h3 className="font-semibold text-white mb-3">Recent Executions</h3>
          <div className="space-y-2">
            {recentReports.map((r) => (
              <div key={r.id} className="flex items-center justify-between text-sm">
                <span className="text-zinc-400 truncate flex-1 mr-4">{r.scenario_title}</span>
                <span className={`text-xs px-2 py-0.5 rounded-full ${
                  r.run_status === 'COMPLETED' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                }`}>
                  {r.risk_level}
                </span>
                <span className="text-zinc-600 ml-3 text-xs">{r.quality_score?.toFixed(0) || '-'}/100</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ExploreTab({ app, exploreMode, setExploreMode, onStart, loading }: {
  app: Application;
  exploreMode: 'FULL' | 'SMART' | 'SKIP';
  setExploreMode: (m: 'FULL' | 'SMART' | 'SKIP') => void;
  onStart: () => void;
  loading: boolean;
}) {
  const modes = [
    { id: 'FULL' as const, icon: '🔍', title: 'Full Explore', desc: 'Complete application mapping — all modules, pages, forms, workflows', time: '15–45 min' },
    { id: 'SMART' as const, icon: '⚡', title: 'Smart Explore', desc: 'Major modules and workflows only — faster but comprehensive', time: '5–15 min' },
    { id: 'SKIP' as const, icon: '🎯', title: 'Skip Explore', desc: 'Semantic runtime reasoning — no pre-exploration needed', time: 'Instant' },
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-2">Explore Application</h1>
      <p className="text-zinc-500 text-sm mb-6">
        QAptain will learn {app.name} semantically — understanding modules, workflows, forms, and dynamic UI behavior.
      </p>

      <div className="space-y-3 mb-6">
        {modes.map((m) => (
          <button
            key={m.id}
            onClick={() => setExploreMode(m.id)}
            className={`w-full text-left p-4 rounded-xl border transition-all ${
              exploreMode === m.id
                ? 'border-blue-500 bg-blue-500/10 ring-1 ring-blue-500'
                : 'border-zinc-800 bg-zinc-900 hover:border-zinc-700'
            }`}
          >
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-2">
                <span>{m.icon}</span>
                <span className="font-medium text-white">{m.title}</span>
              </div>
              <span className="text-xs text-zinc-500">{m.time}</span>
            </div>
            <p className="text-sm text-zinc-400 ml-6">{m.desc}</p>
          </button>
        ))}
      </div>

      <button
        onClick={onStart}
        disabled={loading}
        className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-medium rounded-lg transition-colors disabled:opacity-50 flex items-center gap-2"
      >
        {loading && <div className="animate-spin w-4 h-4 border-2 border-white/30 border-t-white rounded-full" />}
        Start Exploration
      </button>
    </div>
  );
}

function ScenariosTab({ app, scenarios, newTitle, setNewTitle, priority, setPriority, executionMode, setExecutionMode, onCreateScenario, onRunScenario, creating, runningId }: {
  app: Application;
  scenarios: Scenario[];
  newTitle: string;
  setNewTitle: (v: string) => void;
  priority: string;
  setPriority: (v: string) => void;
  executionMode: string;
  setExecutionMode: (v: string) => void;
  onCreateScenario: () => void;
  onRunScenario: (id: string) => void;
  creating: boolean;
  runningId: string | null;
}) {
  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-6">Test Scenarios</h1>

      {/* Create Scenario */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 mb-6">
        <h3 className="font-semibold text-white mb-3">Add Scenario</h3>
        <div className="flex gap-3">
          <input
            type="text"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && onCreateScenario()}
            placeholder="e.g. Create new sample and verify in inventory"
            className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
          />
          <select
            value={priority}
            onChange={(e) => setPriority(e.target.value)}
            className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-zinc-300 text-sm focus:outline-none"
          >
            <option value="CRITICAL">Critical</option>
            <option value="HIGH">High</option>
            <option value="MEDIUM">Medium</option>
            <option value="LOW">Low</option>
          </select>
          <button
            onClick={onCreateScenario}
            disabled={creating || !newTitle.trim()}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition-colors disabled:opacity-50"
          >
            Add
          </button>
        </div>
      </div>

      {/* Execution Mode */}
      <div className="flex items-center gap-3 mb-4">
        <span className="text-sm text-zinc-500">Execution mode:</span>
        <div className="flex gap-1 bg-zinc-900 border border-zinc-800 rounded-lg p-1">
          {['smoke', 'functional', 'regression'].map((m) => (
            <button
              key={m}
              onClick={() => setExecutionMode(m)}
              className={`px-3 py-1 text-xs rounded-md transition-colors ${
                executionMode === m ? 'bg-zinc-700 text-white' : 'text-zinc-500 hover:text-zinc-300'
              }`}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      {/* Scenario List */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
        {scenarios.length === 0 ? (
          <div className="p-10 text-center text-zinc-500">
            No scenarios yet. Add your first test scenario above.
          </div>
        ) : (
          <div className="divide-y divide-zinc-800">
            {scenarios.map((s) => (
              <div key={s.id} className="flex items-center gap-4 px-5 py-3">
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-zinc-300 truncate">{s.title}</div>
                  {s.description && (
                    <div className="text-xs text-zinc-600 truncate">{s.description}</div>
                  )}
                </div>
                <PriorityBadge priority={s.priority} />
                <button
                  onClick={() => onRunScenario(s.id)}
                  disabled={runningId === s.id}
                  className="text-xs px-3 py-1.5 bg-green-600/20 hover:bg-green-600/30 text-green-400 border border-green-600/30 rounded-lg transition-colors disabled:opacity-50 flex items-center gap-1.5"
                >
                  {runningId === s.id && (
                    <div className="animate-spin w-3 h-3 border border-green-400 border-t-transparent rounded-full" />
                  )}
                  {runningId === s.id ? 'Planning...' : 'Run'}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ReportsTab({ reports, workspaceId }: { reports: ReportSummary[]; workspaceId: string }) {
  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-6">Execution Reports</h1>
      {reports.length === 0 ? (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-10 text-center text-zinc-500">
          No reports yet. Run some scenarios to see AI-native reports here.
        </div>
      ) : (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
          <div className="divide-y divide-zinc-800">
            {reports.map((r) => (
              <Link
                key={r.id}
                href={`/workspaces/${workspaceId}/executions/${r.run_id}`}
                className="flex items-center gap-4 px-5 py-4 hover:bg-zinc-800/50 transition-colors"
              >
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-zinc-300 truncate">{r.scenario_title}</div>
                  <div className="text-xs text-zinc-600">{new Date(r.created_at).toLocaleString()}</div>
                </div>
                <span className={`text-xs px-2 py-0.5 rounded-full ${
                  r.risk_level === 'LOW' ? 'bg-green-500/20 text-green-400' :
                  r.risk_level === 'MEDIUM' ? 'bg-amber-500/20 text-amber-400' :
                  'bg-red-500/20 text-red-400'
                }`}>
                  {r.risk_level}
                </span>
                <span className="text-sm font-medium text-white">{r.quality_score?.toFixed(0) || '-'}</span>
                <span className="text-xs text-zinc-600">/ 100</span>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StatCard({ icon, label, value, color }: { icon: string; label: string; value: number | string; color: string }) {
  const bg = color === 'blue' ? 'border-blue-500/20 bg-blue-500/5' :
             color === 'purple' ? 'border-purple-500/20 bg-purple-500/5' :
             color === 'green' ? 'border-green-500/20 bg-green-500/5' :
             color === 'amber' ? 'border-amber-500/20 bg-amber-500/5' :
             'border-red-500/20 bg-red-500/5';
  return (
    <div className={`border rounded-xl p-4 ${bg}`}>
      <div className="text-xl mb-2">{icon}</div>
      <div className="text-2xl font-bold text-white">{value}</div>
      <div className="text-xs text-zinc-500">{label}</div>
    </div>
  );
}

function PriorityBadge({ priority }: { priority: string }) {
  const styles: Record<string, string> = {
    CRITICAL: 'bg-red-500/20 text-red-400',
    HIGH: 'bg-orange-500/20 text-orange-400',
    MEDIUM: 'bg-zinc-700 text-zinc-400',
    LOW: 'bg-zinc-800 text-zinc-500',
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full ${styles[priority] || styles.MEDIUM}`}>
      {priority}
    </span>
  );
}
