import { NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import { requireSessionUserId, unauthorizedResponse, forbiddenResponse } from '@/lib/require-session';
import { assertWorkspaceAccess } from '@/lib/workspace-access';
import { normalizeExecutionMode } from '@/server/execution/execution-modes';

export const dynamic = 'force-dynamic';

async function enqueueExecution(executionRunId: string) {
  if (process.env.REDIS_URL) {
    const { getExecutionQueue } = await import('@/server/queues/bullmq');
    await getExecutionQueue().add('execute', { executionRunId });
  } else {
    const { runExecutionJob } = await import('@/server/execution/run-execution');
    void runExecutionJob(executionRunId).catch((err) => console.error('[execution]', err));
  }
}

type Ctx = { params: Promise<{ workspaceId: string }> };

export async function GET(_req: Request, ctx: Ctx) {
  try {
    const userId = await requireSessionUserId();
    const { workspaceId } = await ctx.params;
    if (!(await assertWorkspaceAccess(workspaceId, userId))) return forbiddenResponse();
    const runs = await prisma.executionRun.findMany({
      where: { workspaceId },
      orderBy: { createdAt: 'desc' },
      take: 50,
      include: { report: true, plan: { select: { id: true, scenarioId: true } } },
    });
    return NextResponse.json({ runs });
  } catch (e) {
    if (e instanceof Error && e.message === 'UNAUTHORIZED') return unauthorizedResponse();
    console.error(e);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}

export async function POST(req: Request, ctx: Ctx) {
  try {
    const userId = await requireSessionUserId();
    const { workspaceId } = await ctx.params;
    if (!(await assertWorkspaceAccess(workspaceId, userId))) return forbiddenResponse();
    const body = await req.json().catch(() => ({}));
    const scenarioId = body.scenarioId != null ? String(body.scenarioId) : '';
    const planIdIn = body.planId != null ? String(body.planId) : '';
    const environmentId = body.environmentId != null ? String(body.environmentId) : null;
    const executionMode = normalizeExecutionMode(body.executionMode != null ? String(body.executionMode) : undefined);

    let planId = planIdIn;
    if (!planId && scenarioId) {
      const scenario = await prisma.scenario.findFirst({ where: { id: scenarioId, workspaceId } });
      if (!scenario) return NextResponse.json({ error: 'Scenario not found' }, { status: 404 });
      let plan = await prisma.executionPlan.findFirst({
        where: { workspaceId, scenarioId },
        orderBy: { createdAt: 'desc' },
      });
      if (!plan) {
        const steps =
          scenario.steps.length > 0
            ? scenario.steps.map((t) => ({ action: 'natural_language', text: t }))
            : [{ action: 'natural_language', text: `Verify ${scenario.title}` }];
        plan = await prisma.executionPlan.create({
          data: {
            workspaceId,
            scenarioId,
            plan: { steps },
          },
        });
      }
      planId = plan.id;
    }
    if (!planId) return NextResponse.json({ error: 'planId or scenarioId required' }, { status: 400 });

    const run = await prisma.executionRun.create({
      data: {
        workspaceId,
        planId,
        environmentId: environmentId || undefined,
        status: 'QUEUED',
        executionMode,
      },
    });
    await enqueueExecution(run.id);
    return NextResponse.json({ run });
  } catch (e) {
    if (e instanceof Error && e.message === 'UNAUTHORIZED') return unauthorizedResponse();
    console.error(e);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}
