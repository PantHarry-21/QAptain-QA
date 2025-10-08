import playwright, { Page, Browser, Locator } from 'playwright-core';
import chromium from '@sparticuz/chromium';
import { v4 as uuidv4 } from 'uuid';
import { databaseService } from '@/lib/database';
import { azureAIService } from './azure-ai';
import { TestLog } from '@/lib/supabase';
import { Server } from 'socket.io';

import { skillFillFormHappyPath } from './skills/fill-form';
import { skillTestFormValidation } from './skills/test-form-validation';
import { getDomContextSelector } from './utils';

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

async function findLocator(page: Page, identifier: string, elementType?: string): Promise<Locator> {
    // Clean the identifier to make it more robust against AI verbosity (e.g., "submit button" -> "submit")
    const cleanedIdentifier = identifier.replace(/\b(tab|button|link|page|the|field|input)\b/gi, '').trim();

    // Use a regex that matches the cleaned identifier, which is more flexible
    const searchRegex = new RegExp(cleanedIdentifier.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i');

    const locators: Locator[] = [
        // Prioritize roles for robustness
        page.getByRole('button', { name: searchRegex }),
        page.getByRole('link', { name: searchRegex }),
        page.getByRole('tab', { name: searchRegex }), // Added tab role
        page.getByRole('checkbox', { name: searchRegex }),
        page.getByRole('radio', { name: searchRegex }),

        // Other common locators
        page.getByLabel(searchRegex),
        page.getByPlaceholder(searchRegex),
        page.getByText(searchRegex),
        
        // Finally, try test IDs with both cleaned and original identifiers
        page.getByTestId(cleanedIdentifier),
        page.getByTestId(identifier),
    ];

    // Add CSS selector if it looks like one (and prioritize it)
    if (identifier.startsWith('#') || identifier.startsWith('.')) {
        locators.unshift(page.locator(identifier));
    }

    // Find the first locator that exists in the DOM
    for (const locator of locators) {
        // Check if any element matches the locator
        if (await locator.count() > 0) {
            // Return the first matching element. The action (.click, .fill) will handle visibility and scrolling.
            return locator.first();
        }
    }

    throw new Error(`Element with identifier \"${identifier}\" not found in the DOM.`);
}

function getLevenshteinDistance(a: string, b: string): number {
    const matrix = Array(b.length + 1).fill(null).map(() => Array(a.length + 1).fill(null));
    for (let i = 0; i <= a.length; i += 1) {
        matrix[0][i] = i;
    }
    for (let j = 0; j < b.length; j += 1) {
        matrix[j + 1][0] = j + 1;
    }
    for (let j = 0; j < b.length; j += 1) {
        for (let i = 0; i < a.length; i += 1) {
            const substitutionCost = a[i] === b[j] ? 0 : 1;
            matrix[j + 1][i + 1] = Math.min(
                matrix[j][i + 1] + 1, // deletion
                matrix[j + 1][i] + 1, // insertion
                matrix[j][i] + substitutionCost // substitution
            );
        }
    }
    return matrix[b.length][a.length];
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
        regex: /^(?:Enter|Type|Fill|Input|Write)\s+['"]?(.+?)['"]?\s+into\s(?:the\s*)?(?!.*?\s(?:with|for)\s(?:placeholder|label|name|aria-label))['"]?(.+?)['"]?$/i,
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

    // LOGIN / SIGN-IN
    {
        regex: /^(?:Login|Log in|Sign in|Sign-in)\s*(?:with|using)?\s*['"]?([^'"]+)['"]?\s*(?:and|\/)?\s*(?:password|pass|pwd)?\s*['"]?([^'"]+)['"]?$/i,
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

function parseStep(step: string): ParsedCommand[] {
    const commands: ParsedCommand[] = [];
    // Split command string by 'then' or 'and then'
    const subSteps = step.split(/\s*,\s*then\s*|\s+and then\s+|\s*;\s*/i);

    for (const subStep of subSteps) {
        if (subStep.trim()) {
            commands.push(parseSingleCommand(subStep));
        }
    }
    return commands;
}

export async function executeSingleCommand(command: ParsedCommand, page: Page, baseUrl: string, sessionId: string, scenarioId: string): Promise<void> {
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
      await page.goto(command.target!, { waitUntil: 'networkidle' });
      break;

    case 'click':
      const locator = await findLocator(page, command.target!); 
      await locator.click({ timeout: 10000 });
      break;

    case 'fill': {
      const { target, value } = command;
      
      // Prioritized list of locators for input fields
      const inputLocators = [
          page.getByLabel(target!),
          page.getByPlaceholder(target!),
          page.locator(`[name="${target!}"]`),
          page.locator(`[id="${target!}"]`)
      ];

      let inputFilled = false;
      for (const locator of inputLocators) {
          try {
              // Let Playwright's auto-scrolling handle visibility.
              // The fill action will wait for the element, scroll it into view, and then fill it.
              await locator.first().fill(value!, { timeout: 5000 });
              inputFilled = true;
              break; // Success, exit the loop
          } catch (e) {
              // This locator failed, so we'll just continue to the next one in the list.
          }
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
    databaseService.createTestLog({ session_id: sessionId, ...fullLog });
  };

  const emitScreenshot = async (page: Page) => {
    try {
      const screenshot = await page.screenshot({ type: 'png' });
      io.to(sessionRoom).emit('browser-view-update', `data:image/png;base64,${screenshot.toString('base64')}`);
    } catch (e) {}
  };

  let sessionResults = {
    totalScenarios: scenarios.length,
    passedScenarios: 0,
    failedScenarios: 0,
    totalSteps: scenarios.reduce((sum, scenario) => sum + scenario.steps.length, 0),
    passedSteps: 0,
    failedSteps: 0
  };
  const scenarioIds = scenarios.map(s => s.id);
  await databaseService.updateTestSession(sessionId, { selected_scenario_ids: scenarioIds });

  try {
    emitLog({ level: 'info', message: `Initializing test session with Playwright...` });

    const isVercel = process.env.VERCEL || process.env.LAMBDA_TASK_ROOT;
    emitLog({ level: 'info', message: `Environment detected as ${isVercel ? 'Vercel' : 'Local'}.` });

    if (isVercel) {
      emitLog({ level: 'info', message: 'Launching browser with @sparticuz/chromium for serverless environment.' });
      browser = await playwright.chromium.launch({
        args: chromium.args,
        executablePath: await chromium.executablePath(),
        headless: chromium.headless,
      });
    } else {
      emitLog({ level: 'info', message: 'Launching browser with local Playwright installation.' });
      browser = await playwright.chromium.launch({
        headless: true
      });
    }
    const context = await browser.newContext({
      recordVideo: { dir: `videos/${sessionId}` }
    });
    const page = await context.newPage();

    emitLog({ level: 'info', message: `Playwright browser initialized. Starting execution for ${scenarios.length} scenarios.` });
    await emitScreenshot(page);

    for (let i = 0; i < scenarios.length; i++) {
      const scenario = scenarios[i];
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
          totalScenarios: scenarios.length,
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
                  
                  const formInputs = activeContext.querySelectorAll('input:not([type="hidden"]):not([type="submit"]), textarea, select');
                  const isFormVisible = formInputs.length > 2;

                  const visibleButtons = Array.from(activeContext.querySelectorAll('button')).map(btn => btn.textContent?.trim() || '').filter(text => text.length > 0 && text.length < 100);
                  const visibleLinks = Array.from(activeContext.querySelectorAll('a')).map(a => a.textContent?.trim() || '').filter(text => text.length > 0 && text.length < 100);
                  
                  return { isFormVisible, visibleButtons, visibleLinks, contextType: selector === 'body' ? 'document' : 'modal' };
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
              const plan = await azureAIService.createWorkflowPlan(stepDescription, pageContext);
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
                  case 'TEST_FORM_VALIDATION':
                    await skillTestFormValidation(page);
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
                completed_at: new Date().toISOString(),
                duration: scenarioDuration
              };
              emitLog({ level: 'success', message: `✅ Scenario completed: "${scenario.title}"`, scenario_id: scenario.id });
            } else {
              sessionResults.failedScenarios++;
              updatePayload = {
                status: 'failed',
                completed_at: new Date().toISOString(),
                duration: scenarioDuration,
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
                const scenarioAnalysis = await azureAIService.analyzeScenario(scenario, scenarioLogs);
        
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

    const aiReport = await azureAIService.generateTestAnalysis(
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

    emitLog({ level: 'success', message: '🎉 All test scenarios completed successfully!' });
    io.to(sessionRoom).emit('test-completed', { sessionId, results: sessionResults, scenarios: finalScenarios });

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