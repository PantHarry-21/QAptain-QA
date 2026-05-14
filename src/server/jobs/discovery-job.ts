import { chromium } from 'playwright';
import sparticuzChromium from '@sparticuz/chromium';
import { prisma } from '@/lib/prisma';
import { decryptSecret } from '@/lib/crypto-secrets';
import { ensureLoggedIn } from '@/lib/skills/ensure-login';
import type { DiscoveryJobData } from '@/server/queues/bullmq';
import { publishRunIoEvent } from '@/server/events/redis-io';
import { ingestModuleMemory } from '@/server/memory/chroma-memory';
import { extractRawFieldsFromPage } from '@/server/intelligence/dom-field-extract';
import { classifyField } from '@/server/intelligence/field-classifier';
import { upsertFieldIntelligence } from '@/server/intelligence/persist-field-intelligence';
import { classifyPageType } from '@/server/intelligence/route-page-classifier';
import { attachApiPatternCollector, settleDom } from '@/server/execution/stability';
import { buildNavigationGraphFromDb } from '@/server/intelligence/build-navigation-graph';
import {
  recordApiObservations,
  upsertNavigationIntelGraph,
  upsertSurfaceWorkflowIntel,
} from '@/server/intelligence/persist-workspace-intel';
import { persistInferredWorkflowsV1 } from '@/server/intelligence/infer-workflows-v1';

async function extractLightGraph(page: import('playwright').Page, baseUrl: string, maxNavItems: number) {
  const origin = new URL(baseUrl).origin;
  const items = await page.evaluate((limit) => {
    const out: { text: string; href: string }[] = [];
    const seen = new Set<string>();
    const anchors = Array.from(document.querySelectorAll('a[href], [role="menuitem"], [role="tab"]'));
    for (const el of anchors) {
      const a = el.closest('a') || (el.tagName === 'A' ? el : null);
      const href = (a as HTMLAnchorElement | null)?.href || '';
      const text = (el.textContent || '').trim().replace(/\s+/g, ' ');
      if (!text || text.length > 80) continue;
      if (!href || href.startsWith('javascript:')) continue;
      const key = `${text}|${href}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ text, href });
      if (out.length >= limit) break;
    }
    return out;
  }, maxNavItems);

  const modules: { name: string; routePattern: string; routes: { path: string; title: string }[] }[] = [];
  const seenPaths = new Set<string>();

  for (const it of items) {
    try {
      const u = new URL(it.href);
      if (u.origin !== origin) continue;
      const p = u.pathname + (u.search || '');
      if (seenPaths.has(p)) continue;
      seenPaths.add(p);
      const modName = it.text.slice(0, 120);
      modules.push({
        name: modName,
        routePattern: p,
        routes: [{ path: p, title: modName }],
      });
    } catch {
      /* skip */
    }
  }
  return modules;
}

async function ingestFieldsForCurrentPage(workspaceId: string, page: import('playwright').Page) {
  const raw = await extractRawFieldsFromPage(page, 120);
  const fp = await page.evaluate(() => `${location.pathname}|${document.title}`);
  for (const r of raw) {
    const cf = classifyField(r);
    await upsertFieldIntelligence(workspaceId, fp, cf);
  }
  return { fp, count: raw.length };
}

export async function processDiscoveryJob(data: DiscoveryJobData) {
  const { discoveryRunId, workspaceId, environmentId, authProfileId } = data;
  const env = await prisma.environment.findUnique({ where: { id: environmentId } });
  const auth = await prisma.authProfile.findUnique({ where: { id: authProfileId } });
  if (!env || !auth) throw new Error('Environment or auth profile not found');

  await prisma.discoveryRun.update({
    where: { id: discoveryRunId },
    data: { status: 'RUNNING', startedAt: new Date(), progress: 5 },
  });
  await publishRunIoEvent(discoveryRunId, 'discovery-status', { status: 'RUNNING', discoveryRunId });

  const isServerless = Boolean(process.env.VERCEL || process.env.LAMBDA_TASK_ROOT);
  const browser = isServerless
    ? await chromium.launch({
        args: sparticuzChromium.args,
        executablePath: await sparticuzChromium.executablePath(),
        headless: (sparticuzChromium as { headless?: boolean }).headless ?? true,
      })
    : await chromium.launch({ headless: true, args: ['--disable-dev-shm-usage'] });

  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    page.setDefaultTimeout(20000);

    const origin = new URL(env.baseUrl).origin;
    const collector = attachApiPatternCollector(page, origin, 60);
    try {
    const workspaceCreds = {
      username: decryptSecret(auth.usernameCipher),
      password: decryptSecret(auth.passwordCipher),
      labName: auth.labName,
      roleHint: auth.roleHint,
    };

    await ensureLoggedIn(page, env.baseUrl, discoveryRunId, undefined, workspaceCreds);
    await page.goto(env.baseUrl, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await settleDom(page, 8000);
    await ingestFieldsForCurrentPage(workspaceId, page);

    const maxItems = Number(process.env.QAPTAIN_DISCOVERY_MAX_NAV || '40');
    const graph = await extractLightGraph(page, env.baseUrl, maxItems);

    await prisma.applicationModule.deleteMany({ where: { workspaceId } });

    let n = 0;
    const routeRows: { moduleId: string; routeId: string; path: string }[] = [];
    for (const m of graph) {
      const mod = await prisma.applicationModule.create({
        data: {
          workspaceId,
          discoveryRunId,
          name: m.name,
          routePattern: m.routePattern,
          metadata: { phase: 1, source: 'light-discovery' },
        },
      });
      for (const r of m.routes) {
        const rt = await prisma.applicationRoute.create({
          data: {
            moduleId: mod.id,
            path: r.path,
            title: r.title,
            fingerprint: null,
            buttons: [],
            formCount: 0,
            apiPatterns: [],
            discoveryMeta: {},
          },
        });
        routeRows.push({ moduleId: mod.id, routeId: rt.id, path: r.path });
      }
      await ingestModuleMemory(workspaceId, mod.id, m.name, m.routePattern);
      n++;
      await prisma.discoveryRun.update({
        where: { id: discoveryRunId },
        data: { progress: Math.min(90, 10 + Math.floor((n / Math.max(graph.length, 1)) * 50)), totalItems: graph.length },
      });
    }

    const maxSamples = Number(process.env.QAPTAIN_DISCOVERY_ROUTE_SAMPLES || '6');
    const samples = routeRows.slice(0, maxSamples);
    let sampledFields = 0;

    for (const sample of samples) {
      try {
        const url = new URL(sample.path, env.baseUrl).toString();
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 25000 });
        await settleDom(page, 8000);
        const title = await page.title();
        const pathname = new URL(page.url()).pathname;
        const { pageType, workflowHints, formClassification } = classifyPageType(pathname, title);
        const { count } = await ingestFieldsForCurrentPage(workspaceId, page);
        sampledFields += count;
        const fp = `${pathname}|${title}`;
        await prisma.applicationRoute.update({
          where: { id: sample.routeId },
          data: {
            fingerprint: fp.slice(0, 500),
            formCount: count,
            discoveryMeta: {
              pageType,
              workflowHints,
              formClassification,
              sampledAt: new Date().toISOString(),
            },
          },
        });
      } catch {
        /* route may be unreachable */
      }
    }

    const apiPatternUrls = collector.patterns;
    const apiObservations = collector.observations;

    const dbModules = await prisma.applicationModule.findMany({
      where: { workspaceId, discoveryRunId },
      include: { routes: true },
    });
    const graphPayload = buildNavigationGraphFromDb({
      baseUrl: env.baseUrl,
      discoveryRunId,
      modules: dbModules,
      apiUrls: apiPatternUrls,
    });
    await upsertNavigationIntelGraph(workspaceId, graphPayload, discoveryRunId);
    await recordApiObservations(
      workspaceId,
      apiObservations,
      dbModules.map((m) => ({ id: m.id, routePattern: m.routePattern })),
      'discovery',
    );
    await upsertSurfaceWorkflowIntel(
      workspaceId,
      dbModules.map((m) => m.name),
    );
    await persistInferredWorkflowsV1(workspaceId, discoveryRunId);

    await prisma.discoveryRun.update({
      where: { id: discoveryRunId },
      data: {
        status: 'COMPLETED',
        completedAt: new Date(),
        progress: 100,
        totalItems: graph.length,
        summary: {
          modules: graph.length,
          routesSampled: samples.length,
          fieldsIndexed: sampledFields,
          phase: 2,
          apiSamples: apiObservations.slice(0, 40).map((o) => ({
            method: o.method,
            path: o.pathPattern,
            status: o.status,
            ms: o.durationMs,
          })),
        },
      },
    });
    await prisma.aiMemoryChunk.create({
      data: {
        workspaceId,
        kind: 'discovery',
        refId: discoveryRunId,
        content: { graph: graph.length, apis: apiObservations.length },
      },
    });
    await publishRunIoEvent(discoveryRunId, 'discovery-status', { status: 'COMPLETED', discoveryRunId });
    } finally {
      collector.dispose();
    }

    await context.close();
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    await prisma.discoveryRun.update({
      where: { id: discoveryRunId },
      data: { status: 'FAILED', error: msg, completedAt: new Date() },
    });
    await publishRunIoEvent(discoveryRunId, 'discovery-status', { status: 'FAILED', error: msg });
    throw e;
  } finally {
    await browser.close().catch(() => {});
  }
}
