import type { ExecutionMode } from '@/lib/execution-modes';

export type AssertionTemplateField = {
  label: string | null;
  required: boolean;
  semanticClass: string | null;
  testPriority: number;
};

export type AssertionTemplateContext = {
  scenarioTitle: string;
  executionMode: ExecutionMode;
  topFields: AssertionTemplateField[];
};

function escRe(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Deterministic post-conditions appended after AI expansion (capped by caller).
 * Uses structured plan actions only — executor stays deterministic.
 */
export function buildAssertionTemplateSteps(ctx: AssertionTemplateContext): unknown[] {
  if (ctx.executionMode === 'smoke') return [];

  const out: unknown[] = [];
  const title = ctx.scenarioTitle;
  const deep = ctx.executionMode === 'validation_heavy' || ctx.executionMode === 'deep_validation';

  const mutating = /\b(add|create|save|submit|register|update|delete|remove|approve|reject)\b/i.test(title);
  if (mutating) {
    out.push({
      action: 'wait_for_network',
      url_substring: '/api',
      timeout: deep ? 28000 : 18000,
    });
    out.push({
      action: 'assert_visible',
      assertRegex: true,
      text: 'success|saved|created|updated|submitted|approved|completed|record',
      timeout: deep ? 14000 : 9000,
    });
  }

  if (deep) {
    const critical = ctx.topFields
      .filter((f) => f.required && f.testPriority >= 55 && f.label && f.label.trim().length > 1)
      .slice(0, 2);
    for (const f of critical) {
      out.push({
        action: 'assert_visible',
        text: escRe(f.label!.trim()).slice(0, 80),
        timeout: 8000,
      });
    }
  }

  return out;
}

export function dedupePlanSteps(steps: unknown[]): unknown[] {
  const seen = new Set<string>();
  const out: unknown[] = [];
  for (const s of steps) {
    if (!s || typeof s !== 'object') {
      out.push(s);
      continue;
    }
    const o = s as Record<string, unknown>;
    const key = `${o.action}|${o.text ?? ''}|${o.url_substring ?? o.pattern ?? ''}|${o.field ?? ''}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(s);
  }
  return out;
}
