'use client';

import { useEffect, useState } from 'react';
import { useParams, useSearchParams } from 'next/navigation';
import { BatchExecutionDashboard, type BatchItem } from '@/components/execution/BatchExecutionDashboard';
import { executions as executionsApi } from '@/lib/api';

export default function BatchExecutionPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const workspaceId = params.workspaceId as string;

  const [items, setItems] = useState<BatchItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const batchId = searchParams.get('batch_id');
    const encodedData = searchParams.get('data');

    if (batchId) {
      // Preferred path: fetch by batch_id — works for any batch size
      executionsApi.getBatch(batchId)
        .then((res) => setItems(res.runs))
        .catch(() => setError('Could not load batch runs.'))
        .finally(() => setLoading(false));
    } else if (encodedData) {
      // Legacy fallback: data was encoded in the URL (small batches)
      try {
        setItems(JSON.parse(decodeURIComponent(encodedData)));
      } catch {
        setError('Malformed batch data.');
      }
      setLoading(false);
    } else {
      setError('No batch data found.');
      setLoading(false);
    }
  }, [searchParams]);

  return (
    <div className="min-h-screen bg-zinc-950 p-6">
      <div className="max-w-5xl mx-auto">
        <div className="flex items-center gap-3 mb-6">
          <a
            href={`/workspaces/${workspaceId}`}
            className="text-zinc-500 hover:text-zinc-300 text-sm transition-colors"
          >
            ← Workspace
          </a>
          <span className="text-zinc-700">/</span>
          <span className="text-zinc-400 text-sm">Batch Execution</span>
        </div>

        {loading ? (
          <div className="text-zinc-500 text-center py-20 text-sm animate-pulse">
            Loading batch runs…
          </div>
        ) : error ? (
          <div className="text-red-400 text-center py-20 text-sm">{error}</div>
        ) : items.length === 0 ? (
          <div className="text-zinc-500 text-center py-20 text-sm">
            No execution data found.
          </div>
        ) : (
          <BatchExecutionDashboard items={items} />
        )}
      </div>
    </div>
  );
}
