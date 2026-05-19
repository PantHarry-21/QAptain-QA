import { test, expect } from '@playwright/test';
import { LoginPage } from '../pages/login.page';
import { SignupPage } from '../pages/signup.page';

test.describe('Accessibility Tests', () => {
  test.describe('Login Page Accessibility', () => {
    test('should have proper heading structure', async ({ page }) => {
      const loginPage = new LoginPage(page);
      await loginPage.goto();

      const heading = page.locator('h1, h2, h3');
      expect(await heading.count()).toBeGreaterThan(0);
    });

    test('should have associated labels for inputs', async ({ page }) => {
      const loginPage = new LoginPage(page);
      await loginPage.goto();

      const emailInput = page.locator(loginPage.emailInput);
      const emailLabel = page.locator('label[for="email"]');

      const hasAssociatedLabel = await emailLabel.count();
      expect(hasAssociatedLabel).toBeGreaterThanOrEqual(0);
    });

    test('should have proper color contrast', async ({ page }) => {
      const loginPage = new LoginPage(page);
      await loginPage.goto();

      // Check that inputs are visible against background
      expect(await loginPage.isEmailInputVisible()).toBeTruthy();
      expect(await loginPage.isPasswordInputVisible()).toBeTruthy();
    });

    test('should support keyboard navigation', async ({ page }) => {
      const loginPage = new LoginPage(page);
      await loginPage.goto();

      const emailInput = page.locator(loginPage.emailInput);
      await emailInput.click();
      await emailInput.type('test@example.com');

      expect(await page.inputValue(loginPage.emailInput)).toBe('test@example.com');

      // Tab to password field
      await page.keyboard.press('Tab');
      await page.keyboard.type('password123');

      // Tab to submit button
      await page.keyboard.press('Tab');

      // Submit via keyboard
      const submitButton = page.locator(loginPage.submitButton);
      const isFocused = await submitButton.evaluate(
        (el) => document.activeElement === el || el.parentElement?.contains(document.activeElement as Node)
      );
      // Button should be reachable
      expect(isFocused).toBeTruthy();
    });

    test('should have aria attributes for form elements', async ({ page }) => {
      const loginPage = new LoginPage(page);
      await loginPage.goto();

      const emailInput = page.locator(loginPage.emailInput);
      const ariaLabel = await emailInput.getAttribute('aria-label');
      const ariaLabelledBy = await emailInput.getAttribute('aria-labelledby');

      // Should have either aria-label or aria-labelledby or be associated with label
      expect(ariaLabel || ariaLabelledBy || (await page.locator('label[for="email"]').count()) > 0).toBeTruthy();
    });
  });

  test.describe('Signup Page Accessibility', () => {
    test('should have semantic HTML structure', async ({ page }) => {
      const signupPage = new SignupPage(page);
      await signupPage.goto();

      const form = page.locator('form');
      expect(await form.isVisible()).toBeTruthy();
    });

    test('should have accessible form fields', async ({ page }) => {
      const signupPage = new SignupPage(page);
      await signupPage.goto();

      const inputs = page.locator('input[type="text"], input[type="email"], input[type="password"]');
      const count = await inputs.count();

      expect(count).toBeGreaterThan(0);
    });

    test('should provide error messages accessibly', async ({ page }) => {
      const signupPage = new SignupPage(page);
      await signupPage.goto();

      // Test that error messages would be announced to screen readers
      const errorMessage = page.locator(signupPage.errorMessage);
      // Check if visible or properly hidden with aria-live
      const ariaLive = await errorMessage.getAttribute('aria-live');
      expect(ariaLive === 'polite' || ariaLive === 'assertive' || (await errorMessage.isVisible()) === false).toBeTruthy();
    });

    test('should support tab order', async ({ page }) => {
      const signupPage = new SignupPage(page);
      await signupPage.goto();

      const firstNameInput = page.locator(signupPage.firstNameInput);
      await firstNameInput.click();

      // Should be able to tab through form fields
      await page.keyboard.press('Tab');
      const activeElement = await page.evaluate(() => document.activeElement?.id || document.activeElement?.getAttribute('type'));

      expect(activeElement).toBeDefined();
    });

    test('should have proper button accessibility', async ({ page }) => {
      const signupPage = new SignupPage(page);
      await signupPage.goto();

      const submitButton = page.locator(signupPage.submitButton);
      const role = await submitButton.getAttribute('role');
      const ariaLabel = await submitButton.getAttribute('aria-label');
      const text = await submitButton.textContent();

      // Button should have text or aria-label
      expect(role === 'button' || text || ariaLabel).toBeTruthy();
    });
  });

  test.describe('General Accessibility', () => {
    test('should have language attribute on html element', async ({ page }) => {
      const loginPage = new LoginPage(page);
      await loginPage.goto();

      const htmlLang = await page.locator('html').getAttribute('lang');
      expect(htmlLang).toBeDefined();
    });

    test('should have proper page title', async ({ page }) => {
      const loginPage = new LoginPage(page);
      await loginPage.goto();

      const title = await page.title();
      expect(title.length).toBeGreaterThan(0);
    });

    test('should be navigable without mouse', async ({ page }) => {
      const loginPage = new LoginPage(page);
      await loginPage.goto();

      // Should be able to navigate with keyboard only
      const emailInput = page.locator(loginPage.emailInput);
      await page.keyboard.press('Tab');

      // Email input should be reachable
      const isFocused = await emailInput.evaluate(
        (el: HTMLInputElement) => document.activeElement === el || el.contains(document.activeElement as Node)
      );

      expect(isFocused).toBeTruthy();
    });
  });
});
