import { NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import { requireSessionUserId, unauthorizedResponse, forbiddenResponse } from '@/lib/require-session';
import { assertWorkspaceAccess } from '@/lib/workspace-access';

export const dynamic = 'force-dynamic';

type Ctx = { params: Promise<{ workspaceId: string; runId: string }> };

export async function GET(_req: Request, ctx: Ctx) {
  try {
    const userId = await requireSessionUserId();
    const { workspaceId, runId } = await ctx.params;
    if (!(await assertWorkspaceAccess(workspaceId, userId))) return forbiddenResponse();
    const run = await prisma.executionRun.findFirst({
      where: { id: runId, workspaceId },
      include: {
        plan: true,
        steps: { orderBy: { stepOrder: 'asc' } },
        logs: { orderBy: { createdAt: 'asc' }, take: 500 },
        report: true,
      },
    });
    if (!run) return NextResponse.json({ error: 'Not found' }, { status: 404 });
    return NextResponse.json({ run });
  } catch (e) {
    if (e instanceof Error && e.message === 'UNAUTHORIZED') return unauthorizedResponse();
    console.error(e);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}
