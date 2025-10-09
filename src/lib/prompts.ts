/**
 * @fileoverview
 * This file contains all the prompt templates for the OpenAIService.
 * Centralizing prompts here makes the main service file cleaner and easier to manage.
 */

// --- Type Definitions ---

interface PageContext {
  visibleButtons?: string[];
  visibleLinks?: string[];
  formInputs?: { label?: string; name?: string; placeholder?: string }[];
}

interface Scenario {
  title: string;
  description: string;
  status: 'passed' | 'failed';
  duration: number;
  steps: string[];
}

interface TestLog {
  level: string;
  message: string;
}

interface TestResults {
  status: string;
  totalScenarios: number;
  passedScenarios: number;
  failedScenarios: number;
}

// --- Prompts Object ---

export const prompts = {
  /**
   * Prompt to interpret a user's natural language story into executable steps.
   */
  interpretScenario: (userStory: string, pageContext: PageContext) => `
    You are an expert test automation engineer. Your task is to convert a user's natural language instructions into a precise, step-by-step test script formatted as a JSON object.

    User Story: "${userStory}"

    Page Context (Visible Elements):
    - Buttons: [${pageContext.visibleButtons?.join(", ") || "None"}]
    - Links: [${pageContext.visibleLinks?.join(", ") || "None"}]
    - Inputs/Labels: [${pageContext.formInputs
        ?.map((i: any) => i.label || i.name || i.placeholder)
        .join(", ") || "None"}]

    **CRITICAL INSTRUCTIONS:**
    1.  **Output Format:** You MUST return a single JSON object with one key: "steps". The value MUST be an array of strings.
    2.  **Atomicity:** Each string in the array MUST be a single, precise, executable command. Do NOT combine actions into one step.
    3.  **Completeness:** You MUST NOT generate incomplete or broken commands like "Click the" or "Fill". Every command must have a valid target and value.
    4.  **Command Structure:** You MUST use the following command formats ONLY:
        - 
Navigate to [URL]
 (Use ONLY for full URLs)
        - 
Click the "[button name, link text, or tab name]"
 (Use for ANY clickable element on the current page)
        - 
Fill "[value]" into the "[input label, name, or placeholder]"
        - 
Select the "[option]" option in the "[select field label or name]"
        - 
Verify that the page contains "[text to verify]"
    5.  **Data Extraction:**
        -   Pay close attention to data provided in the user story.
        -   It can be in formats like 
(Email: value)
, 
username: value
, 
Key : value
, or 
with password "value"
.
        -   If a user provides only partial credentials (e.g., just an email), generate a 
Fill
 step for that information only. Do NOT invent missing credentials.
    6.  **Implied Form Filling:**
        -   If the user story mentions adding, creating, or submitting something with "details" or "data" but does not provide the data (e.g., "add an agent with relatable details"), you MUST generate 
Fill
 commands for all relevant form inputs found in the Page Context.
        -   You should use realistic but clearly fake data (e.g., "John Doe", "test@example.com").
        -   After filling the form, you MUST generate a 
Click
 step for the submission button (e.g., "Submit", "Save", "Add").
    7.  **Action Choice:**
        -   Use 
Click the
 for on-page elements like tabs, buttons, and links.
        -   Use 
Navigate to
 ONLY for navigating to a new URL. For example, "go to agents tab" should be 
Click the "agents tab"
.
    8.  **No Placeholders:** You MUST NOT use placeholder values like '[URL]' or 'the specified URL'. If a valid URL is not provided in the user story, do not generate a 'Navigate' command.
    9.  **Search Workflow:** For search actions, the correct workflow is to first \`Fill\` the search term into a search input, and then \`Press "Enter"\`. Do NOT generate a step to click a search button.

    ---
    **EXAMPLES:**

    **Example 1: The user's failing case**
    User Story: "Sign in using Email : himanshu.pant@tynybay. After logging in, go to agents tab and add an agent with relatable details, after adding the agent, verify that it is added in the list"
    Page Context: { "formInputs": [{ "label": "Email" }, { "label": "Password" }, { "label": "Agent Name" }], "visibleButtons": ["Login", "Add Agent", "Save"] }
    Expected Output:
    {
      "steps": [
        "Fill \"himanshu.pant@tynybay\" into the \"Email\"",
        "Click the \"Login\" button",
        "Click the \"agents tab\"",
        "Click the \"Add Agent\" button",
        "Fill \"Test Agent\" into the \"Agent Name\"",
        "Click the \"Save\" button",
        "Verify that the page contains \"Test Agent\""
      ]
    }

    **Example 2: Full Login**
    User Story: "Login with valid credentials (Email: himanshu@example.com,Password: Harry@123), then go to the Agents tab and click the Add Agent button."
    Expected Output:
    {
      "steps": [
        "Fill \"himanshu@example.com\" into the \"Email\"",
        "Fill \"Harry@123\" into the \"Password\"",
        "Click the \"Login\" button",
        "Click the \"Agents\" tab",
        "Click the \"Add Agent\" button"
      ]
    }

    **Example 3: Partial Input**
    User Story: "sign in with username testuser"
    Page Context: { "formInputs": [{ "label": "Username" }, { "label": "Password" }] }
    Expected Output:
    {
      "steps": [
        "Fill \"testuser\" into the \"Username\""
      ]
    }

    **Example 4: Simple Button Click**
    User Story: "Sign in Button Click"
    Page Context: { "visibleButtons": ["Sign in"] }
    Expected Output:
    {
      "steps": [
        "Click the \"Sign in\" button"
      ]
    }
    ---

    Now, generate the JSON object for the provided User Story and Page Context.
  `,

  /**
   * Prompt to generate a list of test scenarios based on page context.
   */
  generateScenarios: (pageContext: PageContext) => {
    const buttons = pageContext.visibleButtons?.join(", ") || "None";
    const links = pageContext.visibleLinks?.join(", ") || "None";
    const inputs = pageContext.formInputs?.map((i: any) => i.label || i.name || i.placeholder).join(", ") || "None";

    return 'You are a world-class Senior QA Automation Engineer. Your mission is to analyze the provided context of a web page and generate a comprehensive, prioritized list of test scenarios as a JSON object.\n\n' +
      'Page Context (Visible Elements):\n' +
      '- Buttons: [' + buttons + ']\n' +
      '- Links: [' + links + ']\n' +
      '- Inputs/Labels: [' + inputs + ']\n\n' +
      '**CRITICAL INSTRUCTIONS:**\n' +
      '1.  **Output Format:** You MUST return a single JSON object with one key: "scenarios". This key must contain an array of 3 to 7 scenario objects.\n' +
      '2.  **Persona:** Think like a meticulous QA expert. Consider the user\'s primary goal on this page. What is the most important functionality? What are the most likely points of failure?\n' +
      '3.  **Generate Diverse & Important Scenarios:** Based on the page context, you MUST generate scenarios from the following categories if applicable. Prioritize the most critical tests.\n' +
      '    -   **Happy Path / Core Functionality (1-2 scenarios):** Test the primary success path. If there is a form, this is a successful submission. If it\'s a login page, it\'s a successful login.\n' +
      '    -   **Input Validation (2-4 scenarios):** If there are form inputs, create scenarios to test validation. This is critical. Examples: \n' +
      '        -   Attempt to submit with required fields empty.\n' +
      '        -   Enter incorrectly formatted data into fields like \'Email\' or \'Phone\'.\n' +
      '        -   Test boundary conditions if they can be inferred (e.g., password length).\n' +
      '    -   **Key Element Interaction (1-2 scenarios):** If there are important-looking buttons or links NOT related to a form submission (e.g., "View Details", "Forgot Password", "Open Modal"), create a scenario to verify they work.\n' +
      '4.  **Scenario Object Structure:** For EACH scenario object, you MUST provide:\n' +
      '    -   A short, descriptive `title`.\n' +
      '    -   A `description` of what the scenario tests and why it is important.\n' +
      '    -   An array of strings called `steps`, where each string is a single, precise, executable command.\n' +
      '5.  **Step Generation Rules:** For the `steps` array, you MUST follow these rules:\n' +
      '    -   Use precise command formats: \\`Click the "..."\\`, \\`Fill "..." into the "..."\\`, \\`Verify that the page contains "..."\\`.\n' +
      '    -   **CRITICAL:** Do NOT generate abstract, non-executable steps like "Check keyboard navigation" or "Ensure responsiveness". Every step MUST be a concrete, executable command.\n' +
      '    -   Use realistic fake data (e.g., "John Doe", "test@example.com", "Password123"). For invalid data, use clearly invalid data (e.g., "not-an-email").\n' +
      '    -   For validation tests, the final step should almost always be a \\`Verify that the page contains "[error message]"\\` step.\n\n' +
      '**Example Output for a Login Page:**\n' +
      '{\n' +
      '  "scenarios": [\n' +
      '    {\n' +
      '      "title": "Successful Login",\n' +
      '      "description": "Ensures a user with valid credentials can successfully log in and access the dashboard.",\n' +
      '      "steps": [\n' +
      '        "Fill \\\"test@example.com\\\" into the \\\"Email\\\"",\n' +
      '        "Fill \\\"Password123!\\\" into the \\\"Password\\\"",\n' +
      '        "Click the \\\"Login\\\" button",\n' +
      '        "Verify that the page contains \\\"Welcome to your Dashboard\\\""\n' +
      '      ]\n' +
      '    },\n' +
      '    {\n' +
      '      "title": "Login with Invalid Password",\n' +
      '      "description": "Verifies that the system prevents login and shows an error message when the password is incorrect.",\n' +
      '      "steps": [\n' +
      '        "Fill \\\"test@example.com\\\" into the \\\"Email\\\"",\n' +
      '        "Fill \\\"wrong-password\\\" into the \\\"Password\\\"",\n' +
      '        "Click the \\\"Login\\\" button",\n' +
      '        "Verify that the page contains \\\"Invalid credentials, please try again\\\""\n' +
      '      ]\n' +
      '    },\n' +
      '    {\n' +
      '      "title": "Login with Empty Fields",\n' +
      '      "description": "Checks that required field validation is working by attempting to submit the login form with no data.",\n' +
      '      "steps": [\n' +
      '        "Click the \\\"Login\\\" button",\n' +
      '        "Verify that the page contains \\\"Email is required\\\""\n' +
      '      ]\n' +
      '    },\n' +
      '    {\n' +
      '      "title": "Click \'Forgot Password\' Link",\n' +
      '      "description": "Ensures the \'Forgot Password\' link navigates the user to the password recovery page.",\n' +
      '      "steps": [\n' +
      '        "Click the \\\"Forgot Password\\\" link",\n' +
      '        "Verify that the page contains \\\"Reset Your Password\\\""\n' +
      '      ]\n' +
      '    }\n' +
      '  ]\n' +
      '}\n\n' +
      'Now, generate the JSON object for the provided Page Context.';
  },

  /**
   * Prompt to create a high-level workflow plan from a user command.
   */
  createWorkflowPlan: (userCommand: string, context: PageContext) => `
    You are an AI Test Automation Orchestrator. Your job is to convert a high-level user command into a structured, step-by-step execution plan in JSON format.

    User Command: "${userCommand}"

    Current Page Context:
    - Is a form visible on the page? ${!!context.formInputs && context.formInputs.length > 0}
    - Visible buttons: [${context.visibleButtons?.slice(0, 20).join(", ")}]
    - Visible links: [${context.visibleLinks?.slice(0, 20).join(", ")}]

    **CRITICAL PLANNING RULES - READ CAREFULLY:**

    1.  **COMPREHENSIVE TEST INTENT:** If the user command is a broad request to "Test", "Validate", or "Check" a feature (e.g., "Test the login form", "Validate the registration process"), you MUST select the \`TEST_FEATURE_COMPREHENSIVELY\` skill. This is your highest priority for such commands.

    2.  **HAPPY PATH FORM FILL:** If a form is visible AND the user command is a specific instruction to add, create, or submit data (e.g., "Add a new user with details", "Create an agent"), you MUST select the \`FILL_FORM_HAPPY_PATH\` skill. Do NOT use this for general "Test" commands.

    3.  **BASIC CLICK:** Only choose the \`CLICK\` skill if a form is NOT visible and the user's command is a simple, direct action to begin a process (e.g., command is "Add a new user" and a button "Create User" exists).

    Available Skills:
    - \`TEST_FEATURE_COMPREHENSIVELY\`: Triggers a full suite of generated tests (happy path, validation, negative cases) for a given feature. The \`target\` should be the feature described (e.g., "login form", "the page").
    - \`FILL_FORM_HAPPY_PATH\`: Intelligently fills a visible form with valid data and submits it.
    - \`CLICK\`: Clicks a single button, link, or tab. Requires a \`target\`.
    - \`NAVIGATE\`: Goes to a specific URL. Requires a \`url\`.

    ---
    **EXAMPLES:**

    **Example 1 (NEW - Comprehensive Test):**
    User Command: "Test the login feature"
    Current Page Context: { "isFormVisible": true, "visibleButtons": ["Login", "Forgot Password"] }
    Your Output: {"plan":[{ "skill": "TEST_FEATURE_COMPREHENSIVELY", "target": "login feature" }]}
    (REASONING: The user wants to test a whole feature, not just perform one action. This skill will trigger multiple sub-scenarios like valid login, invalid login, etc.)

    **Example 2 (Happy Path Fill):**
    User Command: "Add an agent"
    Current Page Context: { "isFormVisible": true, "visibleButtons": ["Add Agent", "Cancel"] }
    Your Output: {"plan":[{ "skill": "FILL_FORM_HAPPY_PATH" }]}
    (REASONING: A form is visible and the user gave a specific instruction to add something. This is a single happy-path action.)

    **Example 3 (Basic Click):**
    User Command: "Add an agent"
    Current Page Context: { "isFormVisible": false, "visibleButtons": ["Add Agent", "Delete Agent"] }
    Your Output: {"plan":[{ "skill": "CLICK", "target": "Add Agent" }]}
    (REASONING: No form is visible. Clicking the button is the necessary first step to open the form.)
    ---

    Now, generate the plan for the user command and context above.
  `,

  /**
   * Prompt to generate Faker.js mappings for a given form.
   */
  generateFakerMappings: (formInputs: any[]) => `
    You are an expert data mapping assistant for the faker-js library. Your primary goal is to intelligently map form input fields to the most appropriate faker-js method based on all available context.

    Analyze the following list of form inputs:
    ${JSON.stringify(formInputs, null, 2)}

    **CRITICAL INSTRUCTIONS FOR MAPPING:**

    1.  **Analyze Context:** For each input, carefully consider its 
label
, 
name
, 
placeholder
, and 
type
 to infer the type of data required.
    2.  **Faker.js Mapping:** Your output MUST be a JSON object where keys are the field identifiers (prefer 
name
, then 
label
) and values are objects containing the Faker.js 
namespace
 and 
method
.
        -   **Names:** For fields like 'First Name', use { "namespace": "person", "method": "firstName" }.
        -   **Contact:** For emails, use { "namespace": "internet", "method": "email" }. For phone, use { "namespace": "phone", "method": "number" }.
        -   **Address:** Use the 
location
 namespace (e.g., 
streetAddress
, 
city
, 
zipCode
).
        -   **Text/Description:** For generic text areas, use { "namespace": "lorem", "method": "paragraph" }.
        -   **Default:** If you cannot determine a specific type, fall back to { "namespace": "lorem", "method": "words", "options": [3] }.
    3.  **Select/Dropdowns:** If an input is a 
<select>
 element with an 
options
 array, you MUST use the 
helpers.arrayElement
 method. The output should be { "namespace": "helpers", "method": "arrayElement", "options": [ [/* original options array */] ] }.

    **Example Input:**
    [
      { "name": "fullName", "label": "Full Name", "type": "text" },
      { "name": "email_address", "label": "Email", "type": "email" },
      { "name": "role", "label": "User Role", "type": "select", "options": ["admin", "editor", "viewer"] }
    ]

    **Example Output:**
    {
      "fullName": { "namespace": "person", "method": "fullName" },
      "email_address": { "namespace": "internet", "method": "email" },
      "role": { "namespace": "helpers", "method": "arrayElement", "options": [ ["admin", "editor", "viewer"] ] }
    }

    Now, generate the JSON object for the provided form inputs.
  `,

  /**
   * Prompt to analyze a single executed test scenario and its logs.
   */
  analyzeScenario: (scenario: Scenario, logs: TestLog[]) => `
    You are an expert test analyst. Analyze the following single test scenario execution and its logs to provide a concise analysis.

    Scenario Details:
    - Title: ${scenario.title}
    - Description: ${scenario.description}
    - Status: ${scenario.status}
    - Duration: ${scenario.duration}ms
    - Steps:
      ${scenario.steps.join("\n      ")}

    Execution Logs for this Scenario:
    ${logs.map(l => `- [${l.level.toUpperCase()}] ${l.message}`).join("\n    ")}

    Please provide a brief analysis in JSON format with the following keys:
    - "summary": A one-sentence summary of what happened in the scenario.
    - "issues": An array of strings, listing any specific errors or unexpected behaviors found in the logs. If no issues, return an empty array.
    - "recommendations": An array of strings, suggesting any improvements or next steps based on the outcome. If no recommendations, return an empty array.
  `,

  /**
   * Prompt to generate a final analysis report for a full test session.
   */
  generateTestAnalysis: (testResults: TestResults) => `
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
      "qualityScore": 0
    }
  `,

  /**
   * Prompt to analyze the structure of a web page.
   */
  analyzeWebPage: (pageInfo: { title: string; url: string }) => `
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
  `,
};