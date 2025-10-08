import { NextRequest, NextResponse } from 'next/server';
import playwright, { Browser, Page } from 'playwright-core';
import chromium from '@sparticuz/chromium';
import { azureAIService } from '@/lib/azure-ai';
import { executeSingleCommand } from '@/lib/test-executor'; // We might need to refactor this

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
    const formsData = await page.evaluate(() => {
      const forms = Array.from(document.querySelectorAll('form')).map((form, formIndex) => {
        const inputs = Array.from(form.querySelectorAll('input, textarea, select')).map((input) => {
            const labelEl = input.closest('label');
            let labelText = '';
            if (labelEl) {
                labelText = labelEl.textContent || '';
            } else {
                const labels = input.labels;
                if (labels && labels.length > 0) {
                    labelText = Array.from(labels).map(l => l.textContent).join(' ');
                }
            }
            return {
                tagName: input.tagName.toLowerCase(),
                type: input.getAttribute('type') || 'text',
                name: input.getAttribute('name') || '',
                id: input.id || '',
                placeholder: input.getAttribute('placeholder') || '',
                label: labelText.trim(),
                isDisabled: (input as HTMLInputElement).disabled,
                isReadOnly: (input as HTMLInputElement).readOnly,
            };
        });
        const usefulInputs = inputs.filter(input => !input.isDisabled && !input.isReadOnly && input.type !== 'hidden');
        return { formId: `form_${formIndex}`, inputs: usefulInputs };
      });
      return forms.filter(form => form.inputs.length > 0);
    });

    if (!formsData || formsData.length === 0) {
      return NextResponse.json({ error: 'No usable forms found on the page.' }, { status: 404 });
    }
    const firstForm = formsData[0];

    // 2. Generate the test plan from the AI
    const testPlan = await azureAIService.generateFormValidationScenarios(firstForm);
    const results = [];

    // 3. Execute each scenario in the test plan
    for (const scenario of testPlan.scenarios) {
        console.log(`--- Running Scenario: ${scenario.name} ---`);
        await page.goto(url, { waitUntil: 'networkidle' });

        // Execute fill steps
        for (const step of scenario.steps) {
            // We need a way to execute these steps. For now, we'll use a simplified version.
            // This highlights the need to refactor test-executor to export its command functions.
            try {
                await executeSingleCommand({ type: 'fill', target: step.target, value: step.value }, page, url, 'session-id', 'scenario-id');
            }
            catch (e) {
                console.error(`Error during fill step for target "${step.target}":`, e);
                // In a real scenario, we'd log this failure and continue if possible
            }
        }

        // Find and click the submit button
        const submitButton = await findSubmitButton(page);
        if (submitButton) {
            await submitButton.click();
            // Wait for potential navigation or async validation
            await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});
        } else {
            results.push({ scenarioName: scenario.name, status: 'Failed', error: 'Could not find submit button.' });
            continue; // Move to next scenario
        }

        // 4. Observe the result
        const screenshot = await page.screenshot({ fullPage: true });
        const pageText = await page.content();

        // For now, we just record the outcome. The next step is to use AI to analyze these.
        results.push({
            scenarioName: scenario.name,
            status: 'Completed',
            screenshot: `data:image/png;base64,${screenshot.toString('base64')}`,
            // pageText: pageText, // This can be very large, so we omit it for now
        });
    }

    await browser.close();

    return NextResponse.json({
      success: true,
      message: "Form validation test execution completed.",
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
