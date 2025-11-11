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
    const isVercel = process.env.VERCEL || process.env.LAMBDA_TASK_ROOT;

    if (isVercel) {
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

    const page = await browser.newPage();
    await page.goto(url, { waitUntil: 'load', timeout: 60000 });

    // Extract comprehensive page context
    const pageContext: PageContext = await page.evaluate(() => {
      const allForms = Array.from(document.querySelectorAll('form')).map(form => ({
        id: form.id,
        className: form.className,
        inputs: Array.from(form.querySelectorAll('input, textarea, select')).map(input => ({
          name: (input as HTMLInputElement).name,
          type: (input as HTMLInputElement).type,
          placeholder: (input as HTMLInputElement).placeholder,
        })),
      }));

      const allNavLinks = Array.from(document.querySelectorAll('nav a')).map(link => ({
        href: (link as HTMLAnchorElement).href,
        text: link.textContent,
      }));

      return {
        title: document.title,
        url: window.location.href,
        hasLoginForm: !!document.querySelector('form[id*="login"], form[class*="login"]'),
        hasContactForm: !!document.querySelector('form[id*="contact"], form[class*="contact"]'),
        hasSearchForm: !!document.querySelector('form[role="search"], form[action*="search"]'),
        forms: allForms,
        navLinks: allNavLinks,
      };
    });

    // Generate scenarios directly using the extracted context
    const scenarios = await openAIService.generateScenarios(pageContext);

    return NextResponse.json(scenarios);

  } catch (error) {
    console.error('Error analyzing URL and generating scenarios:', error);
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json(
      { 
        error: 'Failed to analyze URL and generate scenarios',
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