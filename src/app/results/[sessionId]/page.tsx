'use client';

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { 
  Loader2, 
  ArrowLeft, 
  CheckCircle, 
  XCircle, 
  Clock, 
  Activity, 
  BarChart3, 
  Lightbulb, 
  ShieldAlert, 
  Monitor,
  Camera
} from "lucide-react";
import Link from 'next/link';
import Image from 'next/image';

interface TestSession {
  id: string;
  url: string;
  status: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  duration?: number;
  total_scenarios?: number;
  passed_scenarios?: number;
  failed_scenarios?: number;
  passed_steps?: number;
  failed_steps?: number;
}

interface TestScenario {
  id: string;
  title: string;
  description: string;
  priority: 'high' | 'medium' | 'low';
  category: string;
  steps: string[];
  estimated_time: string;
  status: string;
  started_at?: string;
  completed_at?: string;
  duration?: number;
  error_message?: string;
}

interface TestLog {
  id: string;
  timestamp: string;
  level: 'info' | 'success' | 'error' | 'warning';
  message: string;
  step_id?: string;
  scenario_id?: string;
  metadata?: { screenshot?: string };
}

interface TestReport {
  id: string;
  session_id: string;
  summary: string;
  key_findings: string[];
  recommendations: string[];
  risk_level: 'low' | 'medium' | 'high';
  performance_metrics: {
    averageStepTime: number;
    fastestStep: string;
    slowestStep: string;
    totalExecutionTime: number;
  };
  quality_score: number;
}

export default function ResultsPage() {
  const params = useParams();
  const sessionId = params.sessionId as string;

  const [session, setSession] = useState<TestSession | null>(null);
  const [scenarios, setScenarios] = useState<TestScenario[]>([]);
  const [logs, setLogs] = useState<TestLog[]>([]);
  const [report, setReport] = useState<TestReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchResults = async () => {
      try {
        const response = await fetch(`/api/results/${sessionId}`);
        if (!response.ok) {
          const errorData = await response.json();
          throw new Error(errorData.error || 'Failed to fetch test results');
        }
        const { data } = await response.json();
        setSession(data.session);
        setScenarios(data.scenarios);
        setLogs(data.logs);
        setReport(data.report);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'An unknown error occurred');
      } finally {
        setLoading(false);
      }
    };

    fetchResults();
  }, [sessionId]);

  const formatTime = (dateString?: string) => {
    if (!dateString) return 'N/A';
    return new Date(dateString).toLocaleTimeString();
  };

  const formatDate = (dateString?: string) => {
    if (!dateString) return 'N/A';
    return new Date(dateString).toLocaleDateString();
  };

  const getLogIcon = (level: string) => {
    switch (level) {
      case 'success': return <CheckCircle className="w-4 h-4 text-green-500" />;
      case 'error': return <XCircle className="w-4 h-4 text-red-500" />;
      case 'warning': return <Clock className="w-4 h-4 text-yellow-500" />;
      default: return <Activity className="w-4 h-4 text-blue-500" />;
    }
  };

  const getLogColor = (level: string) => {
    switch (level) {
      case 'success': return 'text-green-700 bg-green-50 dark:text-green-300 dark:bg-green-900/20';
      case 'error': return 'text-red-700 bg-red-50 dark:text-red-300 dark:bg-red-900/20';
      case 'warning': return 'text-yellow-700 bg-yellow-50 dark:text-yellow-300 dark:bg-yellow-900/20';
      default: return 'text-blue-700 bg-blue-50 dark:text-blue-300 dark:bg-blue-900/20';
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed': return 'bg-green-500';
      case 'failed': return 'bg-red-500';
      case 'running': return 'bg-blue-500';
      case 'pending': return 'bg-yellow-500';
      default: return 'bg-gray-500';
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-900 dark:to-slate-800">
        <div className="text-center">
          <Loader2 className="w-12 h-12 animate-spin mx-auto mb-4" />
          <p className="text-lg text-slate-700 dark:text-slate-300">Loading test results...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-900 dark:to-slate-800">
        <Alert variant="destructive" className="max-w-md">
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      </div>
    );
  }

  if (!session) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-900 dark:to-slate-800">
        <Alert className="max-w-md">
          <AlertTitle>No Results Found</AlertTitle>
          <AlertDescription>No test session found for ID: {sessionId}. It might not exist or has been deleted.</AlertDescription>
        </Alert>
      </div>
    );
  }

  const totalScenarios = session.total_scenarios || 0;
  const passedScenarios = session.passed_scenarios || 0;
  const failedScenarios = session.failed_scenarios || 0;
  const totalSteps = (session.passed_steps || 0) + (session.failed_steps || 0);
  const passedSteps = session.passed_steps || 0;
  const failedSteps = session.failed_steps || 0;

  const overallProgress = totalScenarios > 0 ? Math.round((passedScenarios / totalScenarios) * 100) : 0;

  const screenshotLogs = logs.filter(log => log.metadata?.screenshot);

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-900 dark:to-slate-800">
      <div className="container mx-auto px-4 py-8">
        <div className="mb-8">
          <Link href="/" passHref>
            <Button variant="ghost" className="mb-4">
              <ArrowLeft className="w-4 h-4 mr-2" />
              Back to Home
            </Button>
          </Link>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h1 className="text-4xl font-bold text-slate-900 dark:text-slate-100 mb-2">Test Results</h1>
              <p className="text-slate-600 dark:text-slate-400">Session ID: <span className="font-mono">{sessionId}</span></p>
              <p className="text-slate-600 dark:text-slate-400">URL: <span className="font-mono">{session.url}</span></p>
            </div>
            <Badge className={`text-lg px-4 py-2 ${getStatusColor(session.status)}`}>
              {session.status.charAt(0).toUpperCase() + session.status.slice(1)}
            </Badge>
          </div>
        </div>

        <Tabs defaultValue="overview" className="w-full">
          <TabsList className="grid w-full grid-cols-4">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="screenshots">Screenshots</TabsTrigger>
            <TabsTrigger value="logs">Test Logs</TabsTrigger>
            <TabsTrigger value="ai-analysis">AI Analysis</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="mt-4">
            {/* Overview Cards */}
            <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-6 mb-8">
              <Card>
                <CardHeader><CardTitle className="text-lg">Total Scenarios</CardTitle></CardHeader>
                <CardContent><p className="text-4xl font-bold">{totalScenarios}</p></CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle className="text-lg">Passed Scenarios</CardTitle></CardHeader>
                <CardContent><p className="text-4xl font-bold text-green-500">{passedScenarios}</p></CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle className="text-lg">Failed Scenarios</CardTitle></CardHeader>
                <CardContent><p className="text-4xl font-bold text-red-500">{failedScenarios}</p></CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle className="text-lg">Overall Progress</CardTitle></CardHeader>
                <CardContent>
                  <Progress value={overallProgress} className="h-3 mb-2" />
                  <p className="text-sm text-slate-600 dark:text-slate-400">{overallProgress}% Completed</p>
                </CardContent>
              </Card>
            </div>

            {/* Scenarios Details */}
            <Card className="mb-8">
              <CardHeader><CardTitle className="flex items-center gap-2"><Activity className="w-5 h-5" />Scenarios Details</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                {scenarios.length === 0 ? (
                  <p className="text-center text-slate-500">No scenarios found for this session.</p>
                ) : (
                  scenarios.map((scenario) => (
                    <Card key={scenario.id} className="border-slate-200 dark:border-slate-700">
                      <CardContent className="p-4">
                        <div className="flex items-center justify-between mb-2">
                          <h3 className="text-lg font-semibold">{scenario.title}</h3>
                          <Badge className={`${getStatusColor(scenario.status)} text-white`}>{scenario.status.toUpperCase()}</Badge>
                        </div>
                        <p className="text-sm text-slate-600 dark:text-slate-400 mb-2">{scenario.description}</p>
                        <div className="flex items-center gap-4 text-sm text-slate-500 dark:text-slate-400">
                          <div className="flex items-center gap-1"><Clock className="w-4 h-4" />{scenario.estimated_time}</div>
                          <div>{scenario.steps.length} steps</div>
                        </div>
                        {scenario.error_message && (
                          <Alert variant="destructive" className="mt-3">
                            <AlertTitle>Error</AlertTitle>
                            <AlertDescription>{scenario.error_message}</AlertDescription>
                          </Alert>
                        )}
                      </CardContent>
                    </Card>
                  ))
                )}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="screenshots" className="mt-4">
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><Camera className="w-5 h-5" />Screenshots</CardTitle></CardHeader>
              <CardContent>
                {screenshotLogs.length === 0 ? (
                  <p className="text-center text-slate-500">No screenshots available for this session.</p>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {screenshotLogs.map((log) => (
                      <div key={log.id} className="border rounded-lg overflow-hidden">
                        <Image 
                          src={log.metadata!.screenshot!} 
                          alt={`Screenshot from log ${log.id}`} 
                          width={800} 
                          height={600} 
                          layout="responsive"
                          className="w-full h-auto"
                        />
                        <p className="p-2 text-sm text-slate-600 dark:text-slate-400">{log.message} ({formatTime(log.timestamp)})</p>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="logs" className="mt-4">
            {/* Test Logs */}
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><Monitor className="w-5 h-5" />Test Logs</CardTitle></CardHeader>
              <CardContent>
                <ScrollArea className="h-96 w-full">
                  <div className="space-y-2">
                    {logs.length === 0 ? (
                      <div className="text-center py-8 text-slate-500">No logs found for this session.</div>
                    ) : (
                      logs.map((log) => (
                        <div key={log.id} className={`p-3 rounded-lg border ${getLogColor(log.level)}`}>
                          <div className="flex items-start gap-3">
                            {getLogIcon(log.level)}
                            <div className="flex-1 space-y-1">
                              <div className="flex items-center justify-between">
                                <p className="text-sm font-medium">{log.message}</p>
                                <span className="text-xs opacity-70">{formatTime(log.timestamp)}</span>
                              </div>
                              {log.metadata?.screenshot && (
                                <div className="mt-2">
                                  <img src={log.metadata.screenshot} alt="Screenshot" className="max-w-full h-auto rounded-md" />
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </ScrollArea>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="ai-analysis" className="mt-4">
            {/* AI Analysis & Report */}
            {report ? (
              <Card>
                <CardHeader><CardTitle className="flex items-center gap-2"><BarChart3 className="w-5 h-5" />AI Test Report</CardTitle></CardHeader>
                <CardContent className="space-y-4">
                  <div>
                    <h3 className="text-lg font-semibold mb-2">Summary</h3>
                    <p className="text-slate-700 dark:text-slate-300">{report.summary}</p>
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold mb-2 flex items-center gap-2"><Lightbulb className="w-5 h-5" />Key Findings</h3>
                    <ul className="list-disc pl-5 space-y-1 text-slate-700 dark:text-slate-300">
                      {report.key_findings.map((finding, index) => (
                        <li key={index}>{finding}</li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold mb-2 flex items-center gap-2"><ShieldAlert className="w-5 h-5" />Recommendations</h3>
                    <ul className="list-disc pl-5 space-y-1 text-slate-700 dark:text-slate-300">
                      {report.recommendations.map((rec, index) => (
                        <li key={index}>{rec}</li>
                      ))}
                    </ul>
                  </div>
                  <Separator />
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <p className="font-medium">Risk Level:</p>
                      <Badge className={`${getStatusColor(report.risk_level)} text-white`}>{report.risk_level.toUpperCase()}</Badge>
                    </div>
                    <div>
                      <p className="font-medium">Quality Score:</p>
                      <Progress value={report.quality_score} className="h-3 mb-2" />
                      <p className="text-sm text-slate-600 dark:text-slate-400">{report.quality_score}/100</p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ) : (
              <Alert>
                <AlertTitle>No AI Analysis Available</AlertTitle>
                <AlertDescription>The AI report could not be generated or is not available for this session.</AlertDescription>
              </Alert>
            )}
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}