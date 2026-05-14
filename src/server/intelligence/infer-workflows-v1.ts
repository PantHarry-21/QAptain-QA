import { prisma } from '@/lib/prisma';

type RouteMeta = { pageType?: string; workflowHints?: string[] } | null;

type LifecycleTag = 'create' | 'approve' | 'invoice' | 'pay' | 'report';

function tagFromRoute(path: string, title: string | null): LifecycleTag | null {
  const b = `${path} ${title || ''}`.toLowerCase();
  if (/\b(create|add|new)\b/.test(b) && /\b(po|purchase|order|request|requisition)\b/.test(b)) return 'create';
  if (/\bapprov/.test(b) || /\bpending\s+review\b/.test(b)) return 'approve';
  if (/\binvoice|billing|bill\b/.test(b)) return 'invoice';
  if (/\bpay|payment|checkout\b/.test(b)) return 'pay';
  if (/\breport|result|certificate\b/.test(b)) return 'report';
  return null;
}

/**
 * Deterministic workflow hypotheses from discovery routes + `discoveryMeta`
 * (no AI). Low confidence; safe for planning hints only.
 */
export async function persistInferredWorkflowsV1(workspaceId: string, discoveryRunId: string): Promise<void> {
  const routes = await prisma.applicationRoute.findMany({
    where: { module: { workspaceId, discoveryRunId } },
    include: { module: { select: { id: true, name: true, routePattern: true } } },
  });

  const approvalPages = routes.filter((r) => {
    const m = r.discoveryMeta as RouteMeta;
    return m?.pageType === 'approval_workflow' || m?.workflowHints?.includes('multi_step_review');
  });
  if (approvalPages.length > 0) {
    const steps = approvalPages.slice(0, 12).map((r, i) => ({
      id: `approval_${i}`,
      label: r.title || r.path,
      path: r.path,
      moduleId: r.moduleId,
      pageType: (r.discoveryMeta as RouteMeta)?.pageType,
    }));
    await prisma.workflowIntel.upsert({
      where: { workspaceId_workflowKey: { workspaceId, workflowKey: 'approval_surface' } },
      create: {
        workspaceId,
        workflowKey: 'approval_surface',
        displayName: 'Approval / review surface',
        steps,
        dependencies: [],
        confidence: 0.52,
        source: 'discovery_meta_page_type',
        metadata: { discoveryRunId, routeCount: approvalPages.length },
      },
      update: {
        steps,
        confidence: 0.52,
        source: 'discovery_meta_page_type',
        metadata: { discoveryRunId, routeCount: approvalPages.length },
      },
    });
  }

  const tagged = routes
    .map((r) => ({ r, tag: tagFromRoute(r.path, r.title) }))
    .filter((x): x is { r: (typeof routes)[0]; tag: LifecycleTag } => x.tag != null);
  const distinct = new Set(tagged.map((t) => t.tag));
  if (distinct.size >= 2) {
    const order: LifecycleTag[] = ['create', 'approve', 'invoice', 'pay', 'report'];
    const steps = order
      .filter((tag) => distinct.has(tag))
      .map((tag) => ({
        id: tag,
        label: tag,
        routePaths: tagged.filter((x) => x.tag === tag).map((x) => x.r.path).slice(0, 4),
      }));
    const dependencies: { from: string; to: string; kind: string }[] = [];
    for (let i = 1; i < steps.length; i++) {
      dependencies.push({ from: steps[i - 1]!.id, to: steps[i]!.id, kind: 'sequence_hint' });
    }
    await prisma.workflowIntel.upsert({
      where: { workspaceId_workflowKey: { workspaceId, workflowKey: 'keyword_lifecycle' } },
      create: {
        workspaceId,
        workflowKey: 'keyword_lifecycle',
        displayName: 'Keyword-inferred business sequence',
        steps,
        dependencies,
        confidence: 0.41,
        source: 'deterministic_route_keywords',
        metadata: { discoveryRunId, tags: [...distinct] },
      },
      update: {
        steps,
        dependencies,
        confidence: 0.41,
        source: 'deterministic_route_keywords',
        metadata: { discoveryRunId, tags: [...distinct] },
      },
    });
  }

  const wizardPages = routes.filter((r) => {
    const m = r.discoveryMeta as RouteMeta;
    return m?.pageType === 'wizard_flow' || m?.workflowHints?.includes('sequential_steps');
  });
  if (wizardPages.length > 0) {
    const steps = wizardPages.slice(0, 10).map((r, i) => ({
      id: `wizard_${i}`,
      label: r.title || r.path,
      path: r.path,
      moduleId: r.moduleId,
    }));
    await prisma.workflowIntel.upsert({
      where: { workspaceId_workflowKey: { workspaceId, workflowKey: 'wizard_surface' } },
      create: {
        workspaceId,
        workflowKey: 'wizard_surface',
        displayName: 'Wizard / sequential flow surface',
        steps,
        dependencies: [],
        confidence: 0.48,
        source: 'discovery_meta_wizard',
        metadata: { discoveryRunId },
      },
      update: {
        steps,
        confidence: 0.48,
        source: 'discovery_meta_wizard',
        metadata: { discoveryRunId },
      },
    });
  }
}
