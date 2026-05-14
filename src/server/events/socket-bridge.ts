import type { Server } from 'socket.io';
import { createRedisSubscriber, QAPTAIN_IO_CHANNEL } from '@/server/events/redis-io';

/** Forwards BullMQ worker events to Socket.IO rooms `run-<id>`. */
export function attachRunEventBridge(io: Server) {
  const url = process.env.REDIS_URL;
  if (!url) {
    console.warn('[qaptain] REDIS_URL not set — start Redis + `npm run worker` for background jobs.');
    return;
  }
  const sub = createRedisSubscriber(url);
  sub.on('message', (channel, message) => {
    if (channel !== QAPTAIN_IO_CHANNEL) return;
    try {
      const parsed = JSON.parse(message) as { runId?: string; event?: string; payload?: unknown };
      if (parsed.runId && parsed.event) {
        io.to(`run-${parsed.runId}`).emit(parsed.event, parsed.payload);
      }
    } catch (e) {
      console.error('[qaptain] redis bridge parse error', e);
    }
  });
  sub.subscribe(QAPTAIN_IO_CHANNEL).catch((e) => console.error('[qaptain] redis subscribe failed', e));
}
