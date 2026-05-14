import { prisma } from '@/lib/prisma';
import type { Prisma } from '@prisma/client';
import type { IntelGraphPayload } from '@/server/intelligence/graph-types';
import type { ApiTrafficObservation } from '@/server/intelligence/api-traffic-types';

function graphConfidence(payload: IntelGraphPayload): number {
  const nRoutes = payload.nodes.filter((x) => x.kind === 'route').length;
  const nApis = payload.nodes.filter((x) => x.kind === 'api').length;
  const base = 0.45;
  const bump = Math.min(0.45, nRoutes * 0.02 + nApis * 0.01);
  return Math.round((base + bump) * 100) / 100;
}

export async function upsertNavigationIntelGraph(
  workspaceId: string,
  payload: IntelGraphPayload,
  sourceDiscoveryId?: string,
): Promise<void> {
  const confidence = graphConfidence(payload);
  await prisma.applicationIntelGraph.upsert({
    where: { workspaceId_label: { workspaceId, label: 'navigation' } },
    create: {
      workspaceId,
      label: 'navigation',
      graph: payload as object,
      confidence,
      source: 'discovery',
      sourceDiscoveryId: sourceDiscoveryId ?? null,
    },
    update: {
      graph: payload as object,
      confidence,
      sourceDiscoveryId: sourceDiscoveryId ?? null,
    },
  });
}

type ModuleRef = { id: string; routePattern: string | null };

function normalizePathFromString(urlOrPath: string): { method: string; pathPattern: string } {
  let path = urlOrPath;
  try {
    path = new URL(urlOrPath).pathname;
  } catch {
    path = urlOrPath.split('?')[0] || urlOrPath;
  }
  if (!path.startsWith('/')) path = `/${path}`;
  return { method: 'GET', pathPattern: path };
}

function guessModule(pathname: string, modules: ModuleRef[]): string | null {
  let best: string | null = null;
  let bestLen = 0;
  for (const m of modules) {
    const p = (m.routePattern || '').split('?')[0];
    if (!p || !p.startsWith('/')) continue;
    if (pathname.startsWith(p) && p.length >= bestLen) {
      best = m.id;
      bestLen = p.length;
    }
  }
  return best;
}

function mergeApiMeta(
  existingMeta: unknown,
  obs: ApiTrafficObservation,
  sourceTag: string,
  priorSampleCount: number,
): Record<string, unknown> {
  const base = (existingMeta && typeof existingMeta === 'object' ? existingMeta : {}) as Record<string, unknown>;
  const hist = { ...((base.statusHistogram as Record<string, number>) || {}) };
  hist[String(obs.status)] = (hist[String(obs.status)] || 0) + 1;

  const oldN = Math.max(0, priorSampleCount);
  const oldAvg = Number(base.avgDurationMs || 0);
  const d = obs.durationMs;
  let avgDurationMs = oldAvg;
  if (d != null && d > 0 && d < 120_000) {
    avgDurationMs = oldN === 0 ? d : (oldAvg * oldN + d) / (oldN + 1);
  }

  return {
    ...base,
    statusHistogram: hist,
    avgDurationMs,
    lastSource: sourceTag,
    lastUrlSample: obs.urlSample.slice(0, 240),
  };
}

function normalizeInput(
  input: string[] | ApiTrafficObservation[],
): ApiTrafficObservation[] {
  if (input.length === 0) return [];
  const first = input[0];
  if (typeof first === 'string') {
    return (input as string[]).map((raw) => {
      const { method, pathPattern } = normalizePathFromString(raw);
      return {
        method,
        pathPattern,
        status: 0,
        urlSample: raw.split('?')[0].slice(0, 500),
      };
    });
  }
  return input as ApiTrafficObservation[];
}

/**
 * Roll up API observations from discovery or execution (incremental stats in `meta`).
 */
export async function recordApiObservations(
  workspaceId: string,
  input: string[] | ApiTrafficObservation[],
  modules: ModuleRef[],
  sourceTag: 'discovery' | 'execution' = 'discovery',
): Promise<void> {
  const list = normalizeInput(input);

  for (const obs of list) {
    const moduleGuess = guessModule(obs.pathPattern, modules);
    const where = {
      workspaceId_method_pathPattern: {
        workspaceId,
        method: obs.method,
        pathPattern: obs.pathPattern,
      },
    };

    const existing = await prisma.apiEndpointIntel.findUnique({ where });
    const priorCount = existing?.sampleCount ?? 0;
    const meta = mergeApiMeta(existing?.meta, obs, sourceTag, priorCount);
    const moduleId = moduleGuess ?? existing?.moduleId ?? null;
    const statusOk = obs.status > 0;

    await prisma.apiEndpointIntel.upsert({
      where,
      create: {
        workspaceId,
        moduleId,
        method: obs.method,
        pathPattern: obs.pathPattern,
        lastStatusCode: statusOk ? obs.status : null,
        sampleCount: 1,
        meta: meta as Prisma.InputJsonValue,
      },
      update: {
        sampleCount: { increment: 1 },
        ...(statusOk ? { lastStatusCode: obs.status } : {}),
        meta: meta as Prisma.InputJsonValue,
        ...(moduleId ? { moduleId } : {}),
      },
    });
  }
}

/** Placeholder workflow surface: ordered module labels (deterministic, low confidence). */
export async function upsertSurfaceWorkflowIntel(workspaceId: string, moduleNames: string[]): Promise<void> {
  if (moduleNames.length === 0) return;
  const steps = moduleNames.map((label, i) => ({
    id: `step_${i}`,
    label,
    kind: 'navigation_target',
  }));
  await prisma.workflowIntel.upsert({
    where: { workspaceId_workflowKey: { workspaceId, workflowKey: 'navigation_surface' } },
    create: {
      workspaceId,
      workflowKey: 'navigation_surface',
      displayName: 'Discovered navigation surface',
      steps,
      dependencies: [],
      confidence: 0.35,
      source: 'deterministic_nav_graph',
      metadata: { note: 'Heuristic surface only; replace with workflow inference when available.' },
    },
    update: {
      steps,
      dependencies: [],
      confidence: 0.35,
      source: 'deterministic_nav_graph',
    },
  });
}
