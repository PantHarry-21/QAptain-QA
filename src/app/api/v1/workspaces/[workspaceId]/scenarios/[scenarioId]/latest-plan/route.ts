import { NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import { requireSessionUserId, unauthorizedResponse, forbiddenResponse } from '@/lib/require-session';
import { assertWorkspaceAccess } from '@/lib/workspace-access';

export const dynamic = 'force-dynamic';

type Ctx = { params: Promise<{ workspaceId: string; scenarioId: string }> };

export async function GET(_req: Request, ctx: Ctx) {
  try {
    const userId = await requireSessionUserId();
    const { workspaceId, scenarioId } = await ctx.params;
    if (!(await assertWorkspaceAccess(workspaceId, userId))) return forbiddenResponse();
    const plan = await prisma.executionPlan.findFirst({
      where: { workspaceId, scenarioId },
      orderBy: { createdAt: 'desc' },
    });
    if (!plan) return NextResponse.json({ plan: null });
    const p = plan.plan as { expansion_preview?: unknown; steps?: unknown[]; intent?: unknown };
    return NextResponse.json({
      plan: {
        id: plan.id,
        createdAt: plan.createdAt,
        expansionPreview: p.expansion_preview ?? null,
        stepCount: Array.isArray(p.steps) ? p.steps.length : 0,
        intentSummary: p.intent && typeof p.intent === 'object' ? (p.intent as { module?: string }).module : null,
      },
    });
  } catch (e) {
    if (e instanceof Error && e.message === 'UNAUTHORIZED') return unauthorizedResponse();
    console.error(e);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}
