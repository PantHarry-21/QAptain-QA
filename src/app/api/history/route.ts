import { NextRequest, NextResponse } from 'next/server';
import { databaseService } from '@/lib/database';
import { getServerSession } from 'next-auth';
import { getAuthOptions } from '@/lib/auth';
import { getNeonClient, isNeonAvailable } from '@/lib/neon';
import { supabase } from '@/lib/supabase';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  try {
    const session = await getServerSession(getAuthOptions());
    if (!session || !session.user || !session.user.id) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { searchParams } = new URL(request.url);
    const page = parseInt(searchParams.get('page') || '1', 10);
    const limit = parseInt(searchParams.get('limit') || '10', 10);
    const sortBy = searchParams.get('sortBy') || 'created_at';
    const order = searchParams.get('order') || 'desc';
    const searchQuery = searchParams.get('search') || '';

    const from = (page - 1) * limit;
    const to = from + limit - 1;

    // Use the appropriate database client
    const db = isNeonAvailable() ? getNeonClient() : supabase;
    if (!db) {
      return NextResponse.json({ error: 'Database not available' }, { status: 500 });
    }

    let query = db
      .from('test_sessions')
      .select('*', { count: 'exact' })
      .eq('user_id', session.user.id);

    if (searchQuery) {
      query = query.or(`name.ilike.%${searchQuery}%,id::text.eq.${searchQuery}`);
    }

    query = query.order(sortBy, { ascending: order === 'asc' });
    query = query.range(from, to);

    const { data, error, count } = await query;

    if (error) throw error;

    return NextResponse.json({
      success: true,
      data,
      pagination: {
        total: count,
        page,
        limit,
        totalPages: Math.ceil((count || 0) / limit),
      },
    });

  } catch (error) {
    console.error('Error fetching test history:', error);
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json(
      { error: 'Failed to fetch test history', details: errorMessage },
      { status: 500 }
    );
  }
}

export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(getAuthOptions());
    if (!session || !session.user || !session.user.id) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { sessionId, url, scenarios } = await request.json();

    if (!sessionId || !url || !scenarios) {
      return NextResponse.json({ error: 'sessionId, url, and scenarios are required' }, { status: 400 });
    }

    // Use database service which handles Neon/Supabase switching
    const newSession = await databaseService.createTestSession({
      id: sessionId,
      user_id: session.user.id,
      url: url,
      status: 'pending',
      total_scenarios: scenarios.length,
      passed_scenarios: 0,
      failed_scenarios: 0,
      total_steps: scenarios.reduce((sum: number, scenario: any) => sum + scenario.steps.length, 0),
      passed_steps: 0,
      failed_steps: 0,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    if (!newSession) {
      throw new Error('Failed to create test session');
    }

    const newScenarios = scenarios.map((scenario: any) => ({
      id: scenario.id,
      session_id: sessionId,
      title: scenario.title,
      description: scenario.description || '',
      steps: scenario.steps,
      status: 'pending',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }));

    // Use database service for batch insert
    const db = isNeonAvailable() ? getNeonClient() : supabase;
    if (!db) {
      throw new Error('Database not available');
    }

    const { error: scenariosError } = await db
      .from('test_scenarios')
      .insert(newScenarios);

    if (scenariosError) throw new Error(scenariosError.message);

    return NextResponse.json({ success: true, session: newSession });

  } catch (error) {
    console.error('Error creating test session:', error);
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json(
      { error: 'Failed to create test session', details: errorMessage },
      { status: 500 }
    );
  }
}