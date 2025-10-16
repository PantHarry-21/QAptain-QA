import { NextRequest, NextResponse } from 'next/server';
import { openAIService } from '@/lib/openai';

export async function POST(request: NextRequest) {
  try {
    const { description, url } = await request.json();

    if (!description) {
      return NextResponse.json({ error: 'Scenario description is required' }, { status: 400 });
    }

    // Note: The pageContext is empty because this legacy route does not provide it.
    // For better results, the client should provide a full page context.
    const pageContext = { visibleButtons: [], visibleLinks: [], formInputs: [] };

    const result = await openAIService.interpretScenario(description, pageContext);

    return NextResponse.json({
      success: true,
      data: result,
    });

  } catch (error) {
    console.error('AI Step Generation Error:', error);
    return NextResponse.json(
      {
        error: 'Failed to generate test steps with AI',
        details: error instanceof Error ? error.message : 'Unknown error'
      },
      { status: 500 }
    );
  }
}
