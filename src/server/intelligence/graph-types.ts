/** Deterministic application graph (Phase 3+). Consumed by planning, impact analysis, UI. */

export type GraphNodeKind = 'spa_root' | 'module' | 'route' | 'api';

export type GraphEdgeKind = 'contains' | 'nav_from_root' | 'observed_api' | 'transition_hint';

export interface IntelGraphNode {
  id: string;
  kind: GraphNodeKind;
  label: string;
  meta?: Record<string, unknown>;
}

export interface IntelGraphEdge {
  id: string;
  from: string;
  to: string;
  kind: GraphEdgeKind;
  meta?: Record<string, unknown>;
}

export interface IntelGraphPayload {
  version: 1;
  generatedAt: string;
  origin: string;
  discoveryRunId?: string;
  nodes: IntelGraphNode[];
  edges: IntelGraphEdge[];
}
