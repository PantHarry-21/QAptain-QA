import type { IntelGraphEdge, IntelGraphNode, IntelGraphPayload } from '@/server/intelligence/graph-types';

type Mod = { id: string; name: string; routePattern: string | null; routes: { id: string; path: string; title: string | null }[] };

function stableId(prefix: string, key: string) {
  return `${prefix}:${key}`;
}

/** Build a navigation + API surface graph from persisted modules/routes (no AI). */
export function buildNavigationGraphFromDb(params: {
  baseUrl: string;
  discoveryRunId?: string;
  modules: Mod[];
  apiUrls: string[];
}): IntelGraphPayload {
  const origin = (() => {
    try {
      return new URL(params.baseUrl).origin;
    } catch {
      return params.baseUrl;
    }
  })();

  const nodes: IntelGraphNode[] = [];
  const edges: IntelGraphEdge[] = [];
  const rootId = stableId('root', origin);

  nodes.push({
    id: rootId,
    kind: 'spa_root',
    label: origin,
    meta: { discoveryRunId: params.discoveryRunId },
  });

  for (const m of params.modules) {
    const mid = stableId('module', m.id);
    nodes.push({
      id: mid,
      kind: 'module',
      label: m.name,
      meta: { routePattern: m.routePattern, moduleId: m.id },
    });
    edges.push({
      id: `e:${rootId}->${mid}`,
      from: rootId,
      to: mid,
      kind: 'nav_from_root',
    });

    for (const r of m.routes) {
      const rid = stableId('route', r.id);
      nodes.push({
        id: rid,
        kind: 'route',
        label: r.path,
        meta: { routeId: r.id, title: r.title, moduleId: m.id },
      });
      edges.push({
        id: `e:${mid}->${rid}`,
        from: mid,
        to: rid,
        kind: 'contains',
      });
    }
  }

  const seenApiPath = new Set<string>();
  for (const raw of params.apiUrls) {
    let pathname = raw;
    try {
      pathname = new URL(raw).pathname;
    } catch {
      pathname = raw.split('?')[0] || raw;
    }
    if (!pathname || pathname === '/') continue;
    if (seenApiPath.has(pathname)) continue;
    seenApiPath.add(pathname);
    const aid = stableId('api', pathname);
    nodes.push({
      id: aid,
      kind: 'api',
      label: pathname,
      meta: { urlSample: raw.slice(0, 500) },
    });
    edges.push({
      id: `e:${rootId}->${aid}`,
      from: rootId,
      to: aid,
      kind: 'observed_api',
    });
  }

  return {
    version: 1,
    generatedAt: new Date().toISOString(),
    origin,
    discoveryRunId: params.discoveryRunId,
    nodes,
    edges,
  };
}
