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
      .select('*, test_reports(*)') // Select session and join with test_reports
      .eq('id', sessionId)
      .single();

    if (sessionError) {
      console.error('Error fetching session:', sessionError);
      return NextResponse.json({ error: 'Session not found' }, { status: 404 });
    }

    // Fetch Test Scenarios
    const { data: scenarios, error: scenariosError } = await supabase
      .from('test_scenarios')
      .select('*')
      .eq('session_id', sessionId)
      .order('created_at', { ascending: true });

    if (scenariosError) {
      console.error('Error fetching scenarios:', scenariosError);
      // Continue even if scenarios fail, as session data might still be useful
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
