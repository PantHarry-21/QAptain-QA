import * as React from 'react';
import HistoryClientPage from './history-client-page';
import { Skeleton } from '@/components/ui/skeleton';

// A basic skeleton component to show while the page is loading.
const HistoryPageSkeleton = () => (
  <div className="container mx-auto py-10">
    <div className="flex justify-between items-center mb-6">
      <div>
        <Skeleton className="h-8 w-64 mb-2" />
        <Skeleton className="h-4 w-80" />
      </div>
      <Skeleton className="h-10 w-80" />
    </div>
    <div className="rounded-md border">
      <div className="animate-pulse">
        <div className="h-12 bg-slate-200 dark:bg-slate-800 rounded-t-md"></div>
        {Array.from({ length: 10 }).map((_, i) => (
          <div key={i} className="h-14 border-b border-slate-200 dark:border-slate-800 flex items-center p-4 space-x-4">
            <Skeleton className="h-6 flex-1" />
            <Skeleton className="h-6 flex-1" />
            <Skeleton className="h-6 flex-1" />
            <Skeleton className="h-6 flex-1" />
          </div>
        ))}
      </div>
    </div>
    <div className="flex items-center justify-end space-x-2 py-4">
      <Skeleton className="h-9 w-24" />
      <Skeleton className="h-9 w-24" />
    </div>
  </div>
);

export default function HistoryPage() {
  return (
    <React.Suspense fallback={<HistoryPageSkeleton />}>
      <HistoryClientPage />
    </React.Suspense>
  );
}
