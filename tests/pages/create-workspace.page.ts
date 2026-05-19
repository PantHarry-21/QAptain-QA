import { Page } from '@playwright/test';
import { BasePage } from './base.page';

export class CreateWorkspacePage extends BasePage {
  // Step 1: Application
  readonly appNameInput = 'input[placeholder*="e.g. Acme"]';
  readonly appDescriptionInput = 'textarea';
  readonly appBaseUrlInput = 'input[placeholder*="https://app"]';
  readonly step1ContinueButton = 'button:has-text("Continue")';

  // Step 2: Auth Profile
  readonly authNameInput = 'input[value="Primary"]';
  readonly usernameInput = 'input[autocomplete="off"]';
  readonly passwordInput = 'input[type="password"]';
  readonly labNameInput = 'input[placeholder*="For multi-step"]';
  readonly roleSelect = 'select';
  readonly step2ContinueButton = 'button:has-text("Continue")';

  // Step 3: Discovery
  readonly startDiscoveryButton = 'button:has-text("Start discovery")';
  readonly discoveryStatusText = '.bg-violet-50\\/80, .bg-violet-950\\/40';

  // Common
  readonly stepIndicator = 'text="·"';
  readonly errorMessage = 'p.text-red-400';

  constructor(page: Page) {
    super(page);
  }

  async goto() {
    await this.page.goto('/workspaces/new');
  }

  // Step 1: Application Details
  async fillApplicationDetails(name: string, description: string, baseUrl: string) {
    await this.fill(this.appNameInput, name);
    await this.fill(this.appDescriptionInput, description);
    await this.fill(this.appBaseUrlInput, baseUrl);
  }

  async clickStep1Continue() {
    await this.click(this.step1ContinueButton);
    await this.page.waitForSelector('text="2 · Authentication"');
  }

  async completeStep1(name: string, description: string, baseUrl: string) {
    await this.fillApplicationDetails(name, description, baseUrl);
    await this.clickStep1Continue();
  }

  // Step 2: Auth Profile
  async fillAuthProfile(
    authName: string,
    username: string,
    password: string,
    labName?: string,
    roleHint?: string
  ) {
    // Clear and fill auth name
    const authNameEl = this.page.locator(this.authNameInput).first();
    await authNameEl.click({ clickCount: 3 });
    await authNameEl.fill(authName);

    await this.fill(this.usernameInput, username);

    // Password field - find the one for password input
    const passwordInputs = await this.page.locator(this.passwordInput).all();
    if (passwordInputs.length > 0) {
      await passwordInputs[0].fill(password);
    }

    if (labName) {
      await this.fill(this.labNameInput, labName);
    }

    if (roleHint && this.roleSelect) {
      await this.page.selectOption(this.roleSelect, roleHint);
    }
  }

  async clickStep2Continue() {
    await this.click(this.step2ContinueButton);
    await this.page.waitForSelector('text="3 · Lightweight discovery"');
  }

  async completeStep2(
    authName: string,
    username: string,
    password: string,
    labName?: string,
    roleHint?: string
  ) {
    await this.fillAuthProfile(authName, username, password, labName, roleHint);
    await this.clickStep2Continue();
  }

  // Step 3: Discovery
  async startDiscovery() {
    await this.click(this.startDiscoveryButton);
    await this.page.waitForURL(/.*workspaces\/[^\?]+\?discovery=.*/);
  }

  async waitForDiscoveryComplete(timeout: number = 180000) {
    let isComplete = false;
    const startTime = Date.now();

    while (!isComplete && Date.now() - startTime < timeout) {
      const statusText = await this.getText(this.discoveryStatusText);

      if (statusText.includes('Analysis complete') || statusText.includes('Complete')) {
        isComplete = true;
        break;
      }

      await this.page.waitForTimeout(5000);
    }

    if (!isComplete) {
      throw new Error('Discovery did not complete within timeout');
    }
  }

  async completeWorkspaceCreation(
    name: string,
    description: string,
    baseUrl: string,
    authName: string,
    username: string,
    password: string,
    labName?: string,
    roleHint?: string
  ) {
    // Step 1
    await this.completeStep1(name, description, baseUrl);

    // Step 2
    await this.completeStep2(authName, username, password, labName, roleHint);

    // Step 3
    await this.startDiscovery();
  }

  async getCurrentStep(): Promise<number> {
    const stepText = await this.getText(this.stepIndicator);
    const match = stepText.match(/(\d+)/);
    return match ? parseInt(match[1]) : 0;
  }

  async getErrorMessage(): Promise<string> {
    return await this.getText(this.errorMessage);
  }
}
