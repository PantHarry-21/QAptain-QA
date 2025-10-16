import { Page } from 'playwright-core';
import { faker } from '@faker-js/faker';
import { openAIService, PageContext } from '@/lib/openai';
import { executeSingleCommand } from '@/lib/test-executor';

async function findSubmitButton(page: Page, contextSelector: string) {
    const context = page.locator(contextSelector);
    const buttonSelectors = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Add Agent")', // More specific
        'button:has-text("Submit")',
        'button:has-text("Save")',
        'button:has-text("Continue")',
        'button:has-text("Next")',
        'button:has-text("Add")' // Fallback
    ];

    for (const selector of buttonSelectors) {
        const button = context.locator(selector).first();
        if (await button.isVisible({ timeout: 1000 })) {
            return button;
        }
    }
    return null;
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

    // Construct a PageContext object for the new AI service
    const pageContext: PageContext = {
        title: await page.title(),
        url: originalUrl,
        hasLoginForm: false, // Context is limited to the form, so these are unknown
        hasContactForm: false,
        hasSearchForm: false,
        forms: [{ id: formToTest.formId, className: '', inputs: formToTest.inputs.map(i => ({name: i.name, type: i.type, placeholder: i.placeholder})) }],
        navLinks: [], // Not available in this limited context
    };

    // 2. Generate the validation test plan from the AI
    const testPlan = await openAIService.generateScenarios(pageContext);
    
    // NOTE: The execution part of this skill has been temporarily disabled.
    // The new `generateScenarios` method produces a different output format that is not compatible
    // with the old execution logic. This section needs to be refactored.
    const results: any[] = [];
    /*
    // 3. Augment the Happy Path scenario with Faker data using the AI+Faker mapping
    const happyPathScenario = testPlan.scenarios.find((s: any) => s.title.toLowerCase().includes('happy path'));
    if (happyPathScenario) {
        const fakerMappings = await openAIService.generateFakerMappings(formToTest);
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
            await submitButton.evaluate(element => element.click()); // Use evaluate to click

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
    */

    return {
        testPlan,
        results
    };
}