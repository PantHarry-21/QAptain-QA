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

  const res = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, err.detail || 'Request failed');
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
  list: () => request<{ workspaces: Workspace[]; total: number }>('/workspaces'),

  create: (data: { name: string }) =>
    request<Workspace>('/workspaces', { method: 'POST', body: JSON.stringify(data) }),

  get: (workspaceId: string) => request<Workspace>(`/workspaces/${workspaceId}`),

  listApplications: (workspaceId: string) =>
    request<Application[]>(`/workspaces/${workspaceId}/applications`),

  createApplication: (workspaceId: string, data: CreateApplicationPayload) =>
    request<Application>(`/workspaces/${workspaceId}/applications`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
};

// ─── Applications ─────────────────────────────────────────────────────────────

export const applications = {
  get: (id: string) => request<Application>(`/applications/${id}`),

  listEnvironments: (id: string) => request<Environment[]>(`/applications/${id}/environments`),

  listModules: (id: string) => request<Module[]>(`/applications/${id}/modules`),
};

// ─── Explore ──────────────────────────────────────────────────────────────────

export const explore = {
  start: (data: { application_id: string; mode: ExploreMode }) =>
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
  source: string;
  is_active: boolean;
  created_at: string;
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
  summary: Record<string, unknown>;
  created_at: string;
  run_status?: string;
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
};
