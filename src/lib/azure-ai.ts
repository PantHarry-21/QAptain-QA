import OpenAI from 'openai';

// Note: This service is now configured to use the standard OpenAI API.
// OpenAI configuration
const apiKey = process.env.OPENAI_API_KEY!;
const modelName = process.env.OPENAI_MODEL_NAME || 'gpt-4-turbo';
const scenarioGenerationModelName = process.env.SCENARIO_GENERATION_MODEL_NAME || modelName;

if (!apiKey) {
  throw new Error('Missing OPENAI_API_KEY environment variable');
}

const client = new OpenAI({
  apiKey: apiKey,
});

export interface AIServiceConfig {
  temperature?: number;
  maxTokens?: number;
  topP?: number;
  frequencyPenalty?: number;
  presencePenalty?: number;
}

export class AzureAIService {
  private defaultConfig: AIServiceConfig = {
    temperature: 0.7,
    maxTokens: 2000,
    topP: 0.9,
    frequencyPenalty: 0,
    presencePenalty: 0
  };

  async generateCompletion(
    prompt: string,
    config: Partial<AIServiceConfig> = {}
  ): Promise<string> {
    const finalConfig = { ...this.defaultConfig, ...config };
    
    try {
      const completion = await client.chat.completions.create({
        model: scenarioGenerationModelName,
        messages: [
          { role: 'system', content: 'You are a helpful AI assistant designed to output JSON.' },
          { role: 'user', content: prompt }
        ],
        response_format: { type: "json_object" },
        max_tokens: finalConfig.maxTokens,
        temperature: finalConfig.temperature,
        top_p: finalConfig.topP,
        frequency_penalty: finalConfig.frequencyPenalty,
        presence_penalty: finalConfig.presencePenalty,
      });

      return completion.choices[0]?.message?.content || '';
    } catch (error) {
      console.error('OpenAI API Error:', error);
      throw new Error(`Failed to generate AI completion: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
  }

  async analyzeWebPage(pageInfo: any): Promise<{
    summary: string;
    keyElements: string[];
    suggestedTests: string[];
    complexity: 'simple' | 'medium' | 'complex';
  }> {
    const prompt = `
You are an expert web testing AI assistant. Analyze the following webpage information and provide insights for test automation.

Page Information:
- Title: ${pageInfo.title}
- URL: ${pageInfo.url}
- Description: ${pageInfo.metaDescription}
- Forms: ${JSON.stringify(pageInfo.forms, null, 2)}
- Navigation Links: ${pageInfo.navLinks.length} found
- Buttons: ${pageInfo.buttons.length} found
- Links: ${pageInfo.links.length} found
- Images: ${pageInfo.images.length} found
- Headings: ${pageInfo.headings.length} found
- Has Login Form: ${pageInfo.hasLoginForm}
- Has Contact Form: ${pageInfo.hasContactForm}
- Has Search Form: ${pageInfo.hasSearchForm}

Please provide:
1. A brief summary of what this webpage appears to be
2. Key interactive elements that should be tested
3. Suggested test scenarios that would be valuable
4. Complexity assessment (simple/medium/complex)

Respond in JSON format:
{
  "summary": "Brief description of the webpage",
  "keyElements": ["element1", "element2", ...],
  "suggestedTests": ["test1", "test2", ...],
  "complexity": "simple|medium|complex"
}
`;

    const response = await this.generateCompletion(prompt);
    
    try {
      return JSON.parse(response);
    } catch (error) {
      console.error('Failed to parse AI response:', response);
      throw new Error('Invalid AI response format');
    }
  }

  async generateTestScenarios(
    pageInfo: any,
    existingScenarios: string[] = []
  ): Promise<Array<{
    title: string;
    description: string;
    priority: 'high' | 'medium' | 'low';
    category: string;
    steps: string[];
    estimatedTime: string;
    reasoning: string;
  }>> {
    const existingScenariosText = existingScenarios.length > 0 
      ? `Existing scenarios to avoid duplicating:\n${existingScenarios.join('\n')}\n\n`
      : '';

    const prompt = `
You are an expert test automation engineer. Generate comprehensive, executable test scenarios for the following webpage.

${existingScenariosText}Page Information:
- Title: ${pageInfo.title}
- URL: ${pageInfo.url}
- Description: ${pageInfo.metaDescription}
- Forms: ${JSON.stringify(pageInfo.forms, null, 2)}
- Navigation Links: ${pageInfo.navLinks.length} found
- Buttons: ${pageInfo.buttons.length} found

IMPORTANT: You MUST generate steps that conform ONLY to the following allowed actions. Use the exact phrasing and structure provided.

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

Generate 5-7 test scenarios that would be most valuable for this webpage. Each scenario should:
1. Be specific and actionable, using ONLY the allowed step actions.
2. Prioritize critical user journeys like login, search, or form submissions.
3. Include clear, step-by-step instructions.

Do NOT generate steps for performance, SEO, accessibility, or other non-functional tests. Only generate steps that can be executed through direct browser interaction based on the allowed actions above.

Respond in JSON format:
{
  "scenarios": [
    {
      "title": "Scenario title",
      "description": "Brief description of what this test verifies",
      "priority": "high|medium|low",
      "category": "authentication|forms|navigation|usability",
      "steps": ["Step 1 using allowed actions", "Step 2 using allowed actions", ...],
      "estimatedTime": "30 seconds|1 minute|2 minutes",
      "reasoning": "Why this scenario is important for testing the web application's functionality."
    }
  ]
}
`;

    const response = await this.generateCompletion(prompt, { maxTokens: 3000 });
    
    try {
      const parsed = JSON.parse(response);
      return parsed.scenarios || [];
    } catch (error) {
      console.error('Failed to parse AI scenarios response:', response);
      throw new Error('Invalid AI response format for scenarios');
    }
  }

  async translateNaturalLanguageToSelenium(
    scenarios: Array<{
      title: string;
      steps: string[];
    }>,
    url: string,
    language: 'javascript' | 'python' = 'javascript'
  ): Promise<Array<{
    scenarioId: string;
    scenarioTitle: string;
    script: string;
    dependencies: string[];
    setupCode: string;
    teardownCode: string;
    explanation: string;
  }>> {
    const scenariosText = scenarios.map(s => 
      `Title: ${s.title}\nSteps:\n${s.steps.map((step, i) => `${i + 1}. ${step}`).join('\n')}`
    ).join('\n\n---\n\n');

    const prompt = `
You are an expert Selenium test automation engineer. Convert the following natural language test scenarios into executable Selenium WebDriver scripts.

Target URL: ${url}
Programming Language: ${language}

Test Scenarios:
${scenariosText}

For each scenario, generate:
1. Complete, executable Selenium WebDriver code
2. All necessary imports and dependencies
3. Setup and teardown code
4. Clear comments explaining each step
5. Proper error handling and waits

The code should be production-ready and follow best practices.

Respond in JSON format:
{
  "scripts": [
    {
      "scenarioId": "unique_identifier",
      "scenarioTitle": "Scenario title",
      "script": "complete executable code",
      "dependencies": ["dependency1", "dependency2"],
      "setupCode": "setup code snippet",
      "teardownCode": "teardown code snippet",
      "explanation": "Brief explanation of how the script works"
    }
  ]
}
`;

    const response = await this.generateCompletion(prompt, { maxTokens: 4000 });
    
    try {
      const parsed = JSON.parse(response);
      return parsed.scripts || [];
    } catch (error) {
      console.error('Failed to parse AI translation response:', response);
      throw new Error('Invalid AI response format for translation');
    }
  }

  async generateTestAnalysis(
    testResults: any,
    logs: any[],
    scenarios: any[]
  ): Promise<{
    summary: string;
    keyFindings: string[];
    recommendations: string[];
    riskAssessment: {
      level: 'low' | 'medium' | 'high';
      issues: string[];
    };
    performanceMetrics: {
      averageStepTime: number;
      fastestStep: string;
      slowestStep: string;
      totalExecutionTime: number;
    };
    qualityScore: number;
  }> {
    const prompt = `
You are an expert test analyst. Analyze the following test execution results and provide comprehensive insights.

Test Results:
- Status: ${testResults.status}
- Total Scenarios: ${testResults.totalScenarios}
- Passed Scenarios: ${testResults.passedScenarios}
- Failed Scenarios: ${testResults.failedScenarios}
- Total Steps: ${testResults.totalSteps}
- Passed Steps: ${testResults.passedSteps}
- Failed Steps: ${testResults.failedSteps}
- Duration: ${testResults.duration}ms

Sample Logs:
${logs.slice(0, 10).map(log => `[${log.level}] ${log.message}`).join('\n')}

Failed Scenarios:
${scenarios.filter(s => s.status === 'failed').map(s => `- ${s.title}`).join('\n')}

Please provide:
1. Executive summary of the test execution
2. Key findings and patterns
3. Actionable recommendations
4. Risk assessment with specific issues
5. Performance analysis
6. Overall quality score (0-100)

Respond in JSON format:
{
  "summary": "Executive summary",
  "keyFindings": ["finding1", "finding2", ...],
  "recommendations": ["recommendation1", "recommendation2", ...],
  "riskAssessment": {
    "level": "low|medium|high",
    "issues": ["issue1", "issue2", ...]
  },
  "performanceMetrics": {
    "averageStepTime": number,
    "fastestStep": "step description",
    "slowestStep": "step description",
    "totalExecutionTime": number
  },
  "qualityScore": number
}
`;

    const response = await this.generateCompletion(prompt, { maxTokens: 3000 });
    
    try {
      const parsed = JSON.parse(response);
      return parsed;
    } catch (error) {
      console.error('Failed to parse AI analysis response:', response);
      throw new Error('Invalid AI response format for analysis');
    }
  }

  async analyzeScenario(
    scenario: any,
    logs: any[]
  ): Promise<{
    summary: string;
    issues: string[];
    recommendations: string[];
  }> {
    const scenarioLogs = logs.filter(log => log.scenario_id === scenario.id);
    const prompt = `
You are an expert test analyst. Analyze the following test scenario execution and provide insights.

Scenario Details:
- Title: ${scenario.title}
- Description: ${scenario.description}
- Status: ${scenario.status}
- Duration: ${scenario.duration}ms
- Steps:
${scenario.steps.map((step: string) => `- ${step}`).join('\n')}

Logs for this scenario:
${scenarioLogs.map(log => `[${log.level}] ${log.message}`).join('\n')}

Please provide:
1. A brief summary of the scenario execution.
2. Any issues or errors that occurred.
3. Actionable recommendations for improvement, if any.

Respond in JSON format:
{
  "summary": "Brief summary of the scenario execution.",
  "issues": ["issue1", "issue2", ...],
  "recommendations": ["recommendation1", "recommendation2", ...]
}
`;

    const response = await this.generateCompletion(prompt);

    try {
      return JSON.parse(response);
    } catch (error) {
      console.error('Failed to parse AI scenario analysis response:', response);
      throw new Error('Invalid AI response format for scenario analysis');
    }
  }
}

export const azureAIService = new AzureAIService();
