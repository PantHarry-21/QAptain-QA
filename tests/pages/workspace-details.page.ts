import { Page } from '@playwright/test';
import { BasePage } from './base.page';

export class WorkspaceDetailsPage extends BasePage {
  // Selectors
  readonly workspaceName = 'h1, h2';
  readonly modulesTab = 'button[role="tab"]:has-text("Modules")';
  readonly scenariosTab = 'button[role="tab"]:has-text("Scenarios")';
  readonly runsTab = 'button[role="tab"]:has-text("Runs")';
  readonly settingsTab = 'button[role="tab"]:has-text("Settings")';
  readonly modulesList = 'table tbody tr';
  readonly startRunButton = 'button:has-text("Start Test Run")';
  readonly backButton = 'a:has-text("Back")';

  constructor(page: Page) {
    super(page);
  }

  async goto(workspaceId: string) {
    await this.page.goto(`/workspaces/${workspaceId}`);
  }

  async clickModulesTab() {
    await this.click(this.modulesTab);
    await this.page.waitForTimeout(1000); // Wait for tab content to load
  }

  async clickScenariosTab() {
    await this.click(this.scenariosTab);
    await this.page.waitForTimeout(1000);
  }

  async clickRunsTab() {
    await this.click(this.runsTab);
    await this.page.waitForTimeout(1000);
  }

  async clickSettingsTab() {
    await this.click(this.settingsTab);
    await this.page.waitForTimeout(1000);
  }

  async getModulesCount(): Promise<number> {
    await this.clickModulesTab();
    return await this.page.locator(this.modulesList).count();
  }

  async getModuleNames(): Promise<string[]> {
    await this.clickModulesTab();
    const rows = await this.page.locator(this.modulesList).count();
    const names: string[] = [];

    for (let i = 0; i < rows; i++) {
      const name = await this.page
        .locator(`${this.modulesList}:nth-child(${i + 1})`)
        .textContent();
      if (name) names.push(name.trim());
    }

    return names;
  }

  async getWorkspaceName(): Promise<string> {
    return await this.getText(this.workspaceName);
  }

  async isModulesTabVisible(): Promise<boolean> {
    return await this.isVisible(this.modulesTab);
  }

  async clickStartRun() {
    await this.click(this.startRunButton);
    // Wait for navigation to run page
    await this.page.waitForURL('**/runs/**');
  }
}
