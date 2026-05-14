import dotenv from 'dotenv';
import { resolve } from 'path';

dotenv.config({ path: resolve(process.cwd(), '.env') });

import type { Job } from 'bullmq';
import {
  registerWorkers,
  type DiscoveryJobData,
  type ExecutionJobData,
  type ScenarioExpandJobData,
} from './src/server/queues/bullmq';
import { processDiscoveryJob } from './src/server/jobs/discovery-job';
import { runExecutionJob } from './src/server/execution/run-execution';
import { processScenarioExpandJob } from './src/server/jobs/scenario-expand-job';

async function onDiscovery(job: Job<DiscoveryJobData>) {
  await processDiscoveryJob(job.data);
}

async function onExecution(job: Job<ExecutionJobData>) {
  await runExecutionJob(job.data.executionRunId);
}

async function onExpand(job: Job<ScenarioExpandJobData>) {
  await processScenarioExpandJob(job.data);
}

const { discoveryWorker, executionWorker, expandWorker } = registerWorkers(onDiscovery, onExecution, onExpand);

for (const w of [discoveryWorker, executionWorker, expandWorker]) {
  w.on('failed', (job, err) => {
    console.error(`[worker] job ${job?.id} failed`, err);
  });
}

console.log('[qaptain-worker] BullMQ workers listening (discovery, execution, scenario-expand)');
