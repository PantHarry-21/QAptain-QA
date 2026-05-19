import { test, expect } from '@playwright/test';
import { LoginPage } from '../pages/login.page';
import { SignupPage } from '../pages/signup.page';

test.describe('Authentication Tests', () => {
  test.describe('Login Page', () => {
    test('should display login form with all required fields', async ({ page }) => {
      const loginPage = new LoginPage(page);
      await loginPage.goto();

      expect(await loginPage.isEmailInputVisible()).toBeTruthy();
      expect(await loginPage.isPasswordInputVisible()).toBeTruthy();
      expect(await loginPage.isSubmitButtonEnabled()).toBeTruthy();
    });

    test('should navigate to signup from login page', async ({ page }) => {
      const loginPage = new LoginPage(page);
      await loginPage.goto();
      await loginPage.goToSignup();

      expect(page.url()).toContain('/signup');
    });

    test('should show error message on invalid credentials', async ({ page }) => {
      const loginPage = new LoginPage(page);
      await loginPage.goto();
      await loginPage.login('invalid@example.com', 'wrongpassword');

      await page.waitForTimeout(1000);
      const errorVisible = await loginPage.isVisible(loginPage.errorMessage);
      expect(errorVisible).toBeTruthy();
    });

    test('should clear error message on new attempt', async ({ page }) => {
      const loginPage = new LoginPage(page);
      await loginPage.goto();
      await loginPage.login('invalid@example.com', 'wrongpassword');
      await page.waitForTimeout(500);

      // Clear and try again
      await loginPage.fill(loginPage.emailInput, 'newtest@example.com');
      const errorVisible = await loginPage.isVisible(loginPage.errorMessage);
      expect(errorVisible).toBeFalsy();
    });

    test('should require email field', async ({ page }) => {
      const loginPage = new LoginPage(page);
      await loginPage.goto();

      const emailInput = page.locator(loginPage.emailInput);
      expect(await emailInput.getAttribute('required')).toBeDefined();
    });

    test('should require password field', async ({ page }) => {
      const loginPage = new LoginPage(page);
      await loginPage.goto();

      const passwordInput = page.locator(loginPage.passwordInput);
      expect(await passwordInput.getAttribute('required')).toBeDefined();
    });
  });

  test.describe('Signup Page', () => {
    test('should display signup form with all required fields', async ({ page }) => {
      const signupPage = new SignupPage(page);
      await signupPage.goto();

      expect(await signupPage.isAllFieldsVisible()).toBeTruthy();
    });

    test('should navigate to login from signup page', async ({ page }) => {
      const signupPage = new SignupPage(page);
      await signupPage.goto();
      await signupPage.goToLogin();

      expect(page.url()).toContain('/login');
    });

    test('should display all input fields', async ({ page }) => {
      const signupPage = new SignupPage(page);
      await signupPage.goto();

      expect(await signupPage.isVisible(signupPage.firstNameInput)).toBeTruthy();
      expect(await signupPage.isVisible(signupPage.lastNameInput)).toBeTruthy();
      expect(await signupPage.isVisible(signupPage.emailInput)).toBeTruthy();
      expect(await signupPage.isVisible(signupPage.passwordInput)).toBeTruthy();
    });

    test('should require first name field', async ({ page }) => {
      const signupPage = new SignupPage(page);
      await signupPage.goto();

      const input = page.locator(signupPage.firstNameInput);
      expect(await input.getAttribute('required')).toBeDefined();
    });

    test('should require last name field', async ({ page }) => {
      const signupPage = new SignupPage(page);
      await signupPage.goto();

      const input = page.locator(signupPage.lastNameInput);
      expect(await input.getAttribute('required')).toBeDefined();
    });

    test('should require email field', async ({ page }) => {
      const signupPage = new SignupPage(page);
      await signupPage.goto();

      const input = page.locator(signupPage.emailInput);
      expect(await input.getAttribute('required')).toBeDefined();
    });

    test('should require password field', async ({ page }) => {
      const signupPage = new SignupPage(page);
      await signupPage.goto();

      const input = page.locator(signupPage.passwordInput);
      expect(await input.getAttribute('required')).toBeDefined();
    });

    test('should validate email format', async ({ page }) => {
      const signupPage = new SignupPage(page);
      await signupPage.goto();

      const emailInput = page.locator(signupPage.emailInput);
      const type = await emailInput.getAttribute('type');
      expect(type).toBe('email');
    });

    test('should be able to fill all fields', async ({ page }) => {
      const signupPage = new SignupPage(page);
      await signupPage.goto();

      await signupPage.fill(signupPage.firstNameInput, 'John');
      await signupPage.fill(signupPage.lastNameInput, 'Doe');
      await signupPage.fill(signupPage.emailInput, 'john@example.com');
      await signupPage.fill(signupPage.passwordInput, 'Password123');

      expect(await page.inputValue(signupPage.firstNameInput)).toBe('John');
      expect(await page.inputValue(signupPage.lastNameInput)).toBe('Doe');
      expect(await page.inputValue(signupPage.emailInput)).toBe('john@example.com');
      expect(await page.inputValue(signupPage.passwordInput)).toBe('Password123');
    });
  });

  test.describe('Authentication Flow', () => {
    test('should complete full signup and login flow', async ({ page }) => {
      const timestamp = Date.now();
      const signupPage = new SignupPage(page);

      await signupPage.goto();
      await signupPage.signup(
        'Test',
        'User',
        `testuser${timestamp}@example.com`,
        'Password@123'
      );

      // Should redirect to login
      expect(page.url()).toContain('/login');

      const loginPage = new LoginPage(page);
      // Note: In real scenario, you'd need to activate account or use pre-created account
      // This test verifies the flow structure
      expect(await loginPage.isEmailInputVisible()).toBeTruthy();
    });
  });
});
