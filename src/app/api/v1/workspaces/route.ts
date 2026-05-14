import { NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import {
  requireSessionUserId,
  unauthorizedResponse,
} from '@/lib/require-session';
import { readinessScore } from '@/lib/workspace-access';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const userId = await requireSessionUserId();
    const list = await prisma.workspace.findMany({
      where: { OR: [{ ownerId: userId }, { members: { some: { userId } } }] },
      orderBy: { updatedAt: 'desc' },
      include: {
        _count: { select: { modules: true, scenarios: true, executionRuns: true } },
      },
    });
    const enriched = await Promise.all(
      list.map(async (w) => ({
        ...w,
        readiness: await readinessScore(w.id),
      })),
    );
    return NextResponse.json({ workspaces: enriched });
  } catch (e) {
    if (e instanceof Error && e.message === 'UNAUTHORIZED') return unauthorizedResponse();
    console.error(e);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}

export async function POST(req: Request) {
  try {
    const userId = await requireSessionUserId();
    const body = await req.json().catch(() => ({}));
    const name = String(body.name || '').trim();
    const description = body.description ? String(body.description) : null;
    const baseUrl = String(body.baseUrl || '').trim();
    if (!name || !baseUrl) {
      return NextResponse.json({ error: 'name and baseUrl are required' }, { status: 400 });
    }
    const ws = await prisma.$transaction(async (tx) => {
      const w = await tx.workspace.create({
        data: { ownerId: userId, name, description },
      });
      await tx.workspaceMember.create({
        data: { workspaceId: w.id, userId, role: 'OWNER' },
      });
      await tx.environment.create({
        data: { workspaceId: w.id, name: 'Default', baseUrl },
      });
      return w;
    });
    const full = await prisma.workspace.findUnique({
      where: { id: ws.id },
      include: { environments: true, authProfiles: true },
    });
    return NextResponse.json({ workspace: full });
  } catch (e) {
    if (e instanceof Error && e.message === 'UNAUTHORIZED') return unauthorizedResponse();
    console.error(e);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}
