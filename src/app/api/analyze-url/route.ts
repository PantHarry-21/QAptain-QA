import { NextResponse } from 'next/server';
import playwright from 'playwright-core';
import chromium from '@sparticuz/chromium';
import { openAIService, PageContext } from '@/lib/openai';

export const dynamic = 'force-dynamic';

export async function POST(request: Request) {
  const { url } = await request.json();

  if (!url) {
    return NextResponse.json({ error: 'URL is required' }, { status: 400 });
  }

  let browser: playwright.Browser | null = null;
  try {
    const normalizedUrl = url.startsWith('http://') || url.startsWith('https://') ? url : `https://${url}`;
    const isServerless = process.env.VERCEL || process.env.LAMBDA_TASK_ROOT || process.env.RENDER;

    if (isServerless) {
      browser = await playwright.chromium.launch({
        args: chromium.args,
        executablePath: await chromium.executablePath(),
        headless: chromium.headless,
      });
    } else {
      browser = await playwright.chromium.launch({
        headless: true,
      });
    }

    const context = await browser.newContext({
      // UAT/self-signed certs are common; don't fail early on cert chain errors.
      ignoreHTTPSErrors: true,
      userAgent:
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    });
    const page = await context.newPage();
    // Make sure we don't hang forever on slow/unresponsive pages.
    page.setDefaultTimeout(7000);
    page.setDefaultNavigationTimeout(20000);

    // Fast mode: block heavy resources we don't need for initial form/link/context discovery.
    await page.route('**/*', (route) => {
      const type = route.request().resourceType();
      if (['image', 'font', 'media'].includes(type)) {
        return route.abort();
      }
      return route.continue();
    });

    // Retry strategy for slow/JS-heavy UATs:
    // 1) domcontentloaded
    // 2) commit + body availability check
    // Never block on full "load" because many UATs keep long-lived requests.
    let navigated = false;
    let lastNavError: unknown = null;
    const hasUsableDom = async () => {
      try {
        return await page.evaluate(() => {
          const hasBody = !!document.body;
          const textLen = (document.body?.innerText || '').trim().length;
          return hasBody && textLen > 20;
        });
      } catch {
        return false;
      }
    };

    try {
      await page.goto(normalizedUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
      navigated = true;
    } catch (e) {
      lastNavError = e;
    }

    if (!navigated) {
      // Fallback: accept early commit and then wait for body to appear.
      try {
        await page.goto(normalizedUrl, { waitUntil: 'commit', timeout: 30000 });
        await page.waitForSelector('body', { timeout: 15000 });
        navigated = await hasUsableDom();
      } catch (e) {
        lastNavError = e;
      }
    }

    // If navigation APIs timed out but page still rendered enough DOM, continue.
    if (!navigated) {
      navigated = await hasUsableDom();
    }

    if (!navigated) {
      throw lastNavError instanceof Error ? lastNavError : new Error('Navigation failed for target URL');
    }

    // Small settle delay for dynamic forms after initial render.
    await page.waitForTimeout(1000);

    // Extract comprehensive page context
    const pageContext: PageContext = await page.evaluate(() => {
      const limit = <T>(arr: T[], n: number) => arr.slice(0, n);

      const allForms = limit(Array.from(document.querySelectorAll('form')), 8).map(form => ({
        id: form.id,
        className: form.className,
        inputs: limit(
          Array.from(form.querySelectorAll('input, textarea, select')),
          25,
        ).map(input => ({
          name: (input as HTMLInputElement).name,
          type: (input as HTMLInputElement).type,
          placeholder: (input as HTMLInputElement).placeholder,
        })),
      }));

      const allNavLinks = limit(Array.from(document.querySelectorAll('nav a')), 20).map(link => ({
        href: (link as HTMLAnchorElement).href,
        text: link.textContent,
      }));

      const visibleFormsCount = allForms.reduce((sum, f) => sum + (f.inputs?.length ? 1 : 0), 0);

      return {
        title: document.title,
        url: window.location.href,
        hasLoginForm: !!document.querySelector('form[id*="login"], form[class*="login"]'),
        hasContactForm: !!document.querySelector('form[id*="contact"], form[class*="contact"]'),
        hasSearchForm: !!document.querySelector('form[role="search"], form[action*="search"]'),
        // Keep payload small for faster OpenAI calls.
        forms: visibleFormsCount > 0 ? allForms : limit(allForms, 3),
        navLinks: allNavLinks,
      };
    });

    // Generate scenarios directly using the extracted context
    const scenarios = await openAIService.generateScenarios(pageContext);

    // Return both the raw context and the generated scenarios so the UI (and
    // Excel import) can interpret user stories without re-visiting the page.
    return NextResponse.json({ scenarios, pageContext });

  } catch (error) {
    console.error('Error analyzing URL and generating scenarios:', error);
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    const friendly = errorMessage.includes('Timeout')
      ? 'Target website took too long to load. Please retry or check site availability/network access.'
      : 'Failed to analyze URL and generate scenarios';
    return NextResponse.json(
      {
        error: friendly,
        details: errorMessage
      },
      { status: 500 }
    );
  } finally {
    if (browser) {
      await browser.close();
    }
  }
}