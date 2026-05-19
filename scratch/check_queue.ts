import dotenv from 'dotenv';
dotenv.config();
import { getDiscoveryQueue, QUEUE_DISCOVERY } from '../src/server/queues/bullmq';
async function main() {
  const q = getDiscoveryQueue();
  const counts = await q.getJobCounts();
  console.log('Job counts:', counts);
  const active = await q.getActive();
  console.log('Active jobs:', active.map(j => ({ id: j.id, data: j.data })));
  const waiting = await q.getWaiting();
  console.log('Waiting jobs:', waiting.map(j => ({ id: j.id, data: j.data })));
}
main().catch(console.error);
