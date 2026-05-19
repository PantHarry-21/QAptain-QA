import { prisma } from '../src/lib/prisma';
async function main() {
  const workspaces = await prisma.workspace.findMany({
    include: {
      _count: true,
      discoveryRuns: { orderBy: { createdAt: 'desc' }, take: 1 }
    }
  });
  console.log(JSON.stringify(workspaces, null, 2));
}
main().catch(console.error);
