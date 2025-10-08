import { NextRequest, NextResponse } from 'next/server';
import { databaseService } from '@/lib/database';

/**
 * GET handler to fetch saved scenarios for a given URL.
 */
export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const url = searchParams.get('url');

    if (!url) {
      return NextResponse.json({ error: 'URL query parameter is required' }, { status: 400 });
    }

    const savedScenarios = await databaseService.getSavedScenariosByUrl(url);
    
    return NextResponse.json({ success: true, data: savedScenarios });

  } catch (error) {
    console.error('Error fetching saved scenarios:', error);
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json(
      { 
        error: 'Failed to fetch saved scenarios',
        details: errorMessage
      },
      { status: 500 }
    );
  }
}

/**
 * POST handler to create a new saved scenario.
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { url, title, user_story, steps } = body;

    if (!url || !title || !user_story || !steps) {
      return NextResponse.json({ error: 'url, title, user_story, and steps are required' }, { status: 400 });
    }

    const newScenario = await databaseService.createSavedScenario({
      url,
      title,
      user_story,
      steps,
    });

    // If the scenario already existed, createSavedScenario returns null
    if (!newScenario) {
        return NextResponse.json({ success: true, message: 'Scenario already exists.', data: null });
    }

    return NextResponse.json({ success: true, data: newScenario }, { status: 201 });

  } catch (error) {
    console.error('Error creating saved scenario:', error);
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json(
      { 
        error: 'Failed to create saved scenario',
        details: errorMessage
      },
      { status: 500 }
    );
  }
}
