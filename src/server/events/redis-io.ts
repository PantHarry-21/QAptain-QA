import Redis from 'ioredis';

const CHANNEL = 'qaptain:io';

let publisher: Redis | null = null;

function getPublisher(): Redis | null {
  const url = process.env.REDIS_URL;
  if (!url) return null;
  if (!publisher) {
    publisher = new Redis(url, { maxRetriesPerRequest: null });
  }
  return publisher;
}

export async function publishRunIoEvent(runId: string, event: string, payload: unknown): Promise<void> {
  const pub = getPublisher();
  if (!pub) return;
  await pub.publish(CHANNEL, JSON.stringify({ runId, event, payload }));
}

export function createRedisSubscriber(url: string): Redis {
  return new Redis(url, { maxRetriesPerRequest: null });
}

export { CHANNEL as QAPTAIN_IO_CHANNEL };
