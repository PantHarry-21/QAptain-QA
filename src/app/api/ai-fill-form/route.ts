import { NextRequest, NextResponse } from 'next/server';
import playwright, { Browser } from 'playwright-core';
import chromium from '@sparticuz/chromium';
import { openAIService } from '@/lib/openai';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  let browser: Browser | null = null;
  try {
    const { url } = await request.json();

    if (!url) {
      return NextResponse.json({ error: 'URL is required' }, { status: 400 });
    }

    const isVercel = process.env.VERCEL || process.env.LAMBDA_TASK_ROOT;
    console.log(`[ai-fill-form] Environment detected as ${isVercel ? 'Vercel' : 'Local'}.`);

    if (isVercel) {
      console.log('[ai-fill-form] Launching browser with @sparticuz/chromium for serverless environment.');
      browser = await playwright.chromium.launch({
        args: chromium.args,
        executablePath: await chromium.executablePath(),
        headless: chromium.headless,
      });
    } else {
      console.log('[ai-fill-form] Launching browser with local Playwright installation.');
      browser = await playwright.chromium.launch({
        headless: true
      });
    }
    const page = await browser.newPage();
    await page.goto(url, { waitUntil: 'networkidle' });

    // Extract all forms from the page
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

        // Filter out hidden, disabled, or read-only fields that are not useful for the AI
        const usefulInputs = inputs.filter(input => !input.isDisabled && !input.isReadOnly && input.type !== 'hidden');

        return { formId: `form_${formIndex}`, inputs: usefulInputs };
      });
      return forms.filter(form => form.inputs.length > 0);
    });

    if (!formsData || formsData.length === 0) {
      return NextResponse.json({ error: 'No usable forms found on the page.' }, { status: 404 });
    }

    // For now, we'll just process the first form found.
    // This could be extended to select a form based on user input.
    const firstForm = formsData[0];

    // Call the AI service to generate the form filling steps
    const result = await openAIService.generateFakerMappings(firstForm);

    return NextResponse.json({
      success: true,
      message: "Form analysis complete. The following steps have been generated to fill the form.",
      data: result,
    });

  } catch (error) {
    console.error('AI Form Fill Error:', error);
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json(
      { 
        error: 'Failed to intelligently fill form',
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