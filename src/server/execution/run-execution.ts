import path from 'path';
import fs from 'fs';
import { chromium, type Browser, type BrowserContext, type Page } from 'playwright';
import sparticuzChromium from '@sparticuz/chromium';
import { prisma } from '@/lib/prisma';
import { decryptSecret } from '@/lib/crypto-secrets';
import { ensureLoggedIn } from '@/lib/skills/ensure-login';
import { publishRunIoEvent } from '@/server/events/redis-io';
import { executeStep, findLocator, isExecutionRunStopped, clearExecutionRunStop } from '@/lib/test-executor';
import { generateSmartValue, profileForStep, type DataProfile } from '@/server/data/smart-data-generator';
import { settleDom, waitForNavigationStable, attachApiPatternCollector } from '@/server/execution/stability';
import { recordApiObservations } from '@/server/intelligence/persist-workspace-intel';
import { findFieldDefinitionForHint } from '@/server/intelligence/persist-field-intelligence';
import { normalizeExecutionMode } from '@/server/execution/execution-modes';
import { RcaEngine } from '@/server/intelligence/rca-engine';

type PlanStep = Record<string, unknown>;

type RunReportAgg = {
  timeline: { at: string; step: number; action: string; status: string; ms?: number }[];
  generatedData: { step: number; field?: string; valuePreview: string }[];
  selectorDiagnostics: { target: string; attempts: unknown[]; healedWith?: string }[];
};

async function appendLog(runId: string, level: string, message: string, metadata?: unknown) {
  await prisma.executionLog.create({
    data: { runId, level, message, metadata: metadata as object | undefined },
  });
  await publishRunIoEvent(runId, 'run-log', { level, message, metadata, ts: new Date().toISOString() });
}

function rankSelectorIndices(strategies: string[], scores: number[] | null): number[] {
  const n = strategies.length;
  const idx = Array.from({ length: n }, (_, i) => i);
  const sc = scores && scores.length === n ? scores : strategies.map(() => 0.5);
  idx.sort((a, b) => sc[b] - sc[a]);
  return idx;
}

async function healClick(
  page: Page,
  workspaceId: string,
  target: string,
  explicitSelectors: string[],
  agg: RunReportAgg,
): Promise<{ healAttempts: number; recovery: unknown[] }> {
  const memory = await prisma.selectorMemory.findUnique({
    where: { workspaceId_targetKey: { workspaceId, targetKey: target } },
  });
  const fromMem = memory?.strategies || [];
  const merged = [...new Set([...explicitSelectors, ...fromMem])];
  const strategies = merged.length ? merged : [];
  const scoresJson = (memory?.strategyScores as number[] | null) || null;
  const order = strategies.length ? rankSelectorIndices(strategies, scoresJson) : [0];
  const recovery: unknown[] = [];
  let healAttempts = 0;
  const tries = strategies.length ? order.length : 1;
  let lastErr: Error | null = null;

  for (let k = 0; k < tries; k++) {
    const i = strategies.length ? order[k]! : k;
    const sel = strategies[i];
    try {
      if (sel) await page.locator(sel).first().click({ timeout: 15000 });
      else {
        const loc = await findLocator(page, target);
        await loc.first().click({ timeout: 15000 });
      }
      const used = sel || `accessibility:${target}`;
      recovery.push({ ok: true, selector: used, idx: i });
      const newScores =
        strategies.length > 0
          ? strategies.map((_, idx) => {
              if (idx === i) return Math.min(1, (scoresJson?.[idx] ?? 0.5) + 0.12);
              return Math.max(0.05, (scoresJson?.[idx] ?? 0.5) - 0.03);
            })
          : undefined;
      const nextConf = Math.min(0.99, (memory?.confidence ?? 0.5) + 0.04);
      await prisma.selectorMemory.upsert({
        where: { workspaceId_targetKey: { workspaceId, targetKey: target } },
        create: {
          workspaceId,
          targetKey: target,
          strategies: strategies.length ? strategies : [`text:${target}`],
          strategyScores: newScores || [0.55],
          lastSuccessIdx: i,
          confidence: 0.62,
        },
        update: {
          strategies: strategies.length ? strategies : undefined,
          strategyScores: newScores as object | undefined,
          lastSuccessIdx: i,
          confidence: nextConf,
        },
      });
      agg.selectorDiagnostics.push({ target, attempts: [...recovery], healedWith: used });
      await settleDom(page, 6000);
      return { healAttempts, recovery };
    } catch (e) {
      healAttempts++;
      lastErr = e instanceof Error ? e : new Error(String(e));
      recovery.push({ ok: false, selector: sel || '(accessibility)', error: lastErr.message });
    }
  }
  agg.selectorDiagnostics.push({ target, attempts: [...recovery] });
  throw lastErr || new Error(`click failed: ${target}`);
}

async function executeStructuredStep(
  page: Page,
  baseUrl: string,
  step: PlanStep,
  ctx: { runId: string; workspaceId: string; executionMode: string },
  agg: RunReportAgg,
): Promise<{ healAttempts: number }> {
  const action = String(step.action || '');
  if (action === 'navigate') {
    const url = (step.url as string) || '';
    const rel = (step.path as string) || '';
    const target = url || (rel ? new URL(rel, baseUrl).toString() : baseUrl);
    await page.goto(target, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await waitForNavigationStable(page, undefined, 20000);
    return { healAttempts: 0 };
  }
  if (action === 'click') {
    const target = String(step.target || '');
    const selectors = (step.selectors as string[] | undefined) || [];
    const r = await healClick(page, ctx.workspaceId, target, selectors, agg);
    return { healAttempts: r.healAttempts };
  }
  if (action === 'fill') {
    const field = String(step.field || '');
    const valSpec = step.value;
    let value = '';
    const fp = await page.evaluate(() => `${location.pathname}|${document.title}`);
    if (typeof valSpec === 'string') value = valSpec;
    else if (valSpec && typeof valSpec === 'object' && (valSpec as { source?: string }).source === 'generated') {
      const o = valSpec as { fieldType?: string; profile?: string; test_type?: string };
      const hint = await findFieldDefinitionForHint(ctx.workspaceId, fp, field);
      const semantic = hint?.semanticClass || String(o.fieldType || 'text');
      const prof =
        (o.profile as DataProfile) ||
        profileForStep(ctx.executionMode, String(o.test_type || (step as { test_type?: string }).test_type || ''));
      value = generateSmartValue(semantic, prof, {});
      agg.generatedData.push({
        step: -1,
        field,
        valuePreview: value.length > 120 ? `${value.slice(0, 120)}…` : value,
      });
    }
    const stepStr = `Enter "${value}" into ${field}`;
    await executeStep(page, stepStr, baseUrl, ctx.runId, 'plan');
    return { healAttempts: 0 };
  }
  if (action === 'natural_language' || action === 'nl') {
    await executeStep(page, String(step.text || ''), baseUrl, ctx.runId, 'plan');
    return { healAttempts: 0 };
  }
  if (action === 'wait_ms') {
    const ms = Math.min(8000, Math.max(0, Number(step.ms) || 0));
    if (ms > 0) await page.waitForTimeout(ms);
    return { healAttempts: 0 };
  }
  if (action === 'wait_for_network') {
    const sub = String((step as { url_substring?: string }).url_substring || step.pattern || '').trim();
    if (sub) {
      await page
        .waitForResponse((r) => r.url().includes(sub), { timeout: Number(step.timeout) || 20000 })
        .catch(() => {});
    }
    await settleDom(page, 5000);
    return { healAttempts: 0 };
  }
  if (action === 'assert_visible') {
    const t = String(step.text || '');
    const useRawRegex = Boolean((step as { assertRegex?: boolean }).assertRegex);
    const reg = useRawRegex
      ? new RegExp(t, 'i')
      : new RegExp(t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i');
    await page.getByText(reg).first().waitFor({ state: 'visible', timeout: Number(step.timeout) || 15000 });
    return { healAttempts: 0 };
  }
  throw new Error(`Unknown plan action: ${action}`);
}

export async function runExecutionJob(executionRunId: string) {
  const run = await prisma.executionRun.findUnique({
    where: { id: executionRunId },
    include: {
      plan: true,
      environment: true,
      workspace: { include: { authProfiles: true } },
    },
  });
  if (!run || !run.plan) throw new Error('Run or plan missing');

  const executionMode = normalizeExecutionMode(run.executionMode);
  const agg: RunReportAgg = { timeline: [], generatedData: [], selectorDiagnostics: [] };

  const baseUrl =
    run.environment?.baseUrl ||
    (await prisma.environment.findFirst({ where: { workspaceId: run.workspaceId } }))?.baseUrl ||
    '';
  if (!baseUrl) throw new Error('No base URL for execution');

  const auth = run.workspace.authProfiles[0] || null;

  await prisma.executionRun.update({
    where: { id: executionRunId },
    data: { status: 'RUNNING', startedAt: new Date() },
  });
  await publishRunIoEvent(executionRunId, 'run-status', { status: 'RUNNING', executionMode });

  const isServerless = Boolean(process.env.VERCEL || process.env.LAMBDA_TASK_ROOT);
  let browser: Browser | null = null;
  let context: BrowserContext | null = null;
  const videoDir = path.join(process.cwd(), 'videos', executionRunId);
  let apiCollector: ReturnType<typeof attachApiPatternCollector> | null = null;
  try {
    if (isServerless) {
      browser = await chromium.launch({
        args: sparticuzChromium.args,
        executablePath: await sparticuzChromium.executablePath(),
        headless: (sparticuzChromium as { headless?: boolean }).headless ?? true,
      });
    } else {
      if (process.env.RECORD_PLAYWRIGHT_VIDEO === 'true' && !fs.existsSync(videoDir)) {
        fs.mkdirSync(videoDir, { recursive: true });
      }
      browser = await chromium.launch({
        headless: true,
        args: ['--disable-dev-shm-usage'],
      });
    }

    context = await browser.newContext({
      recordVideo: process.env.RECORD_PLAYWRIGHT_VIDEO === 'true' ? { dir: videoDir } : undefined,
    });
    const page = await context.newPage();
    await page.addInitScript(() => {
      (window as any).__name = (t: any) => t;
    });
    page.setDefaultTimeout(15000);
    page.setDefaultNavigationTimeout(40000);
    apiCollector = attachApiPatternCollector(page, new URL(baseUrl).origin, 80);

    const workspaceCreds =
      auth && (auth.usernameCipher || auth.passwordCipher)
        ? {
            username: decryptSecret(auth.usernameCipher),
            password: decryptSecret(auth.passwordCipher),
            labName: auth.labName,
            roleHint: auth.roleHint,
          }
        : null;

    try {
      await ensureLoggedIn(page, baseUrl, executionRunId, undefined, workspaceCreds);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      await appendLog(executionRunId, 'error', `Login failed: ${msg}`);
      await prisma.executionRun.update({
        where: { id: executionRunId },
        data: { status: 'FAILED', error: msg, completedAt: new Date() },
      });
      await publishRunIoEvent(executionRunId, 'run-status', { status: 'FAILED' });
      throw e;
    }

    const planJson = run.plan.plan as { steps?: PlanStep[] };
    const steps = Array.isArray(planJson?.steps) ? planJson.steps : [];

    let passed = 0;
    let failed = 0;
    await prisma.executionRun.update({
      where: { id: executionRunId },
      data: { totalSteps: steps.length, passedSteps: 0, failedSteps: 0 },
    });

    for (let i = 0; i < steps.length; i++) {
      if (isExecutionRunStopped(executionRunId)) {
        await appendLog(executionRunId, 'warning', 'Stopped by user');
        break;
      }
      const raw = steps[i] as PlanStep & { _generatedTest?: string; _testType?: string };
      const { _generatedTest: _g, _testType: _t, ...step } = raw;
      await prisma.executionStep.create({
        data: {
          runId: executionRunId,
          stepOrder: i,
          action: String(step.action || 'unknown'),
          payload: step as object,
          status: 'running',
          startedAtStep: new Date(),
        },
      });
      await publishRunIoEvent(executionRunId, 'run-progress', {
        current: i + 1,
        total: steps.length,
        action: step.action,
        executionMode,
      });

      const t0 = Date.now();
      try {
        const { healAttempts } = await executeStructuredStep(page, baseUrl, step, {
          runId: executionRunId,
          workspaceId: run.workspaceId,
          executionMode,
        }, agg);
        const dt = Date.now() - t0;
        agg.timeline.push({
          at: new Date().toISOString(),
          step: i,
          action: String(step.action),
          status: 'passed',
          ms: dt,
        });
        await prisma.executionStep.updateMany({
          where: { runId: executionRunId, stepOrder: i },
          data: {
            status: 'passed',
            durationMs: dt,
            healAttempts,
            ...(healAttempts
              ? { recoveryLog: { healAttempts } as object }
              : {}),
          },
        });
        await appendLog(executionRunId, 'success', `Step ${i + 1} OK`, { step, executionMode, ms: dt });
        passed++;
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        const dt = Date.now() - t0;
        agg.timeline.push({
          at: new Date().toISOString(),
          step: i,
          action: String(step.action),
          status: 'failed',
          ms: dt,
        });
        await prisma.executionStep.updateMany({
          where: { runId: executionRunId, stepOrder: i },
          data: {
            status: 'failed',
            durationMs: dt,
            error: msg,
            recoveryLog: { selectorDiagnostics: agg.selectorDiagnostics.slice(-5) } as object,
          },
        });
        await appendLog(executionRunId, 'error', `Step ${i + 1} failed: ${msg}`, { step, executionMode });
        
        // --- RCA Engine Integration ---
        try {
          const screenshot = await page.screenshot({ type: 'png', fullPage: false }).catch(() => null);
          const screenshotBase64 = screenshot ? screenshot.toString('base64') : undefined;
          await RcaEngine.analyzeFailure(page, step, msg, executionMode, executionRunId, screenshotBase64);
        } catch (rcaErr) {
          console.error('[execution] RCA Analysis failed', rcaErr);
        }
        // ------------------------------

        failed++;
        await prisma.executionRun.update({
          where: { id: executionRunId },
          data: {
            passedSteps: passed,
            failedSteps: failed,
            status: 'FAILED',
            error: msg,
            completedAt: new Date(),
          },
        });
        await prisma.executionReport.upsert({
          where: { runId: executionRunId },
          create: {
            runId: executionRunId,
            summary: `Failed at step ${i + 1} (${executionMode}): ${msg}`,
            riskLevel: 'high',
            findings: { passed, failed, executionMode } as object,
            selectorDiagnostics: agg.selectorDiagnostics as object,
            timeline: agg.timeline as object,
            generatedDataLog: agg.generatedData as object,
            fieldValidationSummary: { executionMode } as object,
            recoverySummary: { attempts: agg.selectorDiagnostics.length },
          },
          update: {
            summary: `Failed at step ${i + 1} (${executionMode}): ${msg}`,
            riskLevel: 'high',
            findings: { passed, failed, executionMode } as object,
            selectorDiagnostics: agg.selectorDiagnostics as object,
            timeline: agg.timeline as object,
            generatedDataLog: agg.generatedData as object,
            recoverySummary: { attempts: agg.selectorDiagnostics.length },
          },
        });
        await publishRunIoEvent(executionRunId, 'run-status', { status: 'FAILED' });
        throw e;
      }
    }

    const stopped = isExecutionRunStopped(executionRunId);
    await prisma.executionRun.update({
      where: { id: executionRunId },
      data: {
        status: stopped ? 'CANCELLED' : 'COMPLETED',
        passedSteps: passed,
        failedSteps: failed,
        completedAt: new Date(),
      },
    });
    await prisma.executionReport.upsert({
      where: { runId: executionRunId },
      create: {
        runId: executionRunId,
        summary: `Mode ${executionMode}: ${steps.length} step(s). Passed ${passed}, failed ${failed}.`,
        riskLevel: failed > 0 ? 'medium' : 'low',
        findings: { passed, failed, steps: steps.length, executionMode } as object,
        selectorDiagnostics: agg.selectorDiagnostics as object,
        timeline: agg.timeline as object,
        generatedDataLog: agg.generatedData as object,
        fieldValidationSummary: { executionMode, note: 'Field intelligence from discovery feeds data profiles.' },
        recoverySummary: { selectorHeals: agg.selectorDiagnostics.filter((d) => d.healedWith).length },
      },
      update: {
        summary: `Mode ${executionMode}: ${steps.length} step(s). Passed ${passed}, failed ${failed}.`,
        riskLevel: failed > 0 ? 'medium' : 'low',
        findings: { passed, failed, steps: steps.length, executionMode } as object,
        selectorDiagnostics: agg.selectorDiagnostics as object,
        timeline: agg.timeline as object,
        generatedDataLog: agg.generatedData as object,
        recoverySummary: { selectorHeals: agg.selectorDiagnostics.filter((d) => d.healedWith).length },
      },
    });
    await publishRunIoEvent(executionRunId, 'run-status', {
      status: stopped ? 'CANCELLED' : 'COMPLETED',
    });
    await publishRunIoEvent(executionRunId, 'run-completed', { passed, failed, executionMode });
  } finally {
    if (apiCollector) {
      apiCollector.dispose();
      try {
        if (apiCollector.observations.length > 0) {
          const mods = await prisma.applicationModule.findMany({
            where: { workspaceId: run.workspaceId },
            take: 120,
            select: { id: true, routePattern: true },
          });
          await recordApiObservations(run.workspaceId, apiCollector.observations, mods, 'execution');
        }
      } catch (e) {
        console.error('[execution] API intel rollup failed', e);
      }
    }
    await context?.close().catch(() => {});
    clearExecutionRunStop(executionRunId);
    if (browser) await browser.close().catch(() => {});
  }
}
