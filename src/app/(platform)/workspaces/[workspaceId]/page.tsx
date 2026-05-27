'use client';

import { useEffect, useRef, useState } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { useAppToast, useAppConfirm } from '@/components/ui/app-notifications';
import {
  workspaces as workspaceApi,
  applications as appApi,
  scenarios as scenariosApi,
  explore as exploreApi,
  reports as reportsApi,
  executions as executionsApi,
  type Application,
  type Scenario,
  type ExploreSession,
  type ReportSummary,
  type BatchRun,
  type BatchHistory,
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
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [loading, setLoading] = useState(true);

  // Scenario creation
  const [newScenarioTitle, setNewScenarioTitle] = useState('');
  const [newScenarioPriority, setNewScenarioPriority] = useState('MEDIUM');
  const [creatingScenario, setCreatingScenario] = useState(false);
  const [selectedScenarioId, setSelectedScenarioId] = useState<string | null>(null);
  const [generatingPlan, setGeneratingPlan] = useState(false);
  const [executionMode, setExecutionMode] = useState('functional');

  // Batch run
  const [runningModuleId, setRunningModuleId] = useState<string | null>(null);
  // Pre-loaded environment — avoids an extra API call on every "Run All" click
  const [cachedEnv, setCachedEnv] = useState<{ id: string } | null>(null);

  // Document upload modal
  const [docUploadOpen, setDocUploadOpen] = useState(false);
  const [docModuleName, setDocModuleName] = useState('');
  const [docModuleUrl, setDocModuleUrl] = useState('');
  const [docFile, setDocFile] = useState<File | null>(null);
  const [docUploading, setDocUploading] = useState(false);
  const [docUploadResult, setDocUploadResult] = useState<{ imported: number; module: string } | null>(null);

  // Explore
  const [startingExplore, setStartingExplore] = useState(false);
  const [exploreMode, setExploreMode] = useState<'SMART' | 'SKIP'>('SMART');

  // Settings
  const [settingsDesc, setSettingsDesc] = useState('');
  const [settingsUsername, setSettingsUsername] = useState('');
  const [settingsPassword, setSettingsPassword] = useState('');
  const [savingSettings, setSavingSettings] = useState(false);
  const [settingsSaved, setSettingsSaved] = useState(false);
  const [deletingWorkspace, setDeletingWorkspace] = useState(false);

  const toast = useAppToast();
  const confirm = useAppConfirm();

  const selectedAppRef = useRef(selectedApp);
  selectedAppRef.current = selectedApp;

  const socket = getSocket();

  useEffect(() => {
    const appId = searchParams.get('app');
    loadData(appId);
  }, [workspaceId]);

  useEffect(() => {
    socket.connect();

    const offRunCompleted = socket.on('run_completed', () => {
      if (selectedAppRef.current) loadReports(selectedAppRef.current.id);
    });

    // After exploration finishes → jump to Scenarios tab and refresh
    const offExploreCompleted = socket.on('explore_completed', () => {
      setTab('scenarios');
      if (selectedAppRef.current) loadScenarios(selectedAppRef.current.id);
    });

    return () => {
      offRunCompleted();
      offExploreCompleted();
    };
  }, []);

  useEffect(() => {
    if (selectedApp) {
      setSettingsDesc(selectedApp.description || '');
      setSettingsUsername('');
      setSettingsPassword('');
      setSettingsSaved(false);
      loadEnv(selectedApp.id);
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
          loadEnv(target.id),
        ]);
      }
    } catch (e) {
      console.error('Failed to load workspace data', e);
    } finally {
      setLoading(false);
    }
  };

  const loadEnv = async (appId: string) => {
    try {
      const envs = await appApi.listEnvironments(appId);
      const env = envs.find((e) => e.is_default) || envs[0];
      setCachedEnv(env ? { id: env.id } : null);
    } catch { setCachedEnv(null); }
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
      toast.error(e instanceof Error ? e.message : 'Failed to start execution');
    } finally {
      setGeneratingPlan(false);
      setSelectedScenarioId(null);
    }
  };

  const handleRunModule = async (scenarioIds: string[], moduleKey: string) => {
    if (!selectedApp || scenarioIds.length === 0) return;
    setRunningModuleId(moduleKey);

    // Use pre-loaded env — avoids a blocking API call on every Run All click
    let envId = cachedEnv?.id;
    if (!envId) {
      try {
        const envs = await appApi.listEnvironments(selectedApp.id);
        const env = envs.find((e) => e.is_default) || envs[0];
        if (!env) { toast.error('No environment configured'); setRunningModuleId(null); return; }
        envId = env.id;
        setCachedEnv({ id: env.id });
      } catch (e) {
        toast.error('Could not load environment');
        setRunningModuleId(null);
        return;
      }
    }

    try {
      const result = await scenariosApi.runBatch({
        scenario_ids: scenarioIds,
        execution_mode: executionMode,
        environment_id: envId,
      });

      const validRuns = result.runs.filter((r: { run_id?: string }) => r.run_id);
      if (validRuns.length === 0) {
        const firstError = result.runs.find((r: { error?: string }) => r.error);
        toast.error(`All runs failed: ${firstError?.error || 'Unknown error'}`);
        return;
      }

      // Navigate immediately — execution already started in the background
      if (validRuns.length === 1) {
        router.push(`/workspaces/${workspaceId}/executions/${validRuns[0].run_id}`);
      } else {
        const batchId = (result as { batch_id?: string }).batch_id;
        if (batchId) {
          router.push(`/workspaces/${workspaceId}/executions/batch?batch_id=${batchId}`);
        } else {
          // Fallback: encode data directly (small batches only)
          const batchData = (validRuns as Array<{ run_id: string; title: string }>).map((r) => ({
            run_id: r.run_id,
            title: r.title,
          }));
          router.push(`/workspaces/${workspaceId}/executions/batch?data=${encodeURIComponent(JSON.stringify(batchData))}`);
        }
      }
    } catch (e) {
      console.error('Failed to run module', e);
      toast.error(e instanceof Error ? e.message : 'Failed to run module');
    } finally {
      setRunningModuleId(null);
    }
  };

  const handleDeleteScenario = async (id: string) => {
    try {
      await scenariosApi.delete(id);
      setScenarios((s) => s.filter((sc) => sc.id !== id));
    } catch (e) {
      console.error('Failed to delete scenario', e);
    }
  };

  const handleUpdateScenario = async (id: string, data: { title?: string; description?: string; priority?: string; tags?: string[] }) => {
    try {
      const updated = await scenariosApi.update(id, data);
      setScenarios((s) => s.map((sc) => sc.id === id ? { ...sc, ...updated } : sc));
    } catch (e) {
      console.error('Failed to update scenario', e);
    }
  };

  const handleDeleteModule = async (moduleId: string | null) => {
    if (!selectedApp) return;
    try {
      await scenariosApi.deleteByModule(selectedApp.id, moduleId);
      if (moduleId && moduleId !== '__none__') {
        setScenarios((s) => s.filter((sc) => sc.module_id !== moduleId));
      } else {
        setScenarios((s) => s.filter((sc) => sc.module_id != null));
      }
    } catch (e) {
      console.error('Failed to delete module scenarios', e);
    }
  };

  const handleDocUpload = async () => {
    if (!selectedApp || !docModuleName.trim() || !docModuleUrl.trim() || !docFile) return;
    setDocUploading(true);
    setDocUploadResult(null);
    try {
      const result = await scenariosApi.importDocument({
        application_id: selectedApp.id,
        module_name: docModuleName.trim(),
        module_url: docModuleUrl.trim(),
        file: docFile,
      });
      setDocUploadResult({ imported: result.imported, module: result.module });
      await loadScenarios(selectedApp.id);
      // Reset form after success
      setDocModuleName('');
      setDocModuleUrl('');
      setDocFile(null);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Upload failed');
    } finally {
      setDocUploading(false);
    }
  };

  const handleStartExplore = async () => {
    if (!selectedApp) return;
    if (exploreMode === 'SKIP') {
      setTab('scenarios');
      return;
    }
    setStartingExplore(true);
    try {
      const session = await exploreApi.start({
        application_id: selectedApp.id,
        mode: exploreMode,
      });
      router.push(`/workspaces/${workspaceId}/explore/${session.id}`);
    } catch (e) {
      if (e instanceof Error && e.message.includes('already running')) {
        try {
          const active = await exploreApi.getActiveSession(selectedApp.id);
          if (active) {
            router.push(`/workspaces/${workspaceId}/explore/${active.id}`);
            return;
          }
        } catch { /* fall through */ }
      }
      console.error('Failed to start exploration', e);
      toast.error(e instanceof Error ? e.message : 'Exploration failed to start');
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
      toast.error('Failed to save settings');
    } finally {
      setSavingSettings(false);
    }
  };

  const handleDeleteWorkspace = async () => {
    const confirmed = await confirm({
      title: 'Delete this workspace?',
      message:
        'This will permanently remove all scenarios, exploration history, execution reports, and credentials. This action cannot be undone.',
      confirmLabel: 'Delete Workspace',
      destructive: true,
    });
    if (!confirmed) return;

    setDeletingWorkspace(true);
    try {
      await workspaceApi.delete(workspaceId);
      router.push('/workspaces');
    } catch (e) {
      console.error('Failed to delete workspace', e);
      toast.error(e instanceof Error ? e.message : 'Failed to delete workspace');
      setDeletingWorkspace(false);
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
      <div className="flex h-screen">
        {/* Sidebar */}
        <aside className="w-64 bg-zinc-900 border-r border-zinc-800 flex flex-col">
          <div className="p-4 border-b border-zinc-800">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-7 h-7 bg-blue-600 rounded-lg flex items-center justify-center">
                <span className="text-white font-bold text-xs">Q</span>
              </div>
              <span className="text-white font-semibold text-sm">QAptain</span>
            </div>
            <Link href="/workspaces" className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors">
              ← All Workspaces
            </Link>
          </div>

          {/* Application selector */}
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
              href="/workspaces/new"
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
                { id: 'scenarios', label: 'Scenarios', icon: '📋', badge: scenarios.length || undefined },
                { id: 'reports', label: 'Reports', icon: '📈' },
                { id: 'settings', label: 'Settings', icon: '⚙️' },
              ] as const
            ).map((item) => (
              <button
                key={item.id}
                onClick={() => setTab(item.id)}
                className={`w-full text-left flex items-center justify-between px-3 py-2 rounded-lg text-sm transition-colors ${
                  tab === item.id ? 'bg-zinc-800 text-white' : 'text-zinc-500 hover:bg-zinc-800/60 hover:text-zinc-300'
                }`}
              >
                <span className="flex items-center gap-2">
                  <span>{item.icon}</span>
                  {item.label}
                </span>
                {'badge' in item && item.badge ? (
                  <span className="text-xs bg-blue-600/30 text-blue-300 px-1.5 py-0.5 rounded-full">{item.badge}</span>
                ) : null}
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
                <>
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
                    onRunModule={handleRunModule}
                    onDeleteScenario={handleDeleteScenario}
                    onUpdateScenario={handleUpdateScenario}
                    onDeleteModule={handleDeleteModule}
                    onOpenDocUpload={() => { setDocUploadResult(null); setDocUploadOpen(true); }}
                    creating={creatingScenario}
                    runningId={generatingPlan ? selectedScenarioId : null}
                    runningModuleId={runningModuleId}
                  />

                  {/* Document Upload Modal */}
                  {docUploadOpen && (
                    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
                      <div className="bg-zinc-900 border border-zinc-700 rounded-2xl w-full max-w-md shadow-2xl">
                        <div className="p-6 border-b border-zinc-800">
                          <h2 className="text-lg font-semibold text-white">Upload Test Cases Document</h2>
                          <p className="text-sm text-zinc-400 mt-1">
                            AI will extract test cases from your DOCX or PDF file and link them to the module URL.
                            The executor will navigate to that URL automatically.
                          </p>
                        </div>

                        <div className="p-6 space-y-4">
                          {(() => {
                            const existingModules = [
                              ...new Map(
                                scenarios
                                  .filter((s) => s.module_name)
                                  .map((s) => [s.module_name, s.module_url ?? ''])
                              ).entries(),
                            ].map(([name, url]) => ({ name: name!, url }));
                            return (
                              <>
                                <div>
                                  <label className="block text-xs font-medium text-zinc-400 mb-1.5">
                                    Module Name <span className="text-red-400">*</span>
                                  </label>
                                  {existingModules.length > 0 ? (
                                    <>
                                      <select
                                        value={existingModules.some((m) => m.name === docModuleName) ? docModuleName : '__new__'}
                                        onChange={(e) => {
                                          if (e.target.value === '__new__') {
                                            setDocModuleName('');
                                            setDocModuleUrl('');
                                          } else {
                                            const found = existingModules.find((m) => m.name === e.target.value);
                                            if (found) {
                                              setDocModuleName(found.name);
                                              setDocModuleUrl(found.url);
                                            }
                                          }
                                        }}
                                        className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:ring-2 focus:ring-blue-500 mb-2"
                                      >
                                        <option value="__new__">— New module —</option>
                                        {existingModules.map((m) => (
                                          <option key={m.name} value={m.name}>{m.name}</option>
                                        ))}
                                      </select>
                                      {(!existingModules.some((m) => m.name === docModuleName) || docModuleName === '') && (
                                        <input
                                          type="text"
                                          value={docModuleName}
                                          onChange={(e) => setDocModuleName(e.target.value)}
                                          placeholder="Enter new module name…"
                                          className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                                        />
                                      )}
                                    </>
                                  ) : (
                                    <input
                                      type="text"
                                      value={docModuleName}
                                      onChange={(e) => setDocModuleName(e.target.value)}
                                      placeholder="e.g. Samples & Receipts"
                                      className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                                    />
                                  )}
                                </div>

                                <div>
                                  <label className="block text-xs font-medium text-zinc-400 mb-1.5">
                                    Module URL <span className="text-red-400">*</span>
                                  </label>
                                  <input
                                    type="text"
                                    value={docModuleUrl}
                                    onChange={(e) => setDocModuleUrl(e.target.value)}
                                    placeholder="e.g. http://ylims.app/#/samples"
                                    className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                                  />
                                  <p className="text-xs text-zinc-600 mt-1">
                                    After login, the executor will navigate here before running each scenario.
                                  </p>
                                </div>
                              </>
                            );
                          })()}

                          <div>
                            <label className="block text-xs font-medium text-zinc-400 mb-1.5">
                              Test Cases File (DOCX, PDF, or Excel) <span className="text-red-400">*</span>
                            </label>
                            <label className="flex items-center gap-3 w-full bg-zinc-800 border border-dashed border-zinc-600 rounded-lg px-3 py-3 cursor-pointer hover:border-blue-500 transition-colors">
                              <span className="text-lg">📄</span>
                              <div className="flex-1 min-w-0">
                                {docFile ? (
                                  <span className="text-sm text-zinc-200 truncate block">{docFile.name}</span>
                                ) : (
                                  <span className="text-sm text-zinc-500">Click to choose file…</span>
                                )}
                              </div>
                              <input
                                type="file"
                                accept=".docx,.pdf,.xlsx,.xls"
                                className="hidden"
                                onChange={(e) => setDocFile(e.target.files?.[0] || null)}
                              />
                            </label>
                          </div>

                          {docUploadResult && (
                            <div className="bg-green-500/10 border border-green-500/30 rounded-lg px-4 py-3">
                              <p className="text-sm text-green-300 font-medium">
                                ✓ {docUploadResult.imported} test cases extracted for "{docUploadResult.module}"
                              </p>
                              <p className="text-xs text-green-400/70 mt-0.5">
                                They are now visible in the Scenarios list below.
                              </p>
                            </div>
                          )}
                        </div>

                        <div className="p-6 pt-0 flex items-center justify-between gap-3">
                          <button
                            onClick={() => { setDocUploadOpen(false); setDocUploadResult(null); }}
                            className="px-4 py-2 text-sm text-zinc-400 hover:text-zinc-200 transition-colors"
                          >
                            {docUploadResult ? 'Close' : 'Cancel'}
                          </button>
                          {!docUploadResult && (
                            <button
                              onClick={handleDocUpload}
                              disabled={docUploading || !docModuleName.trim() || !docModuleUrl.trim() || !docFile}
                              className="px-5 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50 flex items-center gap-2"
                            >
                              {docUploading && (
                                <div className="animate-spin w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full" />
                              )}
                              {docUploading ? 'Extracting with AI…' : 'Upload & Extract'}
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </>
              )}
              {tab === 'reports' && selectedApp && (
                <ReportsTab reports={reports} workspaceId={workspaceId} appId={selectedApp.id} />
              )}
              {tab === 'settings' && (
                <SettingsTab
                  app={selectedApp}
                  desc={settingsDesc}
                  setDesc={setSettingsDesc}
                  username={settingsUsername}
                  setUsername={setSettingsUsername}
                  password={settingsPassword}
                  setPassword={setSettingsPassword}
                  onSave={handleSaveSettings}
                  saving={savingSettings}
                  saved={settingsSaved}
                  onDeleteWorkspace={handleDeleteWorkspace}
                  deletingWorkspace={deletingWorkspace}
                />
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}

// ─── Overview Tab ─────────────────────────────────────────────────────────────

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

      <div className="grid grid-cols-4 gap-4 mb-8">
        <StatCard icon="📦" label="Modules" value={app.modules_count} color="blue" />
        <StatCard icon="📋" label="Scenarios" value={scenarios.length} color="purple" />
        <StatCard icon="📊" label="Executions" value={reports.length} color="green" />
        <StatCard icon="✓" label="Pass Rate" value={`${passRate}%`} color={passRate >= 80 ? 'green' : passRate >= 50 ? 'amber' : 'red'} />
      </div>

      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 mb-6">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="font-semibold text-white mb-1">Application Knowledge</h3>
            <p className="text-sm text-zinc-500">
              {app.has_knowledge
                ? `Knowledge graph built. ${app.modules_count} modules discovered.`
                : 'No knowledge graph yet. Run exploration to let AI understand your application.'}
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

      {scenarios.length > 0 && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 mb-6">
          <h3 className="font-semibold text-white mb-3">Quick Execute</h3>
          <div className="space-y-2">
            {scenarios.slice(0, 5).map((s) => (
              <div key={s.id} className="flex items-center justify-between p-3 bg-zinc-800/50 rounded-lg">
                <div className="flex-1 min-w-0 mr-3">
                  <span className="text-sm text-zinc-300 truncate block">{s.title}</span>
                  {s.module_name && (
                    <span className="text-xs text-zinc-500">{s.module_name}</span>
                  )}
                </div>
                <PriorityBadge priority={s.priority} />
                <button
                  onClick={() => onRunScenario(s.id)}
                  className="ml-3 text-xs px-3 py-1 bg-green-600/20 hover:bg-green-600/30 text-green-400 border border-green-600/30 rounded-lg transition-colors"
                >
                  Run
                </button>
              </div>
            ))}
          </div>
          {scenarios.length > 5 && (
            <button onClick={onScenariosClick} className="mt-3 text-xs text-zinc-500 hover:text-zinc-300">
              View all {scenarios.length} scenarios →
            </button>
          )}
        </div>
      )}

      {recentReports.length > 0 && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5">
          <h3 className="font-semibold text-white mb-3">Recent Executions</h3>
          <div className="space-y-2">
            {recentReports.map((r) => (
              <div key={r.id} className="flex items-center justify-between text-sm">
                <span className="text-zinc-400 truncate flex-1 mr-4">{r.scenario_title}</span>
                <span className={`text-xs px-2 py-0.5 rounded-full ${
                  r.run_status === 'COMPLETED' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                }`}>{r.risk_level}</span>
                <span className="text-zinc-600 ml-3 text-xs">{r.quality_score?.toFixed(0) || '-'}/100</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Explore Tab ──────────────────────────────────────────────────────────────

function ExploreTab({ app, exploreMode, setExploreMode, onStart, loading }: {
  app: Application;
  exploreMode: 'SMART' | 'SKIP';
  setExploreMode: (m: 'SMART' | 'SKIP') => void;
  onStart: () => void;
  loading: boolean;
}) {
  const modes = [
    { id: 'SMART' as const, icon: '🔍', title: 'Smart Explore', desc: 'Complete application mapping — clicks every module, sub-module, and link. Builds full knowledge graph including forms, workflows, and test scenarios.', time: '15–45 min' },
    { id: 'SKIP' as const, icon: '🎯', title: 'Skip Explore', desc: 'Semantic runtime reasoning — no pre-exploration needed', time: 'Instant' },
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-2">Explore Application</h1>
      <p className="text-zinc-500 text-sm mb-6">
        QAptain will learn {app.name} semantically — understanding modules, workflows, forms, and dynamic UI behavior.
        After exploration finishes you will be taken directly to the Scenarios page.
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
        {exploreMode === 'SKIP' ? 'Go to Scenarios →' : 'Start Exploration'}
      </button>
    </div>
  );
}

// ─── Scenarios Tab ────────────────────────────────────────────────────────────

function ScenarioViewModal({ scenario, onClose, onEdit }: { scenario: Scenario; onClose: () => void; onEdit: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-zinc-900 border border-zinc-700 rounded-2xl w-full max-w-2xl max-h-[85vh] flex flex-col shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between px-6 py-4 border-b border-zinc-800">
          <div className="flex-1 min-w-0 pr-4">
            <div className="flex items-center gap-2 flex-wrap mb-1">
              <PriorityBadge priority={scenario.priority} />
              <SourceBadge source={scenario.source} />
              {scenario.module_name && (
                <span className="text-xs bg-zinc-700/60 text-zinc-400 px-2 py-0.5 rounded-full">{scenario.module_name}</span>
              )}
            </div>
            <h2 className="text-lg font-semibold text-white leading-snug">{scenario.title}</h2>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button onClick={onEdit} className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border border-blue-600/30 rounded-lg transition-colors">
              ✏️ Edit
            </button>
            <button onClick={onClose} className="text-zinc-500 hover:text-white transition-colors text-xl leading-none px-1">✕</button>
          </div>
        </div>
        <div className="overflow-y-auto flex-1 px-6 py-5 space-y-5">
          {scenario.description ? (
            <div>
              <h3 className="text-xs font-semibold text-zinc-500 uppercase tracking-wide mb-2">Description / Steps</h3>
              <div className="text-sm text-zinc-300 whitespace-pre-wrap bg-zinc-800/50 rounded-xl p-4 border border-zinc-700/50 leading-relaxed">
                {scenario.description}
              </div>
            </div>
          ) : (
            <p className="text-sm text-zinc-600 italic">No description provided.</p>
          )}
          {scenario.tags && scenario.tags.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-zinc-500 uppercase tracking-wide mb-2">Tags</h3>
              <div className="flex flex-wrap gap-1.5">
                {scenario.tags.map((tag) => (
                  <span key={tag} className="text-xs bg-zinc-700/60 text-zinc-400 px-2 py-0.5 rounded-full">{tag}</span>
                ))}
              </div>
            </div>
          )}
          <div className="text-xs text-zinc-600">
            Created {scenario.created_at ? new Date(scenario.created_at).toLocaleString() : '—'}
          </div>
        </div>
      </div>
    </div>
  );
}

function ScenarioEditModal({ scenario, onClose, onSave }: {
  scenario: Scenario;
  onClose: () => void;
  onSave: (id: string, data: { title: string; description: string; priority: string; tags: string[] }) => Promise<void>;
}) {
  const [title, setTitle] = useState(scenario.title);
  const [description, setDescription] = useState(scenario.description || '');
  const [priority, setPriority] = useState<string>(scenario.priority);
  const [tagsInput, setTagsInput] = useState((scenario.tags || []).join(', '));
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (!title.trim()) return;
    setSaving(true);
    try {
      await onSave(scenario.id, {
        title: title.trim(),
        description: description.trim(),
        priority,
        tags: tagsInput.split(',').map((t) => t.trim()).filter(Boolean),
      });
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-zinc-900 border border-zinc-700 rounded-2xl w-full max-w-2xl max-h-[90vh] flex flex-col shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-800">
          <h2 className="text-base font-semibold text-white">Edit Scenario</h2>
          <button onClick={onClose} className="text-zinc-500 hover:text-white transition-colors text-xl leading-none px-1">✕</button>
        </div>
        <div className="overflow-y-auto flex-1 px-6 py-5 space-y-4">
          <div>
            <label className="text-xs font-medium text-zinc-400 uppercase tracking-wide block mb-1.5">Title</label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2.5 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-zinc-400 uppercase tracking-wide block mb-1.5">Description / Steps</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={10}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2.5 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y font-mono leading-relaxed"
              placeholder="Describe the test steps and expected outcome…"
            />
          </div>
          <div className="flex gap-4">
            <div className="flex-1">
              <label className="text-xs font-medium text-zinc-400 uppercase tracking-wide block mb-1.5">Priority</label>
              <select
                value={priority}
                onChange={(e) => setPriority(e.target.value)}
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2.5 text-zinc-300 text-sm focus:outline-none"
              >
                <option value="CRITICAL">Critical</option>
                <option value="HIGH">High</option>
                <option value="MEDIUM">Medium</option>
                <option value="LOW">Low</option>
              </select>
            </div>
            <div className="flex-1">
              <label className="text-xs font-medium text-zinc-400 uppercase tracking-wide block mb-1.5">Tags (comma-separated)</label>
              <input
                value={tagsInput}
                onChange={(e) => setTagsInput(e.target.value)}
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2.5 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="smoke, regression, critical-path"
              />
            </div>
          </div>
        </div>
        <div className="flex justify-end gap-3 px-6 py-4 border-t border-zinc-800">
          <button onClick={onClose} className="px-4 py-2 text-sm text-zinc-400 hover:text-white transition-colors">Cancel</button>
          <button
            onClick={handleSave}
            disabled={saving || !title.trim()}
            className="px-5 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition-colors disabled:opacity-50 flex items-center gap-2"
          >
            {saving && <div className="animate-spin w-3.5 h-3.5 border border-white border-t-transparent rounded-full" />}
            {saving ? 'Saving…' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  );
}

function ScenariosTab({
  app, scenarios, newTitle, setNewTitle, priority, setPriority,
  executionMode, setExecutionMode, onCreateScenario, onRunScenario,
  onRunModule, onDeleteScenario, onUpdateScenario, onDeleteModule, onOpenDocUpload,
  creating, runningId, runningModuleId,
}: {
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
  onRunModule: (ids: string[], moduleKey: string) => void;
  onDeleteScenario: (id: string) => void;
  onUpdateScenario: (id: string, data: { title?: string; description?: string; priority?: string; tags?: string[] }) => Promise<void>;
  onDeleteModule: (moduleId: string | null) => Promise<void>;
  onOpenDocUpload: () => void;
  creating: boolean;
  runningId: string | null;
  runningModuleId: string | null;
}) {
  const [search, setSearch] = useState('');
  const [viewScenario, setViewScenario] = useState<Scenario | null>(null);
  const [editScenario, setEditScenario] = useState<Scenario | null>(null);
  const [deletingModuleId, setDeletingModuleId] = useState<string | null>(null);

  const filtered = search.trim()
    ? scenarios.filter((s) =>
        s.title.toLowerCase().includes(search.toLowerCase()) ||
        (s.module_name || '').toLowerCase().includes(search.toLowerCase()) ||
        (s.description || '').toLowerCase().includes(search.toLowerCase()),
      )
    : scenarios;

  type Group = { moduleName: string | null; moduleUrl: string | null; moduleId: string | null; items: Scenario[] };
  const groups: Group[] = [];
  const moduleMap = new Map<string, Group>();

  for (const s of filtered) {
    const key = s.module_id || '__none__';
    if (!moduleMap.has(key)) {
      const g: Group = { moduleName: s.module_name || null, moduleUrl: s.module_url || null, moduleId: s.module_id || null, items: [] };
      moduleMap.set(key, g);
      groups.push(g);
    }
    moduleMap.get(key)!.items.push(s);
  }

  const handleDeleteModule = async (moduleId: string | null) => {
    const key = moduleId || '__none__';
    if (!window.confirm(`Delete all ${moduleMap.get(key)?.items.length ?? 0} scenarios in this group?`)) return;
    setDeletingModuleId(key);
    try {
      await onDeleteModule(moduleId);
    } finally {
      setDeletingModuleId(null);
    }
  };

  return (
    <div>
      {/* View modal */}
      {viewScenario && !editScenario && (
        <ScenarioViewModal
          scenario={viewScenario}
          onClose={() => setViewScenario(null)}
          onEdit={() => { setEditScenario(viewScenario); setViewScenario(null); }}
        />
      )}
      {/* Edit modal */}
      {editScenario && (
        <ScenarioEditModal
          scenario={editScenario}
          onClose={() => setEditScenario(null)}
          onSave={async (id, data) => {
            await onUpdateScenario(id, data);
            setEditScenario(null);
          }}
        />
      )}

      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Test Scenarios</h1>
          <p className="text-sm text-zinc-500 mt-0.5">
            {scenarios.length} scenario{scenarios.length !== 1 ? 's' : ''} for {app.name}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onOpenDocUpload}
            className="flex items-center gap-2 px-4 py-2 bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-zinc-200 text-sm rounded-lg transition-colors"
          >
            <span>📄</span> Upload Test Cases
          </button>
        </div>
      </div>

      {/* Search */}
      <div className="relative mb-5">
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500 text-sm">🔍</span>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search scenarios or modules…"
          className="w-full bg-zinc-900 border border-zinc-800 rounded-xl pl-9 pr-4 py-2.5 text-sm text-zinc-200 placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        {search && filtered.length > 0 && (
          <button
            onClick={() => onRunModule(filtered.map((s) => s.id), '__search__')}
            disabled={!!runningModuleId}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-xs px-3 py-1 bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border border-blue-600/30 rounded-md transition-colors disabled:opacity-50"
          >
            {runningModuleId === '__search__' ? <span className="animate-spin inline-block w-3 h-3 border border-blue-300 border-t-transparent rounded-full" /> : null}
            {' '}Run {filtered.length} matching
          </button>
        )}
      </div>

      {/* Execution mode */}
      <div className="flex items-center gap-3 mb-5">
        <span className="text-xs text-zinc-500">Execution mode:</span>
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

      {/* Add scenario */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 mb-6">
        <h3 className="text-xs font-medium text-zinc-500 mb-3 uppercase tracking-wide">Add Scenario Manually</h3>
        <div className="flex gap-2">
          <input
            type="text"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && onCreateScenario()}
            placeholder="e.g. Verify sample creation and inventory update"
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

      {/* Scenario groups */}
      {filtered.length === 0 ? (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-12 text-center">
          <p className="text-zinc-500 mb-4">
            {search ? `No scenarios matching "${search}"` : 'No scenarios yet.'}
          </p>
          {!search && (
            <div className="flex flex-col items-center gap-3">
              <p className="text-zinc-600 text-sm">Start by exploring the application or uploading a test cases file.</p>
              <button
                onClick={onOpenDocUpload}
                className="px-4 py-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm rounded-lg transition-colors"
              >
                Upload Test Cases Document
              </button>
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          {groups.map((group, gi) => (
            <div key={gi} className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
              {/* Module header */}
              <div className="flex items-center justify-between px-5 py-3 bg-zinc-800/60 border-b border-zinc-800">
                <div className="flex items-center gap-2 min-w-0">
                  {group.moduleName ? (
                    <>
                      <span className="text-sm font-medium text-zinc-200">{group.moduleName}</span>
                      {group.moduleUrl && (
                        <span className="text-xs text-zinc-500 truncate max-w-xs">{group.moduleUrl}</span>
                      )}
                      <span className="text-xs bg-blue-600/20 text-blue-300 px-1.5 py-0.5 rounded-full">
                        {group.items.length}
                      </span>
                    </>
                  ) : (
                    <>
                      <span className="text-sm font-medium text-zinc-400">General / Unassigned</span>
                      <span className="text-xs bg-zinc-700/60 text-zinc-400 px-1.5 py-0.5 rounded-full">
                        {group.items.length}
                      </span>
                    </>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0 ml-4">
                  <button
                    onClick={() => onRunModule(group.items.map((s) => s.id), group.moduleId || '__ungrouped__')}
                    disabled={!!runningModuleId}
                    className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border border-blue-600/30 rounded-lg transition-colors disabled:opacity-50"
                  >
                    {runningModuleId === (group.moduleId || '__ungrouped__') ? (
                      <div className="animate-spin w-3 h-3 border border-blue-300 border-t-transparent rounded-full" />
                    ) : '▶'}
                    {runningModuleId === (group.moduleId || '__ungrouped__') ? ' Starting…' : ' Run All'}
                  </button>
                  <button
                    onClick={() => handleDeleteModule(group.moduleId)}
                    disabled={deletingModuleId === (group.moduleId || '__none__')}
                    className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-red-600/10 hover:bg-red-600/20 text-red-400 border border-red-600/20 rounded-lg transition-colors disabled:opacity-50"
                    title="Delete all scenarios in this group"
                  >
                    {deletingModuleId === (group.moduleId || '__none__') ? (
                      <div className="animate-spin w-3 h-3 border border-red-400 border-t-transparent rounded-full" />
                    ) : '🗑'}
                    Delete All
                  </button>
                </div>
              </div>

              {/* Scenario rows */}
              <div className="divide-y divide-zinc-800">
                {group.items.map((s) => (
                  <div key={s.id} className="flex items-center gap-3 px-5 py-3 hover:bg-zinc-800/30 transition-colors group">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm text-zinc-200 truncate">{s.title}</span>
                        <SourceBadge source={s.source} />
                      </div>
                      {s.description && (
                        <div className="text-xs text-zinc-600 truncate mt-0.5">{s.description}</div>
                      )}
                    </div>
                    <PriorityBadge priority={s.priority} />
                    {/* View */}
                    <button
                      onClick={() => setViewScenario(s)}
                      className="text-zinc-600 hover:text-blue-400 transition-colors opacity-0 group-hover:opacity-100 text-sm px-1 shrink-0"
                      title="View full scenario"
                    >
                      👁
                    </button>
                    {/* Edit */}
                    <button
                      onClick={() => setEditScenario(s)}
                      className="text-zinc-600 hover:text-yellow-400 transition-colors opacity-0 group-hover:opacity-100 text-sm px-1 shrink-0"
                      title="Edit scenario"
                    >
                      ✏️
                    </button>
                    <button
                      onClick={() => onRunScenario(s.id)}
                      disabled={runningId === s.id}
                      className="text-xs px-3 py-1.5 bg-green-600/20 hover:bg-green-600/30 text-green-400 border border-green-600/30 rounded-lg transition-colors disabled:opacity-50 flex items-center gap-1.5 shrink-0"
                    >
                      {runningId === s.id && (
                        <div className="animate-spin w-3 h-3 border border-green-400 border-t-transparent rounded-full" />
                      )}
                      {runningId === s.id ? 'Planning…' : 'Run'}
                    </button>
                    {/* Delete */}
                    <button
                      onClick={() => onDeleteScenario(s.id)}
                      className="text-zinc-600 hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100 text-sm px-1 shrink-0"
                      title="Delete scenario"
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Reports Tab ──────────────────────────────────────────────────────────────

function ReportsTab({
  reports,
  workspaceId,
  appId,
}: {
  reports: ReportSummary[];
  workspaceId: string;
  appId: string;
}) {
  const router = useRouter();
  const [view, setView] = useState<'reports' | 'history'>('reports');
  const [history, setHistory] = useState<BatchHistory[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [expandedBatch, setExpandedBatch] = useState<string | null>(null);

  const loadHistory = async () => {
    setHistoryLoading(true);
    try {
      const data = await executionsApi.batchHistory(appId, 30);
      setHistory(data);
    } catch { setHistory([]); }
    finally { setHistoryLoading(false); }
  };

  useEffect(() => {
    if (view === 'history') loadHistory();
  }, [view]);

  const openBatchDetail = (batch: BatchHistory) => {
    router.push(
      `/workspaces/${workspaceId}/executions/batch?batch_id=${batch.batch_id}`
    );
  };

  const passRate = (b: BatchHistory) =>
    b.total > 0 ? Math.round((b.passed / b.total) * 100) : 0;

  return (
    <div>
      {/* Header + toggle */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">Execution Reports</h1>
        <div className="flex bg-zinc-800 rounded-lg p-1 gap-1">
          <button
            onClick={() => setView('reports')}
            className={`px-4 py-1.5 text-sm rounded-md transition-colors font-medium ${
              view === 'reports' ? 'bg-zinc-700 text-white' : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            AI Reports
          </button>
          <button
            onClick={() => setView('history')}
            className={`px-4 py-1.5 text-sm rounded-md transition-colors font-medium ${
              view === 'history' ? 'bg-zinc-700 text-white' : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            Run History
          </button>
        </div>
      </div>

      {/* ── AI Reports view ───────────────────────────────────────── */}
      {view === 'reports' && (
        reports.length === 0 ? (
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-10 text-center text-zinc-500">
            No reports yet. Run some scenarios to see AI-native reports here.
          </div>
        ) : (
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
            <div className="divide-y divide-zinc-800">
              {reports.map((r) => {
                const s = r.summary;
                const passRate = s.pass_rate ?? (s.total ? Math.round(((s.passed ?? 0) / s.total) * 100) : null);
                const checkpointInfo = s.checkpoints_total
                  ? `${s.checkpoints_passed ?? 0}/${s.checkpoints_total} checkpoints`
                  : null;
                return (
                  <Link
                    key={r.id}
                    href={`/workspaces/${workspaceId}/executions/${r.run_id}`}
                    className="flex items-start gap-4 px-5 py-4 hover:bg-zinc-800/50 transition-colors"
                  >
                    {/* Status dot */}
                    <div className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${
                      r.run_status === 'COMPLETED' ? 'bg-green-500' :
                      r.run_status === 'FAILED' ? 'bg-red-500' : 'bg-zinc-500'
                    }`} />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-zinc-300 truncate">{r.scenario_title}</div>
                      <div className="flex items-center gap-3 mt-1 flex-wrap">
                        <span className="text-xs text-zinc-600">
                          {new Date(r.created_at).toLocaleString(undefined, {
                            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
                          })}
                        </span>
                        {s.workflow_type && (
                          <span className="text-xs text-zinc-600 bg-zinc-800 px-1.5 py-0.5 rounded">{s.workflow_type}</span>
                        )}
                        {s.total != null && (
                          <span className="text-xs text-zinc-500">{s.passed}/{s.total} steps</span>
                        )}
                        {checkpointInfo && (
                          <span className="text-xs text-zinc-500">{checkpointInfo}</span>
                        )}
                        {(s.phases_failed?.length ?? 0) > 0 && (
                          <span className="text-xs text-red-400/70">{s.phases_failed!.join(', ')} failed</span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      {passRate !== null && (
                        <div className="text-right">
                          <div className={`text-sm font-bold tabular-nums ${
                            passRate === 100 ? 'text-green-400' : passRate >= 50 ? 'text-amber-400' : 'text-red-400'
                          }`}>{passRate}%</div>
                          <div className="text-xs text-zinc-600">pass rate</div>
                        </div>
                      )}
                      <div className="text-right">
                        <div className="text-sm font-bold text-white tabular-nums">{r.quality_score?.toFixed(0) ?? '–'}</div>
                        <div className="text-xs text-zinc-600">/ 100</div>
                      </div>
                      <span className={`text-xs px-2 py-0.5 rounded-full ${
                        r.risk_level === 'LOW' ? 'bg-green-500/20 text-green-400' :
                        r.risk_level === 'MEDIUM' ? 'bg-amber-500/20 text-amber-400' :
                        'bg-red-500/20 text-red-400'
                      }`}>
                        {r.risk_level ?? 'LOW'}
                      </span>
                    </div>
                  </Link>
                );
              })}
            </div>
          </div>
        )
      )}

      {/* ── Run History view ──────────────────────────────────────── */}
      {view === 'history' && (
        historyLoading ? (
          <div className="flex items-center justify-center py-20">
            <div className="w-6 h-6 border-2 border-blue-500/40 border-t-blue-500 rounded-full animate-spin" />
          </div>
        ) : history.length === 0 ? (
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-10 text-center text-zinc-500">
            No batch execution history yet. Click "Run All" on a module to start.
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {history.map((batch) => {
              const rate = passRate(batch);
              const isExpanded = expandedBatch === batch.batch_id;
              const isRunning = batch.running > 0;
              return (
                <div
                  key={batch.batch_id}
                  className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden"
                >
                  {/* Batch summary row */}
                  <div className="flex items-center gap-4 px-5 py-4">
                    <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${
                      isRunning ? 'bg-blue-500 animate-pulse' :
                      batch.failed === 0 ? 'bg-green-500' :
                      batch.passed === 0 ? 'bg-red-500' : 'bg-amber-500'
                    }`} />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-zinc-200">
                        {new Date(batch.started_at).toLocaleString(undefined, {
                          month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
                        })}
                      </div>
                      <div className="text-xs text-zinc-500 mt-0.5">
                        {batch.total} scenarios · {batch.passed} passed · {batch.failed} failed
                        {isRunning ? ` · ${batch.running} running` : ''}
                      </div>
                    </div>

                    {/* Pass rate bar */}
                    <div className="hidden sm:flex items-center gap-2 w-32">
                      <div className="flex-1 h-1.5 bg-zinc-800 rounded-full overflow-hidden flex">
                        <div className="bg-green-500 h-full" style={{ width: `${rate}%` }} />
                        <div className="bg-red-500 h-full" style={{ width: `${batch.total > 0 ? (batch.failed / batch.total) * 100 : 0}%` }} />
                      </div>
                      <span className={`text-xs font-medium tabular-nums w-8 text-right ${
                        rate === 100 ? 'text-green-400' : rate >= 50 ? 'text-amber-400' : 'text-red-400'
                      }`}>{rate}%</span>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        onClick={() => setExpandedBatch(isExpanded ? null : batch.batch_id)}
                        className="text-xs text-zinc-400 hover:text-zinc-200 transition-colors px-2 py-1 rounded hover:bg-zinc-800"
                      >
                        {isExpanded ? 'Hide' : 'Details'}
                      </button>
                      <button
                        onClick={() => openBatchDetail(batch)}
                        className="text-xs bg-blue-600 hover:bg-blue-500 text-white px-3 py-1.5 rounded-lg transition-colors font-medium"
                      >
                        View Full Report
                      </button>
                    </div>
                  </div>

                  {/* Expanded scenario list */}
                  {isExpanded && (
                    <div className="border-t border-zinc-800 divide-y divide-zinc-800/60">
                      {batch.runs.map((run) => {
                        const stepRate = run.total_steps > 0
                          ? Math.round((run.passed_steps / run.total_steps) * 100)
                          : null;
                        return (
                          <div
                            key={run.run_id}
                            className="flex items-center gap-3 px-6 py-3 hover:bg-zinc-800/30 transition-colors cursor-pointer"
                            onClick={() => router.push(`/workspaces/${workspaceId}/executions/${run.run_id}`)}
                          >
                            <div className={`w-2 h-2 rounded-full shrink-0 ${
                              run.status === 'COMPLETED' ? 'bg-green-500' :
                              run.status === 'FAILED' ? 'bg-red-500' :
                              run.status === 'RUNNING' ? 'bg-blue-500 animate-pulse' :
                              'bg-zinc-600'
                            }`} />
                            <span className="flex-1 text-xs text-zinc-300 truncate">{run.title || 'Untitled scenario'}</span>
                            {stepRate !== null && (
                              <span className={`text-xs tabular-nums ${
                                stepRate === 100 ? 'text-green-400' : stepRate >= 50 ? 'text-amber-400' : 'text-red-400'
                              }`}>{stepRate}%</span>
                            )}
                            <span className={`text-xs px-2 py-0.5 rounded-full ${
                              run.status === 'COMPLETED' ? 'bg-green-500/15 text-green-400' :
                              run.status === 'FAILED' ? 'bg-red-500/15 text-red-400' :
                              run.status === 'RUNNING' ? 'bg-blue-500/15 text-blue-300' :
                              'bg-zinc-800 text-zinc-500'
                            }`}>
                              {run.status === 'COMPLETED' ? 'Passed' : run.status === 'FAILED' ? 'Failed' : run.status}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )
      )}
    </div>
  );
}

// ─── Settings Tab ─────────────────────────────────────────────────────────────

function SettingsTab({ app, desc, setDesc, username, setUsername, password, setPassword, onSave, saving, saved, onDeleteWorkspace, deletingWorkspace }: {
  app: Application;
  desc: string;
  setDesc: (v: string) => void;
  username: string;
  setUsername: (v: string) => void;
  password: string;
  setPassword: (v: string) => void;
  onSave: () => void;
  saving: boolean;
  saved: boolean;
  onDeleteWorkspace: () => void;
  deletingWorkspace: boolean;
}) {
  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-white mb-1">Application Settings</h2>
        <p className="text-sm text-zinc-500">Update description and credentials for {app.name}</p>
      </div>

      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-4">
        <h3 className="text-sm font-medium text-zinc-300">General</h3>
        <div>
          <label className="block text-xs text-zinc-500 mb-1">Description</label>
          <textarea
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
            rows={3}
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-blue-500"
            placeholder="What does this application do?"
          />
        </div>
        <div>
          <label className="block text-xs text-zinc-500 mb-1">Base URL</label>
          <input
            value={app.base_url}
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
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-blue-500"
            placeholder="username or email"
          />
        </div>
        <div>
          <label className="block text-xs text-zinc-500 mb-1">New Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-blue-500"
            placeholder="leave blank to keep existing"
          />
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={onSave}
          disabled={saving}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save Changes'}
        </button>
        {saved && <span className="text-sm text-green-400">✓ Saved successfully</span>}
      </div>

      {/* Danger Zone */}
      <div className="border border-red-500/30 rounded-xl overflow-hidden">
        <div className="px-5 py-3 bg-red-500/5 border-b border-red-500/20">
          <h3 className="text-sm font-semibold text-red-400">Danger Zone</h3>
        </div>
        <div className="p-5 flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-white">Delete this workspace</p>
            <p className="text-xs text-zinc-500 mt-0.5">
              Permanently removes all scenarios, exploration data, execution reports, and settings. Cannot be undone.
            </p>
          </div>
          <button
            onClick={onDeleteWorkspace}
            disabled={deletingWorkspace}
            className="shrink-0 px-4 py-2 bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
          >
            {deletingWorkspace ? 'Deleting…' : 'Delete Workspace'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Shared components ────────────────────────────────────────────────────────

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
    <span className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${styles[priority] || styles.MEDIUM}`}>
      {priority}
    </span>
  );
}

function SourceBadge({ source }: { source: string }) {
  const map: Record<string, { label: string; style: string }> = {
    ai_generated: { label: 'AI', style: 'bg-purple-500/20 text-purple-300' },
    document: { label: 'Doc', style: 'bg-amber-500/20 text-amber-300' },
    excel: { label: 'Excel', style: 'bg-green-500/20 text-green-300' },
    csv: { label: 'CSV', style: 'bg-teal-500/20 text-teal-300' },
    manual: { label: 'Manual', style: 'bg-zinc-700 text-zinc-400' },
  };
  const info = map[source] || map.manual;
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded ${info.style} shrink-0`}>
      {info.label}
    </span>
  );
}
