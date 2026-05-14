/** Execution strategy presets (Phase 2). Shared by API routes and client UI. */
export const EXECUTION_MODES = [
  'smoke',
  'functional',
  'validation_heavy',
  'regression',
  'deep_validation',
] as const;

export type ExecutionMode = (typeof EXECUTION_MODES)[number];

export const DEFAULT_EXECUTION_MODE: ExecutionMode = 'functional';

export const EXPANSION_CASE_CAP: Record<string, number> = {
  smoke: 2,
  functional: 4,
  validation_heavy: 6,
  regression: 8,
  deep_validation: 10,
};

export const EXPANSION_STEP_CAP: Record<string, number> = {
  smoke: 8,
  functional: 18,
  validation_heavy: 35,
  regression: 50,
  deep_validation: 70,
};

export function normalizeExecutionMode(mode: string | undefined | null): ExecutionMode {
  const m = (mode || '').toLowerCase();
  if (EXECUTION_MODES.includes(m as ExecutionMode)) return m as ExecutionMode;
  return DEFAULT_EXECUTION_MODE;
}
