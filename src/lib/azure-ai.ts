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
You are an expert test automation engineer. Your task is to generate a comprehensive set of executable test scenarios based on the provided webpage information.

${existingScenariosText}Page Information:
- Title: ${pageInfo.title}
- URL: ${pageInfo.url}
- Page Features:
  - Has Login Form: ${pageInfo.hasLoginForm}
  - Has Contact Form: ${pageInfo.hasContactForm}
  - Has Search Form: ${pageInfo.hasSearchForm}
  - Number of Forms: ${pageInfo.forms.length}
  - Number of Navigation Links: ${pageInfo.navLinks.length}

Please generate 5-7 test scenarios. Prioritize critical user journeys like authentication, form submissions, and core feature interactions.

**IMPORTANT**: You MUST respond in a valid JSON format. The root object should contain a single key, "scenarios", which is an array of scenario objects. Each scenario object MUST have the following structure and keys:
- "title": (string) A short, descriptive title for the test case. THIS IS REQUIRED AND CANNOT BE EMPTY.
- "description": (string) A brief explanation of what the test case covers. THIS IS REQUIRED AND CANNOT BE EMPTY.
- "priority": (string) The priority of the test, which must be one of 'high', 'medium', or 'low'.
- "category": (string) A relevant category for the test (e.g., 'authentication', 'forms', 'navigation', 'search', 'usability').
- "steps": (array of strings) A list of simple, clear, and executable steps for the test.
- "estimatedTime": (string) A rough estimate of how long the test will take (e.g., "30 seconds", "1 minute").
- "reasoning": (string) A brief justification for why this scenario is important to test.

Example of a single scenario object:
{
  "title": "User Login with Valid Credentials",
  "description": "This test verifies that a user can successfully log in with a correct username and password.",
  "priority": "high",
  "category": "authentication",
  "steps": [
    "Navigate to the login page",
    "Enter a valid username in the username field",
    "Enter a valid password in the password field",
    "Click the 'Login' button",
    "Verify that the user is redirected to the dashboard"
  ],
  "estimatedTime": "45 seconds",
  "reasoning": "Login is a critical path for all authenticated user flows."
}

Now, generate the full JSON response containing the "scenarios" array.
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

  async generateFakerMappings(formData: any): Promise<any> {
    const prompt = `
    You are a data mapping expert for the faker-js library. Your task is to analyze a simplified list of form inputs and map each field to a specific faker-js method.

    Here is the simplified form structure:
    ${JSON.stringify(formData, null, 2)}

    **CRITICAL INSTRUCTIONS**:
    1.  You MUST return a JSON object.
    2.  The keys of the JSON object MUST EXACTLY MATCH the 'label', 'name', or 'placeholder' of the corresponding input. Prioritize the 'label'.
    3.  The value for each key MUST be a JSON object with a 'namespace', 'method', and optional 'options' array.
    4.  For phone numbers, you MUST use the format '##########'.
    5.  If you are uncertain about a field, map it to { "namespace": "lorem", "method": "word" }. DO NOT leave any field unmapped.

    Example Input:
    { "inputs": [ { "label": "First Name", "name": "fname" }, { "label": "Contact Phone", "name": "phone" } ] }

    Example Output:
    {
      "First Name": { "namespace": "person", "method": "firstName" },
      "Contact Phone": { "namespace": "phone", "method": "number", "options": ["##########"] }
    }
    `;

    const response = await this.generateCompletion(prompt, { maxTokens: 2000 });
    
    try {
      return JSON.parse(response);
    } catch (error) {
      console.error('Failed to parse AI response for faker mappings:', response);
      throw new Error('Invalid AI response format for faker mappings');
    }
  }

  async generateFormValidationScenarios(formData: any): Promise<any> {
    const prompt = `
    You are a senior QA automation engineer. Your task is to create a comprehensive set of validation test scenarios for an HTML form.

    Here is the form structure, provided as a JSON object:
    ${JSON.stringify(formData, null, 2)}

    Generate a list of test scenarios to verify its validation rules. You MUST generate the following scenarios:
    1.  An empty submission to check for required field validation.
    2.  Invalid data scenarios for fields with specific formats (like email or phone).
    3.  A happy path scenario with all valid data.

    For each scenario, provide a title, a brief description, and a list of steps. Each step should be an object with an action, target, and value.

    Your final output MUST be a JSON object containing an array named "scenarios".

    Example output:
    {
      "scenarios": [
        {
          "title": "Empty Submission",
          "description": "Tests required field validation by submitting the form with no data.",
          "steps": []
        },
        {
          "title": "Invalid Email Scenario",
          "description": "Tests email format validation by submitting with an invalid email address.",
          "steps": [
            { "action": "fill", "target": "Email Address", "value": "not-an-email" }
          ]
        },
        {
          "title": "Happy Path",
          "description": "Tests the successful submission of the form with all valid data.",
          "steps": [
            { "action": "fill", "target": "First Name", "value": "Jane" },
            { "action": "fill", "target": "Email Address", "value": "jane.doe@example.com" }
          ]
        }
      ]
    }
    `;

    const response = await this.generateCompletion(prompt, { maxTokens: 3500 });
    
    try {
      const parsed = JSON.parse(response);
      if (!parsed.scenarios || !Array.isArray(parsed.scenarios)) {
        throw new Error('Invalid AI response format: "scenarios" array not found.');
      }
      return parsed;
    } catch (error) {
      console.error('Failed to parse AI response for validation scenarios:', response);
      throw new Error('Invalid AI response format for validation scenarios');
    }
  }

  async createWorkflowPlan(userCommand: string, context: any): Promise<any> {
    const prompt = `
    You are an AI Test Automation Orchestrator. Your job is to convert a high-level user command into a structured, step-by-step execution plan in JSON format.

    User Command: "${userCommand}"

    Current Page Context:
    - Is a form visible on the page? ${context.isFormVisible}
    - Visible buttons: [${context.visibleButtons.slice(0, 20).join(', ')}]
    - Visible links: [${context.visibleLinks.slice(0, 20).join(', ')}]

    Available Skills:
    - 'CLICK': Clicks a button, link, or tab. Requires a 'target'.
    - 'NAVIGATE': Go to a specific URL. Requires a 'url'.
    - 'FILL_FORM_HAPPY_PATH': Intelligently analyze and fill a form on the current page with valid data.
    - 'TEST_FORM_VALIDATION': Intelligently run a full validation test suite on a form on the current page.

    Based on the user's command AND the current page context, generate a JSON object containing an array named "plan" of steps.

    **CRITICAL PLANNING RULES**:
    1.  If the user's intent is to add, create, or submit data (e.g., "Add an agent") AND a form is visible (isFormVisible is true), your primary goal is to fill that form. You MUST use the FILL_FORM_HAPPY_PATH or TEST_FORM_VALIDATION skill.
    2.  Do NOT choose to CLICK a button if a form is already visible and the intent is to fill it, even if the button's name matches the user command. The click will happen inside the form-filling skill.
    3.  If a form is NOT visible, your plan should be to CLICK the button or link that would reveal the form.

    Example 1:
    User Command: "Add an agent"
    Current Page Context: { "isFormVisible": false, "visibleButtons": ["Add New Agent", "Delete Agent"] }
    Your Output: {"plan":[{ "skill": "CLICK", "target": "Add New Agent" }]}
    (Rationale: The user wants to add an agent, no form is visible, but an "Add New Agent" button is. The plan is to click the button to reveal the form. The next step will handle filling it.)

    Example 2:
    User Command: "Add an agent"
    Current Page Context: { "isFormVisible": true, "visibleButtons": ["Save Agent", "Cancel"] }
    Your Output: {"plan":[{ "skill": "FILL_FORM_HAPPY_PATH" }]}
    (Rationale: The user wants to add an agent and a form is already visible. The plan is to fill the form directly.)

    Now, generate the plan for the user command and context above.
    `;

    const response = await this.generateCompletion(prompt, { maxTokens: 2000 });
    
    try {
      const parsed = JSON.parse(response);
      if (!parsed.plan || !Array.isArray(parsed.plan)) {
        throw new Error('Invalid AI response format: "plan" array not found.');
      }
      return parsed;
    } catch (error) {
      console.error('Failed to parse AI response for workflow plan:', response);
      throw new Error('Invalid AI response format for workflow plan');
    }
  }

  async generateTestAnalysis(
    testResults: any,
    logs: any[],
    scenarios: any[]
  ): Promise<any> {
    const prompt = `
    You are an expert test analyst. Analyze the following test execution results and provide comprehensive insights.

    Test Results:
    - Status: ${testResults.status}
    - Total Scenarios: ${testResults.totalScenarios}
    - Passed Scenarios: ${testResults.passedScenarios}
    - Failed Scenarios: ${testResults.failedScenarios}

    Please provide:
    1. Executive summary of the test execution
    2. Key findings and patterns
    3. Actionable recommendations
    4. Risk assessment with specific issues
    5. Overall quality score (0-100)

    Respond in JSON format:
    {
      "summary": "Executive summary",
      "keyFindings": ["finding1", "finding2", ...],
      "recommendations": ["recommendation1", "recommendation2", ...],
      "riskAssessment": {
        "level": "low|medium|high",
        "issues": ["issue1", "issue2", ...]
      },
      "qualityScore": number
    }
    `;

    const response = await this.generateCompletion(prompt, { maxTokens: 3000 });
    
    try {
      return JSON.parse(response);
    } catch (error) {
      console.error('Failed to parse AI analysis response:', response);
      throw new Error('Invalid AI response format for analysis');
    }
  }
}

export const azureAIService = new AzureAIService();
