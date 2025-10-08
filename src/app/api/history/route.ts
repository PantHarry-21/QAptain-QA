import { NextRequest, NextResponse } from 'next/server';
import { supabase } from '@/lib/supabase';

export async function GET(request: NextRequest) {
  try {
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
      .select('*', { count: 'exact' });

    // Apply search query if it exists
    if (searchQuery) {
      // Assuming 'name' is a column you want to search on. 
      // The user can provide a name for a test session.
      // Also searching by id.
      query = query.or(`name.ilike.%${searchQuery}%,id::text.eq.${searchQuery}`);
    }

    // Apply sorting
    query = query.order(sortBy, { ascending: order === 'asc' });

    // Apply pagination
    query = query.range(from, to);

    const { data, error, count } = await query;

    if (error) {
      throw error;
    }

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
      { 
        error: 'Failed to fetch test history',
        details: errorMessage
      },
      { status: 500 }
    );
  }
}

export async function POST(request: NextRequest) {
  try {
    const { sessionId, url, scenarios } = await request.json();

    if (!sessionId || !url || !scenarios) {
      return NextResponse.json({ error: 'sessionId, url, and scenarios are required' }, { status: 400 });
    }

    const newSession = {
      id: sessionId,
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

    if (error) {
      throw new Error(error.message);
    }

    // Insert scenarios
    const newScenarios = scenarios.map((scenario: any) => ({
      id: scenario.id,
      session_id: sessionId,
      title: scenario.title,
      description: scenario.description || '',
      priority: scenario.priority || 'medium',
      category: scenario.category || 'custom',
      steps: scenario.steps,
      estimated_time: scenario.estimatedTime || 'unknown',
      status: 'pending',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      is_custom: true,
    }));

    const { error: scenariosError } = await supabase
      .from('test_scenarios')
      .insert(newScenarios);

    if (scenariosError) {
      throw new Error(scenariosError.message);
    }

    return NextResponse.json({ success: true, session: data });

  } catch (error) {
    console.error('Error creating test session:', error);
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json(
      { 
        error: 'Failed to create test session',
        details: errorMessage
      },
      { status: 500 }
    );
  }
}