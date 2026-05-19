import { test, expect } from '@playwright/test';
import { LoginPage } from '../pages/login.page';
import { WorkspacesPage } from '../pages/workspaces.page';
import { TestHelpers } from '../utils/helpers';
import { testData } from '../utils/test-data';

/**
 * Example Test Suite demonstrating best practices
 * This file shows how to write maintainable and robust tests
 */
test.describe('Example Test Suite - Best Practices', () => {
  test.beforeEach(async ({ page }) => {
    // Setup before each test
    console.log('Starting test: ' + test.info().title);
  });

  test.afterEach(async ({ page }, testInfo) => {
    // Cleanup after each test
    if (testInfo.status === 'failed') {
      await page.screenshot({ path: `test-results/screenshots/${testInfo.title}.png` });
    }
  });

  test('Example 1: Basic page navigation', async ({ page }) => {
    // Arrange: Set up test data
    const loginPage = new LoginPage(page);

    // Act: Navigate to login page
    await loginPage.goto();

    // Assert: Verify page elements are visible
    expect(await loginPage.isEmailInputVisible()).toBeTruthy();
    expect(await loginPage.isPasswordInputVisible()).toBeTruthy();
  });

  test('Example 2: Form interaction with test data', async ({ page }) => {
    const loginPage = new LoginPage(page);

    // Use predefined test data
    await loginPage.goto();
    await loginPage.fill(
      loginPage.emailInput,
      testData.validCredentials.email
    );

    // Verify filled value
    expect(await page.inputValue(loginPage.emailInput)).toBe(
      testData.validCredentials.email
    );
  });

  test('Example 3: Using helper functions', async ({ page }) => {
    const loginPage = new LoginPage(page);

    await loginPage.goto();

    // Use TestHelpers for common operations
    const isEmailVisible = await TestHelpers.isElementVisible(
      page,
      loginPage.emailInput
    );
    expect(isEmailVisible).toBeTruthy();

    // Check page load time
    const loadTime = await TestHelpers.checkPageLoadTime(page);
    console.log(`Page loaded in ${loadTime}ms`);
  });

  test('Example 4: Multiple step workflow', async ({ page }) => {
    const loginPage = new LoginPage(page);
    const workspacesPage = new WorkspacesPage(page);

    // Step 1: Navigate to login
    await loginPage.goto();
    expect(page.url()).toContain('/login');

    // Step 2: Navigate to signup
    await loginPage.goToSignup();
    expect(page.url()).toContain('/signup');

    // Step 3: Go back to login
    await loginPage.goto();
    expect(page.url()).toContain('/login');
  });

  test('Example 5: Generating unique test data', async ({ page }) => {
    // Generate unique email for this test run
    const uniqueEmail = testData.generateUniqueEmail('testuser');
    const uniqueWorkspaceName = testData.generateUniqueWorkspaceName('workspace');

    console.log(`Generated email: ${uniqueEmail}`);
    console.log(`Generated workspace name: ${uniqueWorkspaceName}`);

    // Use in test
    expect(uniqueEmail).toMatch(/@mailinator\.com$/);
    expect(uniqueWorkspaceName).toContain('workspace_');
  });

  test('Example 6: Error handling and retries', async ({ page }) => {
    const loginPage = new LoginPage(page);

    await loginPage.goto();

    // Try to interact with element that might not exist
    try {
      await loginPage.click('.non-existent-button');
    } catch (error) {
      console.log('Expected error caught:', error);
    }

    // Verify page is still functional
    expect(await loginPage.isEmailInputVisible()).toBeTruthy();
  });

  test('Example 7: Screenshot on failure', async ({ page }, testInfo) => {
    const loginPage = new LoginPage(page);

    await loginPage.goto();

    // Take screenshot for documentation
    if (testInfo.retry === 0) {
      await TestHelpers.screenshot(page, 'login-page-initial');
    }

    expect(await loginPage.isEmailInputVisible()).toBeTruthy();
  });

  test('Example 8: Waiting for conditions', async ({ page }) => {
    const loginPage = new LoginPage(page);

    await loginPage.goto();

    // Wait for element with timeout
    const hasEmail = await TestHelpers.waitForElement(
      page,
      loginPage.emailInput,
      5000
    );
    expect(hasEmail).toBeTruthy();

    // Wait for custom condition
    await TestHelpers.waitUntil(
      async () => await loginPage.isSubmitButtonEnabled(),
      5000
    );
  });

  test('Example 9: Accessibility checks', async ({ page }) => {
    const loginPage = new LoginPage(page);

    await loginPage.goto();

    // Verify inputs have proper types
    const emailInput = page.locator(loginPage.emailInput);
    expect(await emailInput.getAttribute('type')).toBe('email');

    const passwordInput = page.locator(loginPage.passwordInput);
    expect(await passwordInput.getAttribute('type')).toBe('password');

    // Verify required attributes
    expect(await emailInput.getAttribute('required')).toBeDefined();
  });

  test('Example 10: Responsive design testing', async ({ page }) => {
    const loginPage = new LoginPage(page);

    // Test on mobile viewport
    await page.setViewportSize({ width: 375, height: 667 });
    await loginPage.goto();
    expect(await loginPage.isEmailInputVisible()).toBeTruthy();

    // Test on tablet viewport
    await page.setViewportSize({ width: 768, height: 1024 });
    expect(await loginPage.isEmailInputVisible()).toBeTruthy();

    // Test on desktop viewport
    await page.setViewportSize({ width: 1920, height: 1080 });
    expect(await loginPage.isEmailInputVisible()).toBeTruthy();
  });

  test('Example 11: Keyboard navigation', async ({ page }) => {
    const loginPage = new LoginPage(page);

    await loginPage.goto();

    // Navigate using Tab key
    await page.keyboard.press('Tab');
    await page.keyboard.type('test@example.com');

    // Navigate to next field
    await page.keyboard.press('Tab');
    await page.keyboard.type('password123');

    // Navigate to submit button
    await page.keyboard.press('Tab');

    // Verify email was entered
    expect(await page.inputValue(loginPage.emailInput)).toBe('test@example.com');
  });

  test('Example 12: Handling multiple popups/modals', async ({ page }) => {
    const loginPage = new LoginPage(page);

    await loginPage.goto();

    // Listen for dialog
    page.once('dialog', (dialog) => {
      console.log('Dialog message: ' + dialog.message());
      dialog.dismiss();
    });

    // Verify page is still functional after dialog
    expect(await loginPage.isEmailInputVisible()).toBeTruthy();
  });

  test('Example 13: Data-driven testing', async ({ page }) => {
    const credentials = [
      { email: 'test1@example.com', password: 'Pass1@123' },
      { email: 'test2@example.com', password: 'Pass2@123' },
      { email: 'test3@example.com', password: 'Pass3@123' },
    ];

    const loginPage = new LoginPage(page);

    for (const credential of credentials) {
      await loginPage.goto();
      await loginPage.fill(loginPage.emailInput, credential.email);
      expect(await page.inputValue(loginPage.emailInput)).toBe(credential.email);
    }
  });

  test('Example 14: Extracting dynamic content', async ({ page }) => {
    const loginPage = new LoginPage(page);

    await loginPage.goto();

    // Extract text content
    const heading = await page.textContent('h1, h2, h3');
    console.log('Page heading:', heading);
    expect(heading?.length).toBeGreaterThan(0);

    // Extract all link texts
    const links = await page.locator('a').allTextContents();
    console.log('Page links:', links);
  });

  test('Example 15: Network monitoring', async ({ page }) => {
    const loginPage = new LoginPage(page);

    const responses: string[] = [];

    // Monitor network requests
    page.on('response', (response) => {
      responses.push(`${response.status()} ${response.url()}`);
    });

    await loginPage.goto();

    // Verify page loaded successfully
    expect(responses.length).toBeGreaterThan(0);
    expect(responses.some((r) => r.startsWith('200'))).toBeTruthy();
  });
});
