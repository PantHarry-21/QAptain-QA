import { NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import { encryptSecret } from '@/lib/crypto-secrets';
import { requireSessionUserId, unauthorizedResponse, forbiddenResponse } from '@/lib/require-session';
import { assertWorkspaceAccess } from '@/lib/workspace-access';

export const dynamic = 'force-dynamic';

type Ctx = { params: Promise<{ workspaceId: string }> };

export async function GET(_req: Request, ctx: Ctx) {
  try {
    const userId = await requireSessionUserId();
    const { workspaceId } = await ctx.params;
    if (!(await assertWorkspaceAccess(workspaceId, userId))) return forbiddenResponse();
    const rows = await prisma.authProfile.findMany({ where: { workspaceId } });
    return NextResponse.json({
      authProfiles: rows.map((r) => ({
        id: r.id,
        name: r.name,
        blueprint: r.blueprint,
        labName: r.labName,
        roleHint: r.roleHint,
        storageStatePath: r.storageStatePath,
        createdAt: r.createdAt,
      })),
    });
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
    const name = String(body.name || 'Primary').trim();
    const blueprint = body.blueprint && typeof body.blueprint === 'object' ? body.blueprint : { steps: [] };
    const username = body.username != null ? String(body.username) : '';
    const password = body.password != null ? String(body.password) : '';
    const labName = body.labName != null ? String(body.labName) : null;
    const roleHint = body.roleHint != null ? String(body.roleHint) : null;
    const row = await prisma.authProfile.create({
      data: {
        workspaceId,
        name,
        blueprint: blueprint as object,
        usernameCipher: username ? encryptSecret(username) : null,
        passwordCipher: password ? encryptSecret(password) : null,
        labName,
        roleHint,
      },
    });
    return NextResponse.json({
      authProfile: {
        id: row.id,
        name: row.name,
        blueprint: row.blueprint,
        labName: row.labName,
        roleHint: row.roleHint,
      },
    });
  } catch (e) {
    if (e instanceof Error && e.message === 'UNAUTHORIZED') return unauthorizedResponse();
    console.error(e);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}
