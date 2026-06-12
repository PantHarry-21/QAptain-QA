'use client';

import { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { ExecutionDashboard } from '@/components/execution/ExecutionDashboard';

export default function ExecutionRunPage() {
  const params = useParams();
  const router = useRouter();
  const workspaceId = params.workspaceId as string;
  const runId = params.runId as string;
  const [navigatingBack, setNavigatingBack] = useState(false);

  const handleBack = () => {
    setNavigatingBack(true);
    router.push(`/workspaces/${workspaceId}`);
  };

  return (
    <div className="min-h-screen bg-zinc-950 p-6">
      <div className="max-w-5xl mx-auto">
        <div className="flex items-center gap-3 mb-6">
          <button
            onClick={handleBack}
            disabled={navigatingBack}
            className="flex items-center gap-1.5 text-zinc-500 hover:text-zinc-300 text-sm transition-colors disabled:opacity-60"
          >
            {navigatingBack
              ? <div className="w-3 h-3 border border-zinc-400 border-t-transparent rounded-full animate-spin" />
              : '←'}
            Workspace
          </button>
          <span className="text-zinc-700">/</span>
          <span className="text-zinc-400 text-sm">Execution</span>
        </div>
        <ExecutionDashboard runId={runId} />
      </div>
    </div>
  );
}
