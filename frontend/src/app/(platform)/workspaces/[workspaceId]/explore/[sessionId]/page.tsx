'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { explore as exploreApi, type ExploreSession } from '@/lib/api';
import { ExploreSessionViewer } from '@/components/explore/ExploreSessionViewer';

export default function ExploreSessionPage() {
  const params = useParams();
  const router = useRouter();
  const workspaceId = params.workspaceId as string;
  const sessionId = params.sessionId as string;
  const [session, setSession] = useState<ExploreSession | null>(null);
  const [navigatingBack, setNavigatingBack] = useState(false);

  useEffect(() => {
    exploreApi.getSession(sessionId).then(setSession).catch(console.error);
  }, [sessionId]);

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
