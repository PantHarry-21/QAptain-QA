import { Page } from '@playwright/test';
import { BasePage } from './base.page';

export class WorkspacesPage extends BasePage {
  // Selectors
  readonly addWorkspaceButton = 'a:has-text("Add workspace")';
  readonly workspaceList = 'table tbody tr';
  readonly createWorkspaceButton = 'button:has-text("Create Workspace")';
  readonly emptyState = 'text="No workspaces yet"';

  constructor(page: Page) {
    super(page);
  }

  async goto() {
    await this.page.goto('/workspaces');
  }

  async clickAddWorkspace() {
    await this.click(this.addWorkspaceButton);
    await this.page.waitForURL('**/workspaces/new');
  }

  async getWorkspacesCount(): Promise<number> {
    const count = await this.page.locator(this.workspaceList).count();
    return count;
  }

  async isEmptyStateVisible(): Promise<boolean> {
    return await this.isVisible(this.emptyState);
  }

  async getWorkspaceNames(): Promise<string[]> {
    const rows = await this.page.locator(this.workspaceList).count();
    const names: string[] = [];

    for (let i = 0; i < rows; i++) {
      const name = await this.page.locator(`${this.workspaceList}:nth-child(${i + 1})`).textContent();
      if (name) names.push(name.trim());
    }

    return names;
  }

  async clickWorkspace(workspaceName: string) {
    const selector = `a:has-text("${workspaceName}")`;
    await this.click(selector);
    await this.page.waitForURL('**/workspaces/**');
  }

  async openFirstWorkspace() {
    const firstWorkspace = this.page.locator(`${this.workspaceList}:first-child a`);
    await firstWorkspace.click();
    await this.page.waitForURL('**/workspaces/**');
  }
}
