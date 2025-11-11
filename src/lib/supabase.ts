import { createClient } from '@supabase/supabase-js';
import dotenv from 'dotenv';

dotenv.config();

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

console.log('Supabase URL:', process.env.NEXT_PUBLIC_SUPABASE_URL);
console.log('Supabase Anon Key:', process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY);

if (!supabaseUrl || !supabaseAnonKey) {
  throw new Error('Missing Supabase environment variables');
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey);

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