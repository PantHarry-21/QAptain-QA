import { Page } from 'playwright-core';
import { faker } from '@faker-js/faker';

type FilledField = {
  field: string;
  value: string;
  label?: string;
  placeholder?: string;
  type?: string;
};

export type FillFormResult = {
  filled: FilledField[];
  primaryValue?: string;
  primaryField?: string;
};

export type FillMode = 'create' | 'edit';

type FieldContext = {
  name: string;
  label: string;
  type: string;
  placeholder: string;
  options?: string[];
};

function norm(v: string) {
  return v.toLowerCase();
}

function inferByLabel(field: FieldContext, mode: FillMode): string {
  const key = `${field.name} ${field.label} ${field.placeholder}`.toLowerCase();
  const isEdit = mode === 'edit';

  if (/email/.test(key)) return isEdit ? `updated.${faker.internet.email()}` : faker.internet.email();
  if (/phone|mobile|contact/.test(key)) return faker.phone.number('9#########');
  if (/password|passcode|pwd/.test(key)) return isEdit ? 'Update@12345' : 'Test@12345';
  if (/first.?name|fname/.test(key)) return isEdit ? 'Updated' : 'Test';
  if (/last.?name|lname|surname/.test(key)) return isEdit ? 'User' : 'User';
  if (/full.?name|display.?name|name/.test(key)) return isEdit ? `Updated ${faker.person.fullName()}` : `Test ${faker.person.fullName()}`;
  if (/company|organization|org/.test(key)) return isEdit ? 'Updated QAptain Labs' : 'QAptain Labs';
  if (/title|subject|heading/.test(key)) return isEdit ? `Updated ${faker.lorem.words(3)}` : faker.lorem.words(3);
  if (/description|about|bio|summary|notes|comment|remark/.test(key)) {
    return isEdit ? `Updated ${faker.lorem.sentence()}` : faker.lorem.sentence();
  }
  if (/address|street/.test(key)) return faker.location.streetAddress();
  if (/city/.test(key)) return faker.location.city();
  if (/state|province/.test(key)) return faker.location.state();
  if (/zip|postal|pincode|pin/.test(key)) return faker.location.zipCode();
  if (/country/.test(key)) return 'India';
  if (/url|website|link/.test(key)) return faker.internet.url();
  if (/date|dob|birth/.test(key)) return '1995-01-15';
  if (/time/.test(key)) return '10:30';
  if (/amount|price|cost|salary|total|qty|quantity|count|number/.test(key)) return isEdit ? '25' : '10';
  if (/search/.test(key)) return 'test';
  return isEdit ? `Updated ${faker.lorem.words(2)}` : faker.lorem.words(2);
}

function pickSelectOption(options: string[]): string | null {
  if (!options.length) return null;
  const filtered = options.filter((v) => {
    const k = norm(v);
    return v.trim() && !/select|choose|--|none|default/i.test(k);
  });
  return filtered[0] ?? options[0] ?? null;
}

function pickPrimaryField(filled: FilledField[]): { primaryField?: string; primaryValue?: string } {
  const norm = (s: string) => s.toLowerCase();
  const preferred = ['name', 'title', 'username', 'email', 'code', 'id'];
  for (const key of preferred) {
    const hit = filled.find((f) => norm(f.field).includes(key) || norm(f.label ?? '').includes(key) || norm(f.placeholder ?? '').includes(key));
    if (hit?.value) return { primaryField: hit.field, primaryValue: hit.value };
  }
  const first = filled.find((f) => f.value && f.value.length <= 80);
  return first ? { primaryField: first.field, primaryValue: first.value } : {};
}

/**
 * A skill that uses an AI to map form fields to Faker.js methods, then dynamically
 * generates and fills the form with random, realistic data before submitting it.
 * 
 * @param page The Playwright Page object to interact with.
 */
export async function skillFillFormHappyPath(page: Page, mode: FillMode = 'create'): Promise<FillFormResult> {
  // 1. Find all fillable inputs, textareas, and select elements
  const inputs = await page.locator('input:not([type="hidden"]):not([type="submit"]):not([type="button"]), textarea, select').all();
  
  const formInputs: FieldContext[] = [];
  const inputElementMap = new Map<string, any>();
  const filled: FilledField[] = [];

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

    const inputContext: FieldContext = {
      name: fieldIdentifier,
      label: labelText,
      type: (await input.getAttribute('type')) || 'text',
      placeholder: (await input.getAttribute('placeholder')) || '',
    };

    if (await input.evaluate(el => el.tagName) === 'SELECT') {
        const options = await input.locator('option').all();
        const validOptions: string[] = [];
        for(const opt of options) {
            const value = await opt.getAttribute('value');
            if(value) validOptions.push(value);
        }
        inputContext.options = validOptions;
    }

    formInputs.push(inputContext);
    inputElementMap.set(fieldIdentifier, input);
  }

  // 3. Fill fields based on label/type semantics (deterministic, QA-friendly)
  if (formInputs.length === 0) {
    console.log("No fillable form inputs found.");
    return { filled: [] };
  }

  for (const field of formInputs) {
    const input = inputElementMap.get(field.name);
    if (!input) continue;
    try {
      let fakeValue = inferByLabel(field, mode);

      // Handle different element types
      const tagName = await input.evaluate((el: { tagName: any; }) => el.tagName);
      if (tagName === 'SELECT') {
        const picked = pickSelectOption(field.options || []);
        if (picked) {
          fakeValue = picked;
          await input.selectOption({ value: picked }).catch(async () => {
            await input.selectOption({ label: picked });
          });
        }
      } else {
        await input.fill(String(fakeValue));
      }

      filled.push({
        field: field.name,
        value: String(fakeValue),
        label: field.label,
        placeholder: field.placeholder,
        type: field.type,
      });
    } catch (e) {
      console.error(`Could not fill field "${field.name}". Error: ${e instanceof Error ? e.message : 'Unknown'}`);
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

  const primary = pickPrimaryField(filled);
  return { filled, ...primary };
}
