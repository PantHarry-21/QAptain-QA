import type { Page } from 'playwright';
import { loadFixtureCredentials, type FixtureCredentials } from '../fixture-config';

export type WorkspaceLoginCredentials = {
  username?: string | null;
  password?: string | null;
  labName?: string | null;
  /** When set, drives admin-style location picker handling */
  roleHint?: string | null;
};

function isAdminRole(role: string): boolean {
  const r = role.trim().toUpperCase().replace(/[^A-Z0-9]+/g, '_');
  return r === 'ADMIN';
}

function isDashboardUrl(url: string): boolean {
  if (!url) return false;
  try {
    const u = new URL(url);
    if (/\/dashboard/i.test(u.pathname)) return true;
    if (u.hash && /dashboard/i.test(u.hash)) return true;
    return false;
  } catch {
    return /\/dashboard/i.test(url);
  }
}

function isLoginUrl(url: string): boolean {
  return /\/login(?:\/|$|\?|#)/i.test(url);
}

async function isLocationPickerVisible(page: Page): Promise<boolean> {
  const checks = [
    page.getByText(/choose\s+your\s+location/i).first(),
    page.getByText(/select\s+(your\s+)?location/i).first(),
    page.getByText(/select\s+(a\s+)?lab/i).first(),
    page.getByRole('heading', { name: /location|lab|organization/i }).first(),
    page.getByRole('dialog', { name: /location|lab/i }).first(),
  ];
  for (const loc of checks) {
    if ((await loc.count().catch(() => 0)) > 0 && (await loc.isVisible().catch(() => false))) {
      return true;
    }
  }
  // Location as combobox on same login route after first submit
  const onLogin = isLoginUrl(page.url());
  if (onLogin) {
    const combo = page.getByRole('combobox').first();
    if ((await combo.count().catch(() => 0)) > 0 && (await combo.isVisible().catch(() => false))) {
      const userVisible = page.locator('[name="username"]').first();
      const stillHasUser =
        (await userVisible.count().catch(() => 0)) > 0 && (await userVisible.isVisible().catch(() => false));
      if (!stillHasUser) return true;
    }
  }
  return false;
}

async function selectAdminLocation(page: Page, labName: string): Promise<void> {
  const lab = labName.trim() || 'Arbro - Delhi';

  const choose = page.getByText(/choose\s+your\s+location/i).first();
  if ((await choose.count().catch(() => 0)) > 0 && (await choose.isVisible().catch(() => false))) {
    await choose.click({ timeout: 8000 }).catch(() => {});
  }

  const labSpan = page.getByText(lab, { exact: false }).first();
  if ((await labSpan.count().catch(() => 0)) > 0 && (await labSpan.isVisible().catch(() => false))) {
    await labSpan.click({ timeout: 12000 }).catch(() => {});
    return;
  }

  const locInput = page.getByPlaceholder(/location|lab|branch|site|organization/i).first();
  if ((await locInput.count().catch(() => 0)) > 0 && (await locInput.isVisible().catch(() => false))) {
    await locInput.fill(lab, { timeout: 8000 }).catch(() => {});
    await page.keyboard.press('Enter').catch(() => {});
    return;
  }

  const combo = page.getByRole('combobox').first();
  if ((await combo.count().catch(() => 0)) > 0 && (await combo.isVisible().catch(() => false))) {
    await combo.click({ timeout: 5000 }).catch(() => {});
    await page.getByRole('option', { name: new RegExp(lab.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i') }).first().click({ timeout: 8000 }).catch(() => {});
    return;
  }

  const fallback = page.locator('span[class*="cursor-pointer"], li[role="option"], [role="option"]').first();
  if ((await fallback.count().catch(() => 0)) > 0) {
    await fallback.click({ timeout: 8000 }).catch(() => {});
  }
}

/**
 * Admin: username → password → Sign in → (location UI) → pick lab → Sign in again → dashboard.
 * Other roles: username → password → Sign in → dashboard (no location handling).
 */
export async function ensureLoggedIn(
  page: Page,
  baseUrl: string,
  sessionId: string,
  scenarioId?: string,
  workspaceCreds?: WorkspaceLoginCredentials | null,
) {
  void sessionId;
  void scenarioId;

  const role = (workspaceCreds?.roleHint || process.env.QAPTAIN_TEST_ROLE || 'ADMIN').trim();
  const fixture = loadFixtureCredentials(role);
  const creds: FixtureCredentials = {
    baseUrl: fixture.baseUrl,
    labName: workspaceCreds?.labName ?? fixture.labName,
    username: workspaceCreds?.username ?? fixture.username,
    password: workspaceCreds?.password ?? fixture.password,
  };
  if (!creds.username || !creds.password) return;

  const appBase = (baseUrl || creds.baseUrl || '').replace(/\/+$/, '');
  if (!appBase) return;

  const current = page.url();
  if (isDashboardUrl(current)) {
    return;
  }

  const loginUrl = `${appBase}/login`;
  await page.goto(loginUrl, { waitUntil: 'domcontentloaded', timeout: 35000 }).catch(() => {});

  const usernameInput = page.locator('[name="username"]').first();
  const passwordInput = page.locator('[name="password"]').first();

  if ((await usernameInput.count().catch(() => 0)) === 0 || (await passwordInput.count().catch(() => 0)) === 0) {
    if (isDashboardUrl(page.url())) return;
    return;
  }

  await usernameInput.clear({ timeout: 5000 }).catch(() => usernameInput.fill('').catch(() => {}));
  await passwordInput.clear({ timeout: 5000 }).catch(() => passwordInput.fill('').catch(() => {}));
  await usernameInput.fill(creds.username, { timeout: 15000 }).catch(() => {});
  await passwordInput.fill(creds.password, { timeout: 15000 }).catch(() => {});

  const signIn = page.getByRole('button', { name: /sign\s*in/i }).first();
  if ((await signIn.count().catch(() => 0)) === 0) {
    throw new Error('Login page has no Sign in button.');
  }
  await signIn.click({ timeout: 15000 });

  const admin = isAdminRole(workspaceCreds?.roleHint || role);
  const pollUntil = Date.now() + 42000;

  while (Date.now() < pollUntil) {
    await page.waitForLoadState('domcontentloaded', { timeout: 4000 }).catch(() => {});
    const url = page.url();

    if (isDashboardUrl(url)) {
      await page.waitForTimeout(150);
      return;
    }

    if (admin && (await isLocationPickerVisible(page))) {
      await selectAdminLocation(page, creds.labName || 'Arbro - Delhi');
      await page.waitForTimeout(250);

      const signIn2 = page.getByRole('button', { name: /sign\s*in/i }).first();
      if ((await signIn2.count().catch(() => 0)) > 0 && (await signIn2.isVisible().catch(() => false))) {
        await signIn2.click({ timeout: 15000 }).catch(() => {});
      }

      await page
        .waitForFunction(
          () => {
            const href = window.location.href;
            try {
              const u = new URL(href);
              if (/\/dashboard/i.test(u.pathname)) return true;
              if (u.hash && /dashboard/i.test(u.hash)) return true;
            } catch {
              /* ignore */
            }
            return /dashboard/i.test(href);
          },
          null,
          { timeout: 50000 },
        )
        .catch(() => {});
      if (isDashboardUrl(page.url())) {
        await page.waitForTimeout(150);
        return;
      }
    }

    if (!admin && isLoginUrl(url)) {
      const pwdStill = page.locator('[name="password"]').first();
      const stillForm =
        (await pwdStill.count().catch(() => 0)) > 0 && (await pwdStill.isVisible().catch(() => false));
      if (!stillForm && !isDashboardUrl(url)) {
        await page.waitForTimeout(200);
        continue;
      }
    }

    await page.waitForTimeout(180);
  }

  if (!isDashboardUrl(page.url())) {
    throw new Error(
      `Login did not reach the app dashboard. Current URL: ${page.url()}. Role=${role}. For admin, set LAB_NAME in fixtures/data.env.test.ini (e.g. Arbro - Delhi).`,
    );
  }
}
