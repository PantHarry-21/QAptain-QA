import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { getServerSession } from 'next-auth';
import { getAuthOptions } from '@/lib/auth';
import { openAIService, type PageContext } from '@/lib/openai';
import * as XLSX from 'xlsx';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

function normalizeHeader(header: unknown) {
  return String(header ?? '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, '_')
    .replace(/[^a-z0-9_]/g, '');
}

function splitSteps(value: unknown): string[] {
  if (value == null) return [];
  if (Array.isArray(value)) {
    return value.map((v) => String(v).trim()).filter(Boolean);
  }

  const raw = String(value).trim();
  if (!raw) return [];

  // Try JSON array first.
  if (raw.startsWith('[') && raw.endsWith(']')) {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        return parsed.map((v) => String(v).trim()).filter(Boolean);
      }
    } catch {
      // fall through
    }
  }

  // Common delimiters for "Steps" cells.
  // Keep commas as part of sentences (commas appear in test data frequently).
  const parts = raw
    .split(/\r?\n|;|\|/g)
    .map((s) => s.trim())
    .filter(Boolean);

  // Flatten numbered steps like "1. ...", "2) ...".
  const out: string[] = [];
  for (const p of parts) {
    const sub = p
      .split(/(?:^|\s)(?:\d+[\.\)])\s+/g)
      .map((s) => s.trim())
      .filter(Boolean);
    if (sub.length > 1) out.push(...sub);
    else out.push(p);
  }
  return out;
}

export async function POST(request: NextRequest) {
  const session = await getServerSession(getAuthOptions());
  if (!session || !session.user || !session.user.id) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const formData = await request.formData();
  const file = formData.get('file');
  const url = formData.get('url');
  const pageContextRaw = formData.get('pageContext');

  const fileAny = file as any;
  if (!fileAny || typeof fileAny.arrayBuffer !== 'function') {
    return NextResponse.json({ error: 'Excel file is required (field name: file)' }, { status: 400 });
  }

  if (!url || typeof url !== 'string') {
    return NextResponse.json({ error: 'Target url is required (field name: url)' }, { status: 400 });
  }

  let pageContext: PageContext | null = null;
  if (pageContextRaw && typeof pageContextRaw === 'string' && pageContextRaw.trim()) {
    try {
      pageContext = JSON.parse(pageContextRaw) as PageContext;
    } catch {
      // ignore; optional if excel already provides steps
    }
  }

  const arrayBuffer = await file.arrayBuffer();
  const workbook = XLSX.read(Buffer.from(arrayBuffer), { type: 'buffer' });
  const firstSheetName = workbook.SheetNames[0];
  const sheet = workbook.Sheets[firstSheetName];

  // Convert to rows using header row.
  const rows: Array<Record<string, unknown>> = XLSX.utils.sheet_to_json(sheet, { defval: '' });
  if (!rows.length) {
    return NextResponse.json({ error: 'No rows found in the spreadsheet.' }, { status: 400 });
  }

  const scenarios: { title: string; description?: string; steps: string[] }[] = [];

  const rowToText = (normalizedRow: Record<string, unknown>) => {
    const parts: string[] = [];
    for (const [k, v] of Object.entries(normalizedRow)) {
      const val = String(v ?? '').trim();
      if (!val) continue;
      parts.push(`${k}: ${val}`);
    }
    return parts.join(' | ');
  };

  for (const row of rows) {
    const normalizedRow: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(row)) {
      normalizedRow[normalizeHeader(k)] = v;
    }

    // Supports headers like:
    // - "Scenario"
    // - "Title"
    // - "Test Case" / "Test Case #"
    const scenarioTitleRaw =
      (normalizedRow.scenario as string) ||
      (normalizedRow.title as string) ||
      (normalizedRow.scenario_title as string) ||
      (normalizedRow.test_case as string) ||
      (normalizedRow.test_case_ as string) ||
      (normalizedRow.test_case__ as string) ||
      (normalizedRow.testcase as string) ||
      '';

    const testCaseId =
      (normalizedRow.test_case as string) ||
      (normalizedRow.test_case_ as string) ||
      (normalizedRow.test_case__ as string) ||
      (normalizedRow.tc as string) ||
      (normalizedRow.tc_ as string) ||
      '';

    const moduleName =
      (normalizedRow.module as string) ||
      (normalizedRow.feature as string) ||
      '';

    const fallbackText = rowToText(normalizedRow);
    const scenarioTitle = String(scenarioTitleRaw || '').trim() || (fallbackText.slice(0, 80) || 'Imported Scenario');

    const testData =
      (normalizedRow.test_data as string) ||
      (normalizedRow.data as string) ||
      '';

    const expectedResult =
      (normalizedRow.expected_result as string) ||
      (normalizedRow.expected as string) ||
      '';

    const descriptionParts: string[] = [];
    if (testCaseId) descriptionParts.push(`TestCase: ${String(testCaseId)}`);
    if (moduleName) descriptionParts.push(`Module: ${String(moduleName)}`);
    if (testData) descriptionParts.push(`TestData: ${String(testData)}`);
    if (expectedResult) descriptionParts.push(`Expected: ${String(expectedResult)}`);

    const description =
      descriptionParts.join(' | ') ||
      (normalizedRow.description as string) ||
      (normalizedRow.desc as string) ||
      (normalizedRow.details as string) ||
      fallbackText ||
      undefined;

    const stepsCell =
      normalizedRow.test_steps ??
      normalizedRow.steps ??
      normalizedRow.step_list ??
      normalizedRow.steplist ??
      normalizedRow['step'] ??
      '';

    const userStory =
      (normalizedRow.user_story as string) ||
      (normalizedRow.userstory as string) ||
      (normalizedRow.story as string) ||
      '';

    // Support Step 1 / Step 2 / Step_3 style columns.
    const stepColKeys = Object.keys(normalizedRow).filter((k) => /^step_?\d+$/.test(k));
    const stepFromCols =
      stepColKeys.length > 0
        ? stepColKeys
            .sort((a, b) => parseInt(a.replace(/^step_?/, ''), 10) - parseInt(b.replace(/^step_?/, ''), 10))
            .map((k) => normalizedRow[k])
            .flatMap(splitSteps)
        : [];

    let steps = splitSteps(stepsCell);
    if (stepFromCols.length) steps = stepFromCols;

    if ((!steps || steps.length === 0) && userStory.trim()) {
      if (pageContext) {
        const interpreted = await openAIService.interpretScenario(userStory, pageContext);
        steps = interpreted.steps;
      } else {
        // Column-agnostic fallback: treat user story as free-form steps.
        steps = splitSteps(userStory);
      }
    }

    steps = steps.filter((s) => s.trim().length > 0);
    if (steps.length === 0) {
      // Last resort: split the row description into steps.
      steps = splitSteps(description || fallbackText);
    }
    if (steps.length === 0) continue;

    // If there is an "Expected Result" but no explicit verify step, add one.
    if (expectedResult && !steps.some((s) => /^verify\b/i.test(s))) {
      steps.push(`Verify that the page contains "${String(expectedResult).trim()}"`);
    }

    scenarios.push({
      title: scenarioTitle.trim(),
      description: description ? String(description) : undefined,
      steps,
    });
  }

  if (!scenarios.length) {
    return NextResponse.json(
      {
        error:
          'No valid scenarios found. Provide at least one non-empty row (any columns). If no steps column exists, the importer will attempt to derive steps from row text.',
      },
      { status: 400 },
    );
  }

  // Keep response intentionally small; UI will assign ids.
  return NextResponse.json({
    success: true,
    url,
    scenarios,
  });
}

