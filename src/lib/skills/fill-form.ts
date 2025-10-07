import { Page } from 'playwright';
import { faker } from '@faker-js/faker';
import { azureAIService } from '@/lib/azure-ai';
import { executeSingleCommand } from '@/lib/test-executor';

async function findSubmitButton(page: Page, contextSelector: string) {
    const context = page.locator(contextSelector);
    const buttonSelectors = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Submit")',
        'button:has-text("Save")',
        'button:has-text("Continue")',
        'button:has-text("Next")',
        'button:has-text("Add")'
    ];

    for (const selector of buttonSelectors) {
        const button = context.locator(selector).first();
        if (await button.isVisible({ timeout: 1000 })) {
            return button;
        }
    }
    return null;
}

// Safely call a faker method based on the AI's mapping
function getFakerData(mapping: { namespace: string; method: string; options?: any[] }): string {
    try {
        const { namespace, method, options = [] } = mapping;
        const ns = faker[namespace as keyof typeof faker];
        if (ns) {
            const fn = ns[method as keyof typeof ns];
            if (typeof fn === 'function') {
                // @ts-ignore
                return fn(...options);
            }
        }
        // Fallback for invalid mapping
        return faker.lorem.word();
    } catch (e) {
        console.error('Faker dispatch error:', e);
        return faker.lorem.word();
    }
}

export async function skillFillFormHappyPath(page: Page, contextSelector: string = 'body'): Promise<any[]> {
    const executionLog = [];

    // 1. Analyze the form on the current page within the given context
    const formsData = await page.evaluate((selector) => {
      const context = document.querySelector(selector) || document;
      
      const inputs = Array.from(context.querySelectorAll('input, textarea, select')).map((input) => {
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

      if (usefulInputs.length > 0) {
        return [{ formId: 'form_in_context', inputs: usefulInputs }];
      }
      return [];
    }, contextSelector);

    if (!formsData || formsData.length === 0) {
        throw new Error("Happy Path skill failed: No usable forms found on the page.");
    }
    const formToFill = formsData[0];

    // 2. Get Faker mappings from AI
    const fakerMappings = await azureAIService.generateFakerMappings(formToFill);

    // 3. Generate fill steps using the AI-Faker mapping
    const fillSteps = formToFill.inputs.map(input => {
        const fieldName = input.label || input.name || input.placeholder;
        const mapping = fakerMappings[fieldName];
        const value = mapping ? getFakerData(mapping) : faker.lorem.words(2); // Fallback
        
        return { 
            action: 'fill', 
            target: fieldName, 
            value: value 
        };
    });

    // 4. Execute fill steps
    for (const step of fillSteps) {
        try {
            await executeSingleCommand({ type: 'fill', target: step.target, value: step.value }, page, page.url(), 'workflow-session', 'workflow-scenario');
            executionLog.push({ action: 'fill', target: step.target, value: step.value, status: 'Completed' });
        } catch (e) {
            const errorMessage = e instanceof Error ? e.message : 'Unknown error';
            executionLog.push({ action: 'fill', target: step.target, value: step.value, status: 'Failed', error: errorMessage });
        }
    }

    // 5. Find and click the submit button
    const submitButton = await findSubmitButton(page, contextSelector);
    if (submitButton) {
        await submitButton.click({ force: true });

        if (contextSelector !== 'body') {
            const modalLocator = page.locator(contextSelector);
            await modalLocator.waitFor({ state: 'hidden', timeout: 10000 });
        } else {
            await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});
        }

        executionLog.push({ action: 'click', target: 'Submit Button', status: 'Completed' });
    } else {
        throw new Error("Happy Path skill failed: Could not find submit button.");
    }

    return executionLog;
}
