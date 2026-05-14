import { NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import { requireSessionUserId, unauthorizedResponse, forbiddenResponse } from '@/lib/require-session';
import { assertWorkspaceAccess } from '@/lib/workspace-access';

export const dynamic = 'force-dynamic';

type Ctx = { params: Promise<{ workspaceId: string }> };

export async function GET(req: Request, ctx: Ctx) {
  try {
    const userId = await requireSessionUserId();
    const { workspaceId } = await ctx.params;
    if (!(await assertWorkspaceAccess(workspaceId, userId))) return forbiddenResponse();
    const { searchParams } = new URL(req.url);
    const limit = Math.min(500, Math.max(1, Number(searchParams.get('limit')) || 200));

    const [fields, validationCount] = await Promise.all([
      prisma.fieldDefinition.findMany({
        where: { workspaceId },
        orderBy: [{ testPriority: 'desc' }, { updatedAt: 'desc' }],
        take: limit,
        include: { _count: { select: { validations: true } } },
      }),
      prisma.validationRule.count({ where: { workspaceId } }),
    ]);

    return NextResponse.json({ fields, validationRuleCount: validationCount });
  } catch (e) {
    if (e instanceof Error && e.message === 'UNAUTHORIZED') return unauthorizedResponse();
    console.error(e);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}
