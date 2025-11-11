import { NextRequest, NextResponse } from 'next/server';
import playwright, { Browser, Page } from 'playwright-core';
import chromium from '@sparticuz/chromium';
import { openAIService, PageContext } from '@/lib/openai';
import { executeSingleCommand } from '@/lib/test-executor'; // We might need to refactor this

export const dynamic = 'force-dynamic';

// Helper to find the submit button
async function findSubmitButton(page: Page) {
    const buttonSelectors = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Submit")',
        'button:has-text("Save")',
        'button:has-text("Continue")',
        'button:has-text("Next")'
    ];

    for (const selector of buttonSelectors) {
        const button = page.locator(selector).first();
        if (await button.isVisible()) {
            return button;
        }
    }
    return null;
}


export async function POST(request: NextRequest) {
  let browser: Browser | null = null;
  try {
    const { url } = await request.json();

    if (!url) {
      return NextResponse.json({ error: 'URL is required' }, { status: 400 });
    }

    const isVercel = process.env.VERCEL || process.env.LAMBDA_TASK_ROOT;
    console.log(`[ai-test-form-validations] Environment detected as ${isVercel ? 'Vercel' : 'Local'}.`);

    if (isVercel) {
      console.log('[ai-test-form-validations] Launching browser with @sparticuz/chromium for serverless environment.');
      browser = await playwright.chromium.launch({
        args: chromium.args,
        executablePath: await chromium.executablePath(),
        headless: chromium.headless,
      });
    } else {
      console.log('[ai-test-form-validations] Launching browser with local Playwright installation.');
      browser = await playwright.chromium.launch({
        headless: true
      });
    }
    const page = await browser.newPage();
    
    // 1. Analyze the form
    await page.goto(url, { waitUntil: 'networkidle' });
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

    if (!pageContext.forms || pageContext.forms.length === 0) {
      return NextResponse.json({ error: 'No usable forms found on the page.' }, { status: 404 });
    }

    // 2. Generate the test plan from the AI
    const testPlan = await openAIService.generateScenarios(pageContext);

    // NOTE: The execution part of this route has been temporarily disabled.
    // The new `generateScenarios` method produces a different output format that is not compatible
    // with the old `executeSingleCommand` function. The test executor needs to be refactored
    // to handle the new scenario structure (e.g., "Fill 'test' into 'username'").
    const results: any[] = [];
    /*
    // 3. Execute each scenario in the test plan
    for (const scenario of testPlan.scenarios) {
        console.log(`--- Running Scenario: ${scenario.title} ---`);
        await page.goto(url, { waitUntil: 'networkidle' });

        // The execution logic below is now incompatible with the new scenario step format.
        // It needs to be refactored to parse and execute string-based commands.

        // Find and click the submit button
        const submitButton = await findSubmitButton(page);
        if (submitButton) {
            await submitButton.click();
            // Wait for potential navigation or async validation
            await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});
        } else {
            results.push({ scenarioName: scenario.title, status: 'Failed', error: 'Could not find submit button.' });
            continue; // Move to next scenario
        }

        // 4. Observe the result
        const screenshot = await page.screenshot({ fullPage: true });
        const pageText = await page.content();

        // For now, we just record the outcome. The next step is to use AI to analyze these.
        results.push({
            scenarioName: scenario.title,
            status: 'Completed',
            screenshot: `data:image/png;base64,${screenshot.toString('base64')}`,
        });
    }
    */

    await browser.close();

    return NextResponse.json({
      success: true,
      message: "Form validation test plan generated successfully. Execution is temporarily disabled.",
      data: {
        testPlan,
        results
      },
    });

  } catch (error) {
    console.error('AI Form Validation Test Error:', error);
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json(
      { 
        error: 'Failed to execute form validation tests',
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
