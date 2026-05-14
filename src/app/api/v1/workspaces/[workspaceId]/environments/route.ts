import { NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import { requireSessionUserId, unauthorizedResponse, forbiddenResponse } from '@/lib/require-session';
import { assertWorkspaceAccess } from '@/lib/workspace-access';

export const dynamic = 'force-dynamic';

type Ctx = { params: Promise<{ workspaceId: string }> };

export async function POST(req: Request, ctx: Ctx) {
  try {
    const userId = await requireSessionUserId();
    const { workspaceId } = await ctx.params;
    if (!(await assertWorkspaceAccess(workspaceId, userId))) return forbiddenResponse();
    const body = await req.json().catch(() => ({}));
    const name = String(body.name || 'Default').trim();
    const baseUrl = String(body.baseUrl || '').trim();
    if (!baseUrl) return NextResponse.json({ error: 'baseUrl required' }, { status: 400 });
    const env = await prisma.environment.create({
      data: { workspaceId, name, baseUrl },
    });
    return NextResponse.json({ environment: env });
  } catch (e) {
    if (e instanceof Error && e.message === 'UNAUTHORIZED') return unauthorizedResponse();
    console.error(e);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}
