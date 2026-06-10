/**
 * QAptain API Client
 * Typed client for the FastAPI backend.
 */

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = 'ApiError';
  }
}

async function request<T>(
  path: string,
  options: RequestInit & { params?: Record<string, string> } = {},
): Promise<T> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('qaptain_token') : null;

  let url = `${BASE_URL}${path}`;
  if (options.params) {
    const qs = new URLSearchParams(options.params).toString();
    url += `?${qs}`;
  }

  // Never set Content-Type for FormData — the browser must set it with the multipart boundary
  const isFormData = options.body instanceof FormData;

  const res = await fetch(url, {
    ...options,
    headers: {
      ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    // FastAPI validation errors return detail as an array of {loc, msg, type} objects
    const raw = err.detail;
    const detail =
      typeof raw === 'string' ? raw
      : Array.isArray(raw) ? raw.map((e: Record<string, unknown>) => String(e.msg ?? JSON.stringify(e))).join('; ')
      : raw != null ? JSON.stringify(raw)
      : 'Request failed';
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

// ─── Auth ─────────────────────────────────────────────────────────────────────

export const auth = {
  signup: (data: { name: string; email: string; password: string }) =>
    request<{ access_token: string; user: User }>('/auth/signup', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  login: (data: { email: string; password: string }) =>
    request<{ access_token: string; user: User }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  me: () => request<User>('/auth/me'),
};

// ─── Workspaces ───────────────────────────────────────────────────────────────

export const workspaces = {
  list: () => request<Workspace[]>('/workspaces'),

  create: (data: { name: string }) =>
    request<Workspace>('/workspaces', { method: 'POST', body: JSON.stringify(data) }),

  get: (workspaceId: string) => request<Workspace>(`/workspaces/${workspaceId}`),

  update: (workspaceId: string, data: { name?: string; description?: string }) =>
    request<Workspace>(`/workspaces/${workspaceId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  delete: (workspaceId: string) =>
    request<void>(`/workspaces/${workspaceId}`, { method: 'DELETE' }),

  listApplications: (workspaceId: string) =>
    request<Application[]>(`/workspaces/${workspaceId}/applications`),

  createApplication: (workspaceId: string, data: CreateApplicationPayload) =>
    request<Application>(`/workspaces/${workspaceId}/applications`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
};

// ─── Applications ─────────────────────────────────────────────────────────────

export interface RoleCredential {
  id: string;
  role_name: string;
  username: string;
}

export interface BulkImportResult {
  imported: number;
  skipped: number;
  total_in_file: number;
  message: string;
}

export interface RbacRoleResult {
  role_name: string;
  username: string;
  login_success: boolean;
  error?: string;
  nav_items: string[];
  module_access: Record<string, 'accessible' | 'blocked' | 'no_url' | 'unknown'>;
}

export interface RbacScanResult {
  id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  results: {
    modules?: string[];
    roles?: RbacRoleResult[];
    scanned_at?: string;
    progress?: { completed: number; total: number; current_role?: string };
  };
}

export const applications = {
  get: (id: string) => request<Application>(`/applications/${id}`),

  listEnvironments: (id: string) => request<Environment[]>(`/applications/${id}/environments`),

  listModules: (id: string) => request<Module[]>(`/applications/${id}/modules`),

  listRoleCredentials: (id: string) =>
    request<RoleCredential[]>(`/applications/${id}/role-credentials`),

  addRoleCredential: (id: string, data: { role_name: string; username: string; password: string }) =>
    request<RoleCredential>(`/applications/${id}/role-credentials`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  deleteRoleCredential: (appId: string, credId: string) =>
    request<void>(`/applications/${appId}/role-credentials/${credId}`, { method: 'DELETE' }),

  bulkImportRoleCredentials: (appId: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return request<BulkImportResult>(`/applications/${appId}/role-credentials/bulk`, {
      method: 'POST',
      body: form,
    });
  },

  startRbacScan: (appId: string) =>
    request<{ scan_id: string; status: string }>(`/applications/${appId}/rbac-scan`, {
      method: 'POST',
    }),

  getLatestRbacScan: (appId: string) =>
    request<RbacScanResult | null>(`/applications/${appId}/rbac-scan/latest`),
};

// ─── Explore ──────────────────────────────────────────────────────────────────

export const explore = {
  discover: (data: { application_id: string }) =>
    request<ExploreSession>('/explore/discover', { method: 'POST', body: JSON.stringify(data) }),

  start: (data: { application_id: string; mode: ExploreMode; selected_module_ids?: string[] }) =>
    request<ExploreSession>('/explore/start', { method: 'POST', body: JSON.stringify(data) }),

  getSession: (sessionId: string) =>
    request<ExploreSession>(`/explore/${sessionId}`),

  getLogs: (sessionId: string, sinceId?: string) =>
    request<ExploreLog[]>(`/explore/${sessionId}/logs`, {
      params: sinceId ? { since_id: sinceId } : undefined,
    }),

  getPendingDecision: (sessionId: string) =>
    request<HumanDecision | null>(`/explore/${sessionId}/pending-decision`),

  resolveDecision: (sessionId: string, data: { decision_id: string; selected_option: Record<string, unknown>; save_as_preference: boolean }) =>
    request<HumanDecision>(`/explore/${sessionId}/decide`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  getKnowledge: (applicationId: string) =>
    request<KnowledgeGraph | null>(`/explore/application/${applicationId}/knowledge`),

  getActiveSession: (applicationId: string) =>
    request<ExploreSession | null>(`/explore/application/${applicationId}/active`),

  continueSession: (sessionId: string, data: { selected_module_ids: string[] }) =>
    request<ExploreSession>(`/explore/${sessionId}/continue`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  cancelSession: (sessionId: string) =>
    request<ExploreSession>(`/explore/${sessionId}/cancel`, { method: 'POST' }),
};

// ─── Scenarios ────────────────────────────────────────────────────────────────

export const scenarios = {
  list: (applicationId: string) =>
    request<Scenario[]>('/scenarios', { params: { application_id: applicationId } }),

  create: (data: CreateScenarioPayload) =>
    request<Scenario>('/scenarios', { method: 'POST', body: JSON.stringify(data) }),

  generatePlan: (scenarioId: string, mode: string = 'functional') =>
    request<ExecutionPlan>(`/scenarios/${scenarioId}/plan`, {
      method: 'POST',
      body: JSON.stringify({ scenario_id: scenarioId, execution_mode: mode }),
    }),

  triggerExecution: (scenarioId: string, data: { plan_id: string; environment_id: string; credential_id?: string }) =>
    request<ExecutionRun>(`/scenarios/${scenarioId}/execute`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  listRuns: (scenarioId: string) =>
    request<ExecutionRun[]>(`/scenarios/${scenarioId}/runs`),

  importExcel: (applicationId: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return request<{ imported: number; titles: string[] }>(
      `/scenarios/import/excel?application_id=${applicationId}`,
      { method: 'POST', body: form, headers: {} },
    );
  },

  importDocument: (data: {
    application_id: string;
    module_name: string;
    module_url: string;
    file: File;
  }) => {
    const form = new FormData();
    form.append('file', data.file);
    const qs = new URLSearchParams({
      application_id: data.application_id,
      module_name: data.module_name,
      module_url: data.module_url,
    }).toString();
    return request<{ imported: number; module: string; module_url: string; module_id: string; titles: string[] }>(
      `/scenarios/import/document?${qs}`,
      { method: 'POST', body: form, headers: {} },
    );
  },

  runBatch: (data: { scenario_ids: string[]; execution_mode: string; environment_id: string; smoke_only?: boolean }) =>
    request<{ runs: BatchRun[]; total: number }>('/scenarios/run-batch', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  update: (scenarioId: string, data: { title?: string; description?: string; priority?: string; tags?: string[] }) =>
    request<Scenario>(`/scenarios/${scenarioId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  delete: (scenarioId: string) =>
    request<void>(`/scenarios/${scenarioId}`, { method: 'DELETE' }),

  aiCopilot: (data: { description: string; application_id: string; output_type: 'scenarios' | 'user_stories' }) =>
    request<{ output_type: string; items: AICopilotItem[]; application_id: string; context_used: boolean; matched_module: string | null }>(
      '/scenarios/ai-copilot/generate',
      { method: 'POST', body: JSON.stringify(data) },
    ),

  deleteByModule: (applicationId: string, moduleId: string | null) =>
    request<{ deleted: number }>(
      `/scenarios/bulk/by-module?application_id=${applicationId}${moduleId && moduleId !== '__none__' ? `&module_id=${moduleId}` : ''}`,
      { method: 'DELETE' },
    ),

  getPlaywrightScript: (scenarioId: string) =>
    request<PlaywrightScript>(`/scenarios/${scenarioId}/playwright-script`),
};

// ─── Executions ───────────────────────────────────────────────────────────────

export const executions = {
  get: (runId: string) => request<ExecutionRun>(`/executions/${runId}`),

  getSteps: (runId: string) => request<ExecutionStep[]>(`/executions/${runId}/steps`),

  getLogs: (runId: string, sinceId?: string) =>
    request<ExecutionLog[]>(`/executions/${runId}/logs`, {
      params: sinceId ? { since_id: sinceId } : undefined,
    }),

  getReport: (runId: string) =>
    request<ExecutionReport | null>(`/executions/${runId}/report`),

  cancel: (runId: string) =>
    request<{ status: string }>(`/executions/${runId}/cancel`, { method: 'POST' }),

  batchHistory: (applicationId: string, limit = 30) =>
    request<BatchHistory[]>(`/executions/batch-history`, {
      params: { application_id: applicationId, limit: String(limit) },
    }),

  getBatch: (batchId: string) =>
    request<{ batch_id: string; runs: Array<{ run_id: string; title: string }> }>(
      `/executions/batch/${batchId}`,
    ),

  getBatchSummary: (batchId: string) =>
    request<BatchRunSummary>(`/executions/batch/${batchId}/summary`),
};

// ─── Reports ──────────────────────────────────────────────────────────────────

export const reports = {
  listForApplication: (applicationId: string, limit = 20) =>
    request<ReportSummary[]>(`/reports/applications/${applicationId}`, {
      params: { limit: String(limit) },
    }),

  get: (reportId: string) => request<ExecutionReport>(`/reports/${reportId}`),
};

// ─── Knowledge ────────────────────────────────────────────────────────────────

export const knowledge = {
  getModules: (applicationId: string) =>
    request<Module[]>(`/knowledge/applications/${applicationId}/modules`),

  getPages: (moduleId: string) => request<Page[]>(`/knowledge/modules/${moduleId}/pages`),

  getWorkflows: (moduleId: string) => request<Workflow[]>(`/knowledge/modules/${moduleId}/workflows`),

  getCoverage: (applicationId: string) =>
    request<KgCoverageReport>(`/knowledge/applications/${applicationId}/coverage`),

  getDrift: (applicationId: string) =>
    request<KgDriftReport>(`/knowledge/applications/${applicationId}/drift`),
};

// ─── Types ────────────────────────────────────────────────────────────────────

export interface User {
  id: string;
  email: string;
  name: string;
  is_active: boolean;
}

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  description?: string;
  created_at: string;
  member_count: number;
  application_count?: number;
  readiness?: number;
}

export interface Application {
  id: string;
  workspace_id: string;
  name: string;
  base_url: string;
  description?: string;
  explore_mode: ExploreMode;
  created_at: string;
  has_knowledge: boolean;
  last_explored_at?: string;
  modules_count: number;
}

export interface Environment {
  id: string;
  application_id: string;
  name: string;
  env_type: string;
  base_url: string;
  is_default: boolean;
}

export interface Module {
  id: string;
  name: string;
  description?: string;
  url_pattern?: string;
  icon?: string;
  is_accordion: boolean;
  parent_id?: string | null;
  semantic_tags: string[];
}

export interface Page {
  id: string;
  title: string;
  url: string;
  page_type: string;
  semantic_map: Record<string, unknown>;
  forms: unknown[];
  tables: unknown[];
}

export interface Workflow {
  id: string;
  name: string;
  description?: string;
  workflow_type: string;
  stages: unknown[];
}

export type ExploreMode = 'FULL' | 'SMART' | 'SKIP';

export interface ExploreSession {
  id: string;
  application_id: string;
  mode: ExploreMode;
  status: 'PENDING' | 'RUNNING' | 'PAUSED' | 'WAITING_HUMAN' | 'COMPLETED' | 'FAILED' | 'CANCELLED';
  discover_only: boolean;
  started_at?: string;
  completed_at?: string;
  pages_discovered: number;
  modules_discovered: number;
  workflows_discovered: number;
  summary: Record<string, unknown>;
  created_at: string;
}

export interface ExploreLog {
  id: string;
  timestamp: string;
  level: 'INFO' | 'SUCCESS' | 'WARNING' | 'MILESTONE';
  category?: string;
  message: string;
  metadata: Record<string, unknown>;
}

export interface HumanDecision {
  id: string;
  question: string;
  context?: string;
  options: Array<{ label: string; value: string; description?: string }>;
  selected_option?: Record<string, unknown>;
  resolved_at?: string;
  is_saved_as_preference: boolean;
}

export interface KnowledgeGraph {
  id: string;
  application_id: string;
  version: number;
  modules_count: number;
  pages_count: number;
  workflows_count: number;
  graph_data: Record<string, unknown>;
  created_at: string;
}

export interface Scenario {
  id: string;
  application_id: string;
  title: string;
  description?: string;
  priority: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
  tags: string[];
  module_id?: string;
  module_name?: string;
  module_url?: string;
  source: string;
  is_active: boolean;
  is_smoke: boolean;
  created_at: string;
  kg_plan_available?: boolean;
  kg_workflow_types?: string[];
  last_run_status?: 'COMPLETED' | 'FAILED' | 'CANCELLED' | 'RUNNING' | string;
  last_run_at?: string;
}

export interface KgModuleCoverage {
  module_id: string;
  module_name: string;
  explored: boolean;
  pages_discovered: number;
  last_explored_at?: string;
  kg_workflow_types: string[];
  kg_workflows_count: number;
  scenarios_total: number;
  scenarios_kg_backed: number;
  kg_coverage_pct: number;
  status: 'kg_ready' | 'explored' | 'not_explored';
}

export interface KgCoverageReport {
  modules: KgModuleCoverage[];
  summary: {
    modules_total: number;
    modules_explored: number;
    modules_kg_ready: number;
    scenarios_total: number;
    scenarios_kg_backed: number;
    kg_coverage_pct: number;
  };
}

export interface KgDriftReport {
  drifted_modules: Array<{
    module_id: string;
    module_name: string;
    runs_checked: number;
    failed_runs: number;
    fail_rate_pct: number;
    severity: 'high' | 'medium';
    top_failing_selectors: Array<{ target: string; error_type: string; occurrences: number }>;
    recommendation: string;
  }>;
  healthy_modules: Array<{ module_id: string; module_name: string; runs_checked: number; fail_rate_pct: number }>;
  total_checked: number;
  drift_detected: boolean;
}

export interface BatchRunSummary {
  batch_id: string;
  summary: {
    total: number; passed: number; failed: number; skipped: number;
    quality_score: number; pass_rate_pct: number;
  };
  root_cause_breakdown: Array<{ error_type: string; count: number; pct: number }>;
  module_health: Array<{
    module_id: string | null; module_name: string;
    total: number; passed: number; failed: number; skipped: number;
  }>;
  scenarios_needing_attention: Array<{
    run_id: string; scenario_title: string; module_name: string;
    failed_steps: number; total_steps: number;
    top_error_type: string; error_message: string;
  }>;
}

export interface BatchRun {
  scenario_id: string;
  run_id?: string;
  title: string;
  error?: string;
}

export interface AICopilotItem {
  title: string;
  description?: string;
  acceptance_criteria?: string[];
  priority?: string;
  category?: string;
  test_hints?: string[];
}

export interface ExecutionPlan {
  id: string;
  scenario_id: string;
  version: number;
  execution_mode: string;
  plan_data: Record<string, unknown>;
  ai_reasoning?: string;
  workflow_stages: unknown[];
  risk_score: number;
  estimated_duration_seconds?: number;
  created_at: string;
}

export interface ExecutionRun {
  id: string;
  scenario_id: string;
  plan_id: string;
  status: 'PENDING' | 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED' | 'PARTIAL';
  started_at?: string;
  completed_at?: string;
  total_steps: number;
  passed_steps: number;
  failed_steps: number;
  healed_steps: number;
  video_path?: string;
}

export interface ExecutionStep {
  id: string;
  sequence: number;
  action_type: string;
  description?: string;
  status: 'PENDING' | 'RUNNING' | 'PASSED' | 'FAILED' | 'SKIPPED' | 'HEALED';
  duration_ms?: number;
  healing_triggered: boolean;
  healing_attempts: unknown[];
  screenshot_path?: string;
  error_message?: string;
}

export interface ExecutionLog {
  id: string;
  timestamp: string;
  level: string;
  category?: string;
  message: string;
  metadata: Record<string, unknown>;
}

export interface ExecutionReport {
  id: string;
  run_id: string;
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  quality_score?: number;
  summary: Record<string, unknown>;
  insights: unknown[];
  rca_analysis: Record<string, unknown>;
  recommendations: string[];
  timeline: unknown[];
  evidence: Record<string, unknown>;
  created_at: string;
}

export interface ReportSummary {
  id: string;
  run_id: string;
  scenario_title: string;
  scenario_id: string;
  risk_level?: string;
  quality_score?: number;
  summary: {
    total?: number;
    passed?: number;
    failed?: number;
    healed?: number;
    pass_rate?: number;
    workflow?: string;
    workflow_type?: string;
    duration_seconds?: number;
    phases_completed?: string[];
    phases_failed?: string[];
    checkpoints_total?: number;
    checkpoints_passed?: number;
    [key: string]: unknown;
  };
  created_at: string;
  run_status?: string;
}

export interface BatchHistoryRun {
  run_id: string;
  title: string;
  status: string;
  passed_steps: number;
  failed_steps: number;
  total_steps: number;
  completed_at?: string;
}

export interface BatchHistory {
  batch_id: string;
  started_at: string;
  environment_id: string;
  total: number;
  passed: number;
  failed: number;
  running: number;
  runs: BatchHistoryRun[];
}

export interface CreateApplicationPayload {
  workspace_id: string;
  name: string;
  base_url: string;
  description: string;
  username: string;
  password: string;
  environment_name?: string;
  environment_type?: string;
  explore_mode?: ExploreMode;
}

export interface CreateScenarioPayload {
  application_id: string;
  title: string;
  description?: string;
  priority?: string;
  tags?: string[];
  module_id?: string;
}

export interface PlaywrightScript {
  scenario_id: string;
  scenario_title: string;
  script: string;
  source: 'kg_recorded' | 'ai' | 'skeleton' | string;
  step_count: number;
  plan_id: string | null;
}

export interface TestDatasetItem {
  id: string;
  application_id: string;
  category: string;
  label: string;
  data_type: 'text' | 'email' | 'number' | 'date' | 'url' | 'file';
  text_value?: string;
  file_path?: string;
  file_name?: string;
  file_size?: number;
  description?: string;
  created_at: string;
}

// ─── Datasets ─────────────────────────────────────────────────────────────────

export const datasets = {
  list: (applicationId: string) =>
    request<TestDatasetItem[]>(`/datasets/${applicationId}`),

  create: (applicationId: string, data: {
    category: string;
    label: string;
    data_type: TestDatasetItem['data_type'];
    text_value?: string;
    description?: string;
  }) =>
    request<TestDatasetItem>(`/datasets/${applicationId}`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  uploadFile: (applicationId: string, data: { category: string; label: string; description?: string; file: File }) => {
    const form = new FormData();
    form.append('file', data.file);
    form.append('category', data.category);
    form.append('label', data.label);
    if (data.description) form.append('description', data.description);
    return request<TestDatasetItem>(`/datasets/${applicationId}/upload`, {
      method: 'POST',
      body: form,
    });
  },

  update: (applicationId: string, itemId: string, data: { label?: string; text_value?: string; description?: string }) =>
    request<TestDatasetItem>(`/datasets/${applicationId}/${itemId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),

  delete: (applicationId: string, itemId: string) =>
    request<void>(`/datasets/${applicationId}/${itemId}`, { method: 'DELETE' }),
};

export { ApiError };

export const api = {
  auth,
  workspaces,
  applications,
  explore,
  scenarios,
  executions,
  reports,
  knowledge,
  datasets,
};
