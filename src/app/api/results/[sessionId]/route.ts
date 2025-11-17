import { NextRequest, NextResponse } from 'next/server';
import pool from '@/lib/db';

export const dynamic = 'force-dynamic';

export async function GET(
  request: NextRequest,
  { params }: { params: { sessionId: string } }
) {
  const { sessionId } = await params;

  if (!sessionId) {
    return NextResponse.json({ error: 'Session ID is required' }, { status: 400 });
  }

  try {
    const client = await pool.connect();
    try {
      // Fetch Test Session
      const { rows: [session] } = await client.query(
        `SELECT 
           ts.*, 
           tr.id AS report_id, tr.session_id AS report_session_id, tr.summary AS report_summary, 
           tr.key_findings AS report_key_findings, tr.recommendations AS report_recommendations, 
           tr.risk_level AS report_risk_level, tr.risk_assessment_issues AS report_risk_assessment_issues, 
           tr.performance_metrics AS report_performance_metrics
         FROM test_sessions ts
         LEFT JOIN test_reports tr ON ts.id = tr.session_id
         WHERE ts.id = $1`,
        [sessionId]
      );

      if (!session) {
        return NextResponse.json({ error: 'Session not found' }, { status: 404 });
      }

      // Reconstruct report object if it exists
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
        // Remove report-related fields from session object
        delete session.report_id;
        delete session.report_session_id;
        delete session.report_summary;
        delete session.report_key_findings;
        delete session.report_recommendations;
        delete session.report_risk_level;
        delete session.report_risk_assessment_issues;
        delete session.report_performance_metrics;
      }

      // Fetch Test Scenarios
      let { rows: scenarios } = await client.query(
        'SELECT * FROM test_scenarios WHERE session_id = $1 ORDER BY created_at ASC',
        [sessionId]
      );

      // Retry logic to handle potential DB replication delay
      let retries = 5;
      if (scenarios) {
          const hasRunningScenarios = scenarios.some(s => s.status === 'running');

          if (session.status === 'completed' && hasRunningScenarios) {
              console.log(`[Results API] Stale data detected for session ${sessionId}. Retrying...`);
              
              while (retries > 0) {
                  await new Promise(resolve => setTimeout(resolve, 1500)); // Wait for 1.5 seconds

                  const { rows: refetchedScenarios } = await client.query(
                      'SELECT * FROM test_scenarios WHERE session_id = $1 ORDER BY created_at ASC',
                      [sessionId]
                  );

                  scenarios = refetchedScenarios;
                  const stillHasRunning = scenarios?.some(s => s.status === 'running');
                  if (!stillHasRunning) {
                      console.log(`[Results API] Fresh data found for session ${sessionId}.`);
                      break; // Exit loop if data is fresh
                  }
                  
                  retries--;
                  console.log(`[Results API] Data still stale. Retries left: ${retries}`);
              }
          }
      }

      // Filter scenarios based on selected_scenario_ids if available
      if (session.selected_scenario_ids && scenarios) {
        scenarios = scenarios.filter((scenario: any) => session.selected_scenario_ids.includes(scenario.id));
      }

      // Fetch Test Logs
      const { rows: logs } = await client.query(
        'SELECT * FROM test_logs WHERE session_id = $1 ORDER BY timestamp ASC',
        [sessionId]
      );

      // Fetch Scenario Reports
      const { rows: scenarioReports } = await client.query(
        'SELECT * FROM scenario_reports WHERE session_id = $1',
        [sessionId]
      );

      return NextResponse.json({
        success: true,
        data: {
          session,
          scenarios: scenarios || [],
          logs: logs || [],
          report,
          scenarioReports: scenarioReports || [],
        },
      });
    } finally {
      client.release();
    }
  } catch (error) {
    console.error('Error in results API:', error);
    return NextResponse.json(
      { error: 'Failed to fetch test results', details: error instanceof Error ? error.message : 'Unknown error' },
      { status: 500 }
    );
  }
}
