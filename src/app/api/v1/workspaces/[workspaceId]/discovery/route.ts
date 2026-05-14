import { NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import { requireSessionUserId, unauthorizedResponse, forbiddenResponse } from '@/lib/require-session';
import { assertWorkspaceAccess } from '@/lib/workspace-access';

export const dynamic = 'force-dynamic';

async function enqueueDiscovery(data: {
  discoveryRunId: string;
  workspaceId: string;
  environmentId: string;
  authProfileId: string;
}) {
  if (process.env.REDIS_URL) {
    const { getDiscoveryQueue } = await import('@/server/queues/bullmq');
    await getDiscoveryQueue().add('discover', data);
  } else {
    const { processDiscoveryJob } = await import('@/server/jobs/discovery-job');
    void processDiscoveryJob(data).catch((err) => console.error('[discovery]', err));
  }
}

type Ctx = { params: Promise<{ workspaceId: string }> };

export async function POST(req: Request, ctx: Ctx) {
  try {
    const userId = await requireSessionUserId();
    const { workspaceId } = await ctx.params;
    if (!(await assertWorkspaceAccess(workspaceId, userId))) return forbiddenResponse();
    const body = await req.json().catch(() => ({}));
    const environmentId = String(body.environmentId || '');
    const authProfileId = String(body.authProfileId || '');
    if (!environmentId || !authProfileId) {
      return NextResponse.json({ error: 'environmentId and authProfileId required' }, { status: 400 });
    }
    const run = await prisma.discoveryRun.create({
      data: {
        workspaceId,
        environmentId,
        phase: 1,
        status: 'PENDING',
      },
    });
    await enqueueDiscovery({
      discoveryRunId: run.id,
      workspaceId,
      environmentId,
      authProfileId,
    });
    return NextResponse.json({ discoveryRun: run });
  } catch (e) {
    if (e instanceof Error && e.message === 'UNAUTHORIZED') return unauthorizedResponse();
    console.error(e);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}
