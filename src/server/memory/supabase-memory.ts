/**
 * Supabase-backed semantic memory for module context.
 * Replaces the previous ChromaDB implementation.
 *
 * Uses a `module_memories` table with PostgreSQL full-text search.
 * Run `supabase-setup.sql` against your Supabase project to create the table.
 */

import { getSupabaseClient } from '@/lib/supabase';

export async function ingestModuleMemory(
  workspaceId: string,
  moduleId: string,
  name: string,
  routePattern: string,
): Promise<void> {
  const supabase = getSupabaseClient();
  if (!supabase) return;

  try {
    const content = `${name} — ${routePattern}`;
    const { error } = await supabase
      .from('module_memories')
      .upsert(
        {
          module_id: moduleId,
          workspace_id: workspaceId,
          content,
          metadata: { workspaceId, moduleId, routePattern },
        },
        { onConflict: 'module_id' },
      );

    if (error) {
      console.warn('[supabase-memory] ingest skipped:', error.message);
    }
  } catch (e) {
    console.warn('[supabase-memory] ingest skipped:', e instanceof Error ? e.message : e);
  }
}

export async function queryModuleContext(
  workspaceId: string,
  query: string,
  k = 6,
): Promise<string[]> {
  const supabase = getSupabaseClient();
  if (!supabase) return [];

  try {
    const { data, error } = await supabase.rpc('match_module_memories', {
      p_workspace_id: workspaceId,
      p_query: query,
      p_limit: k,
    });

    if (error) {
      console.warn('[supabase-memory] RPC failed, trying fallback:', error.message);
      return queryFallback(workspaceId, query, k);
    }

    if (!Array.isArray(data)) return [];
    return data.map((row: { content: string }) => row.content).filter(Boolean);
  } catch {
    return [];
  }
}

async function queryFallback(
  workspaceId: string,
  query: string,
  k: number,
): Promise<string[]> {
  const supabase = getSupabaseClient();
  if (!supabase) return [];

  try {
    const { data, error } = await supabase
      .from('module_memories')
      .select('content')
      .eq('workspace_id', workspaceId)
      .ilike('content', `%${query}%`)
      .limit(k);

    if (error || !data) return [];
    return data.map((row: { content: string }) => row.content).filter(Boolean);
  } catch {
    return [];
  }
}
