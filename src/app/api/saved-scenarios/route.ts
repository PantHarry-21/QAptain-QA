import { NextRequest, NextResponse } from 'next/server';
import { databaseService } from '@/lib/database';
import { openAIService } from '@/lib/openai';

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
 * POST handler to create a new saved scenario.
 * Can either interpret a user story to generate steps or accept a pre-defined title and user story.
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { user_story, pageContext, title: providedTitle, steps: providedSteps } = body;

    if (!user_story) {
      return NextResponse.json({ error: 'user_story is required' }, { status: 400 });
    }

    let steps = providedSteps;
    if (!steps || steps.length === 0) {
      const interpretation = await openAIService.interpretScenario(user_story, pageContext || {});
      steps = interpretation.steps;
    }

    if (!steps || steps.length === 0) {
      return NextResponse.json({ error: "The AI couldn't determine any steps from your description." }, { status: 400 });
    }

    const title = providedTitle || user_story.split('\n')[0];

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

/**
 * DELETE handler to remove a saved scenario.
 */
export async function DELETE(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const id = searchParams.get('id');

    if (!id) {
      return NextResponse.json({ error: 'Scenario ID is required' }, { status: 400 });
    }

    await databaseService.deleteSavedScenario(id);

    return NextResponse.json({ success: true, message: 'Scenario deleted successfully.' });
  } catch (error) {
    console.error('Error deleting saved scenario:', error);
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json(
      { error: 'Failed to delete saved scenario', details: errorMessage },
      { status: 500 }
    );
  }
}