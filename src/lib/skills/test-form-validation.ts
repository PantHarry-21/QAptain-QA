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
function getFakerDataFromMapping(mapping: { namespace: string; method: string; options?: any[] }): string {
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
        return faker.lorem.word(); // Fallback for invalid mapping
    } catch (e) {
        console.error('Faker dispatch error:', e);
        return faker.lorem.word();
    }
}

export async function skillTestFormValidation(page: Page, contextSelector: string = 'body'): Promise<any> {
    const originalUrl = page.url();

    // 1. Analyze the form on the current page
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
        throw new Error("Validation Test skill failed: No usable forms found on the page.");
    }
    const formToTest = formsData[0];

    // 2. Generate the validation test plan from the AI
    const testPlan = await azureAIService.generateFormValidationScenarios(formToTest);
    const results = [];

    // 3. Augment the Happy Path scenario with Faker data using the AI+Faker mapping
    const happyPathScenario = testPlan.scenarios.find((s: any) => s.title.toLowerCase().includes('happy path'));
    if (happyPathScenario) {
        const fakerMappings = await azureAIService.generateFakerMappings(formToTest);
        happyPathScenario.steps = formToTest.inputs.map(input => {
            const fieldName = input.label || input.name || input.placeholder;
            const mapping = fakerMappings[fieldName];
            const value = mapping ? getFakerDataFromMapping(mapping) : faker.lorem.words(2); // Fallback
            return { 
                action: 'fill', 
                target: fieldName, 
                value: value 
            };
        });
    }

    // 4. Execute each scenario in the test plan
    for (const scenario of testPlan.scenarios) {
        // Reset to the form page for each validation scenario
        await page.goto(originalUrl, { waitUntil: 'networkidle' });

        // Execute fill steps
        for (const step of scenario.steps) {
            try {
                await executeSingleCommand({ type: 'fill', target: step.target, value: step.value }, page, originalUrl, 'workflow-session', 'workflow-scenario');
            } catch (e) {
                // Log and ignore errors during fill for negative tests, as the target may not always be interactable
                console.error(`Ignoring error during fill step for negative test: ${scenario.name}`);
            }
        }

        // Find and click the submit button
        const submitButton = await findSubmitButton(page, contextSelector);
        if (submitButton) {
            await submitButton.click({ force: true });

            // After clicking submit, ONLY wait for the modal to close if we are in a modal context.
            if (contextSelector !== 'body') {
                const modalLocator = page.locator(contextSelector);
                await modalLocator.waitFor({ state: 'hidden', timeout: 5000 });
            } else {
                // If it was a normal page form, just wait for a moment or for navigation.
                await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});
            }
        }
        else {
            results.push({ scenarioName: scenario.name, status: 'Failed', error: 'Could not find submit button.' });
            continue; // Move to next scenario
        }

        // 5. Observe the result (basic implementation)
        const screenshot = await page.screenshot({ fullPage: true });
        results.push({
            scenarioName: scenario.name,
            status: 'Completed',
            observation: {
                screenshot: `data:image/png;base64,${screenshot.toString('base64')}`,
                note: 'Initial observation complete. AI analysis of validation messages is the next step.'
            }
        });
    }

    return {
        testPlan,
        results
    };
}