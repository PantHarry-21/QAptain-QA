'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { explore as exploreApi, type ExploreSession } from '@/lib/api';
import { ExploreSessionViewer } from '@/components/explore/ExploreSessionViewer';

export default function ExploreSessionPage() {
  const params = useParams();
  const workspaceId = params.workspaceId as string;
  const sessionId = params.sessionId as string;
  const [session, setSession] = useState<ExploreSession | null>(null);

  useEffect(() => {
    exploreApi.getSession(sessionId).then(setSession).catch(console.error);
  }, [sessionId]);

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
        {session ? (
          <ExploreSessionViewer sessionId={sessionId} applicationId={session.application_id} />
        ) : (
          <div className="flex items-center justify-center h-64 text-zinc-500">
            <div className="animate-spin w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full mr-3" />
            Loading session...
          </div>
        )}
      </div>
    </div>
  );
}
