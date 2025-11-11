// This HTTP endpoint is no longer used for starting tests.
// Test execution is now triggered via the 'start-test' socket event.
// The core logic has been moved to src/lib/test-executor.ts and is called from src/lib/socket.ts.

import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

export async function POST() {
  return NextResponse.json(
    { 
      error: 'This endpoint is deprecated. Please use the WebSocket connection to start tests.' 
    },
    { status: 410 } // 410 Gone
  );
}
