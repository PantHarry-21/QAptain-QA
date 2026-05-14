import type { Page } from 'playwright';

function escapeRe(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Strip leading "Navigate to" / "Go to" and environment suffixes. */
function normalizeSegment(raw: string): string {
  return raw
    .replace(/^(?:navigate\s+to|go\s+to|open)\s+/i, '')
    .replace(/\s+on\s+UAT\b.*$/i, '')
    .trim();
}

/**
 * Pull parent → child module path from scenario title/description when steps
 * do not already say "Navigate …".
 */
export function extractModulePathFromScenario(title: string, description?: string): string[] {
  const desc = description?.trim() || '';
  let head = `${title}`.trim();

  const pipeSplit = head.split(/\s*\|\s*/);
  if (pipeSplit.length > 1) {
    head = pipeSplit[0].trim();
    const tail = pipeSplit.slice(1).join(' | ').trim();
    if (!/^verify\b/i.test(tail) && tail) {
      head = `${head} | ${tail}`;
    }
  }

  if (!head.trim() && !desc) return [];

  const primary = head || title;
  const parts = primary
    .split(/\s*(?:→|➜)\s*|\s*->\s*|\s*\|\s*/g)
    .map((p) => normalizeSegment(p))
    .filter(Boolean);

  const isStepVerbage = (s: string) =>
    /^(click|verify|assert|check|search|fill|type|select|press|wait|enter)\b/i.test(s) || s.length > 120;

  const fromTitle = parts.filter((s) => !isStepVerbage(s));

  const moduleFromDesc = desc.match(/\bmodule:\s*([^|]+)/i);
  if (moduleFromDesc && !fromTitle.length) {
    const mod = normalizeSegment(moduleFromDesc[1]);
    if (mod && !isStepVerbage(mod)) return [mod];
  }

  // Description sometimes holds paths without arrows in the title.
  if (!fromTitle.length && desc) {
    const descParts = desc
      .split(/\s*(?:→|➜)\s*|\s*->\s*|\s*\|\s*/g)
      .map((p) => normalizeSegment(p))
      .filter(Boolean)
      .filter((s) => !isStepVerbage(s));
    return descParts;
  }

  return fromTitle;
}

/** True if any step explicitly navigates (URL or named page). */
export function stepsHaveExplicitNavigate(steps: string[]): boolean {
  for (const step of steps) {
    const pieces = step
      .split(/\s*\|\s*|\s*(?:→|➜)\s*|\s*->\s*/g)
      .map((s) => s.trim())
      .filter(Boolean);
    for (const p of pieces) {
      const t = p.replace(/^\d+\.\s*/, '');
      if (/^(?:navigate|go|open|visit|browse)\b/i.test(t)) return true;
    }
  }
  return false;
}

async function tryGlobalMenuSearch(page: Page, query: string): Promise<boolean> {
  const candidates = [
    page.getByRole('searchbox').first(),
    page.locator('input[type="search"]').first(),
    page.locator('input[placeholder*="Search" i]').first(),
    page.locator('input[placeholder*="Filter" i]').first(),
    page.locator('input[aria-label*="search" i]').first(),
  ];
  for (const loc of candidates) {
    if ((await loc.count().catch(() => 0)) === 0) continue;
    if (!(await loc.first().isVisible().catch(() => false))) continue;
    await loc.first().fill(query).catch(() => {});
    await page.keyboard.press('Enter').catch(() => {});
    await page.waitForTimeout(450);
    return true;
  }
  return false;
}

async function tryClickLabeled(page: Page, label: string): Promise<boolean> {
  const re = new RegExp(escapeRe(label), 'i');

  const link = page.getByRole('link', { name: re }).first();
  if ((await link.count().catch(() => 0)) > 0 && (await link.isVisible().catch(() => false))) {
    await link.click({ timeout: 15000 });
    await page.waitForLoadState('domcontentloaded', { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(250);
    return true;
  }

  const menu = page.getByRole('menuitem', { name: re }).first();
  if ((await menu.count().catch(() => 0)) > 0 && (await menu.isVisible().catch(() => false))) {
    await menu.click({ timeout: 10000 });
    await page.waitForTimeout(300);
    return true;
  }

  const btn = page.getByRole('button', { name: re }).first();
  if ((await btn.count().catch(() => 0)) > 0 && (await btn.isVisible().catch(() => false))) {
    await btn.click({ timeout: 10000 });
    await page.waitForTimeout(300);
    return true;
  }

  const treeBtn = page.locator(`[role="treeitem"]:has-text("${label.replace(/"/g, '\\"')}")`).first();
  if ((await treeBtn.count().catch(() => 0)) > 0 && (await treeBtn.isVisible().catch(() => false))) {
    await treeBtn.click({ timeout: 10000 });
    await page.waitForTimeout(300);
    return true;
  }

  const anyText = page.getByText(re).first();
  if ((await anyText.count().catch(() => 0)) > 0 && (await anyText.isVisible().catch(() => false))) {
    await anyText.click({ timeout: 8000 });
    await page.waitForTimeout(300);
    return true;
  }

  return false;
}

/** Expand collapsed groups in sidebar / nav (bounded). */
async function expandCollapsedNavGroups(page: Page, maxClicks: number) {
  const roots = page.locator('nav, aside, [role="navigation"]');
  if ((await roots.count().catch(() => 0)) === 0) return;

  const collapsed = roots.locator('button[aria-expanded="false"], [aria-expanded="false"]').filter({
    hasNot: page.locator('input'),
  });

  const n = Math.min(await collapsed.count().catch(() => 0), maxClicks);
  for (let i = 0; i < n; i++) {
    const el = collapsed.nth(i);
    if (await el.isVisible().catch(() => false)) {
      await el.click({ timeout: 3000 }).catch(() => {});
      await page.waitForTimeout(200);
    }
  }
}

/**
 * Human-style: search, expand parents, click module labels in order.
 */
export async function navigateModulePathHuman(
  page: Page,
  segments: string[],
  log?: (message: string) => void,
): Promise<void> {
  for (const raw of segments) {
    const label = normalizeSegment(raw);
    if (!label) continue;

    log?.(`Exploring navigation toward "${label}"…`);

    let opened = false;

    if (await tryClickLabeled(page, label)) {
      log?.(`Opened "${label}" via menu/link.`);
      opened = true;
    } else if (await tryGlobalMenuSearch(page, label) && (await tryClickLabeled(page, label))) {
      log?.(`Opened "${label}" after menu search.`);
      opened = true;
    } else {
      for (let round = 0; round < 4; round++) {
        await expandCollapsedNavGroups(page, 14);
        if (await tryClickLabeled(page, label)) {
          log?.(`Opened "${label}" after expanding nav (round ${round + 1}).`);
          opened = true;
          break;
        }
        await page.waitForTimeout(200);
      }
    }

    if (!opened) {
      log?.(`Could not resolve navigation item "${label}"; continuing with remaining steps.`);
    }
  }
}
