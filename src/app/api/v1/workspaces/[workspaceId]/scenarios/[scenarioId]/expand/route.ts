import { NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import { requireSessionUserId, unauthorizedResponse, forbiddenResponse } from '@/lib/require-session';
import { assertWorkspaceAccess } from '@/lib/workspace-access';

export const dynamic = 'force-dynamic';

async function enqueueExpand(data: { scenarioId: string; workspaceId: string; executionMode?: string }) {
  if (process.env.REDIS_URL) {
    const { getScenarioExpandQueue } = await import('@/server/queues/bullmq');
    await getScenarioExpandQueue().add('expand', data);
  } else {
    const { processScenarioExpandJob } = await import('@/server/jobs/scenario-expand-job');
    void processScenarioExpandJob(data).catch((err) => console.error('[expand]', err));
  }
}

type Ctx = { params: Promise<{ workspaceId: string; scenarioId: string }> };

export async function POST(req: Request, ctx: Ctx) {
  try {
    const userId = await requireSessionUserId();
    const { workspaceId, scenarioId } = await ctx.params;
    if (!(await assertWorkspaceAccess(workspaceId, userId))) return forbiddenResponse();
    const scenario = await prisma.scenario.findFirst({ where: { id: scenarioId, workspaceId } });
    if (!scenario) return NextResponse.json({ error: 'Not found' }, { status: 404 });
    const body = await req.json().catch(() => ({}));
    const executionMode = body.executionMode != null ? String(body.executionMode) : undefined;
    await enqueueExpand({ scenarioId, workspaceId, executionMode });
    return NextResponse.json({ ok: true, queued: true });
  } catch (e) {
    if (e instanceof Error && e.message === 'UNAUTHORIZED') return unauthorizedResponse();
    console.error(e);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}
