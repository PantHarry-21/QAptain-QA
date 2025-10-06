"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { 
  ArrowLeft, 
  Download, 
  Share, 
  RefreshCw, 
  CheckCircle, 
  XCircle, 
  Clock,
  Activity,
  FileText,
  Image as ImageIcon,
  Video,
  BarChart3,
  TrendingUp,
  AlertTriangle,
  Info
} from "lucide-react";
import { databaseService } from "@/lib/database";
import { TestSession, TestScenario, TestStep, TestLog, TestReport } from "@/lib/supabase";

interface TestResult {
  status: 'completed' | 'failed' | 'running';
  startTime: string;
  endTime: string;
  duration: number;
  totalScenarios: number;
  passedScenarios: number;
  failedScenarios: number;
  totalSteps: number;
  passedSteps: number;
  failedSteps: number;
}

interface TestLog {
  id: string;
  timestamp: string;
  level: 'info' | 'success' | 'error' | 'warning';
  message: string;
  step?: string;
  screenshot?: string;
}

interface ScenarioResult {
  id: string;
  title: string;
  status: 'passed' | 'failed';
  duration: number;
  steps: {
    description: string;
    status: 'passed' | 'failed';
    timestamp: string;
    screenshot?: string;
  }[];
}

interface AIAnalysis {
  summary: string;
  keyFindings: string[];
  recommendations: string[];
  riskAssessment: {
    level: 'low' | 'medium' | 'high';
    issues: string[];
  };
  performanceMetrics: {
    averageStepTime: number;
    fastestStep: string;
    slowestStep: string;
    totalExecutionTime: number;
  };
}

export default function ResultsPage() {
  const params = useParams();
  const router = useRouter();
  const sessionId = params.sessionId as string;
  
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [logs, setLogs] = useState<TestLog[]>([]);
  const [scenarioResults, setScenarioResults] = useState<ScenarioResult[]>([]);
  const [aiAnalysis, setAiAnalysis] = useState<AIAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    loadTestResults();
  }, [sessionId]);

  const loadTestResults = async () => {
    setLoading(true);
    setError("");

    try {
      // Fetch data from Supabase
      const [session, scenarios, logs, report] = await Promise.all([
        databaseService.getTestSession(sessionId),
        databaseService.getTestScenarios(sessionId),
        databaseService.getTestLogs(sessionId, 100),
        databaseService.getTestReport(sessionId)
      ]);

      if (!session) {
        throw new Error('Test session not found');
      }

      // Convert session to test result format
      const testResult: TestResult = {
        status: session.status,
        startTime: session.started_at || session.created_at,
        endTime: session.completed_at || new Date().toISOString(),
        duration: session.duration || 0,
        totalScenarios: session.total_scenarios,
        passedScenarios: session.passed_scenarios,
        failedScenarios: session.failed_scenarios,
        totalSteps: session.total_steps,
        passedSteps: session.passed_steps,
        failedSteps: session.failed_steps
      };

      // Convert scenarios to scenario results format
      const scenarioResults: ScenarioResult[] = await Promise.all(
        scenarios.map(async (scenario) => {
          const steps = await databaseService.getTestSteps(scenario.id);
          return {
            id: scenario.id,
            title: scenario.title,
            status: scenario.status,
            duration: scenario.duration || 0,
            steps: steps.map(step => ({
              description: step.description,
              status: step.status,
              timestamp: step.completed_at || step.started_at || new Date().toISOString(),
              screenshot: step.screenshot_url
            }))
          };
        })
      );

      // Convert logs to test log format
      const testLogs: TestLog[] = logs.map(log => ({
        id: log.id,
        timestamp: log.timestamp,
        level: log.level,
        message: log.message,
        step: log.metadata?.step,
        screenshot: log.metadata?.screenshot
      }));

      // Convert report to AI analysis format
      let aiAnalysis: AIAnalysis | null = null;
      if (report) {
        aiAnalysis = {
          summary: report.summary,
          keyFindings: report.key_findings,
          recommendations: report.recommendations,
          riskAssessment: {
            level: report.risk_level,
            issues: [] // This would need to be stored separately
          },
          performanceMetrics: report.performance_metrics || {
            averageStepTime: 0,
            fastestStep: '',
            slowestStep: '',
            totalExecutionTime: testResult.duration
          }
        };
      }

      setTestResult(testResult);
      setLogs(testLogs);
      setScenarioResults(scenarioResults);
      setAiAnalysis(aiAnalysis);

    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load test results');
    } finally {
      setLoading(false);
    }
  };

  const formatDuration = (ms: number) => {
    const seconds = Math.floor(ms / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    
    if (hours > 0) {
      return `${hours}h ${minutes % 60}m ${seconds % 60}s`;
    } else if (minutes > 0) {
      return `${minutes}m ${seconds % 60}s`;
    } else {
      return `${seconds}s`;
    }
  };

  const formatTime = (dateString: string) => {
    return new Date(dateString).toLocaleString();
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed':
      case 'passed':
        return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200';
      case 'failed':
        return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200';
      case 'running':
        return 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200';
      default:
        return 'bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-200';
    }
  };

  const getRiskColor = (level: string) => {
    switch (level) {
      case 'high': return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200';
      case 'medium': return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200';
      case 'low': return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200';
      default: return 'bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-200';
    }
  };

  const handleDownloadReport = async () => {
    try {
      const response = await fetch(`/api/generate-pdf`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          sessionId,
          testResult,
          logs,
          scenarioResults,
          aiAnalysis,
          url: testResult ? 'URL from session' : ''
        }),
      });

      if (response.ok) {
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `test-report-${sessionId}.pdf`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
      } else {
        alert('Failed to generate PDF report');
      }
    } catch (error) {
      console.error('Error downloading report:', error);
      alert('Failed to download report');
    }
  };

  const handleShareResults = () => {
    // Placeholder for sharing functionality
    alert('Share functionality would be implemented here');
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-900 dark:to-slate-800 flex items-center justify-center">
        <div className="text-center">
          <RefreshCw className="w-12 h-12 animate-spin mx-auto mb-4" />
          <p className="text-lg">Loading test results...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-900 dark:to-slate-800 flex items-center justify-center">
        <div className="max-w-md w-full">
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
          <Button onClick={() => router.push('/')} className="w-full mt-4">
            Back to Home
          </Button>
        </div>
      </div>
    );
  }

  if (!testResult) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-900 dark:to-slate-800 flex items-center justify-center">
        <div className="text-center">
          <AlertTriangle className="w-12 h-12 mx-auto mb-4 text-yellow-500" />
          <p className="text-lg">No test results found</p>
          <Button onClick={() => router.push('/')} className="mt-4">
            Back to Home
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-900 dark:to-slate-800">
      <div className="container mx-auto px-4 py-8">
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-4">
              <Button
                variant="ghost"
                onClick={() => router.push('/test-execution/' + sessionId)}
              >
                <ArrowLeft className="w-4 h-4 mr-2" />
                Back to Execution
              </Button>
              
              <div>
                <h1 className="text-3xl font-bold text-slate-900 dark:text-slate-100">
                  Test Results
                </h1>
                <p className="text-slate-600 dark:text-slate-400">
                  Session ID: {sessionId}
                </p>
              </div>
            </div>
            
            <div className="flex items-center gap-2">
              <Button variant="outline" onClick={handleShareResults}>
                <Share className="w-4 h-4 mr-2" />
                Share
              </Button>
              <Button onClick={handleDownloadReport}>
                <Download className="w-4 h-4 mr-2" />
                Download PDF
              </Button>
            </div>
          </div>
        </div>

        {/* Summary Cards */}
        <div className="grid md:grid-cols-4 gap-4 mb-8">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Overall Status</CardTitle>
              {testResult.status === 'completed' ? (
                <CheckCircle className="h-4 w-4 text-green-500" />
              ) : (
                <XCircle className="h-4 w-4 text-red-500" />
              )}
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {testResult.status.charAt(0).toUpperCase() + testResult.status.slice(1)}
              </div>
              <Badge className={getStatusColor(testResult.status)}>
                {Math.round((testResult.passedScenarios / testResult.totalScenarios) * 100)}% Success
              </Badge>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Scenarios</CardTitle>
              <BarChart3 className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {testResult.passedScenarios}/{testResult.totalScenarios}
              </div>
              <p className="text-xs text-muted-foreground">
                {testResult.failedScenarios} failed
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Steps</CardTitle>
              <Activity className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {testResult.passedSteps}/{testResult.totalSteps}
              </div>
              <p className="text-xs text-muted-foreground">
                {testResult.failedSteps} failed
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Duration</CardTitle>
              <Clock className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {formatDuration(testResult.duration)}
              </div>
              <p className="text-xs text-muted-foreground">
                {formatTime(testResult.startTime)}
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Main Content Tabs */}
        <Tabs defaultValue="overview" className="space-y-6">
          <TabsList className="grid w-full grid-cols-4">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="scenarios">Scenarios</TabsTrigger>
            <TabsTrigger value="ai-analysis">AI Analysis</TabsTrigger>
            <TabsTrigger value="logs">Logs</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="space-y-6">
            {/* Progress Overview */}
            <Card>
              <CardHeader>
                <CardTitle>Execution Summary</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <div className="flex justify-between text-sm mb-2">
                    <span>Overall Progress</span>
                    <span>{Math.round((testResult.passedSteps / testResult.totalSteps) * 100)}%</span>
                  </div>
                  <Progress 
                    value={(testResult.passedSteps / testResult.totalSteps) * 100} 
                    className="h-3" 
                  />
                </div>
                
                <div className="grid md:grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <span>Scenario Success Rate</span>
                      <span>{Math.round((testResult.passedScenarios / testResult.totalScenarios) * 100)}%</span>
                    </div>
                    <Progress 
                      value={(testResult.passedScenarios / testResult.totalScenarios) * 100} 
                      className="h-2" 
                    />
                  </div>
                  
                  <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <span>Step Success Rate</span>
                      <span>{Math.round((testResult.passedSteps / testResult.totalSteps) * 100)}%</span>
                    </div>
                    <Progress 
                      value={(testResult.passedSteps / testResult.totalSteps) * 100} 
                      className="h-2" 
                    />
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Quick Stats */}
            <div className="grid md:grid-cols-2 gap-6">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <TrendingUp className="w-5 h-5" />
                    Performance Metrics
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="flex justify-between">
                    <span>Average Step Time:</span>
                    <span className="font-medium">
                      {aiAnalysis ? formatDuration(aiAnalysis.performanceMetrics.averageStepTime) : 'N/A'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>Fastest Step:</span>
                    <span className="font-medium">
                      {aiAnalysis?.performanceMetrics.fastestStep || 'N/A'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>Slowest Step:</span>
                    <span className="font-medium">
                      {aiAnalysis?.performanceMetrics.slowestStep || 'N/A'}
                    </span>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <AlertTriangle className="w-5 h-5" />
                    Risk Assessment
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="flex items-center justify-between">
                    <span>Risk Level:</span>
                    <Badge className={getRiskColor(aiAnalysis?.riskAssessment.level || 'low')}>
                      {aiAnalysis?.riskAssessment.level?.toUpperCase() || 'LOW'}
                    </Badge>
                  </div>
                  <div className="space-y-1">
                    <p className="text-sm font-medium">Issues Found:</p>
                    <ul className="text-sm text-slate-600 dark:text-slate-400 space-y-1">
                      {aiAnalysis?.riskAssessment.issues.slice(0, 3).map((issue, index) => (
                        <li key={index} className="flex items-start gap-2">
                          <span className="text-slate-400">•</span>
                          {issue}
                        </li>
                      ))}
                    </ul>
                  </div>
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          <TabsContent value="scenarios" className="space-y-6">
            <div className="space-y-4">
              {scenarioResults.map((scenario) => (
                <Card key={scenario.id}>
                  <CardHeader>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div className={`w-3 h-3 rounded-full ${
                          scenario.status === 'passed' ? 'bg-green-500' : 'bg-red-500'
                        }`} />
                        <CardTitle className="text-lg">{scenario.title}</CardTitle>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge className={getStatusColor(scenario.status)}>
                          {scenario.status.toUpperCase()}
                        </Badge>
                        <span className="text-sm text-slate-500">
                          {formatDuration(scenario.duration)}
                        </span>
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-3">
                      {scenario.steps.map((step, index) => (
                        <div key={index} className="flex items-start gap-3 p-3 rounded-lg border">
                          <div className={`w-2 h-2 rounded-full mt-2 ${
                            step.status === 'passed' ? 'bg-green-500' : 'bg-red-500'
                          }`} />
                          <div className="flex-1">
                            <p className="font-medium">{step.description}</p>
                            <div className="flex items-center gap-4 mt-1">
                              <span className="text-sm text-slate-500">
                                {formatTime(step.timestamp)}
                              </span>
                              <Badge variant="outline" className={getStatusColor(step.status)}>
                                {step.status}
                              </Badge>
                            </div>
                          </div>
                          {step.screenshot && (
                            <Button variant="outline" size="sm">
                              <ImageIcon className="w-4 h-4 mr-2" />
                              Screenshot
                            </Button>
                          )}
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </TabsContent>

          <TabsContent value="ai-analysis" className="space-y-6">
            {aiAnalysis && (
              <>
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <Info className="w-5 h-5" />
                      AI Summary
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-slate-700 dark:text-slate-300">
                      {aiAnalysis.summary}
                    </p>
                  </CardContent>
                </Card>

                <div className="grid md:grid-cols-2 gap-6">
                  <Card>
                    <CardHeader>
                      <CardTitle>Key Findings</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <ul className="space-y-2">
                        {aiAnalysis.keyFindings.map((finding, index) => (
                          <li key={index} className="flex items-start gap-2">
                            <div className="w-2 h-2 bg-blue-500 rounded-full mt-2" />
                            <span className="text-sm">{finding}</span>
                          </li>
                        ))}
                      </ul>
                    </CardContent>
                  </Card>

                  <Card>
                    <CardHeader>
                      <CardTitle>Recommendations</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <ul className="space-y-2">
                        {aiAnalysis.recommendations.map((recommendation, index) => (
                          <li key={index} className="flex items-start gap-2">
                            <div className="w-2 h-2 bg-green-500 rounded-full mt-2" />
                            <span className="text-sm">{recommendation}</span>
                          </li>
                        ))}
                      </ul>
                    </CardContent>
                  </Card>
                </div>
              </>
            )}
          </TabsContent>

          <TabsContent value="logs" className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Execution Logs</CardTitle>
                <CardDescription>
                  Detailed logs from test execution
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ScrollArea className="h-96 w-full">
                  <div className="space-y-2">
                    {logs.map((log) => (
                      <div
                        key={log.id}
                        className={`p-3 rounded-lg border ${
                          log.level === 'success' ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800' :
                          log.level === 'error' ? 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800' :
                          log.level === 'warning' ? 'bg-yellow-50 dark:bg-yellow-900/20 border-yellow-200 dark:border-yellow-800' :
                          'bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800'
                        }`}
                      >
                        <div className="flex items-start gap-3">
                          {log.level === 'success' && <CheckCircle className="w-4 h-4 text-green-500" />}
                          {log.level === 'error' && <XCircle className="w-4 h-4 text-red-500" />}
                          {log.level === 'warning' && <AlertTriangle className="w-4 h-4 text-yellow-500" />}
                          {log.level === 'info' && <Info className="w-4 h-4 text-blue-500" />}
                          
                          <div className="flex-1 space-y-1">
                            <div className="flex items-center justify-between">
                              <p className="text-sm font-medium">{log.message}</p>
                              <span className="text-xs opacity-70">
                                {formatTime(log.timestamp)}
                              </span>
                            </div>
                            {log.step && (
                              <p className="text-xs opacity-80">
                                Step: {log.step}
                              </p>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}