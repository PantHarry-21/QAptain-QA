import { test as base, Page } from '@playwright/test';

export interface AuthFixture {
  authenticatedPage: Page;
  login: (email: string, password: string) => Promise<Page>;
  signup: (firstName: string, lastName: string, email: string, password: string) => Promise<Page>;
}

export const test = base.extend<AuthFixture>({
  authenticatedPage: async ({ page }, use) => {
    await page.goto('/login');
    await page.fill('#email', 'test@example.com');
    await page.fill('#password', 'Test@123');
    await page.click('button[type="submit"]');
    await page.waitForURL('**/workspaces');
    await use(page);
  },

  login: async ({ page }, use) => {
    const loginFunc = async (email: string, password: string) => {
      await page.goto('/login');
      await page.fill('#email', email);
      await page.fill('#password', password);
      await page.click('button[type="submit"]');
      await page.waitForURL('**/workspaces');
      return page;
    };
    await use(loginFunc);
  },

  signup: async ({ page }, use) => {
    const signupFunc = async (
      firstName: string,
      lastName: string,
      email: string,
      password: string
    ) => {
      await page.goto('/signup');
      await page.fill('#firstName', firstName);
      await page.fill('#lastName', lastName);
      await page.fill('#email', email);
      await page.fill('#password', password);
      await page.click('button[type="submit"]');
      await page.waitForURL('**/login');
      return page;
    };
    await use(signupFunc);
  },
});

export { expect } from '@playwright/test';
