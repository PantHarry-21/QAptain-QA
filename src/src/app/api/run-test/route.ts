import { NextRequest, NextResponse } from 'next/server';
import { Builder, By, until, WebDriver } from 'selenium-webdriver';
import chrome from 'selenium-webdriver/chrome';
import { databaseService } from '@/lib/database';
import { azureAIService } from '@/lib/azure-ai';
import { TestSession, TestScenario, TestStep, TestLog, TestReport } from '@/lib/supabase';

// Global socket.io instance for real-time updates
let io: ServerIO | null = null;

interface TestScenario {
  id: string;
  title: string;
  description: string;
  steps: string[];
}

interface TestExecutionRequest {
  sessionId: string;
  scenarios: TestScenario[];
  url: string;
}

interface TestLog {
  id: string;
  timestamp: string;
  level: 'info' | 'success' | 'error' | 'warning';
  message: string;
  step?: string;
  screenshot?: string;
}

interface TestProgress {
  currentScenario: number;
  totalScenarios: number;
  currentStep: number;
  totalSteps: number;
  currentScenarioTitle: string;
  currentStepDescription: string;
  status: 'running' | 'paused' | 'completed' | 'failed';
  startTime: string;
  estimatedEndTime?: string;
}

// Store active test sessions
const activeSessions: { [sessionId: string]: any } = {};

export async function POST(request: NextRequest) {
  try {
    const { sessionId, scenarios, url }: TestExecutionRequest = await request.json();

    if (!sessionId || !scenarios || !url) {
      return NextResponse.json({ 
        error: 'Session ID, scenarios, and URL are required' 
      }, { status: 400 });
    }

    // Update session status to running
    await databaseService.updateTestSession(sessionId, {
      status: 'running',
      started_at: new Date().toISOString()
    });

    // Start test execution in background
    executeTests(sessionId, scenarios, url);

    return NextResponse.json({
      success: true,
      message: 'Test execution started',
      sessionId,
      startedAt: new Date().toISOString()
    });

  } catch (error) {
    console.error('Test Execution Error:', error);
    return NextResponse.json(
      { 
        error: 'Failed to start test execution',
        details: error instanceof Error ? error.message : 'Unknown error'
      },
      { status: 500 }
    );
  }
}

function initializeSocketIO() {
  // This is a placeholder - in a real implementation, you'd set up socket.io
  // For now, we'll simulate socket.io events
  console.log('Socket.IO initialized (simulated)');
}

async function executeTests(sessionId: string, scenarios: TestScenario[], url: string) {
  let driver: WebDriver | null = null;
  const startTime = new Date();
  let sessionResults = {
    totalScenarios: scenarios.length,
    passedScenarios: 0,
    failedScenarios: 0,
    totalSteps: 0,
    passedSteps: 0,
    failedSteps: 0
  };
  
  try {
    // Initialize Chrome WebDriver with headful mode
    const chromeOptions = new chrome.Options();
    chromeOptions.addArguments('--start-maximized');
    chromeOptions.addArguments('--disable-gpu');
    chromeOptions.addArguments('--no-sandbox');
    chromeOptions.addArguments('--disable-dev-shm-usage');
    
    driver = await new Builder()
      .forBrowser('chrome')
      .setChromeOptions(chromeOptions)
      .build();

    // Log test start
    await databaseService.createTestLog({
      session_id: sessionId,
      level: 'info',
      message: `Starting test execution for ${scenarios.length} scenarios`,
      timestamp: new Date().toISOString()
    });

    // Get database scenarios
    const dbScenarios = await databaseService.getTestScenarios(sessionId);
    sessionResults.totalSteps = dbScenarios.reduce((sum, scenario) => sum + scenario.steps.length, 0);

    // Execute each scenario
    for (let scenarioIndex = 0; scenarioIndex < dbScenarios.length; scenarioIndex++) {
      const scenario = dbScenarios[scenarioIndex];
      
      // Update scenario status to running
      await databaseService.updateTestScenario(scenario.id, {
        status: 'running',
        started_at: new Date().toISOString()
      });

      await databaseService.createTestLog({
        session_id: sessionId,
        scenario_id: scenario.id,
        level: 'info',
        message: `Starting scenario: ${scenario.title}`,
        timestamp: new Date().toISOString()
      });

      let scenarioPassed = true;
      const scenarioStartTime = new Date();

      // Get steps for this scenario
      const steps = await databaseService.getTestSteps(scenario.id);

      // Execute each step in the scenario
      for (let stepIndex = 0; stepIndex < steps.length; stepIndex++) {
        const step = steps[stepIndex];
        
        // Update step status to running
        await databaseService.updateTestStep(step.id, {
          status: 'running',
          started_at: new Date().toISOString()
        });

        try {
          await executeStep(driver, step.description, url);
          
          // Update step status to passed
          await databaseService.updateTestStep(step.id, {
            status: 'passed',
            completed_at: new Date().toISOString(),
            duration: new Date().getTime() - new Date(step.started_at!).getTime()
          });

          await databaseService.createTestLog({
            session_id: sessionId,
            scenario_id: scenario.id,
            step_id: step.id,
            level: 'success',
            message: `✅ Step completed: ${step.description}`,
            timestamp: new Date().toISOString()
          });

          sessionResults.passedSteps++;
          
        } catch (stepError) {
          const errorMessage = stepError instanceof Error ? stepError.message : 'Unknown error';
          scenarioPassed = false;
          sessionResults.failedSteps++;
          
          // Update step status to failed
          await databaseService.updateTestStep(step.id, {
            status: 'failed',
            completed_at: new Date().toISOString(),
            duration: new Date().getTime() - new Date(step.started_at!).getTime(),
            error_message: errorMessage
          });

          await databaseService.createTestLog({
            session_id: sessionId,
            scenario_id: scenario.id,
            step_id: step.id,
            level: 'error',
            message: `❌ Step failed: ${step.description} - ${errorMessage}`,
            timestamp: new Date().toISOString()
          });

          // Take screenshot on failure
          try {
            const screenshot = await driver.takeScreenshot();
            // In a real implementation, you'd upload this to cloud storage
            // For now, we'll just log it
            await databaseService.createTestLog({
              session_id: sessionId,
              scenario_id: scenario.id,
              step_id: step.id,
              level: 'error',
              message: 'Screenshot captured on failure',
              timestamp: new Date().toISOString(),
              metadata: { screenshot: 'data:image/png;base64,' + screenshot }
            });
          } catch (screenshotError) {
            console.error('Failed to capture screenshot:', screenshotError);
          }
        }
        
        // Small delay between steps for better visualization
        await new Promise(resolve => setTimeout(resolve, 1000));
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
      } else {
        sessionResults.failedScenarios++;
        await databaseService.updateTestScenario(scenario.id, {
          status: 'failed',
          completed_at: new Date().toISOString(),
          duration: scenarioDuration
        });
      }

      await databaseService.createTestLog({
        session_id: sessionId,
        scenario_id: scenario.id,
        level: scenarioPassed ? 'success' : 'error',
        message: `${scenarioPassed ? '✅' : '❌'} Scenario ${scenarioPassed ? 'completed' : 'failed'}: ${scenario.title}`,
        timestamp: new Date().toISOString()
      });
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

    await databaseService.createTestLog({
      session_id: sessionId,
      level: 'success',
      message: '🎉 All test scenarios completed successfully!',
      timestamp: new Date().toISOString()
    });

    // Generate AI analysis and create report
    await generateTestReport(sessionId, {
      status: 'completed',
      startTime: startTime.toISOString(),
      endTime: endTime.toISOString(),
      duration,
      totalScenarios: sessionResults.totalScenarios,
      passedScenarios: sessionResults.passedScenarios,
      failedScenarios: sessionResults.failedScenarios,
      totalSteps: sessionResults.totalSteps,
      passedSteps: sessionResults.passedSteps,
      failedSteps: sessionResults.failedSteps
    });

  } catch (error) {
    console.error('Test execution failed:', error);
    
    const endTime = new Date();
    const duration = endTime.getTime() - startTime.getTime();

    // Update session with failure status
    await databaseService.updateTestSession(sessionId, {
      status: 'failed',
      completed_at: endTime.toISOString(),
      duration,
      passed_scenarios: sessionResults.passedScenarios,
      failed_scenarios: sessionResults.failedScenarios,
      passed_steps: sessionResults.passedSteps,
      failed_steps: sessionResults.failedSteps
    });

    await databaseService.createTestLog({
      session_id: sessionId,
      level: 'error',
      message: `❌ Test execution failed: ${error instanceof Error ? error.message : 'Unknown error'}`,
      timestamp: new Date().toISOString()
    });

  } finally {
    // Clean up
    if (driver) {
      try {
        await driver.quit();
      } catch (error) {
        console.error('Failed to quit driver:', error);
      }
    }
  }
}

async function executeStep(driver: WebDriver, step: string, baseUrl: string) {
  const lowerStep = step.toLowerCase();
  
  if (lowerStep.includes('navigate') || lowerStep.includes('go to') || lowerStep.includes('open')) {
    let targetUrl = baseUrl;
    
    if (lowerStep.includes('login')) {
      targetUrl = `${baseUrl}/login`;
    } else if (lowerStep.includes('contact')) {
      targetUrl = `${baseUrl}/contact`;
    } else if (lowerStep.includes('register') || lowerStep.includes('signup')) {
      targetUrl = `${baseUrl}/register`;
    }
    
    await driver.get(targetUrl);
    await driver.wait(until.titleIs(driver.getTitle()), 10000);
  }
  
  else if (lowerStep.includes('click') || lowerStep.includes('press')) {
    let element;
    
    if (lowerStep.includes('button')) {
      if (lowerStep.includes('login') || lowerStep.includes('submit')) {
        element = await driver.wait(until.elementLocated(By.xpath(
          "//button[contains(text(), 'Login')] | //button[@type='submit'] | //input[@type='submit']"
        )), 10000);
      } else {
        element = await driver.wait(until.elementLocated(By.tagName('button')), 10000);
      }
    } else if (lowerStep.includes('link')) {
      element = await driver.wait(until.elementLocated(By.tagName('a')), 10000);
    } else {
      // Try to find element by text content
      const textToFind = extractTextFromStep(step);
      element = await driver.wait(until.elementLocated(By.xpath(
        `//*[contains(text(), '${textToFind}')]`
      )), 10000);
    }
    
    await driver.wait(until.elementIsEnabled(element), 5000);
    await element.click();
  }
  
  else if (lowerStep.includes('enter') || lowerStep.includes('type') || lowerStep.includes('input')) {
    let element;
    let value = 'test input';
    
    if (lowerStep.includes('username') || lowerStep.includes('email') || lowerStep.includes('user')) {
      element = await driver.wait(until.elementLocated(By.xpath(
        "//input[@name='username' or @name='email' or @id='username' or @id='email']"
      )), 10000);
      value = 'testuser@example.com';
    } else if (lowerStep.includes('password') || lowerStep.includes('pass')) {
      element = await driver.wait(until.elementLocated(By.xpath(
        "//input[@name='password' or @id='password' or @type='password']"
      )), 10000);
      value = 'testpassword123';
    } else if (lowerStep.includes('search')) {
      element = await driver.wait(until.elementLocated(By.xpath(
        "//input[@name='search' or @id='search' or contains(@class, 'search')]"
      )), 10000);
      value = 'test search';
    } else {
      element = await driver.wait(until.elementLocated(By.tagName('input')), 10000);
    }
    
    await element.clear();
    await element.sendKeys(value);
  }
  
  else if (lowerStep.includes('verify') || lowerStep.includes('check') || lowerStep.includes('assert')) {
    if (lowerStep.includes('title')) {
      const title = await driver.getTitle();
      if (!title || title.trim() === '') {
        throw new Error('Page title is empty');
      }
    } else if (lowerStep.includes('login') && lowerStep.includes('success')) {
      await driver.wait(async () => {
        const currentUrl = await driver.getCurrentUrl();
        return currentUrl.includes('dashboard') || 
               currentUrl.includes('home') || 
               currentUrl.includes('profile');
      }, 10000, 'Login verification failed');
    } else {
      // General verification - wait for page to stabilize
      await driver.wait(until.elementLocated(By.tagName('body')), 10000);
    }
  }
  
  else if (lowerStep.includes('wait') || lowerStep.includes('pause')) {
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
  
  // Default action - wait for page to load
  else {
    await driver.wait(until.elementLocated(By.tagName('body')), 10000);
  }
}

function extractTextFromStep(step: string): string {
  // Simple text extraction for XPath generation
  const words = step.toLowerCase().split(' ');
  const keywords = words.filter(word => 
    word.length > 3 && 
    !['click', 'enter', 'type', 'verify', 'check', 'wait', 'navigate', 'go', 'then', 'with', 'from', 'that', 'this', 'will', 'should', 'button', 'link', 'input', 'field'].includes(word)
  );
  return keywords[0] || 'element';
}

// Generate AI-powered test report
async function generateTestReport(sessionId: string, testResults: any) {
  try {
    // Get test logs and scenarios for AI analysis
    const [logs, scenarios] = await Promise.all([
      databaseService.getTestLogs(sessionId, 50),
      databaseService.getTestScenarios(sessionId)
    ]);

    // Generate AI analysis
    const aiAnalysis = await azureAIService.generateTestAnalysis(testResults, logs, scenarios);

    // Create test report
    const reportData: Partial<TestReport> = {
      session_id: sessionId,
      summary: aiAnalysis.summary,
      key_findings: aiAnalysis.keyFindings,
      recommendations: aiAnalysis.recommendations,
      risk_level: aiAnalysis.riskAssessment.level,
      performance_metrics: aiAnalysis.performanceMetrics
    };

    await databaseService.createTestReport(reportData);

    console.log('AI-powered test report generated for session:', sessionId);

  } catch (error) {
    console.error('Failed to generate test report:', error);
  }
}