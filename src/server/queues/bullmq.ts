import { Queue, Worker, type Job } from 'bullmq';
import Redis from 'ioredis';

const connection = () => {
  const url = process.env.REDIS_URL;
  if (!url) throw new Error('REDIS_URL is not set. Start Redis (see docker-compose.yml).');
  return new Redis(url, { maxRetriesPerRequest: null });
};

export const QUEUE_DISCOVERY = 'qaptain-discovery';
export const QUEUE_EXECUTION = 'qaptain-execution';
export const QUEUE_SCENARIO_EXPAND = 'qaptain-scenario-expand';

let discoveryQueue: Queue | null = null;
let executionQueue: Queue | null = null;
let scenarioExpandQueue: Queue | null = null;

export function getDiscoveryQueue() {
  if (!discoveryQueue) discoveryQueue = new Queue(QUEUE_DISCOVERY, { connection: connection() });
  return discoveryQueue;
}

export function getExecutionQueue() {
  if (!executionQueue) executionQueue = new Queue(QUEUE_EXECUTION, { connection: connection() });
  return executionQueue;
}

export function getScenarioExpandQueue() {
  if (!scenarioExpandQueue)
    scenarioExpandQueue = new Queue(QUEUE_SCENARIO_EXPAND, { connection: connection() });
  return scenarioExpandQueue;
}

export type DiscoveryJobData = {
  discoveryRunId: string;
  workspaceId: string;
  environmentId: string;
  authProfileId: string;
};

export type ExecutionJobData = {
  executionRunId: string;
};

export type ScenarioExpandJobData = {
  scenarioId: string;
  workspaceId: string;
  executionMode?: string;
};

export function registerWorkers(
  onDiscovery: (job: Job<DiscoveryJobData>) => Promise<void>,
  onExecution: (job: Job<ExecutionJobData>) => Promise<void>,
  onExpand: (job: Job<ScenarioExpandJobData>) => Promise<void>,
) {
  const conn = connection();
  const discoveryWorker = new Worker<DiscoveryJobData>(QUEUE_DISCOVERY, onDiscovery, { connection: conn });
  const executionWorker = new Worker<ExecutionJobData>(QUEUE_EXECUTION, onExecution, { connection: conn });
  const expandWorker = new Worker<ScenarioExpandJobData>(QUEUE_SCENARIO_EXPAND, onExpand, { connection: conn });
  return { discoveryWorker, executionWorker, expandWorker };
}
