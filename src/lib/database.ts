import { supabase } from './supabase';
import { TestSession, TestScenario, TestStep, TestLog, TestReport, ScenarioReport } from './supabase';

export class DatabaseService {
  // Test Session Operations
  async createTestSession(sessionData: Partial<TestSession>): Promise<TestSession | null> {
    const { data, error } = await supabase
      .from('test_sessions')
      .insert([sessionData])
      .select()
      .single();

    if (error) {
      console.error('Error creating test session:', error);
      return null;
    }

    return data;
  }

  async getTestSession(sessionId: string): Promise<TestSession | null> {
    const { data, error } = await supabase
      .from('test_sessions')
      .select('*')
      .eq('id', sessionId)
      .single();

    if (error) {
      console.error('Error fetching test session:', error);
      return null;
    }

    return data;
  }

  async updateTestSession(sessionId: string, updates: Partial<TestSession>): Promise<TestSession | null> {
    const { data, error } = await supabase
      .from('test_sessions')
      .update(updates)
      .eq('id', sessionId)
      .select()
      .single();

    if (error) {
      console.error('Error updating test session:', error);
      return null;
    }

    return data;
  }

  async listTestSessions(userId?: string, limit: number = 10): Promise<TestSession[]> {
    let query = supabase
      .from('test_sessions')
      .select('*')
      .order('created_at', { ascending: false })
      .limit(limit);

    if (userId) {
      query = query.eq('user_id', userId);
    }

    const { data, error } = await query;

    if (error) {
      console.error('Error listing test sessions:', error);
      return [];
    }

    return data || [];
  }

  // Test Scenario Operations
  async createTestScenario(scenarioData: Partial<TestScenario>): Promise<TestScenario | null> {
    const { data, error } = await supabase
      .from('test_scenarios')
      .insert([scenarioData])
      .select()
      .single();

    if (error) {
      console.error('Error creating test scenario:', error);
      return null;
    }

    return data;
  }

  async getTestScenarios(sessionId: string): Promise<TestScenario[]> {
    const { data, error } = await supabase
      .from('test_scenarios')
      .select('*')
      .eq('session_id', sessionId)
      .order('created_at', { ascending: true });

    if (error) {
      console.error('Error fetching test scenarios:', error);
      return [];
    }

    return data || [];
  }

  async updateTestScenario(scenarioId: string, updates: Partial<TestScenario>): Promise<TestScenario | null> {
    const { data, error } = await supabase
      .from('test_scenarios')
      .update(updates)
      .eq('id', scenarioId)
      .select()
      .single();

    if (error) {
      console.error('Error updating test scenario:', error);
      return null;
    }

    return data;
  }

  async getTestScenario(scenarioId: string): Promise<TestScenario | null> {
    const { data, error } = await supabase
      .from('test_scenarios')
      .select('*')
      .eq('id', scenarioId)
      .single();

    if (error) {
      console.error('Error fetching test scenario:', error);
      return null;
    }

    return data;
  }

  // Test Step Operations
  async createTestStep(stepData: Partial<TestStep>): Promise<TestStep | null> {
    const { data, error } = await supabase
      .from('test_steps')
      .insert([stepData])
      .select()
      .single();

    if (error) {
      console.error('Error creating test step:', error);
      return null;
    }

    return data;
  }

  async getTestSteps(scenarioId: string): Promise<TestStep[]> {
    const { data, error } = await supabase
      .from('test_steps')
      .select('*')
      .eq('scenario_id', scenarioId)
      .order('order', { ascending: true });

    if (error) {
      console.error('Error fetching test steps:', error);
      return [];
    }

    return data || [];
  }

  async updateTestStep(stepId: string, updates: Partial<TestStep>): Promise<TestStep | null> {
    const { data, error } = await supabase
      .from('test_steps')
      .update(updates)
      .eq('id', stepId)
      .select()
      .single();

    if (error) {
      console.error('Error updating test step:', error);
      return null;
    }

    return data;
  }

  // Test Log Operations
  async createTestLog(logData: Partial<TestLog>): Promise<TestLog | null> {
    const { data, error } = await supabase
      .from('test_logs')
      .insert([logData])
      .select()
      .single();

    if (error) {
      console.error('Error creating test log:', error);
      return null;
    }

    return data;
  }

  async getTestLogs(sessionId: string, limit: number = 100): Promise<TestLog[]> {
    const { data, error } = await supabase
      .from('test_logs')
      .select('*')
      .eq('session_id', sessionId)
      .order('timestamp', { ascending: false })
      .limit(limit);

    if (error) {
      console.error('Error fetching test logs:', error);
      return [];
    }

    return data || [];
  }

  // Test Report Operations
  async createTestReport(reportData: Partial<TestReport>): Promise<TestReport | null> {
    const { data, error } = await supabase
      .from('test_reports')
      .insert([reportData])
      .select()
      .single();

    if (error) {
      console.error('Error creating test report:', error);
      return null;
    }

    return data;
  }

  async getTestReport(sessionId: string): Promise<TestReport | null> {
    const { data, error } = await supabase
      .from('test_reports')
      .select('*')
      .eq('session_id', sessionId)
      .single();

    if (error) {
      console.error('Error fetching test report:', error);
      return null;
    }

    return data;
  }

  // Scenario Report Operations
  async createScenarioReport(reportData: Partial<ScenarioReport>): Promise<ScenarioReport | null> {
    const { data, error } = await supabase
      .from('scenario_reports')
      .insert([reportData])
      .select()
      .single();

    if (error) {
      console.error('Error creating scenario report:', error);
      return null;
    }

    return data;
  }

  // Batch Operations
  async createTestStepsBatch(steps: Partial<TestStep>[]): Promise<TestStep[]> {
    const { data, error } = await supabase
      .from('test_steps')
      .insert(steps)
      .select();

    if (error) {
      console.error('Error creating test steps batch:', error);
      return [];
    }

    return data || [];
  }

  async createTestLogsBatch(logs: Partial<TestLog>[]): Promise<TestLog[]> {
    const { data, error } = await supabase
      .from('test_logs')
      .insert(logs)
      .select();

    if (error) {
      console.error('Error creating test logs batch:', error);
      return [];
    }

    return data || [];
  }

  // Analytics and Statistics
  async getTestStatistics(userId?: string): Promise<{
    totalSessions: number;
    totalScenarios: number;
    successRate: number;
    averageDuration: number;
    recentActivity: any[];
  }> {
    let sessionQuery = supabase.from('test_sessions').select('*');
    if (userId) {
      sessionQuery = sessionQuery.eq('user_id', userId);
    }

    const { data: sessions, error } = await sessionQuery;

    if (error || !sessions) {
      return {
        totalSessions: 0,
        totalScenarios: 0,
        successRate: 0,
        averageDuration: 0,
        recentActivity: []
      };
    }

    const totalSessions = sessions.length;
    const totalScenarios = sessions.reduce((sum, session) => sum + session.total_scenarios, 0);
    const totalPassed = sessions.reduce((sum, session) => sum + session.passed_scenarios, 0);
    const successRate = totalScenarios > 0 ? (totalPassed / totalScenarios) * 100 : 0;
    const averageDuration = sessions.length > 0 
      ? sessions.reduce((sum, session) => sum + (session.duration || 0), 0) / sessions.length 
      : 0;

    const recentActivity = sessions
      .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
      .slice(0, 5)
      .map(session => ({
        id: session.id,
        url: session.url,
        status: session.status,
        createdAt: session.created_at,
        duration: session.duration
      }));

    return {
      totalSessions,
      totalScenarios,
      successRate,
      averageDuration,
      recentActivity
    };
  }

  // Cleanup Operations
  async deleteTestSession(sessionId: string): Promise<boolean> {
    // Delete related records first (foreign key constraints)
    await supabase.from('test_reports').delete().eq('session_id', sessionId);
    await supabase.from('test_logs').delete().eq('session_id', sessionId);
    
    // Delete steps and scenarios
    const scenarios = await this.getTestScenarios(sessionId);
    for (const scenario of scenarios) {
      await supabase.from('test_steps').delete().eq('scenario_id', scenario.id);
    }
    await supabase.from('test_scenarios').delete().eq('session_id', sessionId);

    // Delete session
    const { error } = await supabase
      .from('test_sessions')
      .delete()
      .eq('id', sessionId);

    if (error) {
      console.error('Error deleting test session:', error);
      return false;
    }

    return true;
  }

  // Saved Scenario Operations
  async createSavedScenario(scenarioData: Partial<SavedScenario>): Promise<SavedScenario | null> {
    // Avoid duplicates: Check if a scenario with the same user_story and url already exists
    const { data: existing, error: existingError } = await supabase
      .from('saved_scenarios')
      .select('id')
      .eq('url', scenarioData.url)
      .eq('user_story', scenarioData.user_story)
      .limit(1);

    if (existingError) {
      console.error('Error checking for existing saved scenarios:', existingError);
      // Decide not to block creation, just log the error
    } else if (existing && existing.length > 0) {
      console.log('Not saving scenario, as it already exists.');
      return null; // Or return the existing one if needed
    }

    const { data, error } = await supabase
      .from('saved_scenarios')
      .insert([scenarioData])
      .select()
      .single();

    if (error) {
      console.error('Error creating saved scenario:', error);
      return null;
    }
    return data;
  }

  async getSavedScenariosByUrl(url: string): Promise<SavedScenario[]> {
    const { data, error } = await supabase
      .from('saved_scenarios')
      .select('*')
      .eq('url', url)
      .order('created_at', { ascending: false });

    if (error) {
      console.error('Error fetching saved scenarios:', error);
      return [];
    }
    return data || [];
  }
}

export const databaseService = new DatabaseService();