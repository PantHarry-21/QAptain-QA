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
  knowledge as knowledgeApi,
  datasets as datasetsApi,
  type Application,
  type Module,
  type Scenario,
  type ReportSummary,
  type BatchHistory,
  type KgCoverageReport,
  type KgModuleCoverage,
  type TestDatasetItem,
  type PlaywrightScript,
} from '@/lib/api';
import { getSocket } from '@/lib/websocket';

type ActiveTab = 'overview' | 'explore' | 'scenarios' | 'dataset' | 'knowledge' | 'reports' | 'settings';

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

  // App switching
  const [loadingAppId, setLoadingAppId] = useState<string | null>(null);

  // Batch run
  const [runningModuleId, setRunningModuleId] = useState<string | null>(null);
  // Pre-loaded environment — avoids an extra API call on every "Run All" click
  const [cachedEnv, setCachedEnv] = useState<{ id: string } | null>(null);
  // Live run tracking — updated by WebSocket events
  const [activeRunCount, setActiveRunCount] = useState(0);

  // Add Application modal
  const [showAddApp, setShowAddApp] = useState(false);
  const [addAppName, setAddAppName] = useState('');
  const [addAppUrl, setAddAppUrl] = useState('');
  const [addAppDesc, setAddAppDesc] = useState('');
  const [addAppUser, setAddAppUser] = useState('');
  const [addAppPass, setAddAppPass] = useState('');
  const [addingApp, setAddingApp] = useState(false);

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
  const [discoveryStatus, setDiscoveryStatus] = useState<'idle' | 'running' | 'completed'>('idle');
  const [selectedModuleIds, setSelectedModuleIds] = useState<Set<string>>(new Set());

  // Settings
  const [settingsDesc, setSettingsDesc] = useState('');
  const [settingsUsername, setSettingsUsername] = useState('');
  const [settingsPassword, setSettingsPassword] = useState('');
  const [settingsHasPassword, setSettingsHasPassword] = useState(false);
  const [savingSettings, setSavingSettings] = useState(false);
  const [settingsSaved, setSettingsSaved] = useState(false);
  const [deletingWorkspace, setDeletingWorkspace] = useState(false);
  const [deletingApp, setDeletingApp] = useState(false);

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

    const offRunStarted = socket.on('run_started', () => {
      setActiveRunCount((n) => n + 1);
    });

    const offRunCompleted = socket.on('run_completed', () => {
      setActiveRunCount((n) => Math.max(0, n - 1));
      if (selectedAppRef.current) {
        loadReports(selectedAppRef.current.id);
        loadScenarios(selectedAppRef.current.id);
      }
    });

    const offRunFailed = socket.on('run_failed', () => {
      setActiveRunCount((n) => Math.max(0, n - 1));
      if (selectedAppRef.current) loadReports(selectedAppRef.current.id);
    });

    const offRunCancelled = socket.on('run_cancelled', () => {
      setActiveRunCount((n) => Math.max(0, n - 1));
    });

    // After exploration finishes → jump to Scenarios tab and refresh
    const offExploreCompleted = socket.on('explore_completed', () => {
      setTab('scenarios');
      if (selectedAppRef.current) loadScenarios(selectedAppRef.current.id);
    });

    return () => {
      offRunStarted();
      offRunCompleted();
      offRunFailed();
      offRunCancelled();
      offExploreCompleted();
    };
  }, []);

  // When user opens the Explore tab, redirect to any already-running session
  useEffect(() => {
    if (tab === 'explore' && selectedApp) {
      exploreApi.getActiveSession(selectedApp.id).then((active) => {
        if (active) router.push(`/workspaces/${workspaceId}/explore/${active.id}`);
      }).catch(() => {});
    }
  }, [tab, selectedApp?.id]);

  useEffect(() => {
    if (selectedApp) {
      setSettingsDesc(selectedApp.description || '');
      setSettingsPassword('');
      setSettingsSaved(false);
      loadEnv(selectedApp.id);
      // Load saved credentials so user doesn't need to re-enter them after restart
      const apiBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';
      fetch(`${apiBase}/applications/${selectedApp.id}/settings`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('qaptain_token')}` },
      })
        .then((r) => r.json())
        .then((data) => {
          setSettingsUsername(data.username || '');
          setSettingsHasPassword(!!data.has_password);
        })
        .catch(() => {
          setSettingsUsername('');
          setSettingsHasPassword(false);
        });
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

  const handleAddApplication = async () => {
    if (!addAppName.trim() || !addAppUrl.trim() || !addAppDesc.trim() || !addAppUser.trim() || !addAppPass.trim()) return;
    setAddingApp(true);
    try {
      const newApp = await workspaceApi.createApplication(workspaceId, {
        workspace_id: workspaceId,
        name: addAppName.trim(),
        base_url: addAppUrl.trim(),
        description: addAppDesc.trim(),
        username: addAppUser.trim(),
        password: addAppPass,
      });
      setApps((prev) => [...prev, newApp]);
      setSelectedApp(newApp);
      setShowAddApp(false);
      setAddAppName(''); setAddAppUrl(''); setAddAppDesc(''); setAddAppUser(''); setAddAppPass('');
    } catch (e) { console.error(e); }
    finally { setAddingApp(false); }
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
      try {
        sessionStorage.setItem('qaptain_active_run', JSON.stringify({
          runId: run.id,
          workspaceId,
          title: scenarios.find((s) => s.id === scenarioId)?.title || 'Execution',
        }));
      } catch {}
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
        try {
          sessionStorage.setItem('qaptain_active_run', JSON.stringify({
            runId: validRuns[0].run_id,
            workspaceId,
            title: `${validRuns.length} scenario`,
          }));
        } catch {}
        router.push(`/workspaces/${workspaceId}/executions/${validRuns[0].run_id}`);
      } else {
        const batchId = (result as { batch_id?: string }).batch_id;
        if (batchId) {
          try {
            sessionStorage.setItem('qaptain_active_run', JSON.stringify({
              runId: null,
              batchId,
              workspaceId,
              title: `${validRuns.length} scenarios batch`,
            }));
          } catch {}
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
    } catch (e) {
      console.error('Failed to import document', e);
      setDocUploadResult({ imported: 0, module: 'Error' });
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
        selected_module_ids: Array.from(selectedModuleIds),
      });
      try {
        sessionStorage.setItem('qaptain_active_explore', JSON.stringify({
          sessionId: session.id,
          workspaceId,
          appName: selectedApp?.name || 'Application',
        }));
      } catch {}
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
      toast.error(e instanceof Error ? e.message : 'Failed to start explore');
    } finally {
      setStartingExplore(false);
    }
  };

  const handleStartDiscovery = async () => {
    if (!selectedApp) return;
    setDiscoveryStatus('running');
    try {
      const session = await exploreApi.discover({ application_id: selectedApp.id });
      try {
        sessionStorage.setItem('qaptain_active_explore', JSON.stringify({
          sessionId: session.id,
          workspaceId,
          appName: selectedApp?.name || 'Application',
        }));
      } catch {}
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
      toast.error(e instanceof Error ? e.message : 'Failed to start discovery');
      setDiscoveryStatus('idle');
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
      if (settingsPassword) setSettingsHasPassword(true);
      setTimeout(() => setSettingsSaved(false), 3000);
    } catch (e) {
      console.error('Failed to save settings', e);
      toast.error('Failed to save settings');
    } finally {
      setSavingSettings(false);
    }
  };

  const handleDeleteApp = async () => {
    if (!selectedApp) return;
    const confirmed = await confirm({
      title: `Delete "${selectedApp.name}"?`,
      message:
        'This will permanently remove the application, all its scenarios, exploration data, execution reports, and credentials. This action cannot be undone.',
      confirmLabel: 'Delete Application',
      destructive: true,
    });
    if (!confirmed) return;

    setDeletingApp(true);
    try {
      await workspaceApi.deleteApplication(workspaceId, selectedApp.id);
      setSelectedApp(null);
      await loadData();
      setTab('overview');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to delete application');
      setDeletingApp(false);
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
                disabled={!!loadingAppId}
                onClick={async () => {
                  if (loadingAppId) return;
                  setLoadingAppId(app.id);
                  setSelectedApp(app);
                  try {
                    await Promise.all([loadScenarios(app.id), loadReports(app.id), loadEnv(app.id)]);
                  } finally {
                    setLoadingAppId(null);
                  }
                }}
                className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                  selectedApp?.id === app.id
                    ? 'bg-blue-600/20 text-blue-300 border border-blue-600/30'
                    : 'text-zinc-400 hover:bg-zinc-800 hover:text-zinc-300'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium truncate">{app.name}</span>
                  {loadingAppId === app.id && (
                    <div className="w-3 h-3 border border-blue-400 border-t-transparent rounded-full animate-spin shrink-0" />
                  )}
                </div>
                <div className="text-xs text-zinc-600 truncate">{app.base_url}</div>
              </button>
            ))}
            <button
              onClick={() => setShowAddApp(true)}
              className="flex items-center gap-1 mt-2 px-3 py-2 text-xs text-zinc-600 hover:text-zinc-400 transition-colors w-full text-left"
            >
              + Add Application
            </button>
          </div>

          {/* Navigation */}
          <nav className="flex-1 p-3 space-y-1">
            {(
              [
                { id: 'overview', label: 'Overview', icon: '📊' },
                { id: 'explore', label: 'Explore', icon: '🔍' },
                { id: 'scenarios', label: 'Scenarios', icon: '📋', badge: scenarios.length || undefined },
                { id: 'dataset', label: 'Dataset', icon: '🗂️' },
                { id: 'knowledge', label: 'Knowledge Graph', icon: '🧠' },
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
          {/* Active run indicator — shown while any scenario is executing */}
          {activeRunCount > 0 && (
            <div className="flex items-center gap-3 bg-blue-500/10 border border-blue-500/25 rounded-xl px-4 py-2.5 mb-5 text-sm">
              <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse shrink-0" />
              <span className="text-blue-300 font-medium">
                {activeRunCount} execution{activeRunCount > 1 ? 's' : ''} in progress
              </span>
              <span className="text-blue-400/60 text-xs">Scenario badges will update when complete.</span>
            </div>
          )}
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
                  exploreLoading={startingExplore}
                />
              )}
              {tab === 'explore' && (
                <ExploreTab
                  app={selectedApp}
                  exploreMode={exploreMode}
                  setExploreMode={setExploreMode}
                  onStart={handleStartExplore}
                  loading={startingExplore}
                  discoveryStatus={discoveryStatus}
                  onStartDiscovery={handleStartDiscovery}
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
              {tab === 'dataset' && selectedApp && (
                <DatasetTab app={selectedApp} />
              )}
              {tab === 'knowledge' && selectedApp && (
                <KnowledgeGraphTab app={selectedApp} onExploreClick={() => setTab('explore')} />
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
                  hasPassword={settingsHasPassword}
                  onSave={handleSaveSettings}
                  saving={savingSettings}
                  saved={settingsSaved}
                  onDeleteApp={handleDeleteApp}
                  deletingApp={deletingApp}
                  onDeleteWorkspace={handleDeleteWorkspace}
                  deletingWorkspace={deletingWorkspace}
                />
              )}
            </>
          )}
        </main>
      </div>

      {/* ── Add Application Modal ── */}
      {showAddApp && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg bg-zinc-900 border border-zinc-700 rounded-2xl p-6 shadow-2xl">
            <h2 className="text-lg font-semibold text-white mb-1">Add Application</h2>
            <p className="text-sm text-zinc-500 mb-5">Add another application to this workspace.</p>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-zinc-400 mb-1">Application Name *</label>
                  <input type="text" value={addAppName} onChange={(e) => setAddAppName(e.target.value)}
                    placeholder="My App" className="w-full bg-zinc-800 border border-zinc-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
                <div>
                  <label className="block text-xs font-medium text-zinc-400 mb-1">Base URL *</label>
                  <input type="text" value={addAppUrl} onChange={(e) => setAddAppUrl(e.target.value)}
                    placeholder="http://localhost:4200" className="w-full bg-zinc-800 border border-zinc-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-zinc-400 mb-1">Description * <span className="text-zinc-600">(guides AI exploration)</span></label>
                <textarea value={addAppDesc} onChange={(e) => setAddAppDesc(e.target.value)}
                  rows={2} placeholder="Enterprise inventory management system with modules for Products, Price Lists, Orders..."
                  className="w-full bg-zinc-800 border border-zinc-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-zinc-400 mb-1">Username *</label>
                  <input type="text" value={addAppUser} onChange={(e) => setAddAppUser(e.target.value)}
                    placeholder="admin" className="w-full bg-zinc-800 border border-zinc-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
                <div>
                  <label className="block text-xs font-medium text-zinc-400 mb-1">Password *</label>
                  <input type="password" value={addAppPass} onChange={(e) => setAddAppPass(e.target.value)}
                    placeholder="••••••••" className="w-full bg-zinc-800 border border-zinc-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
              </div>
            </div>
            <div className="flex gap-3 mt-5">
              <button onClick={() => setShowAddApp(false)}
                className="flex-1 px-4 py-2 text-sm text-zinc-400 hover:text-white border border-zinc-700 rounded-lg transition-colors">
                Cancel
              </button>
              <button onClick={handleAddApplication}
                disabled={addingApp || !addAppName.trim() || !addAppUrl.trim() || !addAppDesc.trim() || !addAppUser.trim() || !addAppPass.trim()}
                className="flex-1 px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded-lg transition-colors disabled:opacity-50 flex items-center justify-center gap-2">
                {addingApp && <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />}
                {addingApp ? 'Adding…' : 'Add Application'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Overview Tab ─────────────────────────────────────────────────────────────

function OverviewTab({ app, scenarios, reports, onRunScenario, onExploreClick, onScenariosClick, exploreLoading }: {
  app: Application;
  scenarios: Scenario[];
  reports: ReportSummary[];
  onRunScenario: (id: string) => void;
  onExploreClick: () => void;
  onScenariosClick: () => void;
  exploreLoading?: boolean;
}) {
  const recentReports = reports.slice(0, 5);
  const passRate = recentReports.length > 0
    ? Math.round(recentReports.filter((r) => r.run_status === 'COMPLETED').length / recentReports.length * 100)
    : 0;

  const [coverage, setCoverage] = useState<KgCoverageReport | null>(null);
  const [drift, setDrift] = useState<import('@/lib/api').KgDriftReport | null>(null);
  useEffect(() => {
    if (app.has_knowledge) {
      knowledgeApi.getCoverage(app.id).then(setCoverage).catch(() => {});
      knowledgeApi.getDrift(app.id).then(setDrift).catch(() => {});
    }
  }, [app.id, app.has_knowledge]);

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

      {/* Selector drift alert — shown when KG selectors are consistently failing */}
      {drift?.drift_detected && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4 mb-6">
          <div className="flex items-start gap-3">
            <span className="text-amber-400 text-lg shrink-0">⚠️</span>
            <div className="flex-1 min-w-0">
              <p className="text-amber-300 font-medium text-sm">
                Selector drift detected in {drift.drifted_modules.length} module{drift.drifted_modules.length > 1 ? 's' : ''}
              </p>
              <p className="text-amber-400/70 text-xs mt-1">
                KG selectors are failing consistently — the application UI may have changed.
              </p>
              <div className="mt-2 space-y-1.5">
                {drift.drifted_modules.map((m) => (
                  <div key={m.module_id} className="flex items-center gap-2 text-xs">
                    <span className={`w-2 h-2 rounded-full shrink-0 ${m.severity === 'high' ? 'bg-red-400' : 'bg-amber-400'}`} />
                    <span className="text-amber-200 font-medium">{m.module_name}</span>
                    <span className="text-amber-400/60">{m.fail_rate_pct}% failure rate</span>
                    {m.top_failing_selectors[0] && (
                      <span className="text-zinc-500 truncate max-w-xs">
                        Top: "{m.top_failing_selectors[0].target}" ({m.top_failing_selectors[0].error_type})
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
            <button
              onClick={onExploreClick}
              disabled={exploreLoading}
              className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/30 text-xs rounded-lg transition-colors disabled:opacity-50"
            >
              {exploreLoading && <div className="w-3 h-3 border border-amber-300 border-t-transparent rounded-full animate-spin" />}
              Re-explore now
            </button>
          </div>
        </div>
      )}

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
            disabled={exploreLoading}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition-colors disabled:opacity-50"
          >
            {exploreLoading && <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />}
            {app.has_knowledge ? 'Re-explore' : 'Start Explore'}
          </button>
        </div>
      </div>

      {/* KG Coverage Panel */}
      {coverage && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 mb-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-white">KG Coverage</h3>
            <div className="flex items-center gap-3 text-xs text-zinc-500">
              <span>{coverage.summary.modules_kg_ready}/{coverage.summary.modules_total} modules KG-ready</span>
              <span className={`font-semibold ${
                coverage.summary.kg_coverage_pct >= 75 ? 'text-emerald-400' :
                coverage.summary.kg_coverage_pct >= 40 ? 'text-amber-400' : 'text-zinc-400'
              }`}>{coverage.summary.kg_coverage_pct}% KG-backed</span>
            </div>
          </div>
          {/* Progress bar */}
          <div className="w-full bg-zinc-800 rounded-full h-1.5 mb-4">
            <div
              className="bg-emerald-500 h-1.5 rounded-full transition-all"
              style={{ width: `${coverage.summary.kg_coverage_pct}%` }}
            />
          </div>
          <div className="space-y-1.5">
            {coverage.modules.map((m) => (
              <div key={m.module_id} className="flex items-center gap-3 text-sm">
                <span className={`w-2 h-2 rounded-full shrink-0 ${
                  m.status === 'kg_ready' ? 'bg-emerald-500' :
                  m.status === 'explored' ? 'bg-blue-400' : 'bg-zinc-600'
                }`} />
                <span className="text-zinc-300 flex-1 truncate">{m.module_name}</span>
                {m.kg_workflow_types.length > 0 && (
                  <div className="flex gap-1">
                    {[...new Set(m.kg_workflow_types)].map((t) => (
                      <span key={t} className="text-xs bg-emerald-500/10 text-emerald-400 px-1.5 py-0.5 rounded">
                        {t.replace('crud_', '')}
                      </span>
                    ))}
                  </div>
                )}
                <span className="text-zinc-600 text-xs shrink-0">
                  {m.scenarios_kg_backed}/{m.scenarios_total} scenarios
                </span>
              </div>
            ))}
          </div>
          <div className="mt-3 flex gap-4 text-xs text-zinc-600">
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" /> KG-ready (exact selectors)</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-400 inline-block" /> Explored (no KG yet)</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-zinc-600 inline-block" /> Not explored</span>
          </div>
        </div>
      )}

      {scenarios.length > 0 && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 mb-6">
          <h3 className="font-semibold text-white mb-3">Quick Execute</h3>
          <div className="space-y-2">
            {scenarios.slice(0, 5).map((s) => (
              <div key={s.id} className="flex items-center justify-between p-3 bg-zinc-800/50 rounded-lg">
                <div className="flex-1 min-w-0 mr-3">
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-zinc-300 truncate">{s.title}</span>
                    <KgReadyBadge kgPlanAvailable={s.kg_plan_available} workflowTypes={s.kg_workflow_types} />
                  </div>
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

function ExploreTab({
  app, exploreMode, setExploreMode, onStart, loading,
  discoveryStatus, onStartDiscovery
}: {
  app: Application;
  exploreMode: 'SMART' | 'SKIP';
  setExploreMode: (m: 'SMART' | 'SKIP') => void;
  onStart: () => void;
  loading: boolean;
  discoveryStatus: 'idle' | 'running' | 'completed';
  onStartDiscovery: () => void;
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

      {discoveryStatus === 'idle' && (
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
      )}

      {exploreMode === 'SMART' && (
        <>
          {discoveryStatus === 'idle' && (
            <button
              onClick={onStartDiscovery}
              className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-medium rounded-lg transition-colors flex items-center gap-2"
            >
              Discover Modules
            </button>
          )}

          {discoveryStatus === 'running' && (
            <div className="flex flex-col items-center justify-center p-10 bg-zinc-900 border border-zinc-800 rounded-xl">
              <div className="animate-spin w-8 h-8 border-4 border-blue-500/30 border-t-blue-500 rounded-full mb-4" />
              <p className="text-white font-medium">Discovering URLs and modules...</p>
              <p className="text-zinc-500 text-sm mt-1">Redirecting to the exploration session where you can select modules.</p>
            </div>
          )}
        </>
      )}

      {exploreMode === 'SKIP' && (
        <button
          onClick={onStart}
          disabled={loading}
          className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-medium rounded-lg transition-colors disabled:opacity-50 flex items-center gap-2"
        >
          {loading && <div className="animate-spin w-4 h-4 border-2 border-white/30 border-t-white rounded-full" />}
          Go to Scenarios →
        </button>
      )}
    </div>
  );
}

// ─── Scenarios Tab ────────────────────────────────────────────────────────────

function ScenarioViewModal({ scenario, onClose, onEdit, onRun }: {
  scenario: Scenario;
  onClose: () => void;
  onEdit: () => void;
  onRun?: () => void;
}) {
  const [showScript, setShowScript] = useState(false);
  const [scriptData, setScriptData] = useState<PlaywrightScript | null>(null);
  const [loadingScript, setLoadingScript] = useState(false);
  const [copied, setCopied] = useState(false);
  const toast = useAppToast();

  const handleLoadScript = async () => {
    if (scriptData) { setShowScript(true); return; }
    setLoadingScript(true);
    try {
      const data = await scenariosApi.getPlaywrightScript(scenario.id);
      setScriptData(data);
      setShowScript(true);
    } catch (e) {
      console.error('Failed to load Playwright script', e);
      toast.error(e instanceof Error ? e.message : 'Failed to load Playwright script');
    } finally {
      setLoadingScript(false);
    }
  };

  const handleCopy = () => {
    if (!scriptData) return;
    navigator.clipboard.writeText(scriptData.script);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm" onClick={onClose}>
      <div
        className={`bg-zinc-900 border border-zinc-700 rounded-2xl w-full flex flex-col shadow-2xl transition-all ${
          showScript ? 'max-w-4xl max-h-[92vh]' : 'max-w-2xl max-h-[85vh]'
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between px-6 py-4 border-b border-zinc-800">
          <div className="flex-1 min-w-0 pr-4">
            <div className="flex items-center gap-2 flex-wrap mb-1">
              <PriorityBadge priority={scenario.priority} />
              <SourceBadge source={scenario.source} />
              <KgReadyBadge kgPlanAvailable={scenario.kg_plan_available} workflowTypes={scenario.kg_workflow_types} />
              {scenario.module_name && (
                <span className="text-xs bg-zinc-700/60 text-zinc-400 px-2 py-0.5 rounded-full">{scenario.module_name}</span>
              )}
            </div>
            <h2 className="text-lg font-semibold text-white leading-snug">{scenario.title}</h2>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={handleLoadScript}
              disabled={loadingScript}
              title="View Playwright test script"
              className={`flex items-center gap-1.5 text-xs px-3 py-1.5 border rounded-lg transition-colors disabled:opacity-50 ${
                showScript
                  ? 'bg-violet-600/30 border-violet-500/40 text-violet-300'
                  : 'bg-zinc-800 hover:bg-zinc-700 border-zinc-700 text-zinc-300'
              }`}
            >
              {loadingScript ? <span className="animate-spin inline-block w-3 h-3 border border-zinc-300 border-t-transparent rounded-full" /> : '📜'}
              Script
            </button>
            {onRun && (
              <button
                onClick={() => { onClose(); onRun(); }}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-green-600/20 hover:bg-green-600/30 text-green-300 border border-green-600/30 rounded-lg transition-colors"
              >
                ▶ Run
              </button>
            )}
            <button onClick={onEdit} className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border border-blue-600/30 rounded-lg transition-colors">
              ✏️ Edit
            </button>
            <button onClick={onClose} className="text-zinc-500 hover:text-white transition-colors text-xl leading-none px-1">✕</button>
          </div>
        </div>

        {showScript && scriptData ? (
          <div className="flex flex-col flex-1 overflow-hidden">
            {/* Script header bar */}
            <div className="flex items-center justify-between px-6 py-3 bg-zinc-800/60 border-b border-zinc-800">
              <div className="flex items-center gap-3">
                <span className="text-xs font-mono text-zinc-400">playwright / typescript</span>
                <span className={`text-xs px-2 py-0.5 rounded-full ${
                  scriptData.source === 'kg_recorded'
                    ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                    : scriptData.source === 'skeleton'
                    ? 'bg-zinc-700 text-zinc-400'
                    : 'bg-blue-500/20 text-blue-300 border border-blue-500/30'
                }`}>
                  {scriptData.source === 'kg_recorded' ? '⚡ From KG — exact selectors' : scriptData.source === 'skeleton' ? 'Template skeleton' : 'From AI plan'}
                </span>
                <span className="text-xs text-zinc-600">{scriptData.step_count} steps</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleCopy}
                  className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-zinc-700 hover:bg-zinc-600 text-zinc-200 rounded-lg transition-colors"
                >
                  {copied ? '✓ Copied!' : '📋 Copy'}
                </button>
                <button
                  onClick={() => setShowScript(false)}
                  className="text-xs text-zinc-500 hover:text-zinc-300 px-2 py-1.5 transition-colors"
                >
                  Hide
                </button>
              </div>
            </div>
            {scriptData.source === 'skeleton' && (
              <div className="px-6 py-2.5 bg-amber-500/10 border-b border-amber-500/20 flex items-center gap-2">
                <span className="text-amber-400 text-sm">⚠️</span>
                <p className="text-xs text-amber-300">
                  No execution plan exists yet — this is a template skeleton with no real selectors.
                  Run the scenario first to generate a KG-backed plan, then come back for the full script.
                </p>
              </div>
            )}
            <pre className="overflow-y-auto flex-1 px-6 py-4 text-xs font-mono text-emerald-300 bg-zinc-950 leading-relaxed whitespace-pre-wrap">
              {scriptData.script}
            </pre>
          </div>
        ) : (
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
        )}
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
  const [subTab, setSubTab] = useState<'scenarios' | 'user_stories'>('scenarios');
  const [search, setSearch] = useState('');
  const [sourceFilter, setSourceFilter] = useState<string>('all');
  const [smokeFilter, setSmokeFilter] = useState(false);
  const [viewScenario, setViewScenario] = useState<Scenario | null>(null);
  const [editScenario, setEditScenario] = useState<Scenario | null>(null);
  const [deletingModuleId, setDeletingModuleId] = useState<string | null>(null);
  const confirm = useAppConfirm();

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [selectedGroupKey, setSelectedGroupKey] = useState<string | null>(null);

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleSelectGroup = (ids: string[]) => {
    setSelectedIds((prev) => {
      const allSelected = ids.every((id) => prev.has(id));
      const next = new Set(prev);
      if (allSelected) ids.forEach((id) => next.delete(id));
      else ids.forEach((id) => next.add(id));
      return next;
    });
  };

  const filtered = scenarios.filter((s) => {
    if (search.trim() && !(
      s.title.toLowerCase().includes(search.toLowerCase()) ||
      (s.module_name || '').toLowerCase().includes(search.toLowerCase()) ||
      (s.description || '').toLowerCase().includes(search.toLowerCase())
    )) return false;
    if (sourceFilter !== 'all' && s.source !== sourceFilter) return false;
    if (smokeFilter && !s.is_smoke) return false;
    return true;
  });

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

  const detailItems = selectedGroupKey !== null
    ? scenarios.filter((s) => (s.module_id || '__none__') === selectedGroupKey)
    : [];
  const detailMeta = selectedGroupKey !== null ? {
    moduleId: selectedGroupKey === '__none__' ? null : selectedGroupKey,
    moduleName: detailItems[0]?.module_name ?? null,
    moduleUrl: detailItems[0]?.module_url ?? null,
  } : null;

  const handleDeleteModule = async (moduleId: string | null) => {
    const key = moduleId || '__none__';
    const count = moduleMap.get(key)?.items.length ?? 0;
    const ok = await confirm({
      title: `Delete ${count} scenario${count !== 1 ? 's' : ''}?`,
      message: 'All scenarios in this group will be permanently removed. This cannot be undone.',
      confirmLabel: 'Delete All',
      destructive: true,
    });
    if (!ok) return;
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
          onRun={() => onRunScenario(viewScenario.id)}
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
      <div className="flex items-center justify-between mb-4">
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

      {/* Sub-tabs */}
      <div className="flex gap-1 bg-zinc-900 border border-zinc-800 rounded-lg p-1 w-fit mb-6">
        {([
          { id: 'scenarios' as const, label: 'Scenarios', count: scenarios.length },
          { id: 'user_stories' as const, label: 'User Stories', count: null },
        ]).map((t) => (
          <button key={t.id} onClick={() => setSubTab(t.id)}
            className={`flex items-center gap-1.5 px-4 py-1.5 text-sm rounded-md transition-colors ${
              subTab === t.id ? 'bg-zinc-700 text-white' : 'text-zinc-500 hover:text-zinc-300'
            }`}>
            {t.label}
            {t.count !== null && <span className="text-xs text-zinc-500">({t.count})</span>}
          </button>
        ))}
      </div>

      {subTab === 'user_stories' && (
        <UserStoriesPanel app={app} />
      )}

      {subTab === 'scenarios' && (<>
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

      {/* Filters row */}
      <div className="flex flex-wrap items-center gap-3 mb-5">
        {/* Source filter */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-zinc-500">Source:</span>
          <div className="flex gap-1 bg-zinc-900 border border-zinc-800 rounded-lg p-1">
            {([
              { value: 'all', label: 'All' },
              { value: 'kg_generated', label: 'KG' },
              { value: 'ai_generated', label: 'AI' },
              { value: 'manual', label: 'Manual' },
            ] as const).map((opt) => (
              <button
                key={opt.value}
                onClick={() => setSourceFilter(opt.value)}
                className={`px-3 py-1 text-xs rounded-md transition-colors ${
                  sourceFilter === opt.value ? 'bg-zinc-700 text-white' : 'text-zinc-500 hover:text-zinc-300'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
        {selectedIds.size > 0 && (
          <button
            onClick={() => {
              onRunModule(Array.from(selectedIds), '__selected__');
              setSelectedIds(new Set());
            }}
            disabled={!!runningModuleId}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-violet-600/20 hover:bg-violet-600/30 text-violet-300 border border-violet-600/30 rounded-lg transition-colors disabled:opacity-50 font-medium"
          >
            {runningModuleId === '__selected__'
              ? <div className="animate-spin w-3 h-3 border border-violet-300 border-t-transparent rounded-full" />
              : <span>▶</span>}
            Run Selected ({selectedIds.size})
          </button>
        )}
        {/* Smoke filter */}
        <button
          onClick={() => setSmokeFilter((v) => !v)}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border transition-colors ${
            smokeFilter
              ? 'bg-yellow-500/20 border-yellow-500/40 text-yellow-300'
              : 'bg-zinc-900 border-zinc-800 text-zinc-500 hover:text-zinc-300'
          }`}
        >
          🔥 Smoke Only
        </button>
        {/* Execution mode */}
        <div className="flex items-center gap-2 ml-auto">
          <span className="text-xs text-zinc-500">Run mode:</span>
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
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition-colors disabled:opacity-50"
          >
            {creating && <div className="w-3 h-3 border border-white/40 border-t-white rounded-full animate-spin" />}
            Add
          </button>
        </div>
      </div>

      {/* Two-level view: module card grid → scenario detail */}
      {selectedGroupKey === null ? (
        /* ── Module card grid ── */
        filtered.length === 0 ? (
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
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {groups.map((group, gi) => {
              const passed = group.items.filter((s) => s.last_run_status === 'passed').length;
              const failed = group.items.filter((s) => s.last_run_status === 'failed' || s.last_run_status === 'error').length;
              const notRun = group.items.filter((s) => !s.last_run_status).length;
              const groupKey = group.moduleId || '__none__';
              return (
                <div
                  key={gi}
                  onClick={() => setSelectedGroupKey(groupKey)}
                  className="bg-zinc-900 border border-zinc-800 hover:border-zinc-600 rounded-xl p-5 cursor-pointer transition-all group/card hover:bg-zinc-800/40 flex flex-col gap-4"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2.5 min-w-0">
                      <span className="text-xl shrink-0">🧩</span>
                      <div className="min-w-0">
                        <div className="text-sm font-semibold text-zinc-100 truncate">
                          {group.moduleName || 'General / Unassigned'}
                        </div>
                        {group.moduleUrl && (
                          <div className="text-xs text-zinc-500 truncate">{group.moduleUrl}</div>
                        )}
                      </div>
                    </div>
                    <span className="text-xs bg-blue-600/20 text-blue-300 px-2 py-0.5 rounded-full shrink-0">
                      {group.items.length}
                    </span>
                  </div>

                  <div className="flex items-center gap-3 text-xs">
                    {passed > 0 && (
                      <span className="flex items-center gap-1 text-emerald-400">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block" />
                        {passed} passed
                      </span>
                    )}
                    {failed > 0 && (
                      <span className="flex items-center gap-1 text-red-400">
                        <span className="w-1.5 h-1.5 rounded-full bg-red-400 inline-block" />
                        {failed} failed
                      </span>
                    )}
                    {notRun > 0 && (
                      <span className="flex items-center gap-1 text-zinc-500">
                        <span className="w-1.5 h-1.5 rounded-full bg-zinc-600 inline-block" />
                        {notRun} not run
                      </span>
                    )}
                  </div>

                  <div className="flex items-center justify-between mt-auto">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onRunModule(group.items.map((s) => s.id), group.moduleId || '__ungrouped__');
                      }}
                      disabled={!!runningModuleId}
                      className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border border-blue-600/30 rounded-lg transition-colors disabled:opacity-50"
                    >
                      {runningModuleId === (group.moduleId || '__ungrouped__') ? (
                        <div className="animate-spin w-3 h-3 border border-blue-300 border-t-transparent rounded-full" />
                      ) : '▶'}
                      {runningModuleId === (group.moduleId || '__ungrouped__') ? ' Starting…' : ' Run All'}
                    </button>
                    <span className="text-xs text-zinc-600 group-hover/card:text-zinc-400 transition-colors">
                      View scenarios →
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )
      ) : (
        /* ── Module detail: scenario list ── */
        <div>
          {/* Back + actions bar */}
          <div className="flex items-center justify-between mb-5">
            <button
              onClick={() => { setSelectedGroupKey(null); setSelectedIds(new Set()); }}
              className="flex items-center gap-1.5 text-sm text-zinc-400 hover:text-zinc-100 transition-colors"
            >
              ← Modules
            </button>
            <div className="flex items-center gap-2">
              {selectedIds.size > 0 && (
                <button
                  onClick={() => { onRunModule(Array.from(selectedIds), '__selected__'); setSelectedIds(new Set()); }}
                  disabled={!!runningModuleId}
                  className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-violet-600/20 hover:bg-violet-600/30 text-violet-300 border border-violet-600/30 rounded-lg transition-colors disabled:opacity-50 font-medium"
                >
                  {runningModuleId === '__selected__'
                    ? <div className="animate-spin w-3 h-3 border border-violet-300 border-t-transparent rounded-full" />
                    : <span>▶</span>}
                  Run Selected ({selectedIds.size})
                </button>
              )}
              <button
                onClick={() => onRunModule(detailItems.map((s) => s.id), detailMeta?.moduleId || '__ungrouped__')}
                disabled={!!runningModuleId}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border border-blue-600/30 rounded-lg transition-colors disabled:opacity-50"
              >
                {runningModuleId === (detailMeta?.moduleId || '__ungrouped__') ? (
                  <div className="animate-spin w-3 h-3 border border-blue-300 border-t-transparent rounded-full" />
                ) : '▶'}
                {runningModuleId === (detailMeta?.moduleId || '__ungrouped__') ? ' Starting…' : ' Run All'}
              </button>
              <button
                onClick={() => handleDeleteModule(detailMeta?.moduleId ?? null)}
                disabled={deletingModuleId === (selectedGroupKey)}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-red-600/10 hover:bg-red-600/20 text-red-400 border border-red-600/20 rounded-lg transition-colors disabled:opacity-50"
              >
                {deletingModuleId === selectedGroupKey ? (
                  <div className="animate-spin w-3 h-3 border border-red-400 border-t-transparent rounded-full" />
                ) : '🗑'}
                Delete All
              </button>
            </div>
          </div>

          {/* Module info strip */}
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl px-5 py-3 mb-4 flex items-center gap-3">
            <span className="text-xl shrink-0">🧩</span>
            <div className="min-w-0 flex-1">
              <div className="text-base font-semibold text-zinc-100">
                {detailMeta?.moduleName || 'General / Unassigned'}
              </div>
              {detailMeta?.moduleUrl && (
                <div className="text-xs text-zinc-500 truncate">{detailMeta.moduleUrl}</div>
              )}
            </div>
            <span className="text-xs bg-blue-600/20 text-blue-300 px-2 py-0.5 rounded-full shrink-0">
              {detailItems.length} scenario{detailItems.length !== 1 ? 's' : ''}
            </span>
          </div>

          {/* Scenario list */}
          {detailItems.length === 0 ? (
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-10 text-center text-zinc-500 text-sm">
              No scenarios in this module yet.
            </div>
          ) : (
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
              <div className="flex items-center gap-2 px-5 py-2.5 bg-zinc-800/60 border-b border-zinc-800">
                <input
                  type="checkbox"
                  checked={detailItems.length > 0 && detailItems.every((s) => selectedIds.has(s.id))}
                  onChange={() => toggleSelectGroup(detailItems.map((s) => s.id))}
                  className="w-3.5 h-3.5 rounded border-zinc-600 accent-violet-500 cursor-pointer"
                />
                <span className="text-xs text-zinc-500">Select all</span>
              </div>
              <div className="divide-y divide-zinc-800">
                {detailItems.map((s) => (
                  <div key={s.id} className="flex items-center gap-3 px-5 py-3 hover:bg-zinc-800/30 transition-colors group">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(s.id)}
                      onChange={() => toggleSelect(s.id)}
                      className="w-3.5 h-3.5 rounded border-zinc-600 accent-violet-500 cursor-pointer shrink-0"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm text-zinc-200 truncate">{s.title}</span>
                        {s.is_smoke && (
                          <span className="text-xs bg-yellow-500/20 text-yellow-300 border border-yellow-500/30 px-1.5 py-0.5 rounded-full">🔥 Smoke</span>
                        )}
                        <SourceBadge source={s.source} />
                        <KgReadyBadge kgPlanAvailable={s.kg_plan_available} workflowTypes={s.kg_workflow_types} />
                        <LastRunBadge status={s.last_run_status} />
                      </div>
                      {s.description && (
                        <div className="text-xs text-zinc-600 truncate mt-0.5">{s.description}</div>
                      )}
                    </div>
                    <PriorityBadge priority={s.priority} />
                    <button
                      onClick={() => setViewScenario(s)}
                      className="text-zinc-600 hover:text-blue-400 transition-colors opacity-0 group-hover:opacity-100 text-sm px-1 shrink-0"
                      title="View full scenario"
                    >
                      👁
                    </button>
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
          )}
        </div>
      )}
      </>)}
    </div>
  );
}

// ─── User Stories Panel ───────────────────────────────────────────────────────

function UserStoriesPanel({ app }: { app: Application }) {
  const [description, setDescription] = useState('');
  const [outputType, setOutputType] = useState<'user_stories' | 'scenarios'>('user_stories');
  const [generating, setGenerating] = useState(false);
  const [results, setResults] = useState<import('@/lib/api').AICopilotItem[]>([]);
  const [savedIds, setSavedIds] = useState<Set<number>>(new Set());
  const [savingIdx, setSavingIdx] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [contextMeta, setContextMeta] = useState<{ used: boolean; module: string | null } | null>(null);

  const handleGenerate = async () => {
    if (!description.trim()) return;
    setGenerating(true);
    setResults([]);
    setError(null);
    setContextMeta(null);
    try {
      const res = await scenariosApi.aiCopilot({
        description: description.trim(),
        application_id: app.id,
        output_type: outputType,
      });
      setResults(res.items || []);
      setContextMeta({ used: res.context_used ?? false, module: res.matched_module ?? null });
      if (!res.items?.length) {
        setError('AI returned no items. Try a more specific description.');
      }
    } catch (e: unknown) {
      console.error('AI Copilot failed', e);
      const msg = e instanceof Error ? e.message : String(e);
      if (msg.includes('Failed to fetch') || msg.includes('NetworkError') || msg.includes('fetch')) {
        setError('Cannot reach the backend. Make sure the server is running on port 8000.');
      } else {
        setError(msg || 'Generation failed. Please try again.');
      }
    } finally {
      setGenerating(false);
    }
  };

  const handleSave = async (item: import('@/lib/api').AICopilotItem, idx: number) => {
    setSavingIdx(idx);
    setSaveError(null);
    try {
      await scenariosApi.create({
        application_id: app.id,
        title: item.title,
        description: [
          item.description,
          item.acceptance_criteria?.length
            ? 'Acceptance Criteria:\n' + item.acceptance_criteria.map((c, i) => `${i + 1}. ${c}`).join('\n')
            : null,
          item.test_hints?.length
            ? 'Test Hints:\n' + item.test_hints.map((h) => `- ${h}`).join('\n')
            : null,
        ].filter(Boolean).join('\n\n'),
        priority: (item.priority?.toUpperCase() as Scenario['priority']) || 'MEDIUM',
      });
      setSavedIds((prev) => new Set([...prev, idx]));
    } catch (e: unknown) {
      console.error('Failed to save item', e);
      setSaveError(e instanceof Error ? e.message : 'Failed to save. Please try again.');
    } finally {
      setSavingIdx(null);
    }
  };

  return (
    <div>
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 mb-6">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-lg">✨</span>
          <h3 className="text-sm font-semibold text-white">AI Copilot</h3>
        </div>
        <p className="text-xs text-zinc-500 mb-4">
          Describe a feature or workflow in plain language. AI will generate structured{' '}
          {outputType === 'user_stories' ? 'user stories' : 'test scenarios'} using the application knowledge.
        </p>

        <div className="flex gap-1 bg-zinc-800 rounded-lg p-1 w-fit mb-4">
          {(['user_stories', 'scenarios'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setOutputType(t)}
              className={`px-3 py-1.5 text-xs rounded-md transition-colors ${
                outputType === t ? 'bg-zinc-700 text-white' : 'text-zinc-400 hover:text-zinc-200'
              }`}
            >
              {t === 'user_stories' ? 'User Stories' : 'Test Scenarios'}
            </button>
          ))}
        </div>

        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={4}
          placeholder={
            outputType === 'user_stories'
              ? 'e.g. "User should be able to create a price list, add items to it, and assign it to a customer group"'
              : 'e.g. "Test the Add Price List feature — creation, editing, and deletion with various edge cases"'
          }
          className="w-full bg-zinc-800 border border-zinc-700 text-white rounded-xl px-4 py-3 text-sm placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-violet-500 resize-none mb-3"
        />
        <button
          onClick={handleGenerate}
          disabled={generating || !description.trim()}
          className="flex items-center gap-2 px-5 py-2.5 bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
        >
          {generating && (
            <div className="animate-spin w-4 h-4 border-2 border-white/30 border-t-white rounded-full" />
          )}
          {generating ? 'Generating…' : `Generate ${outputType === 'user_stories' ? 'User Stories' : 'Scenarios'}`}
        </button>

        {error && (
          <div className="mt-3 flex items-start gap-2 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2.5">
            <span className="text-red-400 text-sm mt-0.5">⚠</span>
            <p className="text-red-400 text-xs leading-relaxed">{error}</p>
          </div>
        )}
        {saveError && (
          <div className="mt-3 flex items-start gap-2 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2.5">
            <span className="text-red-400 text-sm mt-0.5">⚠</span>
            <p className="text-red-400 text-xs leading-relaxed">{saveError}</p>
          </div>
        )}
      </div>

      {results.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between mb-1">
            <h3 className="text-sm font-medium text-zinc-300">{results.length} items generated</h3>
            <span className="text-xs text-zinc-600">Click Save to add to your scenarios list</span>
          </div>
          {contextMeta && (
            <div className={`flex items-center gap-2 px-3 py-2 rounded-lg text-xs mb-2 ${
              contextMeta.used
                ? 'bg-violet-500/10 border border-violet-500/20 text-violet-400'
                : 'bg-zinc-800 border border-zinc-700 text-zinc-500'
            }`}>
              {contextMeta.used ? (
                <>
                  <span>⚡</span>
                  <span>
                    Generated using exploration data
                    {contextMeta.module ? <> — matched module: <strong>{contextMeta.module}</strong></> : null}
                  </span>
                </>
              ) : (
                <>
                  <span>ℹ</span>
                  <span>No exploration data found — generic scenarios generated. Run Explore first for precise results.</span>
                </>
              )}
            </div>
          )}
          {results.map((item, idx) => (
            <div
              key={idx}
              className={`bg-zinc-900 border rounded-xl p-4 transition-colors ${
                savedIds.has(idx) ? 'border-green-500/30 bg-green-500/5' : 'border-zinc-800'
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                    {item.priority && (
                      <span className={`text-xs px-1.5 py-0.5 rounded-full ${
                        item.priority.toUpperCase() === 'HIGH' ? 'bg-orange-500/20 text-orange-400' :
                        item.priority.toUpperCase() === 'CRITICAL' ? 'bg-red-500/20 text-red-400' :
                        item.priority.toUpperCase() === 'LOW' ? 'bg-zinc-800 text-zinc-500' :
                        'bg-zinc-700 text-zinc-400'
                      }`}>
                        {item.priority}
                      </span>
                    )}
                    {item.category && (
                      <span className="text-xs bg-blue-500/15 text-blue-400 px-1.5 py-0.5 rounded-full">
                        {item.category.replace(/_/g, ' ')}
                      </span>
                    )}
                  </div>
                  <p className="text-sm font-medium text-white mb-1">{item.title}</p>
                  {item.description && (
                    <p className="text-xs text-zinc-400 mb-2 leading-relaxed">{item.description}</p>
                  )}
                  {item.acceptance_criteria && item.acceptance_criteria.length > 0 && (
                    <div className="mb-2">
                      <p className="text-xs font-medium text-zinc-500 mb-1">Acceptance Criteria:</p>
                      <ul className="space-y-0.5">
                        {item.acceptance_criteria.map((c, ci) => (
                          <li key={ci} className="text-xs text-zinc-400 flex gap-1.5">
                            <span className="text-zinc-600 shrink-0">{ci + 1}.</span>
                            {c}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {item.test_hints && item.test_hints.length > 0 && (
                    <div>
                      <p className="text-xs font-medium text-zinc-500 mb-1">Test Hints:</p>
                      <div className="flex flex-wrap gap-1">
                        {item.test_hints.map((h, hi) => (
                          <span key={hi} className="text-xs bg-zinc-800 text-zinc-400 px-2 py-0.5 rounded-full">
                            {h}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
                <button
                  onClick={() => handleSave(item, idx)}
                  disabled={savedIds.has(idx) || savingIdx === idx}
                  className={`shrink-0 text-xs px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1.5 ${
                    savedIds.has(idx)
                      ? 'bg-green-500/20 text-green-400 border border-green-500/30'
                      : 'bg-zinc-800 hover:bg-zinc-700 text-zinc-300 border border-zinc-700'
                  }`}
                >
                  {savingIdx === idx && (
                    <div className="animate-spin w-3 h-3 border border-zinc-300 border-t-transparent rounded-full" />
                  )}
                  {savedIds.has(idx) ? '✓ Saved' : savingIdx === idx ? 'Saving…' : 'Save'}
                </button>
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

  const exportReportsCSV = () => {
    if (!reports.length) return;
    const headers = ['Scenario', 'Run Status', 'Quality Score', 'Risk Level', 'Pass Rate (%)', 'Steps Passed', 'Steps Total', 'Date'];
    const rows = reports.map((r) => {
      const s = r.summary;
      const pr = s.pass_rate ?? (s.total ? Math.round(((s.passed ?? 0) / s.total) * 100) : '');
      return [
        `"${(r.scenario_title ?? '').replace(/"/g, '""')}"`,
        r.run_status ?? '',
        r.quality_score?.toFixed(0) ?? '',
        r.risk_level ?? '',
        pr,
        s.passed ?? '',
        s.total ?? '',
        `"${new Date(r.created_at).toLocaleString()}"`,
      ].join(',');
    });
    const csv = [headers.join(','), ...rows].join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `qaptain-reports-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div>
      {/* Header + toggle */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">Execution Reports</h1>
        <div className="flex items-center gap-3">
          {view === 'reports' && reports.length > 0 && (
            <button
              onClick={exportReportsCSV}
              className="text-xs px-3 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 border border-zinc-700 transition-colors"
              title="Export visible reports as CSV"
            >
              ↓ Export CSV
            </button>
          )}
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

function SettingsTab({ app, desc, setDesc, username, setUsername, password, setPassword, hasPassword, onSave, saving, saved, onDeleteApp, deletingApp, onDeleteWorkspace, deletingWorkspace }: {
  app: Application;
  desc: string;
  setDesc: (v: string) => void;
  username: string;
  setUsername: (v: string) => void;
  password: string;
  setPassword: (v: string) => void;
  hasPassword: boolean;
  onSave: () => void;
  saving: boolean;
  saved: boolean;
  onDeleteApp: () => void;
  deletingApp: boolean;
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
        <h3 className="text-sm font-medium text-zinc-300">Admin Credentials</h3>
        <p className="text-xs text-zinc-500">The primary account used for exploration and test execution. Password is stored encrypted and persists across restarts.</p>
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
          <label className="block text-xs text-zinc-500 mb-1">
            Password
            {hasPassword && !password && (
              <span className="ml-2 text-green-400 font-normal">✓ Password saved</span>
            )}
          </label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-blue-500"
            placeholder={hasPassword ? 'Enter new password to change' : 'Enter password'}
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

      {/* Test Roles */}
      <TestRolesPanel app={app} />

      {/* Danger Zone */}
      <div className="border border-red-500/30 rounded-xl overflow-hidden">
        <div className="px-5 py-3 bg-red-500/5 border-b border-red-500/20">
          <h3 className="text-sm font-semibold text-red-400">Danger Zone</h3>
        </div>
        <div className="divide-y divide-red-500/10">
          <div className="p-5 flex items-center justify-between gap-4">
            <div>
              <p className="text-sm font-medium text-white">Delete this application</p>
              <p className="text-xs text-zinc-500 mt-0.5">
                Permanently removes all scenarios, exploration data, execution reports, and credentials. Cannot be undone.
              </p>
            </div>
            <button
              onClick={onDeleteApp}
              disabled={deletingApp}
              className="shrink-0 px-4 py-2 bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
            >
              {deletingApp ? 'Deleting…' : 'Delete Application'}
            </button>
          </div>
          <div className="p-5 flex items-center justify-between gap-4">
            <div>
              <p className="text-sm font-medium text-white">Delete this workspace</p>
              <p className="text-xs text-zinc-500 mt-0.5">
                Permanently removes the workspace, all applications, scenarios, and settings. Cannot be undone.
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
    </div>
  );
}

// ─── Test Roles Panel ─────────────────────────────────────────────────────────

function TestRolesPanel({ app }: { app: Application }) {
  const [roles, setRoles] = useState<import('@/lib/api').RoleCredential[]>([]);
  const [loading, setLoading] = useState(true);

  // Manual add form
  const [addRole, setAddRole] = useState('');
  const [addUser, setAddUser] = useState('');
  const [addPass, setAddPass] = useState('');
  const [adding, setAdding] = useState(false);

  // Bulk import
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<string | null>(null);

  // RBAC scan
  const [scan, setScan] = useState<import('@/lib/api').RbacScanResult | null>(null);
  const [scanning, setScanning] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = async () => {
    try {
      const data = await appApi.listRoleCredentials(app.id);
      setRoles(data);
    } catch { setRoles([]); }
    finally { setLoading(false); }
  };

  const loadScan = async () => {
    try {
      const s = await appApi.getLatestRbacScan(app.id);
      if (s) {
        setScan(s);
        if (s.status === 'running' || s.status === 'pending') {
          setScanning(true);
        } else {
          setScanning(false);
          if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
        }
      }
    } catch { /* ignore */ }
  };

  useEffect(() => { load(); loadScan(); }, [app.id]);

  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  const [scanError, setScanError] = useState<string | null>(null);

  const startScan = async () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    setScanError(null);
    setScanning(true);
    try {
      await appApi.startRbacScan(app.id);
      await loadScan();
      pollRef.current = setInterval(loadScan, 4000);
    } catch (e) {
      setScanning(false);
      const msg = e instanceof Error ? e.message : 'Failed to start scan';
      setScanError(msg);
    }
  };

  const handleAdd = async () => {
    if (!addRole.trim() || !addUser.trim() || !addPass.trim()) return;
    setAdding(true);
    try {
      const created = await appApi.addRoleCredential(app.id, {
        role_name: addRole.trim(),
        username: addUser.trim(),
        password: addPass,
      });
      setRoles((prev) => [...prev, created]);
      setAddRole(''); setAddUser(''); setAddPass('');
    } catch (e) { console.error(e); }
    finally { setAdding(false); }
  };

  const handleDelete = async (id: string) => {
    try {
      await appApi.deleteRoleCredential(app.id, id);
      setRoles((prev) => prev.filter((r) => r.id !== id));
    } catch (e) { console.error(e); }
  };

  const handleFileUpload = async (file: File) => {
    setImporting(true);
    setImportResult(null);
    try {
      const result = await appApi.bulkImportRoleCredentials(app.id, file);
      setImportResult(result.message);
      await load();
    } catch (e) {
      setImportResult(e instanceof Error ? e.message : 'Import failed');
    } finally {
      setImporting(false);
    }
  };

  const scanReady = scan?.status === 'completed' && scan.results?.roles && scan.results.roles.length > 0;
  const progress = scan?.results?.progress;

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-800">
        <div>
          <h3 className="text-sm font-semibold text-white">Test Role Credentials</h3>
          <p className="text-xs text-zinc-500 mt-0.5">
            One test account per role — used for RBAC permission verification.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Scan permissions button */}
          <button
            onClick={startScan}
            disabled={scanning || roles.length === 0}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border transition-colors ${
              scanning || roles.length === 0
                ? 'border-zinc-700 text-zinc-600 cursor-not-allowed'
                : 'border-violet-500/50 text-violet-300 hover:bg-violet-500/10 hover:border-violet-500'
            }`}
            title={roles.length === 0 ? 'Add role credentials first' : 'Login as each role and check accessible modules'}
          >
            {scanning
              ? <><div className="w-3 h-3 border border-violet-400 border-t-transparent rounded-full animate-spin" /> Scanning…</>
              : <>🔍 Scan Permissions</>
            }
          </button>

          {/* Bulk import button */}
          <label className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border cursor-pointer transition-colors ${
            importing
              ? 'border-zinc-700 text-zinc-600 cursor-not-allowed'
              : 'border-zinc-700 text-zinc-300 hover:bg-zinc-800'
          }`}>
            {importing
              ? <><div className="w-3 h-3 border border-zinc-500 border-t-transparent rounded-full animate-spin" /> Importing…</>
              : <>📥 Import File</>
            }
            <input
              type="file"
              className="hidden"
              disabled={importing}
              accept=".csv,.tsv,.txt,.json,.xlsx,.xls,.ods"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleFileUpload(f);
                e.target.value = '';
              }}
            />
          </label>
        </div>
      </div>

      {/* Scan progress / status banner */}
      {scanning && (
        <div className="px-5 py-3 bg-violet-500/10 border-b border-violet-500/20 flex items-center gap-3">
          <div className="w-3.5 h-3.5 border-2 border-violet-400/40 border-t-violet-400 rounded-full animate-spin shrink-0" />
          <div className="flex-1">
            {progress ? (
              <>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-violet-300 font-medium">
                    {progress.current_role ? `Scanning: ${progress.current_role}` : 'Preparing scan…'}
                  </span>
                  <span className="text-xs text-violet-400">{progress.completed}/{progress.total} roles</span>
                </div>
                <div className="h-1 bg-violet-900/40 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-violet-500 rounded-full transition-all duration-500"
                    style={{ width: `${progress.total > 0 ? (progress.completed / progress.total) * 100 : 0}%` }}
                  />
                </div>
              </>
            ) : (
              <div className="flex items-center justify-between">
                <span className="text-xs text-violet-300 font-medium">
                  {scan?.status === 'running'
                    ? 'Launching browser — logging in as first role…'
                    : 'Queued — scan starting, please wait…'}
                </span>
                <span className="text-[10px] text-violet-500 font-mono uppercase tracking-wide">
                  {scan?.status ?? 'pending'}
                </span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Scan start error */}
      {scanError && (
        <div className="px-5 py-2.5 bg-red-500/10 border-b border-red-500/20 flex items-center justify-between">
          <span className="text-xs text-red-300">Could not start scan: {scanError}</span>
          <button onClick={() => setScanError(null)} className="text-zinc-500 hover:text-white text-xs">✕</button>
        </div>
      )}

      {/* Scan backend error */}
      {!scanning && scan?.status === 'failed' && (
        <div className="px-5 py-2.5 bg-red-500/10 border-b border-red-500/20 flex items-center justify-between">
          <span className="text-xs text-red-300">Scan failed: {scan.error_message || 'Unknown error'}</span>
          <button onClick={() => setScan(null)} className="text-zinc-500 hover:text-white text-xs">✕</button>
        </div>
      )}

      {/* Import result banner */}
      {importResult && (
        <div className="px-5 py-2.5 bg-blue-500/10 border-b border-blue-500/20 flex items-center justify-between">
          <span className="text-xs text-blue-300">{importResult}</span>
          <button onClick={() => setImportResult(null)} className="text-zinc-500 hover:text-white text-xs">✕</button>
        </div>
      )}

      {/* File format hint */}
      <div className="px-5 py-3 bg-zinc-800/40 border-b border-zinc-800">
        <p className="text-xs text-zinc-500">
          <span className="text-zinc-400 font-medium">Accepted formats:</span>{' '}
          CSV, TSV, TXT, JSON, Excel (.xlsx/.xls) — any delimiter auto-detected.{' '}
          <span className="text-zinc-500">Columns:</span>{' '}
          <code className="text-zinc-400 bg-zinc-800 px-1 rounded">role_name</code>,{' '}
          <code className="text-zinc-400 bg-zinc-800 px-1 rounded">username</code>,{' '}
          <code className="text-zinc-400 bg-zinc-800 px-1 rounded">password</code>{' '}
          (header row optional — positional order also works).
        </p>
      </div>

      {/* Credentials table */}
      {loading ? (
        <div className="p-6 text-center text-zinc-600 text-sm animate-pulse">Loading…</div>
      ) : roles.length === 0 ? (
        <div className="p-8 text-center text-zinc-600 text-sm">
          No role credentials yet. Add one manually or import a file.
        </div>
      ) : (
        <div className="divide-y divide-zinc-800/60">
          {/* Column headers */}
          <div className="grid grid-cols-[1fr_1fr_auto] gap-4 px-5 py-2 text-xs font-medium text-zinc-500 uppercase tracking-wide">
            <span>Role Name</span>
            <span>Username</span>
            <span></span>
          </div>
          {roles.map((r) => (
            <div key={r.id} className="grid grid-cols-[1fr_1fr_auto] gap-4 items-center px-5 py-3 hover:bg-zinc-800/30 transition-colors group">
              <span className="text-sm text-zinc-200 truncate font-medium">{r.role_name}</span>
              <span className="text-sm text-zinc-400 truncate">{r.username}</span>
              <button
                onClick={() => handleDelete(r.id)}
                className="opacity-0 group-hover:opacity-100 text-zinc-600 hover:text-red-400 transition-colors text-xs px-1"
                title="Remove this role credential"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Add manually */}
      <div className="border-t border-zinc-800 p-5">
        <p className="text-xs font-medium text-zinc-500 mb-3 uppercase tracking-wide">Add Manually</p>
        <div className="grid grid-cols-3 gap-2 mb-2">
          <input
            type="text"
            value={addRole}
            onChange={(e) => setAddRole(e.target.value)}
            placeholder="Role name (e.g. Lab Manager)"
            className="bg-zinc-800 border border-zinc-700 text-white rounded-lg px-3 py-2 text-sm placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <input
            type="text"
            value={addUser}
            onChange={(e) => setAddUser(e.target.value)}
            placeholder="Username / email"
            className="bg-zinc-800 border border-zinc-700 text-white rounded-lg px-3 py-2 text-sm placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <input
            type="password"
            value={addPass}
            onChange={(e) => setAddPass(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
            placeholder="Password"
            className="bg-zinc-800 border border-zinc-700 text-white rounded-lg px-3 py-2 text-sm placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <button
          onClick={handleAdd}
          disabled={adding || !addRole.trim() || !addUser.trim() || !addPass.trim()}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition-colors disabled:opacity-50 flex items-center gap-2"
        >
          {adding && <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />}
          {adding ? 'Adding…' : '+ Add Role'}
        </button>
      </div>

      {/* Permission matrix */}
      {scanReady && scan.results.roles && scan.results.modules && (
        <RbacPermissionMatrix
          modules={scan.results.modules}
          roles={scan.results.roles}
          scannedAt={scan.results.scanned_at}
        />
      )}
    </div>
  );
}

// ─── RBAC Permission Matrix ────────────────────────────────────────────────────

function RbacPermissionMatrix({
  modules,
  roles,
  scannedAt,
}: {
  modules: string[];
  roles: import('@/lib/api').RbacRoleResult[];
  scannedAt?: string;
}) {
  const [view, setView] = useState<'matrix' | 'nav'>('matrix');

  return (
    <div className="border-t border-violet-500/20 bg-violet-500/5">
      {/* Matrix header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-violet-500/10">
        <div>
          <span className="text-xs font-semibold text-violet-300 uppercase tracking-wide">Permission Matrix</span>
          {scannedAt && (
            <span className="ml-2 text-xs text-zinc-500">
              Scanned {new Date(scannedAt).toLocaleString()}
            </span>
          )}
        </div>
        <div className="flex gap-1">
          <button
            onClick={() => setView('matrix')}
            className={`px-2.5 py-1 text-xs rounded transition-colors ${view === 'matrix' ? 'bg-violet-600 text-white' : 'text-zinc-400 hover:text-white'}`}
          >
            Module Access
          </button>
          <button
            onClick={() => setView('nav')}
            className={`px-2.5 py-1 text-xs rounded transition-colors ${view === 'nav' ? 'bg-violet-600 text-white' : 'text-zinc-400 hover:text-white'}`}
          >
            Nav Items
          </button>
        </div>
      </div>

      {view === 'matrix' ? (
        <div className="overflow-x-auto">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr>
                <th className="text-left px-4 py-2.5 text-zinc-500 font-medium bg-zinc-900/60 sticky left-0 z-10 min-w-[160px]">
                  Module
                </th>
                {roles.map((r) => (
                  <th key={r.role_name} className="px-3 py-2.5 text-center text-zinc-300 font-medium bg-zinc-900/60 min-w-[90px] whitespace-nowrap">
                    <div className="truncate max-w-[90px]" title={r.role_name}>{r.role_name}</div>
                    {!r.login_success && (
                      <div className="text-red-400 font-normal text-[10px]">login failed</div>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/40">
              {modules.map((mod, i) => (
                <tr key={mod} className={i % 2 === 0 ? 'bg-zinc-900/20' : ''}>
                  <td className="px-4 py-2 text-zinc-300 font-medium sticky left-0 bg-inherit">
                    {mod}
                  </td>
                  {roles.map((r) => {
                    const access = r.module_access?.[mod];
                    return (
                      <td key={r.role_name} className="px-3 py-2 text-center">
                        {!r.login_success ? (
                          <span className="text-zinc-600" title="Login failed">—</span>
                        ) : access === 'accessible' ? (
                          <span className="text-green-400 text-base" title="Accessible">✓</span>
                        ) : access === 'blocked' ? (
                          <span className="text-red-400 text-base" title="Blocked">✗</span>
                        ) : (
                          <span className="text-zinc-600" title="No URL to test">?</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>

          {/* Legend */}
          <div className="flex items-center gap-4 px-4 py-3 border-t border-zinc-800/40 text-[11px] text-zinc-500">
            <span><span className="text-green-400 font-bold">✓</span> Accessible</span>
            <span><span className="text-red-400 font-bold">✗</span> Blocked</span>
            <span><span className="text-zinc-600">?</span> No URL</span>
            <span><span className="text-zinc-600">—</span> Login failed</span>
          </div>
        </div>
      ) : (
        <div className="divide-y divide-zinc-800/40">
          {roles.map((r) => (
            <div key={r.role_name} className="px-5 py-3">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-sm font-medium text-zinc-200">{r.role_name}</span>
                {r.login_success ? (
                  <span className="text-[10px] px-1.5 py-0.5 bg-green-500/15 text-green-400 rounded">logged in</span>
                ) : (
                  <span className="text-[10px] px-1.5 py-0.5 bg-red-500/15 text-red-400 rounded">login failed</span>
                )}
              </div>
              {r.nav_items.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {r.nav_items.map((item) => (
                    <span key={item} className="text-xs px-2 py-0.5 bg-zinc-800 text-zinc-300 rounded-full">
                      {item}
                    </span>
                  ))}
                </div>
              ) : (
                <span className="text-xs text-zinc-600">{r.login_success ? 'No nav items detected' : r.error || 'Login failed'}</span>
              )}
            </div>
          ))}
        </div>
      )}
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
    kg_generated: { label: 'KG', style: 'bg-cyan-500/20 text-cyan-300' },
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

function LastRunBadge({ status }: { status?: string }) {
  if (!status) return null;
  const cfg =
    status === 'COMPLETED' ? { label: '✓ Passed', cls: 'bg-green-500/15 text-green-400 border-green-500/25' } :
    status === 'FAILED'    ? { label: '✗ Failed', cls: 'bg-red-500/15 text-red-400 border-red-500/25' } :
    status === 'RUNNING'   ? { label: '● Running', cls: 'bg-blue-500/15 text-blue-300 border-blue-500/25 animate-pulse' } :
    status === 'CANCELLED' ? { label: '⊘ Cancelled', cls: 'bg-zinc-700 text-zinc-400 border-zinc-600' } :
    null;
  if (!cfg) return null;
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded border shrink-0 ${cfg.cls}`}>
      {cfg.label}
    </span>
  );
}

function KgReadyBadge({ kgPlanAvailable, workflowTypes }: { kgPlanAvailable?: boolean; workflowTypes?: string[] }) {
  if (!kgPlanAvailable) return null;
  return (
    <span
      className="text-xs px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/25 shrink-0"
      title={workflowTypes?.length ? `KG plan covers: ${workflowTypes.join(', ')}` : 'KG-backed plan available'}
    >
      KG Ready
    </span>
  );
}

// ─── Dataset Tab ──────────────────────────────────────────────────────────────

const DATASET_CATEGORIES = [
  { key: 'invalid_email',   label: 'Invalid Email',       icon: '📧', hint: 'e.g. notanemail, user@, @domain.com',    dataType: 'email' as const },
  { key: 'invalid_file',    label: 'Invalid File',        icon: '📎', hint: 'Upload a file with wrong type/format',   dataType: 'file' as const  },
  { key: 'oversized_file',  label: 'Oversized File',      icon: '🔼', hint: 'Upload a file exceeding the size limit', dataType: 'file' as const  },
  { key: 'valid_file',      label: 'Valid File',          icon: '✅', hint: 'A correctly formatted upload for happy-path tests', dataType: 'file' as const },
  { key: 'boundary_number', label: 'Boundary Number',     icon: '🔢', hint: 'e.g. -1, 0, 99999, 2147483647',         dataType: 'number' as const },
  { key: 'boundary_date',   label: 'Boundary Date',       icon: '📅', hint: 'e.g. 1900-01-01, 2099-12-31, today',    dataType: 'date' as const  },
  { key: 'sql_injection',   label: 'SQL Injection',       icon: '💉', hint: "e.g. '; DROP TABLE users; --",           dataType: 'text' as const  },
  { key: 'xss_payload',     label: 'XSS Payload',        icon: '⚡', hint: "e.g. <script>alert('xss')</script>",    dataType: 'text' as const  },
  { key: 'custom',          label: 'Custom',              icon: '🔧', hint: 'Any custom test value',                 dataType: 'text' as const  },
];

const DATASET_MAX_FILE_MB = 50;

function DatasetTab({ app }: { app: Application }) {
  const [items, setItems] = useState<TestDatasetItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [activeCategory, setActiveCategory] = useState<string>(DATASET_CATEGORIES[0].key);
  const [addValue, setAddValue] = useState('');
  const [addLabel, setAddLabel] = useState('');
  const [addDesc, setAddDesc] = useState('');
  const [adding, setAdding] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  // Inline edit state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editLabel, setEditLabel] = useState('');
  const [editValue, setEditValue] = useState('');
  const [editDesc, setEditDesc] = useState('');
  const [savingEdit, setSavingEdit] = useState(false);

  const toast = useAppToast();
  const confirm = useAppConfirm();

  const catMeta = DATASET_CATEGORIES.find((c) => c.key === activeCategory)!;
  const catItems = items.filter((i) => i.category === activeCategory);

  useEffect(() => {
    setLoadError(false);
    datasetsApi.list(app.id)
      .then(setItems)
      .catch(() => { setItems([]); setLoadError(true); })
      .finally(() => setLoading(false));
  }, [app.id]);

  const handleAddText = async () => {
    if (!addValue.trim() && catMeta.dataType !== 'file') return;
    setAdding(true);
    try {
      const item = await datasetsApi.create(app.id, {
        category: activeCategory,
        label: addLabel.trim() || addValue.trim().slice(0, 60),
        data_type: catMeta.dataType === 'file' ? 'text' : catMeta.dataType,
        text_value: addValue.trim(),
        description: addDesc.trim() || undefined,
      });
      setItems((prev) => [...prev, item]);
      setAddValue(''); setAddLabel(''); setAddDesc('');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to add item');
    } finally { setAdding(false); }
  };

  const handleUpload = async () => {
    if (!uploadFile) return;
    if (uploadFile.size > DATASET_MAX_FILE_MB * 1024 * 1024) {
      toast.error(`File exceeds the ${DATASET_MAX_FILE_MB} MB limit. Choose a smaller file.`);
      return;
    }
    setUploading(true);
    try {
      const item = await datasetsApi.uploadFile(app.id, {
        category: activeCategory,
        label: addLabel.trim() || uploadFile.name,
        description: addDesc.trim() || undefined,
        file: uploadFile,
      });
      setItems((prev) => [...prev, item]);
      setUploadFile(null); setAddLabel(''); setAddDesc('');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Upload failed');
    } finally { setUploading(false); }
  };

  const handleDelete = async (id: string) => {
    const ok = await confirm({
      title: 'Delete this item?',
      message: 'This cannot be undone.',
      confirmLabel: 'Delete',
      destructive: true,
    });
    if (!ok) return;
    setDeletingId(id);
    try {
      await datasetsApi.delete(app.id, id);
      setItems((prev) => prev.filter((i) => i.id !== id));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Delete failed');
    } finally { setDeletingId(null); }
  };

  const startEdit = (item: TestDatasetItem) => {
    setEditingId(item.id);
    setEditLabel(item.label);
    setEditValue(item.text_value || '');
    setEditDesc(item.description || '');
  };

  const cancelEdit = () => { setEditingId(null); };

  const handleSaveEdit = async (item: TestDatasetItem) => {
    setSavingEdit(true);
    try {
      const updated = await datasetsApi.update(app.id, item.id, {
        label: editLabel.trim() || item.label,
        text_value: editValue.trim() || undefined,
        description: editDesc.trim() || undefined,
      });
      setItems((prev) => prev.map((i) => i.id === item.id ? updated : i));
      setEditingId(null);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to save changes');
    } finally { setSavingEdit(false); }
  };

  const formatSize = (bytes?: number) => {
    if (!bytes) return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  };

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Test Dataset</h1>
        <p className="text-sm text-zinc-500 mt-1">
          Store test values (invalid emails, oversized files, edge-case inputs) that the executor
          automatically picks up when running validation and boundary scenarios.
        </p>
      </div>

      <div className="flex gap-6">
        {/* Category sidebar */}
        <div className="w-48 shrink-0">
          <div className="space-y-0.5">
            {DATASET_CATEGORIES.map((cat) => {
              const count = items.filter((i) => i.category === cat.key).length;
              return (
                <button
                  key={cat.key}
                  onClick={() => setActiveCategory(cat.key)}
                  className={`w-full text-left flex items-center justify-between px-3 py-2 rounded-lg text-sm transition-colors ${
                    activeCategory === cat.key
                      ? 'bg-zinc-800 text-white'
                      : 'text-zinc-500 hover:bg-zinc-800/60 hover:text-zinc-300'
                  }`}
                >
                  <span className="flex items-center gap-2">
                    <span>{cat.icon}</span>
                    <span className="truncate">{cat.label}</span>
                  </span>
                  {count > 0 && (
                    <span className="text-xs bg-blue-600/30 text-blue-300 px-1.5 py-0.5 rounded-full ml-1 shrink-0">
                      {count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        {/* Main content */}
        <div className="flex-1 min-w-0">
          {/* Category header */}
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 mb-4">
            <div className="flex items-center gap-3 mb-1">
              <span className="text-2xl">{catMeta.icon}</span>
              <div>
                <h2 className="text-base font-semibold text-white">{catMeta.label}</h2>
                <p className="text-xs text-zinc-500">{catMeta.hint}</p>
              </div>
            </div>

            {/* Add form */}
            <div className="mt-4 space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-zinc-500 block mb-1">Label</label>
                  <input
                    value={addLabel}
                    onChange={(e) => setAddLabel(e.target.value)}
                    placeholder={catMeta.dataType === 'file' ? 'e.g. 10 MB PNG file' : 'Short label'}
                    className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="text-xs text-zinc-500 block mb-1">Description (optional)</label>
                  <input
                    value={addDesc}
                    onChange={(e) => setAddDesc(e.target.value)}
                    placeholder="Why this value is useful"
                    className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>

              {catMeta.dataType === 'file' ? (
                <div className="flex items-center gap-3">
                  <label className="flex-1 flex items-center gap-2 cursor-pointer bg-zinc-800 border border-dashed border-zinc-600 rounded-lg px-4 py-3 hover:border-zinc-500 transition-colors">
                    <span className="text-zinc-400 text-sm">
                      {uploadFile ? uploadFile.name : 'Click to select a file…'}
                    </span>
                    <input type="file" className="hidden" onChange={(e) => setUploadFile(e.target.files?.[0] || null)} />
                  </label>
                  {uploadFile && (
                    <span className="text-xs text-zinc-500 shrink-0">{formatSize(uploadFile.size)}</span>
                  )}
                  <button
                    onClick={handleUpload}
                    disabled={uploading || !uploadFile}
                    className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition-colors disabled:opacity-50 flex items-center gap-2"
                  >
                    {uploading && <span className="animate-spin w-3 h-3 border border-white border-t-transparent rounded-full" />}
                    {uploading ? 'Uploading…' : 'Upload'}
                  </button>
                </div>
              ) : (
                <div className="flex items-center gap-3">
                  <input
                    value={addValue}
                    onChange={(e) => setAddValue(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleAddText()}
                    placeholder={catMeta.hint}
                    className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
                  />
                  <button
                    onClick={handleAddText}
                    disabled={adding || !addValue.trim()}
                    className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition-colors disabled:opacity-50"
                  >
                    {adding ? 'Adding…' : 'Add'}
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Existing items */}
          {loading ? (
            <div className="flex items-center gap-2 text-zinc-500 text-sm py-6">
              <span className="animate-spin w-4 h-4 border-2 border-zinc-600 border-t-zinc-300 rounded-full" />
              Loading…
            </div>
          ) : loadError ? (
            <div className="bg-red-500/10 border border-red-500/25 rounded-xl p-8 text-center">
              <div className="text-red-400 text-sm font-medium mb-1">Failed to load dataset items</div>
              <div className="text-zinc-500 text-xs">Check your connection and reload the page.</div>
            </div>
          ) : catItems.length === 0 ? (
            <div className="bg-zinc-900 border border-dashed border-zinc-800 rounded-xl p-8 text-center text-zinc-500 text-sm">
              No {catMeta.label.toLowerCase()} items yet — add one above.
            </div>
          ) : (
            <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
              <div className="px-5 py-2 bg-zinc-800/40 border-b border-zinc-800 text-xs text-zinc-500 font-medium">
                {catItems.length} item{catItems.length !== 1 ? 's' : ''}
              </div>
              <div className="divide-y divide-zinc-800">
                {catItems.map((item) => (
                  <div key={item.id} className="px-5 py-3 group">
                    {editingId === item.id ? (
                      <div className="flex flex-col gap-2">
                        <input
                          className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
                          value={editLabel}
                          onChange={(e) => setEditLabel(e.target.value)}
                          placeholder="Label"
                        />
                        {item.data_type !== 'file' && (
                          <input
                            className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm font-mono text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
                            value={editValue}
                            onChange={(e) => setEditValue(e.target.value)}
                            placeholder="Value"
                          />
                        )}
                        <input
                          className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-400 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
                          value={editDesc}
                          onChange={(e) => setEditDesc(e.target.value)}
                          placeholder="Description (optional)"
                        />
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => handleSaveEdit(item)}
                            disabled={savingEdit}
                            className="text-xs px-3 py-1 rounded bg-zinc-700 hover:bg-zinc-600 text-zinc-200 transition-colors disabled:opacity-50"
                          >
                            {savingEdit ? 'Saving…' : 'Save'}
                          </button>
                          <button
                            onClick={cancelEdit}
                            className="text-xs px-3 py-1 rounded text-zinc-500 hover:text-zinc-300 transition-colors"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="flex items-start gap-3">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-sm text-zinc-200 font-medium">{item.label}</span>
                            {item.data_type === 'file' && item.file_size && (
                              <span className="text-xs text-zinc-600">{formatSize(item.file_size)}</span>
                            )}
                          </div>
                          {item.data_type !== 'file' && item.text_value && (
                            <div className="text-xs font-mono text-zinc-400 mt-0.5 bg-zinc-800/60 px-2 py-1 rounded truncate max-w-lg">
                              {item.text_value}
                            </div>
                          )}
                          {item.data_type === 'file' && item.file_name && (
                            <div className="text-xs text-zinc-500 mt-0.5">{item.file_name}</div>
                          )}
                          {item.description && (
                            <div className="text-xs text-zinc-600 mt-0.5">{item.description}</div>
                          )}
                        </div>
                        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 shrink-0 mt-0.5">
                          {item.data_type !== 'file' && (
                            <button
                              onClick={() => startEdit(item)}
                              className="text-zinc-600 hover:text-zinc-300 transition-colors text-sm px-1"
                              title="Edit"
                            >
                              ✎
                            </button>
                          )}
                          <button
                            onClick={() => handleDelete(item.id)}
                            disabled={deletingId === item.id}
                            className="text-zinc-600 hover:text-red-400 transition-colors text-sm px-1"
                            title="Delete"
                          >
                            {deletingId === item.id ? (
                              <span className="animate-spin inline-block w-3 h-3 border border-zinc-400 border-t-transparent rounded-full" />
                            ) : '✕'}
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Knowledge Graph Tab ──────────────────────────────────────────────────────

function KnowledgeGraphTab({ app, onExploreClick }: { app: Application; onExploreClick: () => void }) {
  const [coverage, setCoverage] = useState<KgCoverageReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedModule, setSelectedModule] = useState<KgModuleCoverage | null>(null);

  useEffect(() => {
    knowledgeApi.getCoverage(app.id)
      .then(setCoverage)
      .catch(() => setCoverage(null))
      .finally(() => setLoading(false));
  }, [app.id]);

  const statusColor = (status: KgModuleCoverage['status']) =>
    status === 'kg_ready' ? 'border-emerald-500/40 bg-emerald-500/5' :
    status === 'explored' ? 'border-amber-500/40 bg-amber-500/5' :
    'border-zinc-700 bg-zinc-900';

  const statusBadge = (status: KgModuleCoverage['status']) =>
    status === 'kg_ready'
      ? <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">⚡ KG Ready</span>
      : status === 'explored'
      ? <span className="text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30">🔍 Explored</span>
      : <span className="text-xs px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-500">Not Explored</span>;

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-zinc-500 text-sm py-20 justify-center">
        <span className="animate-spin w-5 h-5 border-2 border-zinc-600 border-t-zinc-300 rounded-full" />
        Loading knowledge graph…
      </div>
    );
  }

  if (!coverage || coverage.modules.length === 0) {
    return (
      <div>
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-white">Knowledge Graph</h1>
        </div>
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-12 text-center">
          <div className="text-4xl mb-4">🧠</div>
          <p className="text-zinc-400 font-medium mb-2">No knowledge graph yet</p>
          <p className="text-zinc-600 text-sm mb-6">
            Run an Explore session to let QAptain learn the application structure.
            The KG records module layouts, selectors, and workflows — enabling tests without AI calls.
          </p>
          <button
            onClick={onExploreClick}
            className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-lg transition-colors"
          >
            Start Exploration
          </button>
        </div>
      </div>
    );
  }

  const { summary } = coverage;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Knowledge Graph</h1>
          <p className="text-sm text-zinc-500 mt-1">
            Live view of the explored application structure — updates after every Explore session.
          </p>
        </div>
        <button
          onClick={onExploreClick}
          className="px-4 py-2 bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-zinc-200 text-sm rounded-lg transition-colors"
        >
          🔍 Re-Explore
        </button>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-4 gap-4 mb-8">
        <div className="bg-zinc-900 border border-blue-500/20 rounded-xl p-4">
          <div className="text-2xl font-bold text-white">{summary.modules_total}</div>
          <div className="text-xs text-zinc-500">Total Modules</div>
        </div>
        <div className="bg-zinc-900 border border-amber-500/20 rounded-xl p-4">
          <div className="text-2xl font-bold text-amber-400">{summary.modules_explored}</div>
          <div className="text-xs text-zinc-500">Explored</div>
        </div>
        <div className="bg-zinc-900 border border-emerald-500/20 rounded-xl p-4">
          <div className="text-2xl font-bold text-emerald-400">{summary.modules_kg_ready}</div>
          <div className="text-xs text-zinc-500">KG Ready</div>
        </div>
        <div className="bg-zinc-900 border border-violet-500/20 rounded-xl p-4">
          <div className="text-2xl font-bold text-violet-400">{summary.kg_coverage_pct}%</div>
          <div className="text-xs text-zinc-500">KG Coverage</div>
        </div>
      </div>

      {/* Coverage bar */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 mb-6">
        <div className="flex items-center justify-between text-xs text-zinc-500 mb-2">
          <span>KG Scenario Coverage</span>
          <span>{summary.scenarios_kg_backed} / {summary.scenarios_total} scenarios backed by KG</span>
        </div>
        <div className="w-full bg-zinc-800 rounded-full h-2">
          <div
            className="bg-emerald-500 h-2 rounded-full transition-all"
            style={{ width: `${summary.kg_coverage_pct}%` }}
          />
        </div>
      </div>

      {/* Module grid */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
        {coverage.modules.map((mod) => (
          <button
            key={mod.module_id}
            onClick={() => setSelectedModule(selectedModule?.module_id === mod.module_id ? null : mod)}
            className={`text-left border rounded-xl p-4 transition-all hover:border-opacity-70 ${statusColor(mod.status)} ${
              selectedModule?.module_id === mod.module_id ? 'ring-2 ring-blue-500/40' : ''
            }`}
          >
            <div className="flex items-start justify-between gap-2 mb-2">
              <span className="text-sm font-medium text-zinc-200 leading-snug">{mod.module_name}</span>
              {statusBadge(mod.status)}
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-500">
              {mod.pages_discovered > 0 && <span>📄 {mod.pages_discovered} pages</span>}
              {mod.kg_workflows_count > 0 && <span>🔄 {mod.kg_workflows_count} workflows</span>}
              {mod.scenarios_total > 0 && (
                <span className={mod.scenarios_kg_backed > 0 ? 'text-emerald-500/80' : ''}>
                  📋 {mod.scenarios_kg_backed}/{mod.scenarios_total} KG
                </span>
              )}
            </div>
            {mod.kg_workflow_types.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {[...new Set(mod.kg_workflow_types)].map((wt) => (
                  <span key={wt} className="text-xs bg-zinc-800 text-zinc-400 px-1.5 py-0.5 rounded">
                    {wt.replace('crud_', '')}
                  </span>
                ))}
              </div>
            )}
          </button>
        ))}
      </div>

      {/* Selected module detail panel */}
      {selectedModule && (
        <div className="mt-4 bg-zinc-900 border border-zinc-700 rounded-xl p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-white">{selectedModule.module_name}</h3>
            <button
              onClick={() => setSelectedModule(null)}
              className="text-zinc-600 hover:text-zinc-400 text-sm"
            >✕</button>
          </div>
          <div className="grid grid-cols-3 gap-4 text-sm">
            <div>
              <div className="text-xs text-zinc-500 mb-1">Status</div>
              {statusBadge(selectedModule.status)}
            </div>
            <div>
              <div className="text-xs text-zinc-500 mb-1">Pages Discovered</div>
              <div className="text-zinc-300">{selectedModule.pages_discovered}</div>
            </div>
            <div>
              <div className="text-xs text-zinc-500 mb-1">Last Explored</div>
              <div className="text-zinc-400 text-xs">
                {selectedModule.last_explored_at
                  ? new Date(selectedModule.last_explored_at).toLocaleString()
                  : '—'}
              </div>
            </div>
            <div>
              <div className="text-xs text-zinc-500 mb-1">KG Workflows</div>
              <div className="flex flex-wrap gap-1 mt-1">
                {selectedModule.kg_workflow_types.length > 0
                  ? [...new Set(selectedModule.kg_workflow_types)].map((wt) => (
                      <span key={wt} className="text-xs bg-emerald-500/15 text-emerald-400 px-2 py-0.5 rounded-full border border-emerald-500/25">
                        {wt.replace('crud_', '')}
                      </span>
                    ))
                  : <span className="text-zinc-600 text-xs">None recorded yet</span>
                }
              </div>
            </div>
            <div>
              <div className="text-xs text-zinc-500 mb-1">Scenarios</div>
              <div className="text-zinc-300">
                {selectedModule.scenarios_total} total
                {selectedModule.scenarios_kg_backed > 0
                  ? `, ${selectedModule.scenarios_kg_backed} KG-backed`
                  : ''
                }
              </div>
            </div>
            <div>
              <div className="text-xs text-zinc-500 mb-1">KG Coverage</div>
              <div className="flex items-center gap-2">
                <div className="flex-1 bg-zinc-800 rounded-full h-1.5">
                  <div
                    className="bg-emerald-500 h-1.5 rounded-full"
                    style={{ width: `${selectedModule.kg_coverage_pct}%` }}
                  />
                </div>
                <span className="text-xs text-zinc-400 shrink-0">{selectedModule.kg_coverage_pct}%</span>
              </div>
            </div>
          </div>
          {selectedModule.status === 'not_explored' && (
            <div className="mt-4 flex items-center gap-3 p-3 bg-zinc-800/60 rounded-lg">
              <span className="text-zinc-500 text-sm">This module hasn&apos;t been explored yet.</span>
              <button
                onClick={onExploreClick}
                className="shrink-0 text-xs px-3 py-1.5 bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border border-blue-600/30 rounded-lg transition-colors"
              >
                Explore now
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
