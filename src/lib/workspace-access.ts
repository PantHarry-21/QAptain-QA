import { prisma } from '@/lib/prisma';

export async function assertWorkspaceAccess(workspaceId: string, userId: string) {
  const ws = await prisma.workspace.findFirst({
    where: {
      id: workspaceId,
      OR: [{ ownerId: userId }, { members: { some: { userId } } }],
    },
  });
  if (!ws) return null;
  return ws;
}

export async function readinessScore(workspaceId: string): Promise<number> {
  const [mods, auth, disc] = await Promise.all([
    prisma.applicationModule.count({ where: { workspaceId } }),
    prisma.authProfile.count({ where: { workspaceId } }),
    prisma.discoveryRun.findFirst({
      where: { workspaceId, status: 'COMPLETED' },
      orderBy: { createdAt: 'desc' },
    }),
  ]);
  let score = 0;
  if (auth > 0) score += 30;
  if (disc) score += 35;
  score += Math.min(35, mods * 3);
  return Math.min(100, score);
}
