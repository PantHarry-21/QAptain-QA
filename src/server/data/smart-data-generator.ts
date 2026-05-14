import type { Page } from 'playwright';
import { faker } from '@faker-js/faker';
import type { SemanticFieldClass } from '@/server/intelligence/field-classifier';

export type DataProfile =
  | 'positive'
  | 'negative'
  | 'boundary'
  | 'invalid_format'
  | 'unicode'
  | 'empty'
  | 'security_sql'
  | 'security_xss';

const SAFE_XSS = String.raw`<img src=x onerror=alert(1)>`;
const SAFE_SQL = `'; DROP TABLE users--`;

/** Context-aware values for Phase 2 data generation */
export function generateSmartValue(
  semantic: SemanticFieldClass | string,
  profile: DataProfile,
  opts?: { minLen?: number; maxLen?: number },
): string {
  const s = String(semantic).toLowerCase() as SemanticFieldClass;
  const min = opts?.minLen ?? 0;
  const max = opts?.maxLen ?? 9999;

  if (profile === 'security_sql') return SAFE_SQL.slice(0, Math.min(80, max || 80));
  if (profile === 'security_xss') return SAFE_XSS.slice(0, Math.min(60, max || 60));
  if (profile === 'unicode') return '测试-日本語-𝄞';
  if (profile === 'empty') return '';

  if (s === 'email') {
    if (profile === 'positive') return faker.internet.email().slice(0, Math.min(80, max));
    if (profile === 'negative' || profile === 'invalid_format') return 'not-an-email';
    if (profile === 'boundary') return 'a@b';
    return faker.internet.email();
  }

  if (s === 'phone') {
    if (profile === 'positive') return faker.string.numeric(10);
    if (profile === 'negative' || profile === 'invalid_format') return 'abcdefghij';
    if (profile === 'boundary') return '1';
    return faker.phone.number();
  }

  if (s === 'numeric' || s === 'decimal' || s === 'currency') {
    if (profile === 'positive') return String(faker.number.int({ min: 10, max: 99999 }));
    if (profile === 'negative') return 'abc@#';
    if (profile === 'boundary') return faker.helpers.arrayElement(['0', '-1', '999999999999']);
    return String(faker.number.float({ min: 1, max: 999, fractionDigits: 2 }));
  }

  if (s === 'date') {
    if (profile === 'positive') return faker.date.future().toISOString().slice(0, 10);
    if (profile === 'invalid_format') return '32/13/2099';
    if (profile === 'boundary') return '1970-01-01';
    return faker.date.recent().toISOString().slice(0, 10);
  }

  if (s === 'password') {
    if (profile === 'positive') return `Aa1!${faker.string.alphanumeric(10)}`;
    if (profile === 'negative') return '123';
    if (profile === 'boundary') return faker.string.alphanumeric(Math.max(min, 1));
    return faker.internet.password({ length: 14 });
  }

  if (s === 'postal_code') {
    if (profile === 'positive') return faker.location.zipCode('#####');
    if (profile === 'invalid_format') return '!!!!';
    return '00000';
  }

  if (s === 'url') {
    if (profile === 'positive') return faker.internet.url();
    if (profile === 'invalid_format') return 'not-a-url';
    return 'https://example.com';
  }

  // text, textarea, search, address, dropdown, etc.
  const base = faker.lorem.words({ min: 2, max: 5 });
  if (profile === 'positive') return base.slice(0, Math.min(base.length, max > 0 ? max : 200));
  if (profile === 'negative') return faker.helpers.arrayElements('!@#$%^&*()[]'.split(''), { min: 6, max: 12 }).join('');
  if (profile === 'boundary') {
    if (min > 0) return 'x'.repeat(min);
    return '';
  }
  return base;
}

/** Map execution mode + step hint to a data profile (deterministic). */
export function profileForStep(
  executionMode: string,
  testTypeHint?: string,
): DataProfile {
  const mode = executionMode.toLowerCase();
  const hint = (testTypeHint || '').toLowerCase();

  if (hint.includes('negative') || hint.includes('invalid')) return 'invalid_format';
  if (hint.includes('boundary')) return 'boundary';
  if (hint.includes('security') || hint.includes('injection')) return 'security_sql';
  if (mode === 'validation_heavy' || mode === 'deep_validation') {
    return faker.helpers.arrayElement(['positive', 'boundary', 'invalid_format'] as const) as DataProfile;
  }
  if (mode === 'smoke') return 'positive';
  return 'positive';
}
