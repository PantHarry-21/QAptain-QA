import type { ClassifiedField } from './field-classifier';

export type InferredRule = {
  ruleType: string;
  source: 'html' | 'ai';
  details: Record<string, unknown>;
};

export function inferValidationRules(cf: ClassifiedField): InferredRule[] {
  const rules: InferredRule[] = [];

  if (cf.required) {
    rules.push({ ruleType: 'required', source: 'html', details: {} });
  }
  if (cf.minLength != null && cf.minLength > 0) {
    rules.push({ ruleType: 'min_length', source: 'html', details: { min: cf.minLength } });
  }
  if (cf.maxLength != null && cf.maxLength > 0) {
    rules.push({ ruleType: 'max_length', source: 'html', details: { max: cf.maxLength } });
  }
  if (cf.pattern) {
    rules.push({ ruleType: 'pattern', source: 'html', details: { pattern: cf.pattern } });
  }
  if (cf.semanticClass === 'email') {
    rules.push({ ruleType: 'email_format', source: 'html', details: {} });
  }
  if (cf.semanticClass === 'phone') {
    rules.push({ ruleType: 'phone_format', source: 'html', details: {} });
  }
  if (cf.semanticClass === 'numeric' || cf.semanticClass === 'currency' || cf.semanticClass === 'decimal') {
    rules.push({ ruleType: 'numeric', source: 'html', details: { class: cf.semanticClass } });
  }
  if (cf.semanticClass === 'date') {
    rules.push({ ruleType: 'date_format', source: 'html', details: {} });
  }
  if (cf.semanticClass === 'postal_code') {
    rules.push({ ruleType: 'postal_format', source: 'html', details: {} });
  }
  if (cf.semanticClass === 'url') {
    rules.push({ ruleType: 'url_format', source: 'html', details: {} });
  }

  return rules;
}
