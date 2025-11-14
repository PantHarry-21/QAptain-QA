import { createClient } from '@supabase/supabase-js';

/**
 * Determines if we're running in production environment
 */
function isProduction(): boolean {
  return (
    process.env.NODE_ENV === 'production' ||
    process.env.VERCEL_ENV === 'production' ||
    !!process.env.VERCEL
  );
}

/**
 * Gets Neon database URL for production
 * Supports multiple environment variable naming conventions
 */
function getNeonUrl(): string {
  if (!isProduction()) {
    return '';
  }
  
  return (
    process.env.QAPTAIN_URL ||
    process.env.NEON_URL ||
    process.env.NEXT_PUBLIC_NEON_URL ||
    ''
  ).trim();
}

/**
 * Gets Neon anon key for production
 */
function getNeonAnonKey(): string {
  if (!isProduction()) {
    return '';
  }
  
  return (
    process.env.QAPTAIN_ANON_KEY ||
    process.env.NEON_ANON_KEY ||
    process.env.NEXT_PUBLIC_NEON_ANON_KEY ||
    ''
  ).trim();
}

/**
 * Gets Neon service role key for production
 */
function getNeonServiceRoleKey(): string {
  if (!isProduction()) {
    return '';
  }
  
  return (
    process.env.QAPTAIN_SERVICE_ROLE_KEY ||
    process.env.NEON_SERVICE_ROLE_KEY ||
    ''
  ).trim();
}

/**
 * Creates a Neon database client using Supabase JS client
 * (Neon uses PostgREST which is compatible with Supabase client)
 */
function createNeonClient() {
  const url = getNeonUrl();
  const key = getNeonAnonKey();
  
  if (!url || !key) {
    if (process.env.NODE_ENV === 'development') {
      console.warn('[neon] Missing Neon credentials. URL set:', Boolean(url), 'Anon key set:', Boolean(key));
    }
    return null;
  }
  
  // Remove trailing slash if present
  const cleanUrl = url.replace(/\/$/, '');
  
  // Supabase client works with PostgREST APIs like Neon
  return createClient(cleanUrl, key, {
    auth: {
      persistSession: false,
      autoRefreshToken: false,
    },
  });
}

// Lazy initialization
let cachedNeonClient: ReturnType<typeof createClient> | null = null;

/**
 * Gets the Neon database client (production only)
 * Returns null in local development
 */
export function getNeonClient() {
  if (!isProduction()) {
    return null;
  }
  
  if (!cachedNeonClient) {
    cachedNeonClient = createNeonClient();
  }
  
  return cachedNeonClient;
}

/**
 * Gets the Neon service role client for admin operations (production only)
 */
export function getNeonAdminClient() {
  if (!isProduction()) {
    return null;
  }
  
  const url = getNeonUrl();
  const serviceKey = getNeonServiceRoleKey();
  
  if (!url || !serviceKey) {
    return null;
  }
  
  const cleanUrl = url.replace(/\/$/, '');
  
  return createClient(cleanUrl, serviceKey, {
    auth: {
      persistSession: false,
      autoRefreshToken: false,
    },
  });
}

/**
 * Checks if Neon is configured and available
 */
export function isNeonAvailable(): boolean {
  return isProduction() && !!getNeonClient();
}

