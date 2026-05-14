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
    const scenarios = await prisma.scenario.findMany({
      where: { workspaceId },
      orderBy: { updatedAt: 'desc' },
    });
    return NextResponse.json({ scenarios });
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
    const title = String(body.title || '').trim();
    if (!title) return NextResponse.json({ error: 'title required' }, { status: 400 });
    const steps = Array.isArray(body.steps) ? body.steps.map((s: unknown) => String(s)) : [];
    const rawText = body.rawText != null ? String(body.rawText) : null;
    const source = String(body.source || 'manual');
    const scenario = await prisma.scenario.create({
      data: { workspaceId, title, steps, rawText, source },
    });
    return NextResponse.json({ scenario });
  } catch (e) {
    if (e instanceof Error && e.message === 'UNAUTHORIZED') return unauthorizedResponse();
    console.error(e);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}
