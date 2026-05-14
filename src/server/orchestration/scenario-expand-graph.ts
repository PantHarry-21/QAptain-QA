import OpenAI from 'openai';

function getJsonClient(): OpenAI {
  const azureKey = process.env.AZURE_OPENAI_API_KEY;
  const azureEndpoint = process.env.AZURE_OPENAI_ENDPOINT;
  const deployment = process.env.AZURE_OPENAI_DEPLOYMENT || process.env.OPENAI_MODEL_NAME;
  if (azureKey && azureEndpoint && deployment) {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { AzureOpenAI } = require('openai');
    return new AzureOpenAI({
      apiKey: azureKey,
      endpoint: azureEndpoint,
      deployment,
      apiVersion: process.env.AZURE_OPENAI_API_VERSION || '2024-02-15-preview',
    });
  }
  const key = process.env.OPENAI_API_KEY;
  if (!key) throw new Error('Configure Azure OpenAI or OPENAI_API_KEY for scenario expansion.');
  return new OpenAI({ apiKey: key });
}

export type ScenarioExpandGraphInput = {
  title: string;
  rawText: string;
  moduleHints: string[];
  executionMode: string;
  maxSubTests: number;
  maxPlanSteps: number;
  fieldSummary: string;
  resolvedModuleName: string | null;
};

/**
 * Single JSON response from Azure OpenAI — high-level test design only.
 * Deterministic merging / caps happen in `scenario-expand-job`.
 */
export async function runScenarioExpandGraph(input: ScenarioExpandGraphInput): Promise<Record<string, unknown>> {
  const client = getJsonClient();
  const deployment = process.env.AZURE_OPENAI_DEPLOYMENT || process.env.OPENAI_MODEL_NAME || 'gpt-4o-mini';

  const state = { pass: 0, lastError: '' as string };
  const system = `You are a senior QA architect for QAPtain (Phase 2). Output a single JSON object only (no markdown).

Required keys:
- module (string) — best matching feature/module name
- action (string) — short verb phrase
- test_types (string[]) subset of: positive, negative, boundary, validation, invalid_format
- generated_tests (array of { type: string, name: string, priority: number 1-100, plan_steps: object[] })
- reasoning (string) — brief QA rationale

Each plan_steps item must have "action" one of: navigate, click, fill, natural_language, assert_visible, wait_for_network, wait_ms.
For assert_visible with multiple alternative phrases use alternation regex and set assertRegex: true, e.g. { "action":"assert_visible", "assertRegex": true, "text": "success|saved|error" }.
For fill use: { "action":"fill", "field": "visible label or field name", "value": { "source":"generated" }, "test_type":"positive|negative|boundary|validation" } when appropriate.

Rules:
- At most ${input.maxSubTests} items in generated_tests.
- Each generated_tests[].plan_steps should stay under 12 steps.
- Prefer high-risk areas from field summary when choosing validations.
- executionMode=${input.executionMode}: ${input.executionMode === 'smoke' ? 'minimal depth' : input.executionMode === 'validation_heavy' ? 'emphasize validation steps' : 'balanced'}.
- If resolved module hint is provided, align module naming with it.
${input.resolvedModuleName ? `Resolved module hint: "${input.resolvedModuleName}"` : ''}

Field intelligence summary (prioritize high testPriority semantics):
${input.fieldSummary || '(none)'}`;

  const user = JSON.stringify({
    title: input.title,
    rawText: input.rawText,
    moduleHints: input.moduleHints.slice(0, 40),
    executionMode: input.executionMode,
    maxPlanSteps: input.maxPlanSteps,
  });

  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const res = await client.chat.completions.create({
        model: deployment,
        temperature: 0.12,
        messages: [
          { role: 'system', content: system },
          {
            role: 'user',
            content:
              user +
              (attempt ? `\n\nPrevious error: ${state.lastError}\nReturn valid JSON only.` : ''),
          },
        ],
        response_format: { type: 'json_object' },
      });
      const text = res.choices[0]?.message?.content || '{}';
      const intent = JSON.parse(text) as Record<string, unknown>;
      const gt = intent.generated_tests;
      if (!intent.module && !Array.isArray(gt)) {
        state.lastError = 'Missing module or generated_tests';
        continue;
      }
      state.pass = 1;
      return intent;
    } catch (e) {
      state.lastError = e instanceof Error ? e.message : String(e);
    }
  }
  throw new Error(state.lastError || 'Scenario expansion failed');
}
