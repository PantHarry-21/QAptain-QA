import { NextRequest, NextResponse } from 'next/server';
import { databaseService } from '@/lib/database';
import { azureAIService } from '@/lib/azure-ai';

/**
 * GET handler to fetch all saved scenarios.
 */
export async function GET() {
  try {
    const savedScenarios = await databaseService.getAllSavedScenarios();
    return NextResponse.json({ success: true, data: savedScenarios });
  } catch (error) {
    console.error('Error fetching saved scenarios:', error);
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json(
      { error: 'Failed to fetch saved scenarios', details: errorMessage },
      { status: 500 }
    );
  }
}

/**
 * POST handler to create a new saved scenario by interpreting a user story.
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { user_story, pageContext } = body;

    if (!user_story) {
      return NextResponse.json({ error: 'user_story is required' }, { status: 400 });
    }

    const { steps } = await azureAIService.interpretScenario(user_story, pageContext || {});

    if (!steps || steps.length === 0) {
      return NextResponse.json({ error: "The AI couldn't determine any steps from your description." }, { status: 400 });
    }

    const title = user_story.split('\n')[0];

    const newScenario = await databaseService.createSavedScenario({ title, user_story, steps });

    if (!newScenario) {
      return NextResponse.json({ success: true, message: 'Scenario already exists.', data: null });
    }

    return NextResponse.json({ success: true, data: newScenario }, { status: 201 });
  } catch (error) {
    console.error('Error creating saved scenario:', error);
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json(
      { error: 'Failed to create saved scenario', details: errorMessage },
      { status: 500 }
    );
  }
}

/**
 * PUT handler to update an existing saved scenario.
 */
export async function PUT(request: NextRequest) {
  try {
    const body = await request.json();
    const { id, steps, title, user_story } = body;

    if (!id || !steps) {
      return NextResponse.json({ error: 'Scenario ID and steps are required' }, { status: 400 });
    }

    const updatedScenario = await databaseService.updateSavedScenario(id, { steps, title, user_story });

    if (!updatedScenario) {
      return NextResponse.json({ error: 'Failed to update or find the scenario' }, { status: 404 });
    }

    return NextResponse.json({ success: true, data: updatedScenario });
  } catch (error) {
    console.error('Error updating saved scenario:', error);
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json(
      { error: 'Failed to update saved scenario', details: errorMessage },
      { status: 500 }
    );
  }
}