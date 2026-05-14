import { prisma } from '@/lib/prisma';
import type { Prisma } from '@prisma/client';
import type { ScenarioExpandJobData } from '@/server/queues/bullmq';
import { runScenarioExpandGraph } from '@/server/orchestration/scenario-expand-graph';
import { queryModuleContext } from '@/server/memory/chroma-memory';
import { publishRunIoEvent } from '@/server/events/redis-io';
import {
  EXPANSION_CASE_CAP,
  EXPANSION_STEP_CAP,
  normalizeExecutionMode,
} from '@/server/execution/execution-modes';
import { resolveScenarioToModuleId, recordScenarioModuleMapping } from '@/server/intelligence/module-resolve';
import { buildAssertionTemplateSteps, dedupePlanSteps } from '@/server/intelligence/assertion-templates';

type GeneratedTest = {
  type?: string;
  test_type?: string;
  name?: string;
  priority?: number;
  plan_steps?: unknown[];
};

function mergeGeneratedPlans(tests: GeneratedTest[], stepCap: number): unknown[] {
  const sorted = [...tests].sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0));
  const out: unknown[] = [];
  for (const t of sorted) {
    const steps = t.plan_steps;
    if (!Array.isArray(steps)) continue;
    for (const s of steps) {
      if (out.length >= stepCap) return out;
      const stepObj =
        typeof s === 'object' && s !== null
          ? { ...(s as object), _generatedTest: t.name, _testType: t.type }
          : s;
      out.push(stepObj);
    }
  }
  return out;
}

/** Legacy Phase-1 shape: expanded_cases[].plan_steps */
function legacyMerge(cases: unknown[], stepCap: number): unknown[] {
  const tests: GeneratedTest[] = (cases || []).map((c) => {
    const o = c as GeneratedTest;
    return {
      type: o.test_type || o.type,
      name: o.name,
      priority: 50,
      plan_steps: o.plan_steps,
    };
  });
  return mergeGeneratedPlans(tests, stepCap);
}

export async function processScenarioExpandJob(data: ScenarioExpandJobData) {
  const scenario = await prisma.scenario.findFirst({
    where: { id: data.scenarioId, workspaceId: data.workspaceId },
  });
  if (!scenario) throw new Error('Scenario not found');

  const executionMode = normalizeExecutionMode(data.executionMode);
  const maxSubTests = EXPANSION_CASE_CAP[executionMode] ?? EXPANSION_CASE_CAP.functional;
  const maxPlanSteps = EXPANSION_STEP_CAP[executionMode] ?? EXPANSION_STEP_CAP.functional;

  const modules = await prisma.applicationModule.findMany({
    where: { workspaceId: data.workspaceId },
    take: 60,
    select: { name: true, routePattern: true },
  });
  const chromaHints = await queryModuleContext(data.workspaceId, scenario.title);
  const moduleHints = [
    ...chromaHints,
    ...modules.map((m) => `${m.name} (${m.routePattern || ''})`),
  ];

  const resolved = await resolveScenarioToModuleId(data.workspaceId, scenario.title);
  if (resolved.moduleId && resolved.via !== 'none') {
    await prisma.scenario.update({
      where: { id: scenario.id },
      data: { mappedModuleId: resolved.moduleId },
    });
  }

  const topFields = await prisma.fieldDefinition.findMany({
    where: { workspaceId: data.workspaceId },
    orderBy: { testPriority: 'desc' },
    take: 18,
    select: { label: true, semanticClass: true, required: true, testPriority: true },
  });
  const fieldSummary = topFields
    .map((f) => `${f.semanticClass || 'text'}:${f.label || '?'} req=${f.required} pri=${f.testPriority}`)
    .join('; ');

  const intent = await runScenarioExpandGraph({
    title: scenario.title,
    rawText: scenario.rawText || scenario.steps.join('\n'),
    moduleHints,
    executionMode,
    maxSubTests,
    maxPlanSteps,
    fieldSummary,
    resolvedModuleName: resolved.moduleName,
  });

  const gtRaw = intent.generated_tests;
  const legacyCases = intent.expanded_cases;
  let mergedSteps: unknown[] = [];
  if (Array.isArray(gtRaw) && gtRaw.length > 0) {
    mergedSteps = mergeGeneratedPlans(gtRaw as GeneratedTest[], maxPlanSteps);
  } else if (Array.isArray(legacyCases) && legacyCases.length > 0) {
    mergedSteps = legacyMerge(legacyCases, maxPlanSteps);
  } else if (scenario.steps.length > 0) {
    mergedSteps = scenario.steps.map((t) => ({ action: 'natural_language', text: t }));
  } else {
    mergedSteps = [{ action: 'natural_language', text: `Verify ${scenario.title}` }];
  }

  const templateSteps = buildAssertionTemplateSteps({
    scenarioTitle: scenario.title,
    executionMode,
    topFields: topFields.map((f) => ({
      label: f.label,
      required: f.required,
      semanticClass: f.semanticClass,
      testPriority: f.testPriority,
    })),
  });
  mergedSteps = dedupePlanSteps([...mergedSteps, ...templateSteps]).slice(0, maxPlanSteps);

  const testTypes = Array.isArray(intent.test_types) ? intent.test_types.length : 0;
  const genCount = Array.isArray(gtRaw) ? gtRaw.length : Array.isArray(legacyCases) ? legacyCases.length : 0;
  const riskScore = Math.min(100, 15 + testTypes * 10 + genCount * 6 + topFields.filter((f) => f.testPriority > 60).length * 3);

  await prisma.scenario.update({
    where: { id: scenario.id },
    data: { intent: intent as object, riskScore },
  });

  if (resolved.moduleId) {
    await recordScenarioModuleMapping(data.workspaceId, scenario.title, resolved.moduleId);
  }

  const expansionPreview = {
    executionMode,
    generated_tests: gtRaw || legacyCases || [],
    mergedStepCount: mergedSteps.length,
    caps: { maxSubTests, maxPlanSteps },
  };

  await prisma.executionPlan.create({
    data: {
      workspaceId: data.workspaceId,
      scenarioId: scenario.id,
      plan: {
        steps: mergedSteps,
        intent,
        expansion_preview: expansionPreview,
      } as Prisma.InputJsonValue,
    },
  });

  await publishRunIoEvent(scenario.id, 'scenario-expanded', { scenarioId: scenario.id, executionMode });
}
