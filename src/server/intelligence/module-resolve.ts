import { prisma } from '@/lib/prisma';

export function normalizePhrase(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function tokenize(s: string): Set<string> {
  return new Set(
    normalizePhrase(s)
      .split(' ')
      .filter((w) => w.length > 2),
  );
}

function overlapScore(a: Set<string>, b: Set<string>): number {
  let n = 0;
  for (const x of a) if (b.has(x)) n++;
  return n;
}

/** Resolve scenario text to best ApplicationModule id (deterministic). */
export async function resolveScenarioToModuleId(
  workspaceId: string,
  scenarioTitle: string,
): Promise<{ moduleId: string | null; moduleName: string | null; via: 'mapping' | 'similarity' | 'none' }> {
  const norm = normalizePhrase(scenarioTitle);
  if (!norm) return { moduleId: null, moduleName: null, via: 'none' };

  const mapped = await prisma.scenarioModuleMapping.findUnique({
    where: { workspaceId_phraseNormalized: { workspaceId, phraseNormalized: norm } },
  });
  if (mapped) {
    const mod = await prisma.applicationModule.findFirst({
      where: { id: mapped.moduleId, workspaceId },
    });
    return { moduleId: mapped.moduleId, moduleName: mod?.name ?? null, via: 'mapping' };
  }

  const modules = await prisma.applicationModule.findMany({
    where: { workspaceId },
    select: { id: true, name: true, routePattern: true },
    take: 120,
  });
  const titleTokens = tokenize(scenarioTitle);
  let best: { id: string; name: string; score: number } | null = null;
  for (const m of modules) {
    const mTokens = new Set<string>([
      ...tokenize(m.name),
      ...tokenize(m.routePattern || ''),
    ]);
    const score = overlapScore(titleTokens, mTokens);
    if (!best || score > best.score) best = { id: m.id, name: m.name, score };
  }
  if (best && best.score >= 1) {
    return { moduleId: best.id, moduleName: best.name, via: 'similarity' };
  }
  return { moduleId: null, moduleName: null, via: 'none' };
}

export async function recordScenarioModuleMapping(
  workspaceId: string,
  scenarioTitle: string,
  moduleId: string,
): Promise<void> {
  const phraseNormalized = normalizePhrase(scenarioTitle);
  if (!phraseNormalized) return;
  await prisma.scenarioModuleMapping.upsert({
    where: { workspaceId_phraseNormalized: { workspaceId, phraseNormalized } },
    create: { workspaceId, phraseNormalized, moduleId, score: 1, successCount: 1 },
    update: { moduleId, successCount: { increment: 1 } },
  });
}
