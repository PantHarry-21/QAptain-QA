
import { NextRequest, NextResponse } from 'next/server';
import { azureAIService } from '@/lib/azure-ai';

export async function POST(request: NextRequest) {
  try {
    const { description, url } = await request.json();

    if (!description) {
      return NextResponse.json({ error: 'Scenario description is required' }, { status: 400 });
    }

    const prompt = `
You are an expert test automation engineer. Convert the following natural language description of a test scenario into a series of executable steps for a Selenium-based test executor.

The user wants to test the following scenario:
"${description}"

The target URL for the test is: ${url}

You MUST generate steps that conform ONLY to the following allowed actions. Use the exact phrasing and structure provided.

Allowed Step Actions:
- "Navigate to the homepage"
- "Navigate to the login page"
- "Click the button with text \"[button_text]\""
- "Click the link with text \"[link_text]\""
- "Enter \"[text_to_enter]\" into the input field with placeholder \"[placeholder_text]\""
- "Enter \"[text_to_enter]\" into the input field with name \"[name_attribute]\""
- "Verify the page title contains \"[text_to_verify]\""
- "Verify the page contains the text \"[text_to_verify]\""
- "Wait for [number] seconds"

Based on the user's description, generate a sequence of steps using ONLY the allowed actions. Be precise and ensure the steps are logical and follow a clear sequence.

Respond in JSON format with a single array of strings called "steps":
{
  "steps": [
    "Step 1 using allowed actions",
    "Step 2 using allowed actions",
    ...
  ]
}
`;

    const response = await azureAIService.generateCompletion(prompt, { maxTokens: 1000 });
    
    try {
      const parsed = JSON.parse(response);
      if (!parsed.steps || !Array.isArray(parsed.steps)) {
        throw new Error('Invalid AI response format: "steps" array not found.');
      }
      return NextResponse.json({
        success: true,
        data: {
          steps: parsed.steps,
        },
      });
    } catch (error) {
      console.error('Failed to parse AI response for step generation:', response);
      throw new Error('Invalid AI response format');
    }

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
