import { Page } from 'playwright-core';
import { faker } from '@faker-js/faker';
import { azureAIService } from '@/lib/azure-ai';

/**
 * A skill that uses an AI to map form fields to Faker.js methods, then dynamically
 * generates and fills the form with random, realistic data before submitting it.
 * 
 * @param page The Playwright Page object to interact with.
 */
export async function skillFillFormHappyPath(page: Page): Promise<void> {
  // 1. Find all fillable inputs, textareas, and select elements
  const inputs = await page.locator('input:not([type="hidden"]):not([type="submit"]):not([type="button"]), textarea, select').all();
  
  const formInputs = [];
  const inputElementMap = new Map();

  // 2. Gather context from each input field
  for (const input of inputs) {
    if (!(await input.isEditable()) || !(await input.isVisible())) {
      continue; // Skip non-editable or non-visible fields
    }

    const name = (await input.getAttribute('name')) || '';
    const id = await input.getAttribute('id');
    let labelText = '';
    if (id) {
      const label = await page.locator(`label[for="${id}"]`).first();
      if (await label.count() > 0) {
        labelText = (await label.textContent()) || '';
      }
    }

    const fieldIdentifier = name || labelText || id;
    if (!fieldIdentifier) continue; // Skip if we can't identify the field

    const inputContext: any = {
        name: fieldIdentifier,
        label: labelText,
        type: (await input.getAttribute('type')) || 'text',
        placeholder: (await input.getAttribute('placeholder')) || '',
    };

    if (await input.evaluate(el => el.tagName) === 'SELECT') {
        const options = await input.locator('option').all();
        const validOptions = [];
        for(const opt of options) {
            const value = await opt.getAttribute('value');
            if(value) validOptions.push(value);
        }
        inputContext.options = validOptions;
    }

    formInputs.push(inputContext);
    inputElementMap.set(fieldIdentifier, input);
  }

  // 3. Call AI to get Faker.js mappings
  if (formInputs.length === 0) {
    console.log("No fillable form inputs found.");
    return;
  }

  const fakerMappings = await azureAIService.generateFakerMappings(formInputs);

  // 4. Iterate through mappings, generate data, and fill the form
  for (const fieldName in fakerMappings) {
    const input = inputElementMap.get(fieldName);
    if (!input) continue;

    const mapping = fakerMappings[fieldName];
    let fakeValue: any = '';

    try {
      const { namespace, method, options } = mapping;
      if (namespace && method && (faker as any)[namespace] && (faker as any)[namespace][method]) {
        fakeValue = options ? (faker as any)[namespace][method](...options) : (faker as any)[namespace][method]();
      } else {
        fakeValue = 'Sample Text'; // Fallback
      }

      // Handle different element types
      const tagName = await input.evaluate((el: { tagName: any; }) => el.tagName);
      if (tagName === 'SELECT') {
        // For select, the value from faker might be one of the options
        await input.selectOption({ value: String(fakeValue) });
      } else {
        await input.fill(String(fakeValue));
      }
    } catch (e) {
      console.error(`Could not fill field "${fieldName}". Error: ${e instanceof Error ? e.message : 'Unknown'}`);
    }
  }

  // 5. Find and click the submit button
  try {
    const submitButton = page.getByRole('button', { name: /submit|save|add|create|update/i });
    if (await submitButton.count() > 0) {
        await submitButton.first().click();
    } else {
        const genericButton = page.locator('button[type="submit"]').first();
        if(await genericButton.count() > 0) {
            await genericButton.click();
        }
    }
  } catch (e) {
    console.error(`Could not find or click the submit button. Error: ${e instanceof Error ? e.message : 'Unknown'}`);
  }
}
