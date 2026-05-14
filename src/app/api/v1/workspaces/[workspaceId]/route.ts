import { NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import {
  forbiddenResponse,
  requireSessionUserId,
  unauthorizedResponse,
} from '@/lib/require-session';
import { assertWorkspaceAccess, readinessScore } from '@/lib/workspace-access';

export const dynamic = 'force-dynamic';

type Ctx = { params: Promise<{ workspaceId: string }> };

export async function GET(_req: Request, ctx: Ctx) {
  try {
    const userId = await requireSessionUserId();
    const { workspaceId } = await ctx.params;
    const ws = await assertWorkspaceAccess(workspaceId, userId);
    if (!ws) return forbiddenResponse();
    const [environments, authProfiles, modules, lastDiscovery, stats] = await Promise.all([
      prisma.environment.findMany({ where: { workspaceId } }),
      prisma.authProfile.findMany({ where: { workspaceId } }),
      prisma.applicationModule.findMany({
        where: { workspaceId },
        take: 200,
        include: { routes: true },
      }),
      prisma.discoveryRun.findFirst({
        where: { workspaceId },
        orderBy: { createdAt: 'desc' },
      }),
      prisma.scenario.count({ where: { workspaceId } }),
    ]);
    const readiness = await readinessScore(workspaceId);
    return NextResponse.json({
      workspace: ws,
      environments,
      authProfiles,
      modules,
      lastDiscovery,
      scenarioCount: stats,
      readiness,
    });
  } catch (e) {
    if (e instanceof Error && e.message === 'UNAUTHORIZED') return unauthorizedResponse();
    console.error(e);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}

export async function PATCH(req: Request, ctx: Ctx) {
  try {
    const userId = await requireSessionUserId();
    const { workspaceId } = await ctx.params;
    const ws = await assertWorkspaceAccess(workspaceId, userId);
    if (!ws) return forbiddenResponse();
    const body = await req.json().catch(() => ({}));
    const name = body.name != null ? String(body.name).trim() : undefined;
    const description = body.description !== undefined ? (body.description ? String(body.description) : null) : undefined;
    const updated = await prisma.workspace.update({
      where: { id: workspaceId },
      data: {
        ...(name ? { name } : {}),
        ...(description !== undefined ? { description } : {}),
      },
    });
    return NextResponse.json({ workspace: updated });
  } catch (e) {
    if (e instanceof Error && e.message === 'UNAUTHORIZED') return unauthorizedResponse();
    console.error(e);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}

export async function DELETE(_req: Request, ctx: Ctx) {
  try {
    const userId = await requireSessionUserId();
    const { workspaceId } = await ctx.params;
    const ws = await prisma.workspace.findFirst({
      where: { id: workspaceId, ownerId: userId },
    });
    if (!ws) return forbiddenResponse();
    await prisma.workspace.delete({ where: { id: workspaceId } });
    return NextResponse.json({ ok: true });
  } catch (e) {
    if (e instanceof Error && e.message === 'UNAUTHORIZED') return unauthorizedResponse();
    console.error(e);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}
