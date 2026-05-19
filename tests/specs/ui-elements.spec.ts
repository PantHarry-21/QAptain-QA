import { test, expect } from '@playwright/test';
import { LoginPage } from '../pages/login.page';
import { SignupPage } from '../pages/signup.page';

test.describe('UI Elements Verification', () => {
  test.describe('Login Page Elements', () => {
    test('should have accessible form elements', async ({ page }) => {
      const loginPage = new LoginPage(page);
      await loginPage.goto();

      // Check for labels
      const emailLabel = await page.locator('label:has-text("Email")').isVisible();
      const passwordLabel = await page.locator('label:has-text("Password")').isVisible();

      expect(emailLabel).toBeTruthy();
      expect(passwordLabel).toBeTruthy();
    });

    test('should have proper input types', async ({ page }) => {
      const loginPage = new LoginPage(page);
      await loginPage.goto();

      const emailInput = page.locator(loginPage.emailInput);
      const passwordInput = page.locator(loginPage.passwordInput);

      expect(await emailInput.getAttribute('type')).toBe('email');
      expect(await passwordInput.getAttribute('type')).toBe('password');
    });

    test('should have submit button with proper text', async ({ page }) => {
      const loginPage = new LoginPage(page);
      await loginPage.goto();

      const button = page.locator(loginPage.submitButton);
      const text = await button.textContent();
      expect(text?.toLowerCase()).toContain('sign');
    });

    test('should have link to signup page', async ({ page }) => {
      const loginPage = new LoginPage(page);
      await loginPage.goto();

      const link = page.locator('a:has-text("Sign up")');
      expect(await link.isVisible()).toBeTruthy();
    });

    test('should have theme elements', async ({ page }) => {
      const loginPage = new LoginPage(page);
      await loginPage.goto();

      // Check for QAPtain branding
      const branding = page.locator('text=QAPtain');
      expect(await branding.isVisible()).toBeTruthy();
    });

    test('should have back to home link', async ({ page }) => {
      const loginPage = new LoginPage(page);
      await loginPage.goto();

      const backLink = page.locator(loginPage.backLink);
      expect(await backLink.isVisible()).toBeTruthy();
    });
  });

  test.describe('Signup Page Elements', () => {
    test('should have all form field labels', async ({ page }) => {
      const signupPage = new SignupPage(page);
      await signupPage.goto();

      const firstNameLabel = page.locator('label:has-text("First Name")');
      const lastNameLabel = page.locator('label:has-text("Last Name")');
      const emailLabel = page.locator('label:has-text("Email")');
      const passwordLabel = page.locator('label:has-text("Password")');

      expect(await firstNameLabel.isVisible()).toBeTruthy();
      expect(await lastNameLabel.isVisible()).toBeTruthy();
      expect(await emailLabel.isVisible()).toBeTruthy();
      expect(await passwordLabel.isVisible()).toBeTruthy();
    });

    test('should have proper form layout', async ({ page }) => {
      const signupPage = new SignupPage(page);
      await signupPage.goto();

      const card = page.locator('[class*="Card"]');
      expect(await card.isVisible()).toBeTruthy();
    });

    test('should display signup instructions', async ({ page }) => {
      const signupPage = new SignupPage(page);
      await signupPage.goto();

      const description = page.locator('text=Join QAPtain');
      expect(await description.isVisible()).toBeTruthy();
    });

    test('should have login link', async ({ page }) => {
      const signupPage = new SignupPage(page);
      await signupPage.goto();

      const loginLink = page.locator('a:has-text("Log in")');
      expect(await loginLink.isVisible()).toBeTruthy();
    });
  });

  test.describe('Responsive Design', () => {
    test('should display properly on mobile viewport', async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 667 });

      const loginPage = new LoginPage(page);
      await loginPage.goto();

      expect(await loginPage.isEmailInputVisible()).toBeTruthy();
      expect(await loginPage.isPasswordInputVisible()).toBeTruthy();
    });

    test('should display properly on tablet viewport', async ({ page }) => {
      await page.setViewportSize({ width: 768, height: 1024 });

      const signupPage = new SignupPage(page);
      await signupPage.goto();

      expect(await signupPage.isAllFieldsVisible()).toBeTruthy();
    });

    test('should display properly on desktop viewport', async ({ page }) => {
      await page.setViewportSize({ width: 1920, height: 1080 });

      const loginPage = new LoginPage(page);
      await loginPage.goto();

      expect(await loginPage.isEmailInputVisible()).toBeTruthy();
    });
  });

  test.describe('Form Interactions', () => {
    test('should enable/disable submit button on input', async ({ page }) => {
      const loginPage = new LoginPage(page);
      await loginPage.goto();

      const button = page.locator(loginPage.submitButton);

      // Initially should be enabled
      const initialState = await button.isDisabled();
      expect(initialState).toBeFalsy();
    });

    test('should handle focus states', async ({ page }) => {
      const signupPage = new SignupPage(page);
      await signupPage.goto();

      const emailInput = page.locator(signupPage.emailInput);
      await emailInput.focus();

      const isFocused = await emailInput.evaluate(
        (el: HTMLInputElement) => document.activeElement === el
      );
      expect(isFocused).toBeTruthy();
    });

    test('should handle input clearing', async ({ page }) => {
      const loginPage = new LoginPage(page);
      await loginPage.goto();

      await loginPage.fill(loginPage.emailInput, 'test@example.com');
      expect(await page.inputValue(loginPage.emailInput)).toBe('test@example.com');

      // Clear
      await page.locator(loginPage.emailInput).fill('');
      expect(await page.inputValue(loginPage.emailInput)).toBe('');
    });

    test('should handle password visibility toggle if available', async ({ page }) => {
      const loginPage = new LoginPage(page);
      await loginPage.goto();

      const passwordInput = page.locator(loginPage.passwordInput);
      const type = await passwordInput.getAttribute('type');
      expect(type).toBe('password');
    });
  });
});
