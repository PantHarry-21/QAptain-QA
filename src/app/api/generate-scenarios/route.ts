import { NextRequest, NextResponse } from 'next/server';
import { azureAIService } from '@/lib/azure-ai';

/**
 * POST handler to generate a list of test scenarios from a web page's context.
 */
export async function POST(request: NextRequest) {
  try {
    const { pageContext } = await request.json();

    if (!pageContext) {
      return NextResponse.json({ error: 'pageContext is required' }, { status: 400 });
    }

    // Call the new AI service to generate scenarios
    const result = await azureAIService.generateScenarios(pageContext);

    return NextResponse.json(result);

  } catch (error) {
    console.error('Generate Scenarios Error:', error);
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json(
      { 
        error: 'Failed to generate scenarios',
        details: errorMessage
      },
      { status: 500 }
    );
  }
}
