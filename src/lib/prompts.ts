/**
 * @fileoverview
 * This file contains all the prompt templates for the OpenAIService.
 * Centralizing prompts here makes the main service file cleaner and easier to manage.
 */

import { PageContext } from './openai'; // Import the rich PageContext
import { TestLog } from './supabase';

// --- Type Definitions ---

interface Scenario {
  title: string;
  description: string;
  status: 'passed' | 'failed';
  duration: number;
  steps: string[];
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
   * Prompt to generate a list of test scenarios based on a comprehensive page context.
   */
  generateScenarios: (pageContext: PageContext) => {
    // Sanitize and stringify the context to be safely embedded in the prompt
    const contextString = JSON.stringify(
      {
        title: pageContext.title,
        url: pageContext.url,
        hasLoginForm: pageContext.hasLoginForm,
        hasContactForm: pageContext.hasContactForm,
        hasSearchForm: pageContext.hasSearchForm,
        forms: pageContext.forms.map(form => ({
          id: form.id,
          className: form.className,
          inputs: form.inputs.map(input => ({
            name: input.name,
            type: input.type,
            placeholder: input.placeholder,
          })),
        })),
        navLinks: pageContext.navLinks.map(link => ({
          href: link.href,
          text: link.text,
        })),
      },
      null,
      2
    );

    return 'You are a world-class Senior QA Automation Engineer. Your mission is to analyze the provided JSON context of a web page and generate a comprehensive, prioritized list of test scenarios.\n\n' +
    '**Web Page Context:**\n' +
    '```json\n' +
    contextString +
    '\n```\n\n' +
    '**CRITICAL INSTRUCTIONS:**\n\n' +
    '1.  **Analyze the Goal:** First, analyze the context to determine the primary purpose of the page. Is it for logging in? Submitting a contact form? Searching? Displaying information? Your scenarios must be relevant to this goal.\n\n' +
    '2.  **Output Format:** You MUST return a single JSON object with one key: "scenarios". This key must contain an array of 4 to 8 high-quality scenario objects. You MUST NOT use trailing commas in your JSON output.\n\n' +
    '3.  **Persona:** Think like a meticulous QA expert. What is the most critical functionality? What are the most likely points of failure? What would a human tester check first?\n\n' +
    '4.  **Generate Diverse & Important Scenarios:** Based on the page context, you MUST generate scenarios from the following categories. Prioritize the most critical tests.\n\n' +
    '    *   **Happy Path / Core Functionality (1-2 scenarios):**\n' +
    '        *   Test the primary success path. If there is a form (hasLoginForm, hasContactForm, etc.), this is a successful submission with valid data.\n' +
    '        *   If it\'s a navigation page, test the most important links.\n\n' +
    '    *   **Input Validation & Edge Cases (3-5 scenarios):**\n' +
    '        *   This is CRITICAL. If there are forms, create scenarios to test validation.\n' +
    '        *   Examples:\n' +
    '            *   Attempt to submit with required fields empty.\n' +
    '            *   Enter incorrectly formatted data into fields like \'email\' or \'tel\'.\n' +
    '            *   Test boundary conditions if they can be inferred (e.g., password length, number ranges).\n' +
    '            *   Use clearly invalid data (e.g., \'not-an-email\' for an email field, \'abc\' for a number field).\n' +
    '\n' +
    '    *   **Key Element Interaction (1-2 scenarios):**\n' +
    '        *   If there are important-looking buttons or links NOT related to a primary form submission (e.g., "View Details", "Forgot Password", "Switch to Sign Up"), create a scenario to verify they work as expected.\n\n' +
    '5.  **Scenario Object Structure:** For EACH scenario object, you MUST provide:\n' +
    '    *   A short, descriptive title.\n' +
    '    *   A description of what the scenario tests and why it is important.\n' +
    '    *   An array of strings called steps, where each string is a single, precise, executable command.\n\n' +
    '6.  **Step Generation Rules:** For the steps array, you MUST follow these rules:\n' +
    '    *   Use precise command formats: Click the "...", Fill "..." into the "...", Verify that the page contains "...".\n' +
    '    *   **CRITICAL:** Every step MUST be a concrete, executable command. Do NOT generate abstract steps like "Ensure responsiveness".\n' +
    '    *   Use realistic fake data (e.g., "John Doe", "test@example.com", "Password123").\n' +
    '    *   For validation tests, the final step should almost always be a Verify that the page contains "[expected error message]" step. Infer a likely error message if one isn\'t obvious (e.g., "Please enter a valid email").\n' +
    '    *   Base your selectors (e.g., "Email input", "Login button") on the names, placeholders, and text provided in the JSON context.\n\n' +
    '**Example Output for a Login Page:**\n' +
    '```json\n' +
    '{\n' +
    '  "scenarios": [\n' +
    '    {\n' +
    '      "title": "Successful Login",\n' +
    '      "description": "Ensures a user with valid credentials can successfully log in.",\n' +
    '      "steps": [\n' +
    '        "Fill \"test@example.com\" into the \"email\"",\n' +
    '        "Fill \"Password123!\" into the \"password\"",\n' +
    '        "Click the \"Login\" button",\n' +
    '        "Verify that the page contains \"Welcome\""\n' +
    '      ]\n' +
    '    },\n' +
    '    {\n' +
    '      "title": "Login with Invalid Password",\n' +
    '      "description": "Verifies that the system shows an error message for an incorrect password.",\n' +
    '      "steps": [\n' +
    '        "Fill \"test@example.com\" into the \"email\"",\n' +
    '        "Fill \"wrong-password\" into the \"password\"",\n' +
    '        "Click the \"Login\" button",\n' +
    '        "Verify that the page contains \"Invalid credentials\""\n' +
    '      ]\n' +
    '    },\n' +
    '    {\n' +
    '      "title": "Login with Empty Fields",\n' +
    '      "description": "Checks that required field validation is working.",\n' +
    '      "steps": [\n' +
    '        "Click the \"Login\" button",\n' +
    '        "Verify that the page contains \"Email is required\""\n' +
    '      ]\n' +
    '    }\n' +
    '  ]\n' +
    '}\n' +
    '```\n\n' +
    'Now, generate the JSON object for the provided Web Page Context.\n';
  },

  /**
   * Prompt to interpret a user's natural language story into executable steps.
   */
  interpretScenario: (userStory: string, pageContext: any) => {
    let contextString = '';
    if (pageContext && Object.keys(pageContext).length > 0) {
      contextString = `
    Page Context (Visible Elements):
    - Buttons: [${pageContext.visibleButtons?.join(", ") || "None"}]
    - Links: [${pageContext.visibleLinks?.join(", ") || "None"}]
    - Inputs/Labels: [${pageContext.formInputs
        ?.map((i: any) => i.label || i.name || i.placeholder)
        .join(", ") || "None"}]
      `;
    }

    return `
    You are an expert test automation engineer. Your task is to convert a user's natural language instructions into a precise, step-by-step test script formatted as a JSON object.

    User Story: "${userStory}"
    ${contextString}
    **CRITICAL INSTRUCTIONS:**
    1.  **Output Format:** You MUST return a single JSON object with one key: "steps". The value MUST be an array of strings.
    2.  **Atomicity:** Each string in the array MUST be a single, precise, executable command. Do NOT combine actions into one step.
    3.  **Completeness:** You MUST NOT generate incomplete or broken commands like "Click the" or "Fill". Every command must have a valid target and value.
    4.  **Command Structure:** You MUST use the following command formats ONLY:
        - Navigate to [URL] (Use ONLY for full URLs)
        - Click the "[button name, link text, or tab name]" (Use for ANY clickable element on the current page)
        - Fill "[value]" into the "[input label, name, or placeholder]"
        - Select the "[option]" option in the "[select field label or name]"
        - Verify that the page contains "[text to verify]"
    5.  **Data Extraction:**
        -   Pay close attention to data provided in the user story.
        -   It can be in formats like (Email: value), username: value, Key : value, or with password "value".
        -   If a user provides only partial credentials (e.g., just an email), generate a Fill step for that information only. Do NOT invent missing credentials.
    6.  **Implied Form Filling:**
        -   If the user story mentions adding, creating, or submitting something with "details" or "data" but does not provide the data (e.g., "add an agent with relatable details"), you MUST generate Fill commands for all relevant form inputs found in the Page Context.
        -   You should use realistic but clearly fake data (e.g., "John Doe", "test@example.com").
        -   After filling the form, you MUST generate a Click step for the submission button (e.g., "Submit", "Save", "Add").
    7.  **Action Choice:**
        -   Use Click the for on-page elements like tabs, buttons, and links.
        -   Use Navigate to ONLY for navigating to a new URL. For example, "go to agents tab" should be Click the "agents tab".
    8.  **No Placeholders:** You MUST NOT use placeholder values like '[URL]' or 'the specified URL'. If a valid URL is not provided in the user story, do not generate a 'Navigate' command.
    9.  **Search Workflow:** For search actions, the correct workflow is to first Fill the search term into a search input, and then Press "Enter". Do NOT generate a step to click a search button.

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
    ---

    Now, generate the JSON object for the provided User Story and Page Context.
  `},

  /**
   * Prompt to create a high-level workflow plan from a user command.
   */
  createWorkflowPlan: (userCommand: string, context: any) => `
    You are an AI Test Automation Orchestrator. Your job is to convert a high-level user command into a structured, step-by-step execution plan in JSON format.

    User Command: "${userCommand}"

    Current Page Context:
    - Is a form visible on the page? ${!!context.formInputs && context.formInputs.length > 0}
    - Visible buttons: [${context.visibleButtons?.slice(0, 20).join(", ")}]
    - Visible links: [${context.visibleLinks?.slice(0, 20).join(", ")}]

    **CRITICAL PLANNING RULES - READ CAREFULLY:**

    1.  **COMPREHENSIVE TEST INTENT:** If the user command is a broad request to "Test", "Validate", or "Check" a feature (e.g., "Test the login form", "Validate the registration process"), you MUST select the TEST_FEATURE_COMPREHENSIVELY skill. This is your highest priority for such commands.

    2.  **HAPPY PATH FORM FILL:** If a form is visible AND the user command is a specific instruction to add, create, or submit data (e.g., "Add a new user with details", "Create an agent"), you MUST select the FILL_FORM_HAPPY_PATH skill. Do NOT use this for general "Test" commands.

    3.  **BASIC CLICK:** Only choose the CLICK skill if a form is NOT visible and the user's command is a simple, direct action to begin a process (e.g., command is "Add a new user" and a button "Create User" exists).

    Available Skills:
    - TEST_FEATURE_COMPREHENSIVELY: Triggers a full suite of generated tests (happy path, validation, negative cases) for a given feature. The target should be the feature described (e.g., "login form", "the page").
    - FILL_FORM_HAPPY_PATH: Intelligently fills a visible form with valid data and submits it.
    - CLICK: Clicks a single button, link, or tab. Requires a target.
    - NAVIGATE: Goes to a specific URL. Requires a url.

    ---
    **EXAMPLES:**

    **Example 1 (NEW - Comprehensive Test):**
    User Command: "Test the login feature"
    Current Page Context: { "isFormVisible": true, "visibleButtons": ["Login", "Forgot Password"] }
    Your Output: {"plan":[{ "skill": "TEST_FEATURE_COMPREHENSIVELY", "target": "login feature" }]}

    **Example 2 (Happy Path Fill):**
    User Command: "Add an agent"
    Current Page Context: { "isFormVisible": true, "visibleButtons": ["Add Agent", "Cancel"] }
    Your Output: {"plan":[{ "skill": "FILL_FORM_HAPPY_PATH" }]}

    **Example 3 (Basic Click):**
    User Command: "Add an agent"
    Current Page Context: { "isFormVisible": false, "visibleButtons": ["Add Agent", "Delete Agent"] }
    Your Output: {"plan":[{ "skill": "CLICK", "target": "Add Agent" }]}
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

    1.  **Analyze Context:** For each input, carefully consider its label, name, placeholder, and type to infer the type of data required.
    2.  **Faker.js Mapping:** Your output MUST be a JSON object where keys are the field identifiers (prefer name, then label) and values are objects containing the Faker.js namespace and method.
        -   **Names:** For fields like 'First Name', use { "namespace": "person", "method": "firstName" }.
        -   **Contact:** For emails, use { "namespace": "internet", "method": "email" }. For phone, use { "namespace": "phone", "method": "number" }.
        -   **Address:** Use the location namespace (e.g., streetAddress, city, zipCode).
        -   **Text/Description:** For generic text areas, use { "namespace": "lorem", "method": "paragraph" }.
        -   **Default:** If you cannot determine a specific type, fall back to { "namespace": "lorem", "method": "words", "options": [3] }.
    3.  **Select/Dropdowns:** If an input is a <select> element with an options array, you MUST use the helpers.arrayElement method. The output should be { "namespace": "helpers", "method": "arrayElement", "options": [ [/* original options array */] ] }.

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
  generateTestAnalysis: (testResults: TestResults, logs: TestLog[], scenarios: any[]) => `
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
};
