
import { PrismaClient } from '@prisma/client';
import bcrypt from 'bcrypt';
import { v4 as uuidv4 } from 'uuid';

const prisma = new PrismaClient();

async function main() {
  const email = 'test@example.com';
  const password = 'Password123!';
  const hashedPassword = await bcrypt.hash(password, 10);

  const user = await prisma.user.upsert({
    where: { email },
    update: { password: hashedPassword, emailVerified: new Date() },
    create: {
      id: uuidv4(),
      email,
      password: hashedPassword,
      emailVerified: new Date(),
      firstName: 'Test',
      lastName: 'User',
    },
  });

  console.log('User created:', user.email);

  const workspace = await prisma.workspace.create({
    data: {
      ownerId: user.id,
      name: 'Test Workspace',
      description: 'A workspace for testing discovery',
      members: {
        create: { userId: user.id, role: 'OWNER' }
      },
      environments: {
        create: { name: 'Production', baseUrl: 'https://practicetestautomation.com/practice-test-login/' }
      },
      authProfiles: {
        create: {
          name: 'Primary',
          blueprint: {
            steps: [
              { type: 'text', field: 'username' },
              { type: 'password', field: 'password' }
            ]
          },
          usernameCipher: 'student', // Using plain text for now if decryptSecret handles it or I should encrypt it
          passwordCipher: 'Password123',
          roleHint: 'USER'
        }
      }
    }
  });

  console.log('Workspace created:', workspace.id);
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
