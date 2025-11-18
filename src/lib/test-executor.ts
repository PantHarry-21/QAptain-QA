import { Page, Browser, Locator, chromium } from 'playwright';
import sparticuzChromium from '@sparticuz/chromium';
import { v4 as uuidv4 } from 'uuid';
import { openAIService } from './openai';
import { Server } from 'socket.io';

import { skillFillFormHappyPath } from './skills/fill-form';
import { getDomContextSelector } from './utils';
import { goldenScenarios } from './golden-scenarios';
import { databaseService } from './database-service';
import type { TestLog, TestScenario } from './types';

// --- Interfaces ---

interface ParsedCommand {
  type: string;
  target?: any;
  value?: any;
  attribute?: string;
  action?: any;
  option?: string;
  source?: string;
  destination?: string;
  username?: string;
  password?: string;
}

interface CommandDefinition {
    regex: RegExp;
    parser: (matches: RegExpMatchArray) => ParsedCommand;
}

// --- Helper Functions ---

async function findLocator(page: Page, identifier: string): Promise<Locator> {
    const cleanedIdentifier = identifier.replace(/['"“”]/g, '').replace(/\b(tab|button|link|page|the|field|input)\b/gi, '').trim();
    const searchRegex = new RegExp(cleanedIdentifier.replace(/[.*+?^${}()|[\\]/g, '\\$&'), 'i');

    // --- Locator Priority List ---
    // Tries locators in order of reliability. The first one that finds a visible element is used.
    const strategies = [
        () => page.getByRole('button', { name: searchRegex }),
        () => page.getByRole('link', { name: searchRegex }),
        () => page.getByLabel(searchRegex),
        () => page.getByPlaceholder(searchRegex),
        () => page.getByTestId(cleanedIdentifier),
        () => page.getByText(searchRegex),
        // Fallback for buttons that aren't properly labeled for accessibility
        () => page.locator(`button:has-text("${cleanedIdentifier}")`),
    ];

    for (const getLocator of strategies) {
        const locator = getLocator();
        // Use a short timeout to see if this strategy yields any results quickly.
        // The .click() action itself will wait longer for the element to be actionable.
        if (await locator.count() > 0) {
            // Check if the first match is visible.
            if (await locator.first().isVisible()) {
                console.log(`Found visible element for "${cleanedIdentifier}" using a priority strategy.`);
                return locator; // Return the locator group for this strategy
            }
        }
    }

    throw new Error(`Could not find a visible element matching "${identifier}" using any priority strategy.`);
}


// --- Command Definitions ---

const commandDefinitions: CommandDefinition[] = [
    // FILL command with specific attribute (placeholder, label, etc.)
    {
        regex: /^(?:Enter|Type|Fill|Input|Write)\s+['"]?(.+?)['"]?\s+into\s(?:the\s*)?.*?\s(?:with|for)\s(?:the\s*)?(placeholder|label|name|aria-label)\s+['"]?(.+?)['"]?$/i,
        parser: m => ({ type: 'fill', value: m[1], attribute: m[2].toLowerCase(), target: m[3] })
    },
    // FILL command (generic) - This now uses a negative lookahead to avoid being too greedy
    {
        regex: /^(?:Enter|Type|Fill|Input|Write)\s+["']?(.+?)["']?\s+(?:into|in)\s(?:the\s*)?(?!.*?\s(?:with|for)\s(?:placeholder|label|name|aria-label))["']?(.+?)["']?$/i,
        parser: m => ({ type: 'fill', value: m[1], target: m[2] })
    },

    // CONDITIONAL LOGIC
    {
        regex: /^If\s+(?:the\s+)?(?:text\s+)?['"]?(.+?)['"]?\s+(?:is\s+visible|appears|exists|is\s+present),?\s*(?:then\s+)?(.+)$/i,
        parser: m => ({
            type: 'conditional',
            target: { step: `Verify text \"${m[1]}\" is visible` },
            value: { step: m[2] }
        })
    },

    // NAVIGATION — SPECIFIC NAMED PAGES
    {
        regex: /^(?:Navigate|Go|Open|Visit|Browse)\s*(?:to|into)?\s*(?:the)?\s*(homepage|home\s?page|login\s?page|contact\s?page|register\s?page)$/i,
        parser: m => ({ type: 'navigateSpecific', target: m[1].toLowerCase().replace(/\s+/g, '-') })
    },

    // NAVIGATION — CUSTOM URL OR PAGE
    {
        regex: /^(?:Navigate|Go|Open|Visit|Browse)\s*(?:to|into)?\s*(?:the)?\s*(?:page|url)?\s*['"]?(.+?)['"]?$/i,
        parser: m => ({ type: 'navigateUrl', target: m[1] })
    },

    // CLICK / PRESS / TAP / SELECT
    {
        regex: /^(?:Click|Press|Tap|Select)\s*(?:the)?\s*(?:button|link|element)?\s*(?:named|called|with\s+text|with\s+label|with\s+selector)?\s*['"]?(.+?)['"]?(?:\s+button|\s+link|\s+element|\s+tab|\s+option|\s+item)?$/i,
        parser: m => ({ type: 'click', target: m[1].trim() })
    },

    // KEYBOARD PRESS
    {
        regex: /^Press(?: the)?\s*['"]?(.+?)['"]?\s*key$/i,
        parser: m => ({ type: 'press', target: m[1] })
    },

    // LOGIN / SIGN-IN
    {
        regex: /^(?:Login|Log in|Sign in|Sign-in)\s*(?:with|using)?\s*['"]?([^'" ]+)['"]?\s*(?:and|\/)?\s*(?:password|pass|pwd)?\s*['"]?([^'" ]+)['"]?$/i,
        parser: m => ({ type: 'login', username: m[1], password: m[2] })
    },

    // WAIT / PAUSE
    {
        regex: /^(?:Wait|Pause)\s*(?:for)?\s*(\d+)\s*seconds?$/i,
        parser: m => ({ type: 'wait', value: parseInt(m[1], 10) })
    },

    // --- ASSERTIONS (ORDER IS CRITICAL) ---

    // ASSERTIONS — URL (Most specific)
    {
        regex: /^(?:Verify|Assert|Check)\s+(?:that\s+)?(?:the\s+)?page\s+(?:url|address)\s+is\s+['"]?(.+?)['"]?$/i,
        parser: m => ({ type: 'assertUrlIs', value: m[1] })
    },
    {
        regex: /^(?:Verify|Assert|Check)\s+(?:that\s+)?(?:the\s+)?page\s+(?:url|address)\s+contains\s+['"]?(.+?)['"]?$/i,
        parser: m => ({ type: 'assertUrlContains', value: m[1] })
    },

    // ASSERTIONS — PAGE CONTENT (Specific)
    {
        regex: /^(?:Verify|Assert|Check)\s+(?:that\s+)?(?:the\s+)?page\s+contains(?:\s+the\s+text)?\s+['"]?(.+?)['"]?$/i,
        parser: m => ({ type: 'assertPageContains', value: m[1] })
    },

    // ASSERTIONS — VISIBILITY
    {
        regex: /^(?:Verify|Assert|Check)(?:\s+that)?\s*(?:the\s+)?(?:element|text|label)?\s*['"]?(.+?)['"]?\s+(?:is\s+visible|appears|exists|is\s+present)$/i,
        parser: m => ({ type: 'assertVisible', target: m[1] })
    },

    // ASSERTIONS — ELEMENT CONTENT (Generic - must be after page/url checks)
    {
        regex: /^(?:Verify|Assert|Check)\s+(?:that\s+)?(?:the\s*)?(?:element\s*)?['"]?(.+?)['"]?\s+contains(?:\s+the\s+text)?\s+['"]?(.+?)['"]?$/i,
        parser: m => ({ type: 'assertTextContains', target: m[1], value: m[2] })
    },

    // ASSERTIONS — INPUT VALUE
    {
        regex: /^(?:Verify|Assert|Check)\s*(?:that\s+)?(?:the\s+)?(?:input|field)\s*['"]?(.+?)['"]?\s*(?:has|contains)\s*(?:the\s+)?value\s*['"]?(.+?)['"]?$/i,
        parser: m => ({ type: 'assertValue', target: m[1], value: m[2] })
    },

    // CHECKBOXES
    {
        regex: /^(Check|Uncheck|Tick|Untick)\s*(?:the)?\s*(?:checkbox|option|toggle)?\s*['"]?(.+?)['"]?$/i,
        parser: m => ({ type: 'checkUncheck', action: m[1].toLowerCase(), target: m[2] })
    },
    // ASSERTIONS —- VALIDITY
    {
        regex: /^(?:Verify|Assert|Check)\s+(?:that\s+)?(?:the\s*)?['"]?(.+?)['"]?\s*(?:field|input)?\s+is\s+(valid|invalid)$/i,
        parser: m => ({ type: 'assertValidity', target: m[1], value: m[2] })
    },
];

function parseSingleCommand(step: string): ParsedCommand | null {
    const trimmedStep = step.trim().replace(/^\d+\.\s*/, ''); // Remove leading "1. ", "2. ", etc.
    for (const def of commandDefinitions) {
        const matches = trimmedStep.match(def.regex);
        if (matches) {
            return def.parser(matches);
        }
    }
    return null;
}

function parseStep(step: string): (ParsedCommand | null)[] {
    const commands: (ParsedCommand | null)[] = [];
    // Split command string by 'then' or 'and then'
    const subSteps = step.split(/\s*,\s*then\s*|\s+and then\s+|\s*;\s*/i);

    for (const subStep of subSteps) {
        const trimmedSubStep = subStep.trim();
        if (trimmedSubStep) {
            commands.push(parseSingleCommand(trimmedSubStep));
        }
    }
    return commands;
}

export async function executeSingleCommand(command: ParsedCommand, page: Page, baseUrl: string, sessionId: string, scenarioId: string): Promise<void> {
  console.log('Executing command:', command);
  // Add a small delay before each command
  await page.waitForTimeout(250);

  switch (command.type) {
    case 'navigateSpecific':
      const pageName = command.target!.toLowerCase();
      const urlObject = new URL(baseUrl);
      if (pageName.includes('homepage')) urlObject.pathname = '/';
      else if (pageName.includes('login')) urlObject.pathname = '/login';
      else if (pageName.includes('contact')) urlObject.pathname = '/contact';
      else if (pageName.includes('register')) urlObject.pathname = '/register';
      await page.goto(urlObject.toString(), { waitUntil: 'networkidle' });
      break;

    case 'navigateUrl':
      const urlToNavigate = command.target!;
      if (!urlToNavigate.startsWith('http')) {
        throw new Error(`Invalid URL for navigation: "${urlToNavigate}". URL must start with http:// or https://.`);
      }
      await page.goto(urlToNavigate, { waitUntil: 'networkidle' });
      break;

    case 'click':
      const locator = await findLocator(page, command.target!);
      // Removed `force: true` to ensure Playwright's actionability checks are performed.
      // This prevents false positives where a click is reported on a non-interactive element.
      // The click action now auto-waits for the element to be visible, stable, and enabled.
      await locator.first().click({ timeout: 30000 });
      break;

    case 'press':
      await page.keyboard.press(command.target!);
      break;

    case 'fill': {
      const { target, value } = command;
      const cleanedTarget = target!.replace(/['"’]/g, '').replace(/\s+(field|input)$/i, '').trim();

      let potentialTargets: string[] = [cleanedTarget];

      // Based on user feedback, expand common concepts into multiple potential labels
      if (/username|email/i.test(cleanedTarget)) {
        potentialTargets = ['Email', 'Username', 'email address', 'user name', 'login id'];
      } else if (/password/i.test(cleanedTarget)) {
        potentialTargets = ['Password', 'pass'];
      }

      let inputFilled = false;
      for (const pTarget of potentialTargets) {
        const inputLocators = [
            page.getByLabel(pTarget, { exact: true }),
            page.getByLabel(pTarget, { exact: false }),
            page.getByPlaceholder(pTarget),
            page.locator(`[name="${pTarget}"]`),
            page.locator(`[id="${pTarget}"]`)
        ];
        for (const locator of inputLocators) {
            try {
                await locator.first().fill(value!, { timeout: 1000 }); // Use a shorter timeout for each attempt
                inputFilled = true;
                break;
            } catch (e) {
                // This locator failed, continue to the next one
            }
        }
        if (inputFilled) break;
      }

      if (!inputFilled) {
        throw new Error(`Could not find a fillable input field matching "${target!}"`);
      }
      break;
    }

    case 'select': {
      const { target, value } = command;
      const locator = await findLocator(page, target!); 
      await locator.selectOption(value!); 
      break;
    }

    case 'wait': {
      // command.value is in seconds, convert to milliseconds
      await page.waitForTimeout(command.value! * 1000);
      break;
    }

    case 'assertUrlContains': {
      const currentUrl = page.url();
      const expectedText = command.value!;
      if (!currentUrl.includes(expectedText)) {
        // Typo detection logic
        const urlParts = currentUrl.split('/').filter(p => p.length > 2);
        const cleanExpectedText = expectedText.replace(/\//g, '');

        for (const part of urlParts) {
            const distance = getLevenshteinDistance(part, cleanExpectedText);
            if (distance > 0 && distance <= 2) { // Threshold of 2 for typos
                throw new Error(`Expected URL to contain "${expectedText}" but it was not found. Did you mean "${part}"?`);
            }
        }
        throw new Error(`Expected URL "${currentUrl}" to contain "${expectedText}"`);
      }
      break;
    }

    case 'assertVisible': {
        await findLocator(page, command.target!); 
        break;
    }

    case 'assertPageContains': {
        await page.locator(`body:has-text("${command.value}")`).waitFor();
        break;
    }

    case 'assertTextContains': {
        const element = await findLocator(page, command.target!)
        await element.filter({ hasText: new RegExp(command.value, 'i') }).waitFor();
        break;
    }

    case 'assertValue': {
        const input = await findLocator(page, command.target!)
        const value = await input.inputValue();
        if (value !== command.value) {
            throw new Error(`Expected input "${command.target}" to have value "${command.value}", but it was "${value}"`);
        }
        break;
    }

    case 'checkUncheck': {
      const checkbox = await findLocator(page, command.target!); 
      if (command.action.startsWith('check') || command.action.startsWith('tick')) await checkbox.check();
      else await checkbox.uncheck();
      break;
    }

    case 'assertValidity': {
      const { target, value } = command;
      const locator = await findLocator(page, target!); 
      const isValid = await locator.evaluate(el => (el as HTMLInputElement).checkValidity());
      const expectedValid = value === 'valid';
      if (isValid !== expectedValid) {
        throw new Error(`Expected input \"${target}\" to be ${value}, but it was not.`);
      }
      break;
    }

    case 'login': {
        const emailField = await findLocator(page, 'email');
        await emailField.fill(command.username!); 
        const passwordField = await findLocator(page, 'password');
        await passwordField.fill(command.password!);
        await page.getByRole('button', { name: /sign in|login/i }).click();
        break;
    }

    case 'conditional': {
        try {
            await executeStep(page, command.target.step, baseUrl, sessionId, scenarioId);
            await executeStep(page, command.value.step, baseUrl, sessionId, scenarioId);
        } catch (error) {
            console.log(`Conditional step skipped: ${command.target.step}`);
        }
        break;
    }

    default:
      throw new Error(`Unknown command type: "${command.type}"`);
  }
}

async function executeStep(page: Page, step: string, baseUrl: string, sessionId: string, scenarioId: string): Promise<void> {
  const commands = parseStep(step);
  for (const command of commands) {
    if (!command) {
      throw new Error(`Unrecognized command in step: "${step}"`);
    }
    await executeSingleCommand(command, page, baseUrl, sessionId, scenarioId);
  }
}

// --- Test Execution Engine ---

const saveScreenshotToDatabase = async (page: Page, sessionId: string, scenarioId?: string, stepId?: string, message: string = 'Screenshot captured') => {
    try {
      const screenshot = await page.screenshot({ type: 'png' });
      await databaseService.createTestLog({
        session_id: sessionId,
        scenario_id: scenarioId,
        step_id: stepId,
        level: 'info',
        message: message,
        timestamp: new Date().toISOString(),
        metadata: { screenshot: `data:image/png;base64,${screenshot.toString('base64')}` }
      });
    } catch (e) {
      console.error('Failed to save screenshot to database:', e);
    }
  };

export async function executeTests(io: Server, sessionId: string, scenarios: any[], url: string) {
  let browser: Browser | null = null;
  const startTime = new Date();
  const sessionRoom = `session-${sessionId}`;
  const MAX_STEP_RETRIES = 1;
  let completedSteps = 0;
  const finalScenarios: TestScenario[] = [];

  const logs: TestLog[] = [];
  const emitLog = (log: Partial<TestLog>) => {
    const fullLog = { ...log, id: uuidv4(), timestamp: new Date().toISOString() } as TestLog;
    logs.push(fullLog);
    io.to(sessionRoom).emit('test-log', fullLog);
    databaseService
      .createTestLog({ session_id: sessionId, ...fullLog })
      .catch(err => console.error('Failed to persist test log', err));
  };

  const processedScenarios = scenarios.map(scenario => {
    const goldenMatch = goldenScenarios.find(golden => 
      golden.title.toLowerCase() === scenario.title.toLowerCase()
    );

    if (goldenMatch) {
      emitLog({ 
        level: 'info', 
        message: `Golden scenario matched: "${scenario.title}". Overriding AI-generated steps with predefined steps.`,
        scenario_id: scenario.id 
      });
      return { ...scenario, steps: goldenMatch.steps };
    }
    
    return scenario;
  });

  const emitScreenshot = async (page: Page) => {
    try {
      const screenshot = await page.screenshot({ type: 'png' });
      io.to(sessionRoom).emit('browser-view-update', `data:image/png;base64,${screenshot.toString('base64')}`);
    } catch (e) {}
  };

  let sessionResults = {
    totalScenarios: processedScenarios.length,
    passedScenarios: 0,
    failedScenarios: 0,
    totalSteps: processedScenarios.reduce((sum, scenario) => sum + scenario.steps.length, 0),
    passedSteps: 0,
    failedSteps: 0
  };
  const scenarioIds = processedScenarios.map(s => s.id);
  await databaseService.seedSessionData(sessionId, {
    session: {
      id: sessionId,
      url,
      status: 'running',
      total_scenarios: processedScenarios.length,
      passed_scenarios: 0,
      failed_scenarios: 0,
      total_steps: sessionResults.totalSteps,
      passed_steps: 0,
      failed_steps: 0,
      started_at: startTime.toISOString(),
      created_at: startTime.toISOString(),
      updated_at: startTime.toISOString(),
      selected_scenario_ids: scenarioIds,
    },
    scenarios: processedScenarios.map((scenario) => ({
      id: scenario.id,
      session_id: sessionId,
      title: scenario.title,
      description: scenario.description,
      steps: scenario.steps,
      status: 'pending',
    })),
  });
  await databaseService.updateTestSession(sessionId, { selected_scenario_ids: scenarioIds });

  try {
    emitLog({ level: 'info', message: `Initializing test session with Playwright...` });

    const isVercel = process.env.VERCEL || process.env.LAMBDA_TASK_ROOT;
    emitLog({ level: 'info', message: `Environment detected as ${isVercel ? 'Vercel' : 'Local'}.` });

    if (isVercel) {
      emitLog({ level: 'info', message: 'Launching browser with @sparticuz/chromium for serverless environment.' });
      browser = await chromium.launch({
        args: sparticuzChromium.args,
        executablePath: await sparticuzChromium.executablePath(),
        headless: sparticuzChromium.headless,
      });
    } else {
      emitLog({ level: 'info', message: 'Launching browser with local Playwright installation.' });
      browser = await chromium.launch({
        headless: true
      });
    }
    const context = await browser.newContext({
      recordVideo: { dir: isVercel ? `/tmp/videos/${sessionId}` : `videos/${sessionId}` }
    });
    const page = await context.newPage();

    emitLog({ level: 'info', message: `Playwright browser initialized. Starting execution for ${processedScenarios.length} scenarios.` });
    await emitScreenshot(page);

    for (let i = 0; i < processedScenarios.length; i++) {
      const scenario = processedScenarios[i];
      const scenarioStartTime = new Date();
      let scenarioPassed = true;

      const updatedScenarioWithRunningStatus = await databaseService.updateTestScenario(scenario.id, {
        status: 'running',
        started_at: scenarioStartTime.toISOString()
      });
      if (updatedScenarioWithRunningStatus) {
        io.to(sessionRoom).emit('test-scenario-update', updatedScenarioWithRunningStatus);
      }

      emitLog({ level: 'info', message: `Starting scenario: "${scenario.title}"`, scenario_id: scenario.id });

      await page.goto(url, { waitUntil: 'load' });
      await saveScreenshotToDatabase(page, sessionId, scenario.id, undefined, `Initial state for scenario: ${scenario.title}`);
      await emitScreenshot(page);

      for (let j = 0; j < scenario.steps.length; j++) {
        const stepDescription = scenario.steps[j];
        completedSteps++;
        io.to(sessionRoom).emit('test-progress', {
          currentScenario: i + 1,
          totalScenarios: processedScenarios.length,
          currentStep: completedSteps,
          totalSteps: sessionResults.totalSteps,
          currentScenarioTitle: scenario.title,
          currentStepDescription: stepDescription,
          status: 'running',
          startTime: startTime.toISOString(),
        });

        let stepPassed = false;
        let lastError: any = null;

        for (let retry = 0; retry <= MAX_STEP_RETRIES; retry++) {
          try {
            if (retry > 0) {
              emitLog({ level: 'warning', message: `Retrying step: ${stepDescription} (Attempt ${retry + 1}/${MAX_STEP_RETRIES + 1})`, scenario_id: scenario.id });
              await page.waitForTimeout(1000);
            }

            // --- SMART DISPATCHER LOGIC ---
            const parsedCommand = parseSingleCommand(stepDescription);

            if (parsedCommand) {
              // It's a basic, low-level command
              await executeStep(page, stepDescription, url, sessionId, scenario.id);
            } else {
              // It's a high-level, abstract command
              emitLog({ level: 'info', message: `High-level command detected: "${stepDescription}". Analyzing page context...`, scenario_id: scenario.id });

              // Determine the active DOM context (main page or modal)
              const activeContextSelector = await getDomContextSelector(page);

              // Analyze the current page to provide context to the AI planner
              let pageContext = await page.evaluate((selector) => {
                  const activeContext = document.querySelector(selector) || document.body;
                  
                  const formInputs = Array.from(activeContext.querySelectorAll('input:not([type="hidden"]):not([type="submit"]), textarea, select')).map(input => ({ name: (input as any).name, type: (input as any).type, placeholder: (input as any).placeholder, label: (input as any).labels?.[0]?.textContent }));

                  const visibleButtons = Array.from(activeContext.querySelectorAll('button')).map(btn => btn.textContent?.trim() || '').filter(text => text.length > 0 && text.length < 100);
                  const visibleLinks = Array.from(activeContext.querySelectorAll('a')).map(a => a.textContent?.trim() || '').filter(text => text.length > 0 && text.length < 100);
                  
                  return { isFormVisible: formInputs.length > 2, visibleButtons, visibleLinks, formInputs, contextType: selector === 'body' ? 'document' : 'modal' };
              }, activeContextSelector);

              // Pre-process context to remove distracting buttons before sending to AI
              if (pageContext.isFormVisible && /add|create|submit|fill/i.test(stepDescription)) {
                pageContext.visibleButtons = pageContext.visibleButtons.filter(btnText => {
                  // Remove buttons that closely match the command to prevent the AI from just clicking the submit button
                  const commandWords = stepDescription.toLowerCase().split(' ');
                  const btnWords = btnText.toLowerCase().split(' ');
                  return !btnWords.some(word => commandWords.includes(word));
                });
              }

              emitLog({ level: 'info', message: `Engaging AI orchestrator with context: ${JSON.stringify(pageContext)}`, scenario_id: scenario.id });
              const plan = await openAIService.createWorkflowPlan(stepDescription, pageContext);
              emitLog({ level: 'info', message: `AI has generated a sub-plan: ${JSON.stringify(plan.plan)}`, scenario_id: scenario.id });

              for (const subStep of plan.plan) {
                const skill = subStep.skill || subStep.action;
                emitLog({ level: 'info', message: `Executing sub-step: ${skill} -> ${subStep.target || subStep.url || ''}`, scenario_id: scenario.id });
                switch (skill) {
                  case 'CLICK':
                    await executeSingleCommand({ type: 'click', target: subStep.target }, page, url, sessionId, scenario.id);
                    break;
                  case 'NAVIGATE':
                    await executeSingleCommand({ type: 'navigateUrl', target: subStep.url }, page, url, sessionId, scenario.id);
                    break;
                  case 'FILL_FORM_HAPPY_PATH':
                    await skillFillFormHappyPath(page);
                    break;
                  case 'TEST_FEATURE_COMPREHENSIVELY':
                    emitLog({ level: 'info', message: `Comprehensive test requested for "${subStep.target}". Generating sub-scenarios...`, scenario_id: scenario.id });
                    const { scenarios: subScenarios } = await openAIService.generateScenarios(pageContext);
                    emitLog({ level: 'info', message: `Generated ${subScenarios.length} sub-scenarios.` });

                    for (const subScenario of subScenarios) {
                      emitLog({ level: 'info', message: `Starting sub-scenario: "${subScenario.title}"`, scenario_id: scenario.id });
                      try {
                        for (const subScenarioStep of subScenario.steps) {
                          await executeStep(page, subScenarioStep, url, sessionId, scenario.id);
                          await emitScreenshot(page);
                        }
                        emitLog({ level: 'success', message: `✅ Sub-scenario completed: "${subScenario.title}"`, scenario_id: scenario.id });
                      } catch (subError) {
                        emitLog({ level: 'warning', message: `Sub-scenario failed: "${subScenario.title}" - ${subError instanceof Error ? subError.message : 'Unknown error'}` });
                      }
                      // Reset page state for the next sub-scenario to ensure independence
                      await page.goto(url, { waitUntil: 'load' });
                    }
                    break;
                  default:
                    throw new Error(`Unknown AI skill in sub-plan: ${skill}`);
                }
                await emitScreenshot(page);
              }
            }
            // --- END SMART DISPATCHER LOGIC ---

            await saveScreenshotToDatabase(page, sessionId, scenario.id, undefined, `Screenshot after: ${stepDescription}`);

            await emitScreenshot(page);
            emitLog({ level: 'success', message: `✅ Step completed: ${stepDescription}`, scenario_id: scenario.id });
            sessionResults.passedSteps++;
            stepPassed = true;
            break;
          } catch (stepError) {
            lastError = stepError;
            emitLog({ level: 'warning', message: `Step failed: ${stepDescription} - ${stepError instanceof Error ? stepError.message : 'Unknown error'}`, scenario_id: scenario.id });
            await saveScreenshotToDatabase(page, sessionId, scenario.id, undefined, `Failure state for step: ${stepDescription}`);
            await emitScreenshot(page);
          }
        }

        if (!stepPassed) {
          const errorMessage = lastError instanceof Error ? lastError.message : 'Unknown error';
          scenarioPassed = false;
          sessionResults.failedSteps++;
          emitLog({ level: 'error', message: `❌ Step failed after ${MAX_STEP_RETRIES + 1} attempts: ${stepDescription} - ${errorMessage}`, scenario_id: scenario.id });
          break;
        }
        await page.waitForTimeout(500);
      }

            const scenarioDuration = new Date().getTime() - scenarioStartTime.getTime();
            let updatePayload: Partial<TestScenario>;
      
            if (scenarioPassed) {
              sessionResults.passedScenarios++;
              updatePayload = {
                status: 'passed',
                completed_at: new Date().toISOString()
              };
              emitLog({ level: 'success', message: `✅ Scenario completed: "${scenario.title}"`, scenario_id: scenario.id });
            } else {
              sessionResults.failedScenarios++;
              updatePayload = {
                status: 'failed',
                completed_at: new Date().toISOString(),
                error_message: `Scenario failed due to step error.`
              };
              emitLog({ level: 'error', message: `❌ Scenario failed: "${scenario.title}"`, scenario_id: scenario.id });
            }
      
            const updatedScenario = await databaseService.updateTestScenario(scenario.id, updatePayload);
            if (updatedScenario) {
              finalScenarios.push(updatedScenario);
              io.to(sessionRoom).emit('test-scenario-update', updatedScenario);
            }        
              // AI Analysis per scenario
              try {
                const scenarioLogs = logs.filter(log => log.scenario_id === scenario.id);
                const scenarioAnalysis = await openAIService.analyzeScenario(scenario, scenarioLogs);
        
                await databaseService.createScenarioReport({
                  scenario_id: scenario.id,
                  session_id: sessionId,
                  summary: scenarioAnalysis.summary,
                  issues: scenarioAnalysis.issues || [],
                  recommendations: scenarioAnalysis.recommendations || [],
                });
              } catch (aiError) {
                console.error(`AI analysis failed for scenario ${scenario.id}:`, aiError);
                emitLog({ level: 'warning', message: `AI analysis failed for scenario: "${scenario.title}"`, scenario_id: scenario.id });
              }
        
            }

    const endTime = new Date();
    const duration = endTime.getTime() - startTime.getTime();

    await page.close();
    const videoPath = await page.video()?.path();

    await databaseService.updateTestSession(sessionId, {
      status: 'completed',
      completed_at: endTime.toISOString(),
      duration,
      passed_scenarios: sessionResults.passedScenarios,
      failed_scenarios: sessionResults.failedScenarios,
      passed_steps: sessionResults.passedSteps,
      failed_steps: sessionResults.failedSteps,
      video_url: videoPath, 
    });

    const aiReport = await openAIService.generateTestAnalysis(
      { ...sessionResults, status: 'completed', startTime: startTime.toISOString(), endTime: endTime.toISOString(), duration },
      logs,
      scenarios
    );
    const createdReport = await databaseService.createTestReport({
      session_id: sessionId,
      title: `Test Report for ${url} - ${new Date().toLocaleString()}`,
      summary: aiReport.summary,
      key_findings: aiReport.keyFindings,
      recommendations: aiReport.recommendations,
      risk_level: aiReport.riskAssessment.level,
      risk_assessment_issues: aiReport.riskAssessment.issues,
      performance_metrics: aiReport.performanceMetrics || {},
      quality_score: aiReport.qualityScore || 0
    });
    if (createdReport) {
      io.to(sessionRoom).emit('test-report-update', createdReport);
    }

    const clientResults = {
      total_scenarios: sessionResults.totalScenarios,
      totalScenarios: sessionResults.totalScenarios,
      passed_scenarios: sessionResults.passedScenarios,
      passedScenarios: sessionResults.passedScenarios,
      failed_scenarios: sessionResults.failedScenarios,
      failedScenarios: sessionResults.failedScenarios,
      total_steps: sessionResults.totalSteps,
      totalSteps: sessionResults.totalSteps,
      passed_steps: sessionResults.passedSteps,
      passedSteps: sessionResults.passedSteps,
      failed_steps: sessionResults.failedSteps,
      failedSteps: sessionResults.failedSteps,
      status: 'completed',
    };

    emitLog({ level: 'success', message: '🎉 All test scenarios completed successfully!' });
    io.to(sessionRoom).emit('test-completed', { sessionId, results: clientResults, scenarios: finalScenarios });

  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    io.to(sessionRoom).emit('test-failed', { error: errorMessage });
    emitLog({ level: 'error', message: `❌ Test execution failed: ${errorMessage}` });

    const endTime = new Date();
    const duration = endTime.getTime() - startTime.getTime();
    await databaseService.updateTestSession(sessionId, {
      status: 'failed',
      completed_at: endTime.toISOString(),
      duration,
      passed_scenarios: sessionResults.passedScenarios,
      failed_scenarios: sessionResults.failedScenarios,
      passed_steps: sessionResults.passedSteps,
      failed_steps: sessionResults.failedSteps
    });

  } finally {
    if (browser) {
      await browser.close();
    }
  }
}