import dotenv from 'dotenv';
dotenv.config();
import { prisma } from '../src/lib/prisma';
import { getExecutionQueue } from '../src/server/queues/bullmq';

async function main() {
  const workspaceId = 'cmp5i4ldh000ksfgxlwzmcy76';
  const environmentId = 'cmp5i4lt4000osfgx8lv0j4dw';
  
  const scenario = await prisma.scenario.create({
    data: {
      workspaceId,
      title: 'Manual E2E Verification',
      steps: [
        { action: 'navigate', url: 'https://playwright.dev' },
        { action: 'assert_visible', text: 'Playwright' }
      ] as any,
      status: 'active'
    }
  });
  console.log(`Created scenario: ${scenario.id}`);

  const plan = await prisma.executionPlan.create({
    data: {
      workspaceId,
      scenarioId: scenario.id,
      name: 'E2E Verification Plan',
      plan: { steps: scenario.steps } as any
    }
  });
  console.log(`Created plan: ${plan.id}`);

  const run = await prisma.executionRun.create({
    data: {
      workspaceId,
      environmentId,
      planId: plan.id,
      status: 'PENDING',
      executionMode: 'standard'
    }
  });
  console.log(`Created run: ${run.id}`);

  const q = getExecutionQueue();
  await q.add('execution', { executionRunId: run.id });
  console.log('Job queued.');
}

main().catch(console.error);
