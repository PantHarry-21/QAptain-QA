import { NextResponse } from 'next/server';
import * as XLSX from 'xlsx';
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
    const form = await req.formData();
    const file = form.get('file');
    if (!file || !(file instanceof Blob)) {
      return NextResponse.json({ error: 'file required (multipart field "file")' }, { status: 400 });
    }
    const buf = Buffer.from(await file.arrayBuffer());
    const wb = XLSX.read(buf, { type: 'buffer' });
    const sheet = wb.Sheets[wb.SheetNames[0]];
    const rows = XLSX.utils.sheet_to_json<Record<string, unknown>>(sheet, { defval: '' });
    const created: { id: string; title: string }[] = [];
    for (const row of rows) {
      const title =
        String(row['Title'] || row['title'] || row['Scenario'] || row['Test Case'] || '').trim();
      if (!title) continue;
      const stepsRaw = row['Steps'] || row['steps'] || row['Step'] || '';
      const steps =
        typeof stepsRaw === 'string'
          ? stepsRaw.split(/\r?\n|;|→/).map((s) => s.trim()).filter(Boolean)
          : [];
      const s = await prisma.scenario.create({
        data: {
          workspaceId,
          title,
          steps,
          source: 'excel',
          rawText: JSON.stringify(row),
        },
      });
      created.push({ id: s.id, title: s.title });
    }
    return NextResponse.json({ imported: created.length, scenarios: created });
  } catch (e) {
    if (e instanceof Error && e.message === 'UNAUTHORIZED') return unauthorizedResponse();
    console.error(e);
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}
