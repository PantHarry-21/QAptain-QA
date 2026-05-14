import { NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import { requireSessionUserId, unauthorizedResponse, forbiddenResponse } from '@/lib/require-session';
import { assertWorkspaceAccess } from '@/lib/workspace-access';

export const dynamic = 'force-dynamic';

type Ctx = { params: Promise<{ workspaceId: string }> };

export async function GET(_req: Request, ctx: Ctx) {
  try {
    const userId = await requireSessionUserId();
    const { workspaceId } = await ctx.params;
    if (!(await assertWorkspaceAccess(workspaceId, userId))) return forbiddenResponse();

    const [navGraph, workflows, apiEndpoints] = await Promise.all([
      prisma.applicationIntelGraph.findUnique({
        where: { workspaceId_label: { workspaceId, label: 'navigation' } },
      }),
      prisma.workflowIntel.findMany({
        where: { workspaceId },
        orderBy: { updatedAt: 'desc' },
        take: 50,
      }),
      prisma.apiEndpointIntel.findMany({
        where: { workspaceId },
        orderBy: { sampleCount: 'desc' },
        take: 100,
        include: { module: { select: { id: true, name: true } } },
      }),
    ]);

    return NextResponse.json({
      navigationGraph: navGraph,
      workflows,
      apiEndpoints,
    });
  } catch (e) {
    if (e instanceof Error && e.message === 'UNAUTHORIZED') return unauthorizedResponse();
    console.error(e);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}
