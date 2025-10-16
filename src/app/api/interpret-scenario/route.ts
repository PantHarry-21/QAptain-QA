import { NextRequest, NextResponse } from 'next/server';
import playwright from 'playwright-core';
import chromium from '@sparticuz/chromium';
import { openAIService } from '@/lib/openai';

export async function POST(request: NextRequest) {
  let browser: playwright.Browser | null = null;
  try {
    let { url, userStory, pageContext } = await request.json();

    if (!url || !userStory) {
      return NextResponse.json({ error: 'URL and userStory are required' }, { status: 400 });
    }

    if (!pageContext) {
        // Launch browser
        const isVercel = process.env.VERCEL || process.env.LAMBDA_TASK_ROOT;
        if (isVercel) {
        browser = await playwright.chromium.launch({
            args: chromium.args,
            executablePath: await chromium.executablePath(),
            headless: chromium.headless,
        });
        } else {
        browser = await playwright.chromium.launch({
            headless: true
        });
        }
        
        const page = await browser.newPage();
        await page.goto(url, { waitUntil: 'networkidle' });

        // Analyze the page to provide context to the AI
        pageContext = await page.evaluate(() => {
            const visibleButtons = Array.from(document.querySelectorAll('button')).map(btn => btn.textContent?.trim() || '').filter(text => text.length > 0 && text.length < 100);
            const visibleLinks = Array.from(document.querySelectorAll('a')).map(a => a.textContent?.trim() || '').filter(text => text.length > 0 && text.length < 100);
            const formInputs = Array.from(document.querySelectorAll('input, textarea, select')).map(input => {
                const labelEl = input.closest('label');
                let labelText = '';
                if (labelEl) {
                    labelText = labelEl.textContent || '';
                } else {
                    const labels = (input as HTMLInputElement).labels;
                    if (labels && labels.length > 0) {
                        labelText = Array.from(labels).map(l => l.textContent).join(' ');
                    }
                }
                return {
                    label: labelText.trim(),
                    name: input.getAttribute('name') || '',
                    placeholder: input.getAttribute('placeholder') || '',
                    type: input.getAttribute('type') || 'text',
                };
            });

            return { visibleButtons, visibleLinks, formInputs };
        });
    }

    // Call the new AI interpreter service
    const result = await openAIService.interpretScenario(userStory, pageContext);

    return NextResponse.json(result);

  } catch (error) {
    console.error('Interpret Scenario Error:', error);
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    return NextResponse.json(
      { 
        error: 'Failed to interpret scenario',
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
