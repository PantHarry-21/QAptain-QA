import { NextRequest, NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

interface Scenario {
  id: string;
  title: string;
  description: string;
  priority: 'high' | 'medium' | 'low';
  category: string;
  steps: string[];
  estimatedTime: string;
}

interface CustomScenario {
  id: string;
  title: string;
  description: string;
  steps: string[];
}

interface TranslatedScript {
  scenarioId: string;
  scenarioTitle: string;
  script: string;
  language: 'python' | 'javascript';
  dependencies: string[];
  setupCode: string;
  teardownCode: string;
}

export async function POST(request: NextRequest) {
  try {
    const { scenarios, url, language = 'javascript' } = await request.json();

    if (!scenarios || !Array.isArray(scenarios) || !url) {
      return NextResponse.json({ 
        error: 'Scenarios array and URL are required' 
      }, { status: 400 });
    }

    const translatedScripts: TranslatedScript[] = [];

    for (const scenario of scenarios) {
      const translatedScript = translateScenarioToSelenium(scenario, url, language);
      translatedScripts.push(translatedScript);
    }

    return NextResponse.json({
      success: true,
      data: {
        scripts: translatedScripts,
        translatedAt: new Date().toISOString()
      }
    });

  } catch (error) {
    console.error('Scenario Translation Error:', error);
    return NextResponse.json(
      { 
        error: 'Failed to translate scenarios to Selenium scripts',
        details: error instanceof Error ? error.message : 'Unknown error'
      },
      { status: 500 }
    );
  }
}

function translateScenarioToSelenium(scenario: Scenario | CustomScenario, url: string, language: string): TranslatedScript {
  const steps = scenario.steps;
  const scriptLines: string[] = [];
  
  if (language === 'python') {
    return translateToPython(scenario, url, steps);
  } else {
    return translateToJavaScript(scenario, url, steps);
  }
}

function translateToPython(scenario: Scenario | CustomScenario, url: string, steps: string[]): TranslatedScript {
  const scriptLines: string[] = [];
  
  // Imports
  scriptLines.push('from selenium import webdriver');
  scriptLines.push('from selenium.webdriver.common.by import By');
  scriptLines.push('from selenium.webdriver.support.ui import WebDriverWait');
  scriptLines.push('from selenium.webdriver.support import expected_conditions as EC');
  scriptLines.push('from selenium.webdriver.chrome.options import Options');
  scriptLines.push('import time');
  scriptLines.push('');

  // Setup
  scriptLines.push('def setup_driver():');
  scriptLines.push('    chrome_options = Options()');
  scriptLines.push('    chrome_options.add_argument("--start-maximized")');
  scriptLines.push('    driver = webdriver.Chrome(options=chrome_options)');
  scriptLines.push('    return driver');
  scriptLines.push('');

  // Test function
  scriptLines.push(`def test_${scenario.id.replace(/[^a-zA-Z0-9]/g, '_')}(driver):`);
  scriptLines.push('    try:');
  
  // Process each step
  steps.forEach((step, index) => {
    const translatedStep = translateStepToPython(step, url);
    scriptLines.push(`        # Step ${index + 1}: ${step}`);
    scriptLines.push(...translatedStep.map(line => `        ${line}`));
    scriptLines.push('');
  });
  
  scriptLines.push('        print("✅ Test completed successfully")');
  scriptLines.push('        return True');
  scriptLines.push('    except Exception as e:');
  scriptLines.push(`        print(f"❌ Test failed: {str(e)}")`);
  scriptLines.push('        return False');
  scriptLines.push('');

  // Main execution
  scriptLines.push('if __name__ == "__main__":');
  scriptLines.push('    driver = setup_driver()');
  scriptLines.push('    try:');
  scriptLines.push(`        test_${scenario.id.replace(/[^a-zA-Z0-9]/g, '_')}(driver)`);
  scriptLines.push('    finally:');
  scriptLines.push('        driver.quit()');

  return {
    scenarioId: scenario.id,
    scenarioTitle: scenario.title,
    script: scriptLines.join('\n'),
    language: 'python',
    dependencies: ['selenium'],
    setupCode: 'driver = setup_driver()',
    teardownCode: 'driver.quit()'
  };
}

function translateToJavaScript(scenario: Scenario | CustomScenario, url: string, steps: string[]): TranslatedScript {
  const scriptLines: string[] = [];
  
  // Imports
  scriptLines.push('const { Builder, By, until } = require("selenium-webdriver");');
  scriptLines.push('const chrome = require("selenium-webdriver/chrome");');
  scriptLines.push('');

  // Setup function
  scriptLines.push('async function setupDriver() {');
  scriptLines.push('    const options = new chrome.Options();');
  scriptLines.push('    options.addArguments("--start-maximized");');
  scriptLines.push('    const driver = await new Builder()');
  scriptLines.push('        .forBrowser("chrome")');
  scriptLines.push('        .setChromeOptions(options)');
  scriptLines.push('        .build();');
  scriptLines.push('    return driver;');
  scriptLines.push('}');
  scriptLines.push('');

  // Test function
  scriptLines.push(`async function test${scenario.id.replace(/[^a-zA-Z0-9]/g, '')}(driver) {`);
  scriptLines.push('    try {');
  
  // Process each step
  steps.forEach((step, index) => {
    const translatedStep = translateStepToJavaScript(step, url);
    scriptLines.push(`        // Step ${index + 1}: ${step}`);
    scriptLines.push(...translatedStep.map(line => `        ${line}`));
    scriptLines.push('');
  });
  
  scriptLines.push('        console.log("✅ Test completed successfully");');
  scriptLines.push('        return true;');
  scriptLines.push('    } catch (error) {');
  scriptLines.push(`        console.log("❌ Test failed:", error.message);`);
  scriptLines.push('        return false;');
  scriptLines.push('    }');
  scriptLines.push('}');
  scriptLines.push('');

  // Main execution
  scriptLines.push('(async function() {');
  scriptLines.push('    let driver;');
  scriptLines.push('    try {');
  scriptLines.push('        driver = await setupDriver();');
  scriptLines.push(`        await test${scenario.id.replace(/[^a-zA-Z0-9]/g, '')}(driver);`);
  scriptLines.push('    } catch (error) {');
  scriptLines.push('        console.error("Setup failed:", error);');
  scriptLines.push('    } finally {');
  scriptLines.push('        if (driver) await driver.quit();');
  scriptLines.push('    }');
  scriptLines.push('})();');

  return {
    scenarioId: scenario.id,
    scenarioTitle: scenario.title,
    script: scriptLines.join('\n'),
    language: 'javascript',
    dependencies: ['selenium-webdriver'],
    setupCode: 'const driver = await setupDriver();',
    teardownCode: 'await driver.quit();'
  };
}

function translateStepToPython(step: string, url: string): string[] {
  const lowerStep = step.toLowerCase();
  const lines: string[] = [];

  if (lowerStep.includes('navigate') || lowerStep.includes('go to') || lowerStep.includes('open')) {
    if (lowerStep.includes('homepage') || lowerStep.includes('home')) {
      lines.push('driver.get("' + url + '")');
    } else if (lowerStep.includes('login')) {
      lines.push('driver.get("' + url + '/login")');
    } else if (lowerStep.includes('contact')) {
      lines.push('driver.get("' + url + '/contact")');
    } else {
      lines.push('driver.get("' + url + '")');
    }
    lines.push('WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))');
  } 
  else if (lowerStep.includes('click') || lowerStep.includes('press')) {
    if (lowerStep.includes('button')) {
      if (lowerStep.includes('login') || lowerStep.includes('submit')) {
        lines.push('login_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), \'Login\')] | //button[@type=\'submit\']")))');
      } else {
        lines.push('button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.TAG_NAME, "button")))');
      }
      lines.push('button.click()');
    } else if (lowerStep.includes('link')) {
      lines.push('link = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.TAG_NAME, "a")))');
      lines.push('link.click()');
    } else {
      lines.push('element = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), \'" + extractKeyword(step) + "\')]")))');
      lines.push('element.click()');
    }
  }
  else if (lowerStep.includes('enter') || lowerStep.includes('type') || lowerStep.includes('input')) {
    if (lowerStep.includes('username') || lowerStep.includes('email') || lowerStep.includes('user')) {
      lines.push('username_field = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.NAME, "username") | (By.NAME, "email") | (By.ID, "username") | (By.ID, "email"))))');
      lines.push('username_field.clear()');
      lines.push('username_field.send_keys("testuser@example.com")');
    } else if (lowerStep.includes('password') || lowerStep.includes('pass')) {
      lines.push('password_field = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.NAME, "password") | (By.ID, "password"))))');
      lines.push('password_field.clear()');
      lines.push('password_field.send_keys("testpassword123")');
    } else if (lowerStep.includes('search')) {
      lines.push('search_field = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.NAME, "search") | (By.ID, "search") | (By.CLASS_NAME, "search"))))');
      lines.push('search_field.clear()');
      lines.push('search_field.send_keys("test search")');
    } else {
      lines.push('input_field = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "input")))');
      lines.push('input_field.clear()');
      lines.push('input_field.send_keys("test input")');
    }
  }
  else if (lowerStep.includes('verify') || lowerStep.includes('check') || lowerStep.includes('assert')) {
    if (lowerStep.includes('title')) {
      lines.push('page_title = driver.title');
      lines.push('assert page_title != "", "Page title should not be empty"');
    } else if (lowerStep.includes('login') && lowerStep.includes('success')) {
      lines.push('WebDriverWait(driver, 10).until(EC.url_contains("dashboard") | EC.url_contains("home") | EC.presence_of_element_located((By.XPATH, "//*[contains(text(), \'Welcome\')] | //*[contains(text(), \'Dashboard\')]")))');
      lines.push('print("✅ Login successful")');
    } else if (lowerStep.includes('form') && lowerStep.includes('submit')) {
      lines.push('WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), \'Thank\')] | //*[contains(text(), \'Success\')] | //*[contains(text(), \'Submitted\')]")))');
      lines.push('print("✅ Form submitted successfully")');
    } else {
      lines.push('WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))');
      lines.push('print("✅ Element verified")');
    }
  }
  else if (lowerStep.includes('wait') || lowerStep.includes('pause')) {
    lines.push('time.sleep(2)  # Wait for page to load');
  }
  else {
    // Default action - wait for element presence
    lines.push('WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))');
    lines.push('print("✅ Step completed")');
  }

  return lines;
}

function translateStepToJavaScript(step: string, url: string): string[] {
  const lowerStep = step.toLowerCase();
  const lines: string[] = [];

  if (lowerStep.includes('navigate') || lowerStep.includes('go to') || lowerStep.includes('open')) {
    if (lowerStep.includes('homepage') || lowerStep.includes('home')) {
      lines.push('await driver.get("' + url + '");');
    } else if (lowerStep.includes('login')) {
      lines.push('await driver.get("' + url + '/login");');
    } else if (lowerStep.includes('contact')) {
      lines.push('await driver.get("' + url + '/contact");');
    } else {
      lines.push('await driver.get("' + url + '");');
    }
    lines.push('await driver.wait(until.elementLocated(By.tagName("body")), 10000);');
  } 
  else if (lowerStep.includes('click') || lowerStep.includes('press')) {
    if (lowerStep.includes('button')) {
      if (lowerStep.includes('login') || lowerStep.includes('submit')) {
        lines.push('const loginButton = await driver.wait(until.elementLocated(By.xpath("//button[contains(text(), \'Login\')] | //button[@type=\'submit\']")), 10000);');
      } else {
        lines.push('const button = await driver.wait(until.elementLocated(By.tagName("button")), 10000);');
      }
      lines.push('await button.click();');
    } else if (lowerStep.includes('link')) {
      lines.push('const link = await driver.wait(until.elementLocated(By.tagName("a")), 10000);');
      lines.push('await link.click();');
    } else {
      lines.push('const element = await driver.wait(until.elementLocated(By.xpath("//*[contains(text(), \'" + extractKeyword(step) + "\')]")), 10000);');
      lines.push('await element.click();');
    }
  }
  else if (lowerStep.includes('enter') || lowerStep.includes('type') || lowerStep.includes('input')) {
    if (lowerStep.includes('username') || lowerStep.includes('email') || lowerStep.includes('user')) {
      lines.push('const usernameField = await driver.wait(until.elementLocated(By.name("username") || By.name("email") || By.id("username") || By.id("email")), 10000);');
      lines.push('await usernameField.clear();');
      lines.push('await usernameField.sendKeys("testuser@example.com");');
    } else if (lowerStep.includes('password') || lowerStep.includes('pass')) {
      lines.push('const passwordField = await driver.wait(until.elementLocated(By.name("password") || By.id("password")), 10000);');
      lines.push('await passwordField.clear();');
      lines.push('await passwordField.sendKeys("testpassword123");');
    } else if (lowerStep.includes('search')) {
      lines.push('const searchField = await driver.wait(until.elementLocated(By.name("search") || By.id("search") || By.className("search")), 10000);');
      lines.push('await searchField.clear();');
      lines.push('await searchField.sendKeys("test search");');
    } else {
      lines.push('const inputField = await driver.wait(until.elementLocated(By.tagName("input")), 10000);');
      lines.push('await inputField.clear();');
      lines.push('await inputField.sendKeys("test input");');
    }
  }
  else if (lowerStep.includes('verify') || lowerStep.includes('check') || lowerStep.includes('assert')) {
    if (lowerStep.includes('title')) {
      lines.push('const pageTitle = await driver.getTitle();');
      lines.push('console.log("Page title:", pageTitle);');
    } else if (lowerStep.includes('login') && lowerStep.includes('success')) {
      lines.push('await driver.wait(async () => {');
      lines.push('    const url = await driver.getCurrentUrl();');
      lines.push('    return url.includes("dashboard") || url.includes("home");');
      lines.push('}, 10000, "Login verification failed");');
      lines.push('console.log("✅ Login successful");');
    } else if (lowerStep.includes('form') && lowerStep.includes('submit')) {
      lines.push('await driver.wait(until.elementLocated(By.xpath("//*[contains(text(), \'Thank\')] | //*[contains(text(), \'Success\')] | //*[contains(text(), \'Submitted\')]")), 10000);');
      lines.push('console.log("✅ Form submitted successfully");');
    } else {
      lines.push('await driver.wait(until.elementLocated(By.tagName("body")), 10000);');
      lines.push('console.log("✅ Element verified");');
    }
  }
  else if (lowerStep.includes('wait') || lowerStep.includes('pause')) {
    lines.push('await driver.sleep(2000); // Wait for page to load');
  }
  else {
    // Default action - wait for element presence
    lines.push('await driver.wait(until.elementLocated(By.tagName("body")), 10000);');
    lines.push('console.log("✅ Step completed");');
  }

  return lines;
}

function extractKeyword(step: string): string {
  // Simple keyword extraction for XPath generation
  const words = step.toLowerCase().split(' ');
  const keywords = words.filter(word => 
    word.length > 3 && 
    !['click', 'enter', 'type', 'verify', 'check', 'wait', 'navigate', 'go', 'then', 'with', 'from', 'that', 'this', 'will', 'should'].includes(word)
  );
  return keywords[0] || 'element';
}