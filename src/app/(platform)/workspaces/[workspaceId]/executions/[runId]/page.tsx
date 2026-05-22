'use client';

import { useParams } from 'next/navigation';
import { ExecutionDashboard } from '@/components/execution/ExecutionDashboard';

export default function ExecutionRunPage() {
  const params = useParams();
  const workspaceId = params.workspaceId as string;
  const runId = params.runId as string;

  return (
    <div className="min-h-screen bg-zinc-950 p-6">
      <div className="max-w-5xl mx-auto">
        <div className="flex items-center gap-3 mb-6">
          <a href={`/workspaces/${workspaceId}`} className="text-zinc-500 hover:text-zinc-300 text-sm transition-colors">
            ← Workspace
          </a>
          <span className="text-zinc-700">/</span>
          <span className="text-zinc-400 text-sm">Execution</span>
        </div>
        <ExecutionDashboard runId={runId} />
      </div>
    </div>
  );
}
