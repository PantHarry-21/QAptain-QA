import { NextRequest, NextResponse } from 'next/server';
import pool from '@/lib/db';
import { getServerSession } from 'next-auth';
import { getAuthOptions } from '@/lib/auth';
import { v4 as uuidv4 } from 'uuid';

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

    const offset = (page - 1) * limit;

    const client = await pool.connect();
    try {
      // Whitelist sort column to avoid injection
      const allowedSortColumns = new Set(["created_at", "updated_at", "status"]);
      const safeSortBy = allowedSortColumns.has(sortBy) ? sortBy : "created_at";

      let countQuery = "SELECT COUNT(*) FROM test_sessions WHERE user_id = $1";
      let dataQuery = "SELECT * FROM test_sessions WHERE user_id = $1";
      const queryParams: any[] = [session.user.id];
      let paramIndex = 2;

      if (searchQuery) {
        countQuery += ` AND (url ILIKE $${paramIndex} OR id::text ILIKE $${paramIndex})`;
        dataQuery += ` AND (url ILIKE $${paramIndex} OR id::text ILIKE $${paramIndex})`;
        queryParams.push(`%${searchQuery}%`);
        paramIndex++;
      }

      dataQuery += ` ORDER BY ${safeSortBy} ${order.toUpperCase()} LIMIT $${paramIndex} OFFSET $${paramIndex + 1}`;
      queryParams.push(limit, offset);

      const { rows: countRows } = await client.query(countQuery, queryParams.slice(0, paramIndex - 1));
      const total = parseInt(countRows[0].count, 10);

      const { rows: data } = await client.query(dataQuery, queryParams);

      return NextResponse.json({
        success: true,
        data,
        pagination: {
          total,
          page,
          limit,
          totalPages: Math.ceil(total / limit),
        },
      });
    } finally {
      client.release();
    }
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

    const client = await pool.connect();
    try {
      const { rows: [insertedSession] } = await client.query(
        `INSERT INTO test_sessions (
           id, user_id, url, status,
           total_scenarios, passed_scenarios, failed_scenarios,
           total_steps, passed_steps, failed_steps,
           created_at, updated_at
         )
         VALUES (
           $1, $2, $3, $4,
           $5, $6, $7,
           $8, $9, $10,
           $11, $12
         )
         RETURNING *`,
        [
          newSession.id,
          newSession.user_id,
          newSession.url,
          newSession.status,
          newSession.total_scenarios,
          newSession.passed_scenarios,
          newSession.failed_scenarios,
          newSession.total_steps,
          newSession.passed_steps,
          newSession.failed_steps,
          newSession.created_at,
          newSession.updated_at,
        ]
      );

      const scenarioInserts = scenarios.map((scenario: any) => {
        const scenarioId = uuidv4();
        return client.query(
          `INSERT INTO test_scenarios (
             id, session_id, title, description,
             steps, status, created_at, updated_at
           )
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
          [
            scenarioId,
            sessionId,
            scenario.title,
            scenario.description || "",
            scenario.steps,
            "pending",
            new Date().toISOString(),
            new Date().toISOString(),
          ]
        );
      });

      await Promise.all(scenarioInserts);

      return NextResponse.json({ success: true, session: insertedSession });
    } finally {
      client.release();
    }
  } catch (error) {
    console.error('Error creating test session:', error);
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json(
      { error: 'Failed to create test session', details: errorMessage },
      { status: 500 }
    );
  }
}