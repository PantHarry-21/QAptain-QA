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

function isClient(): boolean {
  return typeof window !== 'undefined';
}

/**
 * Gets the appropriate Supabase URL based on environment
 * - CLIENT: Only NEXT_PUBLIC_* variables are available
 * - SERVER: Supports your PRODUCTION_* naming plus standard fallbacks
 */
export function getSupabaseUrl(): string {
  if (isClient()) {
    return process.env.NEXT_PUBLIC_SUPABASE_URL || '';
  }
  if (isProduction()) {
    return (
      // Accept multiple possible production variable names
      process.env.PRODUCTION_NEXT_SUPABASE_URL ||
      process.env.PRODUCTION_PUBLIC_SUPABASE_URL ||
      process.env.PRODUCTION_NEXT_PUBLIC_SUPABASE_URL ||
      process.env.PRODUCTION_SUPABASE_URL ||
      process.env.NEXT_PUBLIC_SUPABASE_URL ||
      process.env.SUPABASE_URL ||
      ''
    );
  }
  return (
    process.env.NEXT_PUBLIC_SUPABASE_URL ||
    process.env.SUPABASE_URL ||
    ''
  );
}

/**
 * Gets the appropriate Supabase Anon Key based on environment
 * - CLIENT: Only NEXT_PUBLIC_* variables are available
 * - SERVER: Supports your PRODUCTION_* naming plus standard fallbacks
 */
export function getSupabaseAnonKey(): string {
  if (isClient()) {
    return process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || '';
  }
  if (isProduction()) {
    return (
      process.env.PRODUCTION_PUBLIC_SUPABASE_ANON_KEY ||
      process.env.PRODUCTION_NEXT_PUBLIC_SUPABASE_ANON_KEY ||
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ||
      ''
    );
  }
  return process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || '';
}

/**
 * Gets the appropriate Supabase Service Role Key based on environment
 * Production: Uses PRODUCTION_SUPABASE_SERVICE_ROLE_KEY
 * Local: Uses SUPABASE_SERVICE_ROLE_KEY
 */
export function getSupabaseServiceRoleKey(): string {
  if (isProduction()) {
    return (
      process.env.PRODUCTION_SUPABASE_SERVICE_ROLE_KEY ||
      // allow alternative naming too
      process.env.PRODUCTION_SUPABASE_SERVICE_ROLE_KEY ||
      process.env.SUPABASE_SERVICE_ROLE_KEY ||
      ''
    );
  }
  return process.env.SUPABASE_SERVICE_ROLE_KEY || '';
}

// Lazily create Supabase client only when credentials are present
type SupabaseClientType = ReturnType<typeof createClient>;

const phase = process.env.NEXT_PHASE;
const isBuildPhase =
  phase === "phase-production-build" || phase === "phase-development-build";

let cachedSupabase: SupabaseClientType | null = null;

function initSupabaseClient(): SupabaseClientType | null {
  if (isBuildPhase) {
    return null;
  }

  const supabaseUrl = getSupabaseUrl();
  const supabaseAnonKey = getSupabaseAnonKey();

  if (!supabaseUrl || !supabaseAnonKey) {
    if (process.env.NODE_ENV === 'development' && !isClient()) {
      console.warn(
        '[supabase] Missing Supabase credentials. URL set:',
        Boolean(supabaseUrl),
        'Anon key set:',
        Boolean(supabaseAnonKey)
      );
    }
    return null;
  }

  return createClient(supabaseUrl, supabaseAnonKey);
}

export function getSupabaseClient(): SupabaseClientType | null {
  if (!cachedSupabase) {
    cachedSupabase = initSupabaseClient();
  }
  return cachedSupabase;
}

function requireSupabaseClient(): SupabaseClientType {
  const client = getSupabaseClient();
  if (!client) {
    throw new Error(
      'Supabase client not initialized. Ensure Supabase credentials are set.'
    );
  }
  return client;
}

// Backwards compatibility export for modules that import { supabase }
export const supabase = new Proxy(
  {},
  {
    get(_target, prop, receiver) {
      const client = requireSupabaseClient();
      const value = (client as any)[prop];
      if (typeof value === 'function') {
        return value.bind(client);
      }
      return value;
    },
  }
) as SupabaseClientType;

// Database types
export interface TestSession {
  id: string;
  user_id?: string;
  url: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  created_at: string;
  updated_at: string;
  started_at?: string;
  completed_at?: string;
  total_scenarios: number;
  passed_scenarios: number;
  failed_scenarios: number;
  total_steps: number;
  passed_steps: number;
  failed_steps: number;
  duration?: number;
  page_analysis?: any;
  ai_analysis?: any;
  selected_scenario_ids?: string[];
}

export interface TestScenario {
  id: string;
  session_id: string;
  title: string;
  description: string;
  priority: 'high' | 'medium' | 'low';
  category: string;
  steps: string[];
  estimated_time: string;
  status: 'pending' | 'running' | 'passed' | 'failed';
  created_at: string;
  updated_at: string;
  started_at?: string;
  completed_at?: string;
  duration?: number;
  is_custom: boolean;
}

export interface TestStep {
  id: string;
  scenario_id: string;
  description: string;
  order: number;
  status: 'pending' | 'running' | 'passed' | 'failed';
  started_at?: string;
  completed_at?: string;
  duration?: number;
  error_message?: string;
  screenshot_url?: string;
  created_at: string;
  updated_at: string;
}

export interface TestLog {
  id: string;
  session_id: string;
  scenario_id?: string;
  step_id?: string;
  level: 'info' | 'success' | 'error' | 'warning';
  message: string;
  timestamp: string;
  metadata?: any;
  created_at: string;
}

export interface TestReport {
  id: string;
  session_id: string;
  pdf_url?: string;
  summary: string;
  key_findings: string[];
  recommendations: string[];
  risk_level: 'low' | 'medium' | 'high';
  risk_assessment_issues: string[];
  performance_metrics: any;
  created_at: string;
  updated_at: string;
}

export interface User {
  id: string;
  first_name?: string;
  last_name?: string;
  email: string;
  password?: string;
  email_verified?: string;
  activation_token?: string;
  image?: string;
  created_at: string;
  updated_at: string;
  subscription_tier?: 'free' | 'pro' | 'enterprise';
}

export interface SavedScenario {
  id: string;
  user_id: string;
  created_at: string;
  url: string;
  title: string;
  user_story: string;
  steps: string[];
}

export interface ScenarioReport {
  id: string;
  scenario_id: string;
  session_id: string;
  summary: string;
  status: 'passed' | 'failed';
  steps_details: any[]; // or a more specific type
  created_at: string;
  updated_at: string;
}