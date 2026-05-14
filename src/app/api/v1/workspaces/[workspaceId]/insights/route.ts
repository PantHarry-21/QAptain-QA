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
    const [modules, fields, scenarios, risk, runs] = await Promise.all([
      prisma.applicationModule.count({ where: { workspaceId } }),
      prisma.fieldDefinition.count({ where: { workspaceId } }),
      prisma.scenario.count({ where: { workspaceId } }),
      prisma.scenario.aggregate({
        where: { workspaceId },
        _avg: { riskScore: true },
      }),
      prisma.executionRun.groupBy({
        by: ['status'],
        where: { workspaceId },
        _count: { _all: true },
      }),
    ]);
    return NextResponse.json({
      modules,
      fields,
      scenarios,
      avgRiskScore: risk._avg.riskScore ?? 0,
      runsByStatus: Object.fromEntries(runs.map((r) => [r.status, r._count._all])),
    });
  } catch (e) {
    if (e instanceof Error && e.message === 'UNAUTHORIZED') return unauthorizedResponse();
    console.error(e);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}
