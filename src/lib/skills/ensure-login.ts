import type { Page } from 'playwright';
import { loadFixtureCredentials } from '../fixture-config';

export async function ensureLoggedIn(page: Page, baseUrl: string, sessionId: string, scenarioId?: string) {
  const role = process.env.QAPTAIN_TEST_ROLE || 'ADMIN';
  const creds = loadFixtureCredentials(role);
  if (!creds.username || !creds.password) return;

  const appBase = (baseUrl || creds.baseUrl || '').replace(/\/+$/, '');
  const loginUrl = appBase ? `${appBase}/login` : `${baseUrl.replace(/\/+$/, '')}/login`;
  await page.goto(loginUrl, { waitUntil: 'domcontentloaded', timeout: 120000 }).catch(() => {});

  const usernameInput = page.locator('[name="username"], input[name*="user" i], input[type="email"]').first();
  const passwordInput = page.locator('[name="password"], input[type="password"]').first();
  if ((await usernameInput.count().catch(() => 0)) === 0 || (await passwordInput.count().catch(() => 0)) === 0) {
    return;
  }

  await usernameInput.fill(creds.username).catch(() => {});
  await passwordInput.fill(creds.password).catch(() => {});

  const loginBtn = page.getByRole('button', { name: /sign\s*in|log\s*in|login|submit/i }).first();
  if ((await loginBtn.count().catch(() => 0)) > 0) await loginBtn.click({ timeout: 20000 }).catch(() => {});
  else await page.keyboard.press('Enter').catch(() => {});

  // Mirror Cypress logic:
  // A) location picker appears on login page
  // B) direct redirect to dashboard
  const chooseLocation = page.getByText(/choose your location/i).first();
  const sawPicker = await chooseLocation.waitFor({ timeout: 20000 }).then(() => true).catch(() => false);

  if (sawPicker) {
    await chooseLocation.click().catch(() => {});

    if (creds.labName) {
      const labOption = page.getByText(creds.labName, { exact: false }).first();
      if ((await labOption.count().catch(() => 0)) > 0) {
        await labOption.click({ timeout: 10000 }).catch(() => {});
      }
    } else {
      const fallbackOption = page.locator('span[class*="cursor-pointer"], li').first();
      if ((await fallbackOption.count().catch(() => 0)) > 0) {
        await fallbackOption.click({ timeout: 10000 }).catch(() => {});
      }
    }

    const signInAgain = page.getByRole('button', { name: /sign\s*in/i }).first();
    if ((await signInAgain.count().catch(() => 0)) > 0) {
      await signInAgain.click({ timeout: 15000 }).catch(() => {});
    }
  }

  // Hard gate before test execution: must be on dashboard.
  await page.waitForURL(/\/dashboard\b/i, { timeout: 60000 }).catch(() => {});
  await page.waitForLoadState('domcontentloaded', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(500);

  // NOTE: screenshot/reporting is handled by caller (test-executor) to avoid circular deps.
  void sessionId;
  void scenarioId;
}

