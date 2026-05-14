/**
 * Optional ChromaDB semantic memory (local Docker). Fails soft if unreachable.
 */
export async function ingestModuleMemory(
  workspaceId: string,
  moduleId: string,
  name: string,
  routePattern: string,
): Promise<void> {
  const url = process.env.CHROMA_URL;
  if (!url) return;
  try {
    const { ChromaClient } = await import(/* webpackIgnore: true */ 'chromadb');
    const client = new ChromaClient({ path: url.replace(/\/$/, '') });
    const collName = `qaptain_ws_${workspaceId}_modules`;
    const coll = await client.getOrCreateCollection({ name: collName, metadata: { workspaceId } });
    const doc = `${name} — ${routePattern}`;
    await coll.upsert({
      ids: [moduleId],
      documents: [doc],
      metadatas: [{ workspaceId, moduleId, routePattern }],
    });
  } catch (e) {
    console.warn('[chroma] ingest skipped:', e instanceof Error ? e.message : e);
  }
}

export async function queryModuleContext(workspaceId: string, query: string, k = 6): Promise<string[]> {
  const url = process.env.CHROMA_URL;
  if (!url) return [];
  try {
    const { ChromaClient } = await import(/* webpackIgnore: true */ 'chromadb');
    const client = new ChromaClient({ path: url.replace(/\/$/, '') });
    const collName = `qaptain_ws_${workspaceId}_modules`;
    const coll = await client.getOrCreateCollection({ name: collName, metadata: { workspaceId } });
    const res = await coll.query({ queryTexts: [query], nResults: k });
    const docs = res.documents?.[0];
    return Array.isArray(docs) ? (docs.filter(Boolean) as string[]) : [];
  } catch {
    return [];
  }
}
