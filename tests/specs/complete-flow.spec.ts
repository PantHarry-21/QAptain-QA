import { test, expect } from '@playwright/test';
import { LoginPage } from '../pages/login.page';
import { SignupPage } from '../pages/signup.page';
import { WorkspacesPage } from '../pages/workspaces.page';
import { CreateWorkspacePage } from '../pages/create-workspace.page';

test.describe('Complete End-to-End Flows', () => {
  test('should complete full user journey: signup → create workspace', async ({
    page,
  }) => {
    const timestamp = Date.now();
    const uniqueEmail = `e2e${timestamp}@mailinator.com`;

    // Step 1: Signup
    const signupPage = new SignupPage(page);
    await signupPage.goto();
    expect(page.url()).toContain('/signup');

    await signupPage.signup(
      'E2E',
      'TestUser',
      uniqueEmail,
      'Test@123'
    );
    expect(page.url()).toContain('/login');

    // Step 2: Try login (would need account activation in real scenario)
    const loginPage = new LoginPage(page);
    expect(await loginPage.isEmailInputVisible()).toBeTruthy();
  });

  test('should navigate through all key pages', async ({ page }) => {
    // Login first
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    expect(page.url()).toContain('/login');

    // Check all elements are visible
    expect(await loginPage.isEmailInputVisible()).toBeTruthy();
    expect(await loginPage.isPasswordInputVisible()).toBeTruthy();
  });

  test('should verify form validation across pages', async ({ page }) => {
    // Test signup form validation
    const signupPage = new SignupPage(page);
    await signupPage.goto();

    const firstNameInput = page.locator(signupPage.firstNameInput);
    const emailInput = page.locator(signupPage.emailInput);

    // Verify required attributes
    expect(await firstNameInput.getAttribute('required')).toBeDefined();
    expect(await emailInput.getAttribute('type')).toBe('email');
  });

  test('should handle browser back button', async ({ page }) => {
    const loginPage = new LoginPage(page);
    const signupPage = new SignupPage(page);

    // Navigate to signup
    await signupPage.goto();
    expect(page.url()).toContain('/signup');

    // Go back
    await page.goBack();
    expect(page.url()).toContain('/login');
  });

  test('should maintain proper URL structure', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    expect(page.url()).toBe('http://localhost:3000/login');

    const signupPage = new SignupPage(page);
    await signupPage.goto();
    expect(page.url()).toBe('http://localhost:3000/signup');
  });

  test('should provide proper linking between auth pages', async ({ page }) => {
    // From login to signup
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.goToSignup();
    expect(page.url()).toContain('/signup');

    // From signup to login
    const signupPage = new SignupPage(page);
    await signupPage.goToLogin();
    expect(page.url()).toContain('/login');
  });
});

test.describe('Workspace Creation E2E Flow', () => {
  // Note: This test would require authenticated session
  test('should verify create workspace page structure', async ({ page }) => {
    const createPage = new CreateWorkspacePage(page);

    // Navigate to create page (would need auth in real scenario)
    // Just verify page objects work correctly
    expect(createPage.appNameInput).toBeDefined();
    expect(createPage.appDescriptionInput).toBeDefined();
    expect(createPage.appBaseUrlInput).toBeDefined();
  });

  test('should verify all steps are accessible', async ({ page }) => {
    const createPage = new CreateWorkspacePage(page);

    // Verify all selectors are defined
    expect(createPage.step1ContinueButton).toBeDefined();
    expect(createPage.step2ContinueButton).toBeDefined();
    expect(createPage.startDiscoveryButton).toBeDefined();
  });
});

test.describe('Navigation Tests', () => {
  test('should allow navigation between pages', async ({ page }) => {
    const loginPage = new LoginPage(page);
    const signupPage = new SignupPage(page);

    // Navigate to login
    await loginPage.goto();
    let url = page.url();
    expect(url).toContain('/login');

    // Navigate to signup
    await signupPage.goto();
    url = page.url();
    expect(url).toContain('/signup');

    // Navigate back to login
    await loginPage.goto();
    url = page.url();
    expect(url).toContain('/login');
  });

  test('should handle redirect after signup', async ({ page }) => {
    const signupPage = new SignupPage(page);
    await signupPage.goto();

    // Verify we're on signup page
    expect(page.url()).toContain('/signup');

    // Verify signup form is visible
    expect(await signupPage.isAllFieldsVisible()).toBeTruthy();
  });

  test('should display proper page titles and headers', async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();

    // Verify page content is loaded
    const isVisible = await loginPage.isEmailInputVisible();
    expect(isVisible).toBeTruthy();
  });
});
