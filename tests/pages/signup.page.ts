import { Page } from '@playwright/test';
import { BasePage } from './base.page';

export class SignupPage extends BasePage {
  // Selectors
  readonly firstNameInput = '#firstName';
  readonly lastNameInput = '#lastName';
  readonly emailInput = '#email';
  readonly passwordInput = '#password';
  readonly submitButton = 'button[type="submit"]';
  readonly loginLink = 'a:has-text("Log in")';
  readonly errorMessage = 'p.text-red-400';
  readonly backLink = 'a:has-text("Back to Home")';

  constructor(page: Page) {
    super(page);
  }

  async goto() {
    await this.page.goto('/signup');
  }

  async signup(firstName: string, lastName: string, email: string, password: string) {
    await this.fill(this.firstNameInput, firstName);
    await this.fill(this.lastNameInput, lastName);
    await this.fill(this.emailInput, email);
    await this.fill(this.passwordInput, password);
    await this.click(this.submitButton);
  }

  async signupAndWait(firstName: string, lastName: string, email: string, password: string) {
    await this.signup(firstName, lastName, email, password);
    await this.page.waitForURL('**/login');
  }

  async goToLogin() {
    await this.click(this.loginLink);
    await this.page.waitForURL('**/login');
  }

  async getErrorMessage(): Promise<string> {
    return await this.getText(this.errorMessage);
  }

  async isFirstNameInputVisible(): Promise<boolean> {
    return await this.isVisible(this.firstNameInput);
  }

  async isAllFieldsVisible(): Promise<boolean> {
    return (
      (await this.isVisible(this.firstNameInput)) &&
      (await this.isVisible(this.lastNameInput)) &&
      (await this.isVisible(this.emailInput)) &&
      (await this.isVisible(this.passwordInput))
    );
  }

  async isSubmitButtonEnabled(): Promise<boolean> {
    const button = this.page.locator(this.submitButton);
    return !(await button.isDisabled());
  }
}
