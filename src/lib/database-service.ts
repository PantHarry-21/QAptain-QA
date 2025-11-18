import type { PoolClient } from '@neondatabase/serverless';
import { v4 as uuidv4 } from 'uuid';
import pool from './db';
import type { TestLog, TestScenario, TestSession, TestReport } from './types';

type TestSessionUpdate = Partial<
  Omit<
    TestSession,
    | 'id'
    | 'user_id'
    | 'created_at'
    | 'updated_at'
    | 'total_scenarios'
    | 'total_steps'
    | 'passed_scenarios'
    | 'failed_scenarios'
    | 'passed_steps'
    | 'failed_steps'
    | 'duration'
    | 'status'
    | 'video_url'
    | 'selected_scenario_ids'
  >
> & {
  total_scenarios?: number;
  total_steps?: number;
  passed_scenarios?: number;
  failed_scenarios?: number;
  passed_steps?: number;
  failed_steps?: number;
  duration?: number;
  status?: TestSession['status'];
  video_url?: string | null;
  selected_scenario_ids?: string[] | null;
  page_analysis?: Record<string, unknown> | null;
  ai_analysis?: Record<string, unknown> | null;
};

type TestScenarioUpdate = Partial<
  Omit<TestScenario, 'id' | 'session_id' | 'created_at' | 'updated_at'>
> & {
  error_message?: string | null;
};

type ScenarioReportInput = {
  session_id: string;
  scenario_id: string;
  summary?: string | null;
  issues?: string[] | null;
  recommendations?: string[] | null;
};

type TestReportInput = {
  session_id: string;
  title: string;
  summary: string;
  key_findings?: string[] | null;
  recommendations?: string[] | null;
  risk_level?: TestReport['risk_level'] | null;
  risk_assessment_issues?: string[] | null;
  performance_metrics?: Record<string, unknown> | null;
  quality_score?: number | null;
};

const SESSION_UPDATE_FIELDS = new Set([
  'status',
  'started_at',
  'completed_at',
  'duration',
  'total_scenarios',
  'passed_scenarios',
  'failed_scenarios',
  'total_steps',
  'passed_steps',
  'failed_steps',
  'video_url',
  'selected_scenario_ids',
  'page_analysis',
  'ai_analysis',
]);

const SCENARIO_UPDATE_FIELDS = new Set([
  'status',
  'started_at',
  'completed_at',
  'duration',
  'error_message',
  'steps',
  'title',
  'description',
]);

const jsonLikeFields = new Set(['selected_scenario_ids', 'page_analysis', 'ai_analysis', 'metadata', 'performance_metrics']);

type StoredScenario = (TestScenario & { session_id?: string }) | (Partial<TestScenario> & { id: string; session_id?: string });

type ScenarioReportRecord = ScenarioReportInput & {
  id: string;
  created_at: string;
  updated_at: string;
};

type StoredTestReport = TestReport & {
  performance_metrics?: Record<string, unknown> | null;
  risk_assessment_issues?: string[] | null;
  updated_at?: string;
};

type ListSessionsParams = {
  userId: string;
  search?: string;
  sortBy?: 'created_at' | 'updated_at' | 'status';
  order?: 'asc' | 'desc';
  limit?: number;
  offset?: number;
};

type ListSessionsResult = {
  rows: TestSession[];
  total: number;
};

type InMemorySessionState = {
  session: (Partial<TestSession> & { id: string }) | null;
  scenarios: Record<string, StoredScenario>;
  logs: TestLog[];
  scenarioReports: Record<string, ScenarioReportRecord>;
  report: (StoredTestReport & { session_id: string }) | null;
};

const inMemorySessions = new Map<string, InMemorySessionState>();
const scenarioSessionMap = new Map<string, string>();
export const isDatabaseConfigured = Boolean(process.env.DATABASE_URL);

function serializeValue(field: string, value: unknown) {
  if (value === undefined) return undefined;
  if (value === null) return null;
  if (jsonLikeFields.has(field)) {
    return JSON.stringify(value);
  }
  return value;
}

function getSessionState(sessionId: string): InMemorySessionState {
  if (!inMemorySessions.has(sessionId)) {
    inMemorySessions.set(sessionId, {
      session: {
        id: sessionId,
        status: 'pending',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      scenarios: {},
      logs: [],
      scenarioReports: {},
      report: null,
    });
  }
  return inMemorySessions.get(sessionId)!;
}

function registerScenario(sessionId: string, scenario: StoredScenario) {
  scenarioSessionMap.set(scenario.id, sessionId);
  const state = getSessionState(sessionId);
  state.scenarios[scenario.id] = {
    ...state.scenarios[scenario.id],
    ...scenario,
  };
}

function getSessionIdForScenario(scenarioId: string): string | undefined {
  return scenarioSessionMap.get(scenarioId);
}

const warnedActions = new Set<string>();

function ensureDatabaseConfigured(action: string): boolean {
  if (isDatabaseConfigured) {
    return true;
  }
  if (!warnedActions.has(action)) {
    console.warn(
      `[databaseService] Skipping "${action}" because DATABASE_URL is not set. Data will be kept in-memory only.`,
    );
    warnedActions.add(action);
  }
  return false;
}

async function withClient<T>(handler: (client: PoolClient) => Promise<T>): Promise<T> {
  if (!isDatabaseConfigured) {
    throw new Error('Database connection attempted while DATABASE_URL is not configured.');
  }
  const client = await pool.connect();
  try {
    return await handler(client);
  } finally {
    client.release();
  }
}

export const databaseService = {
  async createTestLog(log: Partial<TestLog> & { session_id: string; message: string }) {
    if (!ensureDatabaseConfigured('createTestLog')) {
      const state = getSessionState(log.session_id);
      const entry: TestLog = {
        id: log.id || uuidv4(),
        session_id: log.session_id,
        scenario_id: log.scenario_id,
        step_id: log.step_id,
        level: (log.level || 'info') as TestLog['level'],
        message: log.message,
        timestamp: log.timestamp || new Date().toISOString(),
        metadata: log.metadata,
      };
      state.logs.push(entry);
      return entry;
    }
    return withClient(async (client) => {
      await client.query(
        `
          INSERT INTO test_logs (session_id, scenario_id, step_id, level, message, "timestamp", metadata)
          VALUES ($1, $2, $3, $4, $5, $6, $7)
        `,
        [
          log.session_id,
          log.scenario_id || null,
          log.step_id || null,
          log.level || 'info',
          log.message,
          log.timestamp ? new Date(log.timestamp) : new Date(),
          serializeValue('metadata', log.metadata ?? null),
        ],
      );
    });
  },

  async updateTestSession(sessionId: string, updates: TestSessionUpdate) {
    if (!ensureDatabaseConfigured('updateTestSession')) {
      const state = getSessionState(sessionId);
      if (!state.session) {
        state.session = { id: sessionId };
      }
      const nextSession = {
        ...state.session,
        ...updates,
        id: sessionId,
        updated_at: new Date().toISOString(),
      } as TestSession;
      state.session = nextSession;
      return nextSession;
    }
    return withClient(async (client) => {
      const entries = Object.entries(updates).filter(
        ([field, value]) => SESSION_UPDATE_FIELDS.has(field) && value !== undefined,
      );

      if (entries.length === 0) {
        return null;
      }

      const setClauses = entries.map(([field], index) => `"${field}" = $${index + 1}`);
      const values = entries.map(([field, value]) => serializeValue(field, value));

      setClauses.push(`updated_at = NOW()`);

      const result = await client.query(
        `
          UPDATE test_sessions
          SET ${setClauses.join(', ')}
          WHERE id = $${values.length + 1}
          RETURNING *
        `,
        [...values, sessionId],
      );

      return result.rows[0] || null;
    });
  },

  async updateTestScenario(scenarioId: string, updates: TestScenarioUpdate) {
    if (!ensureDatabaseConfigured('updateTestScenario')) {
      const sessionId = getSessionIdForScenario(scenarioId);
      if (!sessionId) {
        console.warn(`[databaseService] Received scenario update for ${scenarioId} without a registered session.`);
        return { id: scenarioId, ...updates } as TestScenario;
      }
      const state = getSessionState(sessionId);
      const existing = state.scenarios[scenarioId] as StoredScenario | undefined;
      const merged = {
        ...(existing || { id: scenarioId, session_id: sessionId }),
        ...updates,
        updated_at: new Date().toISOString(),
      } as TestScenario;
      state.scenarios[scenarioId] = merged;
      return merged;
    }
    return withClient(async (client) => {
      const entries = Object.entries(updates).filter(
        ([field, value]) => SCENARIO_UPDATE_FIELDS.has(field) && value !== undefined,
      );

      if (entries.length === 0) {
        return null;
      }

      const setClauses = entries.map(([field], index) => `"${field}" = $${index + 1}`);
      const values = entries.map(([, value]) => value);
      setClauses.push(`updated_at = NOW()`);

      const result = await client.query(
        `
          UPDATE test_scenarios
          SET ${setClauses.join(', ')}
          WHERE id = $${values.length + 1}
          RETURNING *
        `,
        [...values, scenarioId],
      );

      return result.rows[0] || null;
    });
  },

  async createScenarioReport(report: ScenarioReportInput) {
    if (!ensureDatabaseConfigured('createScenarioReport')) {
      const state = getSessionState(report.session_id);
      const existing = state.scenarioReports[report.scenario_id];
      const entry: ScenarioReportRecord = {
        id: existing?.id || uuidv4(),
        scenario_id: report.scenario_id,
        session_id: report.session_id,
        summary: report.summary || null,
        issues: report.issues || null,
        recommendations: report.recommendations || null,
        created_at: existing?.created_at || new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      state.scenarioReports[report.scenario_id] = entry;
      return entry;
    }
    return withClient(async (client) => {
      const result = await client.query(
        `
          INSERT INTO scenario_reports (scenario_id, session_id, summary, issues, recommendations)
          VALUES ($1, $2, $3, $4, $5)
          ON CONFLICT (scenario_id) DO UPDATE
          SET summary = EXCLUDED.summary,
              issues = EXCLUDED.issues,
              recommendations = EXCLUDED.recommendations
          RETURNING *
        `,
        [
          report.scenario_id,
          report.session_id,
          report.summary || null,
          report.issues || null,
          report.recommendations || null,
        ],
      );

      return result.rows[0] || null;
    });
  },

  async createTestReport(report: TestReportInput) {
    if (!ensureDatabaseConfigured('createTestReport')) {
      const state = getSessionState(report.session_id);
      const entry: StoredTestReport & { session_id: string } = {
        id: state.report?.id || uuidv4(),
        session_id: report.session_id,
        title: report.title,
        summary: report.summary,
        key_findings: report.key_findings || [],
        recommendations: report.recommendations || [],
        risk_level: report.risk_level || 'low',
        risk_assessment_issues: report.risk_assessment_issues || [],
        performance_metrics: report.performance_metrics || {},
        quality_score: report.quality_score || 0,
        created_at: state.report?.created_at || new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      state.report = entry;
      return entry;
    }
    return withClient(async (client) => {
      const result = await client.query(
        `
          INSERT INTO test_reports (
            session_id,
            title,
            summary,
            key_findings,
            recommendations,
            risk_level,
            risk_assessment_issues,
            performance_metrics,
            quality_score
          )
          VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
          ON CONFLICT (session_id) DO UPDATE
          SET title = EXCLUDED.title,
              summary = EXCLUDED.summary,
              key_findings = EXCLUDED.key_findings,
              recommendations = EXCLUDED.recommendations,
              risk_level = EXCLUDED.risk_level,
              risk_assessment_issues = EXCLUDED.risk_assessment_issues,
              performance_metrics = EXCLUDED.performance_metrics,
              quality_score = EXCLUDED.quality_score,
              updated_at = NOW()
          RETURNING *
        `,
        [
          report.session_id,
          report.title,
          report.summary,
          report.key_findings || null,
          report.recommendations || null,
          report.risk_level || null,
          report.risk_assessment_issues || null,
          serializeValue('performance_metrics', report.performance_metrics ?? null),
          report.quality_score ?? null,
        ],
      );

      return result.rows[0] || null;
    });
  },

  async seedSessionData(
    sessionId: string,
    payload: {
      session?: Partial<TestSession>;
      scenarios?: StoredScenario[];
    },
  ) {
    if (isDatabaseConfigured) {
      return;
    }
    const state = getSessionState(sessionId);
    if (payload.session) {
      state.session = {
        ...(state.session || { id: sessionId }),
        ...payload.session,
        id: sessionId,
      } as TestSession;
    }
    payload.scenarios?.forEach((scenario) => {
      registerScenario(sessionId, {
        ...scenario,
        session_id: scenario.session_id || sessionId,
      });
    });
  },

  async getSessionPayload(sessionId: string) {
    if (!isDatabaseConfigured) {
      const state = inMemorySessions.get(sessionId);
      if (!state || !state.session) {
        return null;
      }
      return {
        session: state.session,
        scenarios: Object.values(state.scenarios),
        logs: state.logs,
        report: state.report,
        scenarioReports: Object.values(state.scenarioReports),
      };
    }

    return withClient(async (client) => {
      const {
        rows: [session],
      } = await client.query(
        `SELECT 
           ts.*, 
           tr.id AS report_id, tr.session_id AS report_session_id, tr.summary AS report_summary, 
           tr.key_findings AS report_key_findings, tr.recommendations AS report_recommendations, 
           tr.risk_level AS report_risk_level, tr.risk_assessment_issues AS report_risk_assessment_issues, 
           tr.performance_metrics AS report_performance_metrics
         FROM test_sessions ts
         LEFT JOIN test_reports tr ON ts.id = tr.session_id
         WHERE ts.id = $1`,
        [sessionId],
      );

      if (!session) {
        return null;
      }

      let report = null;
      if (session.report_id) {
        report = {
          id: session.report_id,
          session_id: session.report_session_id,
          summary: session.report_summary,
          key_findings: session.report_key_findings,
          recommendations: session.report_recommendations,
          risk_level: session.report_risk_level,
          risk_assessment_issues: session.report_risk_assessment_issues,
          performance_metrics: session.report_performance_metrics,
        };
        delete session.report_id;
        delete session.report_session_id;
        delete session.report_summary;
        delete session.report_key_findings;
        delete session.report_recommendations;
        delete session.report_risk_level;
        delete session.report_risk_assessment_issues;
        delete session.report_performance_metrics;
      }

      let { rows: scenarios } = await client.query(
        'SELECT * FROM test_scenarios WHERE session_id = $1 ORDER BY created_at ASC',
        [sessionId],
      );

      if (scenarios) {
        let retries = 5;
        const hasRunning = scenarios.some((s) => s.status === 'running');
        if (session.status === 'completed' && hasRunning) {
          while (retries > 0) {
            await new Promise((resolve) => setTimeout(resolve, 1500));
            const { rows: refetched } = await client.query(
              'SELECT * FROM test_scenarios WHERE session_id = $1 ORDER BY created_at ASC',
              [sessionId],
            );
            scenarios = refetched;
            if (!refetched.some((s) => s.status === 'running')) {
              break;
            }
            retries -= 1;
          }
        }
      }

      if (Array.isArray(session.selected_scenario_ids) && scenarios) {
        scenarios = scenarios.filter((scenario: any) => session.selected_scenario_ids.includes(scenario.id));
      }

      const { rows: logs } = await client.query(
        'SELECT * FROM test_logs WHERE session_id = $1 ORDER BY timestamp ASC',
        [sessionId],
      );

      const { rows: scenarioReports } = await client.query(
        'SELECT * FROM scenario_reports WHERE session_id = $1',
        [sessionId],
      );

      return {
        session,
        scenarios: scenarios || [],
        logs: logs || [],
        report,
        scenarioReports: scenarioReports || [],
      };
    });
  },

  async listTestSessions(params: ListSessionsParams): Promise<ListSessionsResult> {
    const {
      userId,
      search = '',
      sortBy = 'created_at',
      order = 'desc',
      limit = 10,
      offset = 0,
    } = params;

    const safeSort = ['created_at', 'updated_at', 'status'].includes(sortBy) ? sortBy : 'created_at';

    if (!isDatabaseConfigured) {
      const sessions = Array.from(inMemorySessions.values())
        .map((state) => state.session)
        .filter((session): session is TestSession & { user_id: string } => Boolean(session && session.user_id))
        .filter((session) => session.user_id === userId)
        .filter((session) => {
          if (!search) return true;
          const haystack = `${session.id} ${session.url ?? ''}`.toLowerCase();
          return haystack.includes(search.toLowerCase());
        });

      const sorted = sessions.sort((a, b) => {
        const direction = order === 'asc' ? 1 : -1;
        const aValue = (a as any)[safeSort] ?? '';
        const bValue = (b as any)[safeSort] ?? '';
        if (aValue === bValue) return 0;
        return aValue > bValue ? direction : -direction;
      });

      const paginated = sorted.slice(offset, offset + limit);

      return {
        rows: paginated,
        total: sessions.length,
      };
    }

    return withClient(async (client) => {
      const paramsList: any[] = [userId];
      let searchClause = '';
      if (search) {
        paramsList.push(`%${search}%`);
        searchClause = ` AND (url ILIKE $2 OR id::text ILIKE $2)`;
      }

      const countQuery = `
        SELECT COUNT(*) 
        FROM test_sessions 
        WHERE user_id = $1
        ${searchClause}
      `;
      const countParams = [...paramsList];
      const { rows: countRows } = await client.query(countQuery, countParams);
      const total = parseInt(countRows[0].count, 10);

      const limitIndex = paramsList.length + 1;
      paramsList.push(limit);
      const offsetIndex = paramsList.length + 1;
      paramsList.push(offset);

      const dataQuery = `
        SELECT *
        FROM test_sessions
        WHERE user_id = $1
        ${searchClause}
        ORDER BY ${safeSort} ${order.toUpperCase()}
        LIMIT $${limitIndex}
        OFFSET $${offsetIndex}
      `;

      const { rows } = await client.query(dataQuery, paramsList);

      return { rows, total };
    });
  },
};

