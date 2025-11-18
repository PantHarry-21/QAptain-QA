import { Pool } from '@neondatabase/serverless';

// Initialize the connection pool only if DATABASE_URL is set.
// The connection string will be read from the environment variables.
let pool: Pool | null = null;

function getPool(): Pool {
  if (!pool) {
    let connectionString = process.env.DATABASE_URL;
    if (!connectionString || connectionString.trim().length === 0) {
      throw new Error('DATABASE_URL environment variable is not set or is empty. Cannot initialize database pool.');
    }
    // Remove quotes if present (dotenv sometimes includes them from .env files)
    connectionString = connectionString.trim().replace(/^["']|["']$/g, '');
    if (connectionString.length === 0) {
      throw new Error('DATABASE_URL environment variable is empty after cleaning. Cannot initialize database pool.');
    }
    pool = new Pool({
      connectionString,
    });
  }
  return pool;
}

export default getPool;
