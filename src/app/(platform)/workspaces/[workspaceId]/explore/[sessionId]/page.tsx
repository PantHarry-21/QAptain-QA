'use client';

import { useParams } from 'next/navigation';
import { ExploreSessionViewer } from '@/components/explore/ExploreSessionViewer';

export default function ExploreSessionPage() {
  const params = useParams();
  const workspaceId = params.workspaceId as string;
  const sessionId = params.sessionId as string;

  return (
    <div className="min-h-screen bg-zinc-950 p-6">
      <div className="max-w-5xl mx-auto">
        <div className="flex items-center gap-3 mb-6">
          <a href={`/workspaces/${workspaceId}`} className="text-zinc-500 hover:text-zinc-300 text-sm transition-colors">
            ← Workspace
          </a>
          <span className="text-zinc-700">/</span>
          <span className="text-zinc-400 text-sm">Explore Session</span>
        </div>
        <ExploreSessionViewer sessionId={sessionId} applicationId="" />
      </div>
    </div>
  );
}
