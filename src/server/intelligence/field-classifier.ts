import type { RawDomField } from './dom-field-extract';

/** Normalized semantic classes for Field Intelligence */
export type SemanticFieldClass =
  | 'email'
  | 'phone'
  | 'numeric'
  | 'decimal'
  | 'currency'
  | 'date'
  | 'password'
  | 'textarea'
  | 'dropdown'
  | 'multi_select'
  | 'checkbox'
  | 'radio'
  | 'file'
  | 'autocomplete'
  | 'search'
  | 'address'
  | 'postal_code'
  | 'text'
  | 'url'
  | 'unknown';

export type ClassifiedField = RawDomField & {
  semanticClass: SemanticFieldClass;
  semanticMeaning: string;
  testPriority: number;
};

const FINANCE = /amount|price|cost|total|tax|payment|fee|balance|currency|invoice|po\b|purchase/i;
const AUTH = /password|passcode|otp|token|mfa|2fa/i;
const PII = /ssn|national\s*id|passport|dob|birth/i;

export function classifyField(raw: RawDomField): ClassifiedField {
  const blob = `${raw.labelText} ${raw.placeholder} ${raw.ariaLabel} ${raw.name} ${raw.fieldKey}`.toLowerCase();
  const t = raw.type;

  let semanticClass: SemanticFieldClass = 'unknown';
  let semanticMeaning = 'generic_input';
  let testPriority = 22;

  if (t === 'checkbox') {
    semanticClass = 'checkbox';
    semanticMeaning = 'boolean_choice';
    testPriority = 18;
  } else if (t === 'radio') {
    semanticClass = 'radio';
    semanticMeaning = 'single_choice';
    testPriority = 18;
  } else if (raw.tag === 'select') {
    semanticClass = raw.multiple ? 'multi_select' : 'dropdown';
    semanticMeaning = 'enumeration';
    testPriority = 28;
  } else if (t === 'textarea') {
    semanticClass = 'textarea';
    semanticMeaning = 'long_text';
    testPriority = 20;
  } else if (t === 'file') {
    semanticClass = 'file';
    semanticMeaning = 'upload';
    testPriority = 35;
  } else if (t === 'password') {
    semanticClass = 'password';
    semanticMeaning = 'secret';
    testPriority = 92;
  } else if (t === 'email' || /\bemail\b|e-mail/.test(blob)) {
    semanticClass = 'email';
    semanticMeaning = 'user_email';
    testPriority = 75;
  } else if (t === 'tel' || /\bphone|mobile|tel\b/.test(blob)) {
    semanticClass = 'phone';
    semanticMeaning = 'phone_number';
    testPriority = 55;
  } else if (t === 'number' || /\bqty|quantity|count\b/.test(blob)) {
    semanticClass = 'numeric';
    semanticMeaning = 'quantity';
    testPriority = 40;
  } else if (/\bpostal|zip\b/.test(blob)) {
    semanticClass = 'postal_code';
    semanticMeaning = 'postal';
    testPriority = 38;
  } else if (/\baddress|street|city|state|country\b/.test(blob)) {
    semanticClass = 'address';
    semanticMeaning = 'location';
    testPriority = 35;
  } else if (t === 'date' || t === 'datetime-local' || /\bdate\b/.test(blob)) {
    semanticClass = 'date';
    semanticMeaning = 'temporal';
    testPriority = 42;
  } else if (/\bsearch\b/.test(blob) || t === 'search') {
    semanticClass = 'search';
    semanticMeaning = 'search_query';
    testPriority = 25;
  } else if (/\burl|website|link\b/.test(blob) || t === 'url') {
    semanticClass = 'url';
    semanticMeaning = 'hyperlink';
    testPriority = 30;
  } else if (FINANCE.test(blob)) {
    semanticClass = /\bprice|amount|cost|fee|total|balance|currency\b/i.test(blob) ? 'currency' : 'decimal';
    semanticMeaning = 'financial';
    testPriority = 88;
  } else if (t === 'text' || t === '') {
    semanticClass = 'text';
    semanticMeaning = 'free_text';
    testPriority = 24;
  }

  if (AUTH.test(blob)) testPriority = Math.max(testPriority, 90);
  if (PII.test(blob)) testPriority = Math.max(testPriority, 80);
  if (raw.required) testPriority += 8;
  if (/comment|description|notes|remarks/i.test(blob)) testPriority = Math.min(testPriority, 22);

  testPriority = Math.min(100, Math.max(1, testPriority));

  return { ...raw, semanticClass, semanticMeaning, testPriority };
}
