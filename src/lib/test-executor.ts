import { Builder, By, until, WebDriver } from 'selenium-webdriver';
import chrome from 'selenium-webdriver/chrome';
import path from 'path';
import { v4 as uuidv4 } from 'uuid';
import { databaseService } from '@/lib/database';
import { azureAIService } from '@/lib/azure-ai';
import { TestLog } from '@/lib/supabase';
import { Server } from 'socket.io';

// --- Command Parser Definition ---
// This section defines the strict set of commands the executor can understand.
// Each command has a regex to parse the natural language step and an action to execute it.

const commands = [
  {
    // Matches: "Navigate to the homepage" or "Navigate to the login page"
    regex: /^Navigate to the (homepage|login page|contact page|register page)/i,
    action: async (driver: WebDriver, baseUrl: string, matches: RegExpMatchArray) => {
      const page = matches[1].toLowerCase();
      const urlObject = new URL(baseUrl);

      if (page.includes('homepage')) {
        urlObject.pathname = '/';
      } else if (page.includes('login')) {
        urlObject.pathname = '/login';
      } else if (page.includes('contact')) {
        urlObject.pathname = '/contact';
      } else if (page.includes('register')) {
        urlObject.pathname = '/register';
      }
      await driver.get(urlObject.toString());
    }
  },
  {
    // Matches: "Click the button/link with text "some text""
    regex: /^Click the (button|link) with text "([^"]+)"/i,
    action: async (driver: WebDriver, baseUrl: string, matches: RegExpMatchArray) => {
      const elementType = matches[1].toLowerCase();
      const text = matches[2];
      const selector = elementType === 'button' ? `//button[contains(., '${text}')]` : `//a[contains(., '${text}')]`;
      const element = await driver.wait(until.elementLocated(By.xpath(selector)), 10000);
      await driver.wait(until.elementIsEnabled(element), 5000);
      await element.click();
    }
  },
  {
    // Matches: "Enter "some text" into the input field with placeholder/name "some_value""
    regex: /^Enter "([^"]+)" into the input field with (placeholder|name) "([^"]+)"/i,
    action: async (driver: WebDriver, baseUrl: string, matches: RegExpMatchArray) => {
      const value = matches[1];
      const attributeType = matches[2].toLowerCase();
      const attributeValue = matches[3];
      const selector = `//input[@${attributeType}='${attributeValue}'] | //textarea[@${attributeType}='${attributeValue}']`;
      const element = await driver.wait(until.elementLocated(By.xpath(selector)), 10000);
      await element.clear();
      await element.sendKeys(value);
    }
  },
  {
    // Matches: "Verify the page title contains "some text""
    regex: /^Verify the page title contains "([^"]+)"/i,
    action: async (driver: WebDriver, baseUrl: string, matches: RegExpMatchArray) => {
      const expectedTitle = matches[1];
      await driver.wait(until.titleContains(expectedTitle), 10000, `Title did not contain "${expectedTitle}"`);
    }
  },
  {
    // Matches: "Verify the page contains the text "some text""
    regex: /^Verify the page contains the text "([^"]+)"/i,
    action: async (driver: WebDriver, baseUrl: string, matches: RegExpMatchArray) => {
      const text = matches[1];
      const selector = `//*[contains(., '${text}')]`;
      await driver.wait(until.elementLocated(By.xpath(selector)), 10000, `Could not find element with text "${text}"`);
    }
  },
  {
    // Matches: "Wait for 2 seconds" (now handles singular 'second' too)
    regex: /^Wait for (\d+) second(s)?/i,
    action: async (driver: WebDriver, baseUrl: string, matches: RegExpMatchArray) => {
      const seconds = parseInt(matches[1], 10);
      await new Promise(resolve => setTimeout(resolve, seconds * 1000));
    }
  }
];

async function executeStep(driver: WebDriver, step: string, baseUrl: string) {
  const trimmedStep = step.trim(); // Trim the step here
  for (const command of commands) {
    const matches = trimmedStep.match(command.regex);
    if (matches) {
      await command.action(driver, baseUrl, matches);
      return; // Stop after the first matching command
    }
  }
  // If no command matched, throw an error.
  throw new Error(`Unknown or malformed step action: "${trimmedStep}"`);
}


// --- Test Execution Engine ---

export async function executeTests(io: Server, sessionId: string, scenarios: any[], url: string) {
  let driver: WebDriver | null = null;
  const startTime = new Date();
  const sessionRoom = `session-${sessionId}`;
  const MAX_STEP_RETRIES = 1; // 1 retry means 2 attempts total

  // Helper to emit logs to both client and database
  const emitLog = (log: Partial<TestLog>) => {
    const fullLog = { ...log, id: uuidv4(), timestamp: new Date().toISOString() };
    io.to(sessionRoom).emit('test-log', fullLog);
    databaseService.createTestLog({ session_id: sessionId, ...fullLog });
  };

  const emitScreenshot = async (driverInstance: WebDriver) => {
    try {
      const screenshot = await driverInstance.takeScreenshot();
      io.to(sessionRoom).emit('browser-view-update', `data:image/png;base64,${screenshot}`);
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
  let completedSteps = 0;

  try {
    emitLog({ level: 'info', message: `Initializing test session...` });

    const chromeDriverPath = path.join(process.cwd(), 'chromedriver.exe');
    const service = new chrome.ServiceBuilder(chromeDriverPath);
    const chromeOptions = new chrome.Options().addArguments('--start-maximized', '--disable-gpu', '--no-sandbox', '--disable-dev-shm-usage');
    driver = await new Builder().forBrowser('chrome').setChromeService(service).setChromeOptions(chromeOptions).build();

    emitLog({ level: 'info', message: `WebDriver initialized. Starting execution for ${scenarios.length} scenarios.` });
    await emitScreenshot(driver);

    for (let i = 0; i < scenarios.length; i++) {
      const scenario = scenarios[i];
      const scenarioStartTime = new Date();
      let scenarioPassed = true;

      // Update scenario status to running
      await databaseService.updateTestScenario(scenario.id, {
        status: 'running',
        started_at: scenarioStartTime.toISOString()
      });

      emitLog({ level: 'info', message: `Starting scenario: "${scenario.title}"` });

      emitLog({ level: 'info', message: `Resetting to base URL: ${url}` });
      await driver.get(url);
      await emitScreenshot(driver);

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
              emitLog({ level: 'warning', message: `Retrying step: ${stepDescription} (Attempt ${retry + 1}/${MAX_STEP_RETRIES + 1})` });
              await new Promise(resolve => setTimeout(resolve, 1000)); // Small delay before retry
            }
            await executeStep(driver, stepDescription, url);
            await emitScreenshot(driver);
            emitLog({ level: 'success', message: `✅ Step completed: ${stepDescription}` });
            sessionResults.passedSteps++;
            stepPassed = true;
            break; // Step succeeded, break retry loop
          } catch (stepError) {
            lastError = stepError;
            emitLog({ level: 'warning', message: `Step failed: ${stepDescription} - ${stepError instanceof Error ? stepError.message : 'Unknown error'}` });
            await emitScreenshot(driver); // Screenshot on failure
          }
        }

        if (!stepPassed) {
          const errorMessage = lastError instanceof Error ? lastError.message : 'Unknown error';
          scenarioPassed = false;
          sessionResults.failedSteps++;
          emitLog({ level: 'error', message: `❌ Step failed after ${MAX_STEP_RETRIES + 1} attempts: ${stepDescription} - ${errorMessage}` });
          break; // Exit step loop if step fails after all retries
        }
        await new Promise(resolve => setTimeout(resolve, 500));
      }

      // Update scenario status based on results
      const scenarioDuration = new Date().getTime() - scenarioStartTime.getTime();
      if (scenarioPassed) {
        sessionResults.passedScenarios++;
        await databaseService.updateTestScenario(scenario.id, {
          status: 'passed',
          completed_at: new Date().toISOString(),
          duration: scenarioDuration
        });
        emitLog({ level: 'success', message: `✅ Scenario completed: "${scenario.title}"` });
      } else {
        sessionResults.failedScenarios++;
        await databaseService.updateTestScenario(scenario.id, {
          status: 'failed',
          completed_at: new Date().toISOString(),
          duration: scenarioDuration,
          error_message: `Scenario failed due to step error.`
        });
        emitLog({ level: 'error', message: `❌ Scenario failed: "${scenario.title}"` });
      }
    }

    // All tests completed successfully
    const endTime = new Date();
    const duration = endTime.getTime() - startTime.getTime();

    // Update session with final results
    await databaseService.updateTestSession(sessionId, {
      status: 'completed',
      completed_at: endTime.toISOString(),
      duration,
      passed_scenarios: sessionResults.passedScenarios,
      failed_scenarios: sessionResults.failedScenarios,
      passed_steps: sessionResults.passedSteps,
      failed_steps: sessionResults.failedSteps
    });

    // Generate AI analysis and create report
    await azureAIService.generateTestAnalysis(
      { ...sessionResults, status: 'completed', startTime: startTime.toISOString(), endTime: endTime.toISOString(), duration },
      [], // logs will be fetched by the service
      []  // scenarios will be fetched by the service
    );

    emitLog({ level: 'success', message: '🎉 All test scenarios completed successfully!' });
    io.to(sessionRoom).emit('test-completed', { sessionId, results: sessionResults });

  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    io.to(sessionRoom).emit('test-failed', { error: errorMessage });
    emitLog({ level: 'error', message: `❌ Test execution failed: ${errorMessage}` });

    // Ensure session status is updated even on overall failure
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
    if (driver) {
      await driver.quit();
    }
  }
}
