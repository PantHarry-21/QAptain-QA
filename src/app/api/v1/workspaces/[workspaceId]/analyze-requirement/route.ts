import { NextResponse } from 'next/server';
import { requireSessionUserId, unauthorizedResponse, forbiddenResponse } from '@/lib/require-session';
import { assertWorkspaceAccess } from '@/lib/workspace-access';
import { RequirementIntelligenceEngine } from '@/server/intelligence/requirement-analyzer';

export const dynamic = 'force-dynamic';

type Ctx = { params: Promise<{ workspaceId: string }> };

export async function POST(req: Request, ctx: Ctx) {
  try {
    const userId = await requireSessionUserId();
    const { workspaceId } = await ctx.params;
    if (!(await assertWorkspaceAccess(workspaceId, userId))) return forbiddenResponse();

    const { text, commit = false } = await req.json();
    if (!text) {
      return NextResponse.json({ error: 'Requirement text is required' }, { status: 400 });
    }

    const result = await RequirementIntelligenceEngine.analyze(workspaceId, text);

    if (commit) {
      await RequirementIntelligenceEngine.commitToLibrary(workspaceId, result);
    }

    return NextResponse.json({ success: true, result });
  } catch (e) {
    if (e instanceof Error && e.message === 'UNAUTHORIZED') return unauthorizedResponse();
    console.error('[Analyze Requirement API] Error:', e);
    return NextResponse.json({ error: 'Failed to analyze requirement' }, { status: 500 });
  }
}
