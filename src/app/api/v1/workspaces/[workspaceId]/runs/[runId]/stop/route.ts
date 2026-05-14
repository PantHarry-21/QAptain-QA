import { NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import { requestStopExecutionRun } from '@/lib/test-executor';
import { requireSessionUserId, unauthorizedResponse, forbiddenResponse } from '@/lib/require-session';
import { assertWorkspaceAccess } from '@/lib/workspace-access';

export const dynamic = 'force-dynamic';

type Ctx = { params: Promise<{ workspaceId: string; runId: string }> };

export async function POST(_req: Request, ctx: Ctx) {
  try {
    const userId = await requireSessionUserId();
    const { workspaceId, runId } = await ctx.params;
    if (!(await assertWorkspaceAccess(workspaceId, userId))) return forbiddenResponse();
    const run = await prisma.executionRun.findFirst({ where: { id: runId, workspaceId } });
    if (!run) return NextResponse.json({ error: 'Not found' }, { status: 404 });
    requestStopExecutionRun(runId);
    return NextResponse.json({ ok: true });
  } catch (e) {
    if (e instanceof Error && e.message === 'UNAUTHORIZED') return unauthorizedResponse();
    console.error(e);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}
