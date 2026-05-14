import type { Page } from 'playwright';
import type { ApiTrafficObservation } from '@/server/intelligence/api-traffic-types';

/** DOM / network stability helpers — prefer waits over blind sleeps. */
export async function settleDom(page: Page, timeoutMs = 10000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const busy = await page.locator('[aria-busy="true"]').count().catch(() => 0);
    const spin = await page
      .locator(
        '[class*="spinner"], [class*="Spinner"], [class*="loading"], [data-loading="true"], .MuiCircularProgress-root',
      )
      .count()
      .catch(() => 0);
    if (busy === 0 && spin === 0) break;
    await page.waitForTimeout(100);
  }
  await page.waitForLoadState('domcontentloaded', { timeout: 5000 }).catch(() => {});
}

export async function waitForNavigationStable(
  page: Page,
  urlOrPredicate?: string | RegExp,
  timeout = 30000,
): Promise<void> {
  await page.waitForLoadState('domcontentloaded', { timeout }).catch(() => {});
  await settleDom(page, 6000);
  if (urlOrPredicate) {
    if (typeof urlOrPredicate === 'string') {
      await page.waitForURL(`**${urlOrPredicate}**`, { timeout }).catch(() => {});
    } else {
      await page.waitForURL(urlOrPredicate, { timeout }).catch(() => {});
    }
  }
}

function isApiLikeUrl(url: string): boolean {
  return /\/api\b|graphql|\/v\d\//i.test(url);
}

function pathnameOnly(url: string): string {
  try {
    let p = new URL(url).pathname;
    if (!p.startsWith('/')) p = `/${p}`;
    return p;
  } catch {
    const q = url.split('?')[0] || url;
    return q.startsWith('/') ? q : `/${q}`;
  }
}

/**
 * Collect API-like traffic: method, path, status, duration (request→response).
 * `patterns` remains URL list (no query) for backward compatibility.
 */
export function attachApiPatternCollector(
  page: Page,
  origin: string,
  maxUniquePatterns = 40,
): { observations: ApiTrafficObservation[]; patterns: string[]; dispose: () => void } {
  const observations: ApiTrafficObservation[] = [];
  const patterns: string[] = [];
  const maxObs = Math.min(400, Math.max(40, maxUniquePatterns * 6));
  const starts = new WeakMap<import('playwright').Request, number>();

  const onRequest = (req: import('playwright').Request) => {
    try {
      const u = req.url();
      if (!u.startsWith(origin)) return;
      if (!isApiLikeUrl(u)) return;
      starts.set(req, Date.now());
    } catch {
      /* ignore */
    }
  };

  const onResponse = (res: import('playwright').Response) => {
    try {
      const u = res.url();
      if (!u.startsWith(origin)) return;
      if (!isApiLikeUrl(u)) return;
      const req = res.request();
      const t0 = starts.get(req);
      starts.delete(req);
      const durationMs =
        t0 != null ? Math.min(120_000, Math.max(0, Date.now() - t0)) : undefined;
      const clean = u.split('?')[0];
      const pathPattern = pathnameOnly(u);
      const method = req.method() || 'GET';
      const status = res.status();
      if (observations.length < maxObs) {
        observations.push({
          method: method.toUpperCase(),
          pathPattern,
          status,
          durationMs,
          urlSample: clean.slice(0, 500),
        });
      }
      if (patterns.length < maxUniquePatterns && !patterns.includes(clean)) patterns.push(clean);
    } catch {
      /* ignore */
    }
  };

  page.on('request', onRequest);
  page.on('response', onResponse);
  return {
    observations,
    patterns,
    dispose: () => {
      page.off('request', onRequest);
      page.off('response', onResponse);
    },
  };
}

export type { ApiTrafficObservation } from '@/server/intelligence/api-traffic-types';
