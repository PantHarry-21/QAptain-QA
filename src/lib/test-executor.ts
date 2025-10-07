import { chromium, Page, Browser, Locator } from 'playwright';
import { v4 as uuidv4 } from 'uuid';
import { databaseService } from '@/lib/database';
import { azureAIService } from '@/lib/azure-ai';
import { TestLog } from '@/lib/supabase';
import { Server } from 'socket.io';

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
  // 1. CSS Selector (if it looks like one)
  if(identifier.startsWith('#') || identifier.startsWith('.')){
    const loc = page.locator(identifier);
    if(await loc.count() > 0) return loc.first();
  }

  // 2. By Role (for buttons, links, etc. - good for clicks)
  let locator = page.getByRole('button', { name: new RegExp(identifier, 'i') });
  if (await locator.count() > 0 && await locator.first().isVisible()) {
    return locator.first();
  }
  locator = page.getByRole('link', { name: new RegExp(identifier, 'i') });
  if (await locator.count() > 0 && await locator.first().isVisible()) {
    return locator.first();
  }

  // 3. By Label (great for form inputs)
  locator = page.getByLabel(new RegExp(identifier, 'i'));
  if (await locator.count() > 0) {
    return locator.first();
  }

  // 4. By Placeholder (great for form inputs)
  locator = page.getByPlaceholder(new RegExp(identifier, 'i'));
  if (await locator.count() > 0) {
    return locator.first();
  }
  
  // 5. By Text (general fallback)
  locator = page.getByText(new RegExp(identifier, 'i'));
  if (await locator.count() > 0 && await locator.first().isVisible()) {
    return locator.first();
  }

  throw new Error(`Element with identifier "${identifier}" not found.`);
}

// --- Command Definitions ---

const commandDefinitions: CommandDefinition[] = [
    // FILL WITH ATTRIBUTE (placeholder, label, name)
    {
        regex: /^(?:Enter|Type|Fill|Input|Write)\s+['"]?(.+?)['"]?\s+(?:in|into|at)?\s*(?:the)?\s*(?:input|field|textbox|textarea)?\s*(?:with\s+(placeholder|label|name|aria-label))\s+['"]?(.+?)['"]?$/i,
        parser: m => ({ type: 'fill', value: m[1], attribute: m[2], target: m[3] })
    },

    // CONDITIONAL LOGIC
    {
        regex: /^If\s+(?:the\s+)?(?:text\s+)?['"]?(.+?)['"]?\s+(?:is\s+visible|appears|exists|is\s+present),?\s*(?:then\s+)?(.+)$/i,
        parser: m => ({
            type: 'conditional',
            target: { step: `Verify text "${m[1]}" is visible` },
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
        regex: /^(?:Click|Press|Tap|Select)\s*(?:the)?\s*(?:button|link|element)?\s*(?:named|called|with\s+text|with\s+label|with\s+selector)?\s*['"]?(.+?)['"]?$/i,
        parser: m => ({ type: 'click', target: m[1].trim() })
    },

    // LOGIN / SIGN-IN
    {
        regex: /^(?:Login|Log in|Sign in|Sign-in)\s*(?:with|using)?\s*['"]?([^'"+]+)['"]?\s*(?:and|\/)?\s*(?:password|pass|pwd)?\s*['"]?([^'"+]+)['"]?$/i,
        parser: m => ({ type: 'login', username: m[1], password: m[2] })
    },

    // FILL / TYPE / INPUT (GENERIC)
    {
        regex: /^(?:Type|Enter|Fill|Input|Write)\s+['"]?(.+?)['"]?\s+(?:in|into|to|at)?\s*(?:the)?\s*(?:input\s+field|input|field|textbox|textarea)?\s*(?:named|called|with\s+(?:label|placeholder|name))?\s*['"]?(.+?)['"]?$/i,
        parser: m => ({ type: 'fill', value: m[1], target: m[2] })
    },

    // ASSERTIONS — VISIBILITY
    {
        regex: /^(?:Verify|Assert|Check)(?:\s+that)?\s*(?:the\s+)?(?:element|text|label)?\s*['"]?(.+?)['"]?\s+(?:is\s+visible|appears|exists|is\s+present)$/i,
        parser: m => ({ type: 'assertVisible', target: m[1] })
    },

    // ASSERTIONS — CONTENT
    {
        regex: /^(?:Verify|Assert|Check)\s*(?:that\s+)?(?:element|text|page)?\s*['"]?(.+?)['"]?\s*contains(?:\s+text)?\s*['"]?(.+?)['"]?$/i,
        parser: m => (
            m[1].toLowerCase() === 'page'
                ? { type: 'assertPageContains', value: m[2] }
                : { type: 'assertTextContains', target: m[1], value: m[2] }
        )
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

function parseSingleCommand(step: string): ParsedCommand {
    const trimmedStep = step.trim();
    for (const def of commandDefinitions) {
        const matches = trimmedStep.match(def.regex);
        if (matches) {
            return def.parser(matches);
        }
    }
    throw new Error(`QAPTAIN PARSER FAILED ON STEP: "${trimmedStep}"`);
}

function parseStep(step: string): ParsedCommand[] {
    const commands: ParsedCommand[] = [];
    const subSteps = step.split(/\s*,\s*then\s*|\s+and then\s+|\s*;\s*/i);

    for (const subStep of subSteps) {
        if (subStep.trim()) {
            commands.push(parseSingleCommand(subStep));
        }
    }
    return commands;
}

async function executeSingleCommand(command: ParsedCommand, page: Page, baseUrl: string, sessionId: string, scenarioId: string): Promise<void> {
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
      await locator.click();
      break;

    case 'fill':
      let targetLocator;
      const locatorType = command.attribute;
      const identifier = command.target!;

      if (locatorType === 'placeholder') {
        targetLocator = page.getByPlaceholder(new RegExp(identifier, 'i'));
      } else if (locatorType === 'label' || locatorType === 'name') {
        targetLocator = page.getByLabel(new RegExp(identifier, 'i'));
      } else {
        targetLocator = await findLocator(page, identifier);
      }
      await targetLocator.fill(command.value!);
      break;

    case 'assertVisible':
        await findLocator(page, command.target!); 
        break;

    case 'assertPageContains':
        await page.locator(`body:has-text("${command.value}")`).waitFor();
        break;

    case 'assertTextContains':
        const element = await findLocator(page, command.target!)
        await element.filter({ hasText: new RegExp(command.value, 'i') }).waitFor();
        break;

    case 'assertValue':
        const input = await findLocator(page, command.target!)
        const value = await input.inputValue();
        if (value !== command.value) {
            throw new Error(`Expected input "${command.target}" to have value "${command.value}", but it was "${value}"`);
        }
        break;

    case 'checkUncheck':
      const checkbox = await findLocator(page, command.target!); 
      if (command.action.startsWith('check') || command.action.startsWith('tick')) await checkbox.check();
      else await checkbox.uncheck();
      break;

    case 'login':
        const emailField = await findLocator(page, 'email');
        await emailField.fill(command.username!); 
        const passwordField = await findLocator(page, 'password');
        await passwordField.fill(command.password!);
        await page.getByRole('button', { name: /sign in|login/i }).click();
        break;

    case 'conditional':
        try {
            await executeStep(page, command.target.step, baseUrl, sessionId, scenarioId);
            await executeStep(page, command.value.step, baseUrl, sessionId, scenarioId);
        } catch (error) {
            console.log(`Conditional step skipped: ${command.target.step}`);
        }
        break;

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

    browser = await chromium.launch({ headless: true });
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

      await databaseService.updateTestScenario(scenario.id, {
        status: 'running',
        started_at: scenarioStartTime.toISOString()
      });
      const updatedScenario = await databaseService.getTestScenarios(scenario.id);
      if (updatedScenario) {
        io.to(sessionRoom).emit('test-scenario-update', updatedScenario);
      }

      emitLog({ level: 'info', message: `Starting scenario: "${scenario.title}"`, scenario_id: scenario.id });

      emitLog({ level: 'info', message: `Resetting to base URL: ${url}` });
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
            await executeStep(page, stepDescription, url, sessionId, scenario.id);
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
      if (scenarioPassed) {
        sessionResults.passedScenarios++;
        const updatedScenario = await databaseService.updateTestScenario(scenario.id, {
          status: 'passed',
          completed_at: new Date().toISOString(),
          duration: scenarioDuration
        });
        if (updatedScenario) {
          io.to(sessionRoom).emit('test-scenario-update', updatedScenario);
        }
        emitLog({ level: 'success', message: `✅ Scenario completed: "${scenario.title}"`, scenario_id: scenario.id });
      } else {
        sessionResults.failedScenarios++;
        const updatedScenario = await databaseService.updateTestScenario(scenario.id, {
          status: 'failed',
          completed_at: new Date().toISOString(),
          duration: scenarioDuration,
          error_message: `Scenario failed due to step error.`
        });
        if (updatedScenario) {
          io.to(sessionRoom).emit('test-scenario-update', updatedScenario);
        }
        emitLog({ level: 'error', message: `❌ Scenario failed: "${scenario.title}"`, scenario_id: scenario.id });
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
    io.to(sessionRoom).emit('test-completed', { sessionId, results: sessionResults });

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