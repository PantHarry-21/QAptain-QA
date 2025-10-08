import { NextRequest, NextResponse } from 'next/server';
import { supabase } from '@/lib/supabase';
import { TestSession, TestScenario, TestLog, TestReport } from '@/lib/supabase';

export async function GET(
  request: NextRequest,
  { params }: { params: { sessionId: string } }
) {
  const { sessionId } = await params;

  if (!sessionId) {
    return NextResponse.json({ error: 'Session ID is required' }, { status: 400 });
  }

  try {
    // Fetch Test Session
    const { data: session, error: sessionError } = await supabase
      .from('test_sessions')
      .select('*, test_reports(*), selected_scenario_ids') // Select session and join with test_reports
      .eq('id', sessionId)
      .single();

    if (sessionError) {
      console.error('Error fetching session:', sessionError);
      return NextResponse.json({ error: 'Session not found' }, { status: 404 });
    }

    // Fetch Test Scenarios
    let { data: scenarios, error: scenariosError } = await supabase
      .from('test_scenarios')
      .select('*')
      .eq('session_id', sessionId)
      .order('created_at', { ascending: true });

    if (scenariosError) {
      console.error('Error fetching scenarios:', scenariosError);
      scenarios = []; // Ensure scenarios is an empty array on error
    }

    // Retry logic to handle potential DB replication delay
    let retries = 5;
    if (scenarios) {
        const hasRunningScenarios = scenarios.some(s => s.status === 'running');

        if (session.status === 'completed' && hasRunningScenarios) {
            console.log(`[Results API] Stale data detected for session ${sessionId}. Retrying...`);
            
            while (retries > 0) {
                await new Promise(resolve => setTimeout(resolve, 1500)); // Wait for 1.5 seconds

                const { data: refetchedScenarios, error: refetchError } = await supabase
                    .from('test_scenarios')
                    .select('*')
                    .eq('session_id', sessionId)
                    .order('created_at', { ascending: true });

                if (refetchError) {
                    break; // If refetch fails, break and use the data we have
                }

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
      scenarios = scenarios.filter(scenario => session.selected_scenario_ids.includes(scenario.id));
    }

    // Fetch Test Logs
    const { data: logs, error: logsError } = await supabase
      .from('test_logs')
      .select('*')
      .eq('session_id', sessionId)
      .order('timestamp', { ascending: true });

    if (logsError) {
      console.error('Error fetching logs:', logsError);
      // Continue even if logs fail
    }

    // Fetch Scenario Reports
    const { data: scenarioReports, error: scenarioReportsError } = await supabase
      .from('scenario_reports')
      .select('*')
      .eq('session_id', sessionId);

    if (scenarioReportsError) {
      console.error('Error fetching scenario reports:', scenarioReportsError);
      // Continue even if reports fail
    }

    // The report is already joined with the session, so it's in session.test_reports
    const report = session.test_reports?.[0] || null; // Assuming one report per session
    delete session.test_reports; // Remove the joined report from the session object

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
  } catch (error) {
    console.error('Error in results API:', error);
    return NextResponse.json(
      { error: 'Failed to fetch test results', details: error instanceof Error ? error.message : 'Unknown error' },
      { status: 500 }
    );
  }
}
