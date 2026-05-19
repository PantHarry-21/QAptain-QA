/**
 * @fileoverview Server-side Supabase client for QAptain.
 * Used for module memory (semantic search replacement for ChromaDB).
 *
 * Requires:
 *   NEXT_PUBLIC_SUPABASE_URL
 *   SUPABASE_SERVICE_ROLE_KEY  (preferred, bypasses RLS)
 *     — or —
 *   NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY  (fallback, requires RLS disabled on table)
 */

import { createClient, type SupabaseClient } from '@supabase/supabase-js';

let _client: SupabaseClient | null = null;

/**
 * Returns a lazily-initialised, singleton Supabase client.
 * Prefers the service-role key for server-side operations;
 * falls back to the publishable key when the service-role key is absent.
 */
export function getSupabaseClient(): SupabaseClient | null {
  if (_client) return _client;

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key =
    process.env.SUPABASE_SERVICE_ROLE_KEY ||
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

  if (!url || !key) {
    return null;
  }

  _client = createClient(url, key, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  return _client;
}
