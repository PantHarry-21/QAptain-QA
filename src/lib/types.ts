export interface TestLog {
  id?: string;
  session_id: string;
  scenario_id?: string;
  step_id?: string;
  level: 'info' | 'warning' | 'error' | 'success';
  message: string;
  timestamp?: string;
  metadata?: any;
}

export interface TestScenario {
  id: string;
  title: string;
  steps: string[];
  status: 'pending' | 'running' | 'passed' | 'failed';
  started_at?: string;
  completed_at?: string;
}

export interface TestSession {
  id: string;
  user_id: string;
  url: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  total_scenarios: number;
  passed_scenarios: number;
  failed_scenarios: number;
  total_steps: number;
  passed_steps: number;
  failed_steps: number;
  created_at: string;
  updated_at: string;
  video_url?: string;
  selected_scenario_ids?: string[];
}

export interface TestReport {
  id: string;
  session_id: string;
  summary: string;
  key_findings: string[];
  recommendations: string[];
  risk_level: 'low' | 'medium' | 'high';
  risk_assessment_issues: string[];
  performance_metrics: any;
  created_at: string;
}
