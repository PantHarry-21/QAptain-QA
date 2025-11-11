import { NextRequest, NextResponse } from 'next/server';
import { supabase } from '@/lib/supabase';
import { getServerSession } from 'next-auth';
import { authOptions } from '../auth/[...nextauth]/route';

export async function GET(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
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

    let query = supabase
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
    const session = await getServerSession(authOptions);
    if (!session || !session.user || !session.user.id) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { sessionId, url, scenarios } = await request.json();

    if (!sessionId || !url || !scenarios) {
      return NextResponse.json({ error: 'sessionId, url, and scenarios are required' }, { status: 400 });
    }

    const newSession = {
      id: sessionId,
      user_id: session.user.id, // Associate with the logged-in user
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
    };

    const { data, error } = await supabase
      .from('test_sessions')
      .insert([newSession])
      .select()
      .single();

    if (error) throw new Error(error.message);

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

    const { error: scenariosError } = await supabase
      .from('test_scenarios')
      .insert(newScenarios);

    if (scenariosError) throw new Error(scenariosError.message);

    return NextResponse.json({ success: true, session: data });

  } catch (error) {
    console.error('Error creating test session:', error);
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json(
      { error: 'Failed to create test session', details: errorMessage },
      { status: 500 }
    );
  }
}