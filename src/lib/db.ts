import { Pool } from '@neondatabase/serverless';

// Initialize the connection pool.
// The connection string will be read from the environment variables.
const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
});

export default pool;
