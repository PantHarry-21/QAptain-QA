import { Page } from '@playwright/test';
import { BasePage } from './base.page';

export class LoginPage extends BasePage {
  // Selectors
  readonly emailInput = '#email';
  readonly passwordInput = '#password';
  readonly submitButton = 'button[type="submit"]';
  readonly signupLink = 'a:has-text("Sign up")';
  readonly errorMessage = 'p.text-red-400';
  readonly successMessage = 'p.text-emerald-400';
  readonly backLink = 'a:has-text("Back to Home")';

  constructor(page: Page) {
    super(page);
  }

  async goto() {
    await this.page.goto('/login');
  }

  async login(email: string, password: string) {
    await this.fill(this.emailInput, email);
    await this.fill(this.passwordInput, password);
    await this.click(this.submitButton);
  }

  async loginAndWait(email: string, password: string) {
    await this.login(email, password);
    await this.page.waitForURL('**/workspaces');
  }

  async goToSignup() {
    await this.click(this.signupLink);
    await this.page.waitForURL('**/signup');
  }

  async getErrorMessage(): Promise<string> {
    return await this.getText(this.errorMessage);
  }

  async getSuccessMessage(): Promise<string> {
    return await this.getText(this.successMessage);
  }

  async isEmailInputVisible(): Promise<boolean> {
    return await this.isVisible(this.emailInput);
  }

  async isPasswordInputVisible(): Promise<boolean> {
    return await this.isVisible(this.passwordInput);
  }

  async isSubmitButtonEnabled(): Promise<boolean> {
    const button = this.page.locator(this.submitButton);
    return !(await button.isDisabled());
  }
}
