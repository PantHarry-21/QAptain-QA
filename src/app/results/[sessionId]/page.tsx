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
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
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
  Camera,
  Download,
  FileText,
  Video
} from "lucide-react";
import Link from 'next/link';
import Image from 'next/image';
import { io, Socket } from "socket.io-client";

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
  video_url?: string;
}

interface TestScenario {
  id: string;
  title: string;
  description: string;
  steps: string[];
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
  scenario_id?: string;
  metadata?: { screenshot?: string };
}

interface TestReport {
  id: string;
  summary: string;
  key_findings: string[];
  recommendations: string[];
  risk_level: 'low' | 'medium' | 'high';
  quality_score: number;
}

interface ScenarioReport {
  scenario_id: string;
  summary: string;
  issues: string[];
  recommendations: string[];
}

export default function ResultsPage() {
  const params = useParams();
  const sessionId = params.sessionId as string;

  const [session, setSession] = useState<TestSession | null>(null);
  const [scenarios, setScenarios] = useState<TestScenario[]>([]);
  const [logs, setLogs] = useState<TestLog[]>([]);
  const [report, setReport] = useState<TestReport | null>(null);
  const [scenarioReports, setScenarioReports] = useState<ScenarioReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isDownloading, setIsDownloading] = useState(false);

  useEffect(() => {
    const newSocket = io(process.env.NEXT_PUBLIC_SOCKET_URL || 'http://localhost:3000', {
      path: '/api/socketio',
      transports: ['websocket', 'polling']
    });

    newSocket.on('connect', () => newSocket.emit('join-session', { sessionId }));

    newSocket.on('session-data', (data) => {
      if (data) {
        setSession(data.session);
        setScenarios(Array.isArray(data.scenarios) ? data.scenarios : []);
        setLogs(Array.isArray(data.logs) ? data.logs : []);
        setReport(data.report);
        setScenarioReports(data.scenarioReports || []);
      }
      setLoading(false);
    });

    newSocket.on('test-log', (log: TestLog) => setLogs(prev => [...prev, log]));
    newSocket.on('test-scenario-update', (updatedScenario: TestScenario) => {
      setScenarios(prev => prev.map(s => s.id === updatedScenario.id ? updatedScenario : s));
    });
    newSocket.on('test-report-update', (updatedReport: TestReport) => setReport(updatedReport));
    newSocket.on('test-completed', (data: { results: TestSession, scenarios: TestScenario[] }) => {
      setSession(prev => ({ ...prev, ...data.results, status: 'completed' }));
      if (data.scenarios) setScenarios(data.scenarios);
    });

    return () => { newSocket.disconnect(); };
  }, [sessionId]);
  
  const handleDownloadReport = async () => {
    if (!session) return;
    setIsDownloading(true);
    try {
      const response = await fetch('/api/generate-pdf', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sessionId: session.id }),
      });
      if (!response.ok) throw new Error('Failed to generate PDF from server.');
      const pdfBlob = await response.blob();
      const url = window.URL.createObjectURL(pdfBlob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `test-report-${sessionId}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to download report');
    } finally {
      setIsDownloading(false);
    }
  };

  const getStatusBadge = (status: string) => {
    const colorMap = {
      passed: 'bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-300',
      failed: 'bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-300',
      running: 'bg-blue-100 text-blue-800 dark:bg-blue-900/20 dark:text-blue-300 animate-pulse',
      pending: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/20 dark:text-yellow-300',
    };
    return <Badge className={`capitalize ${colorMap[status] || 'bg-gray-100 text-gray-800'}`}>{status}</Badge>;
  };

  const StatCard = ({ title, value, icon, color }) => (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        {icon}
      </CardHeader>
      <CardContent>
        <div className={`text-2xl font-bold ${color || ''}`}>{value}</div>
      </CardContent>
    </Card>
  );

  const renderScenarioItem = (scenario: TestScenario) => {
    const scenarioReport = scenarioReports.find(r => r.scenario_id === scenario.id);
    return (
      <AccordionItem value={scenario.id} key={scenario.id}>
        <AccordionTrigger>
          <div className="flex items-center justify-between w-full">
            <div className="flex items-center gap-3">
              {scenario.status === 'passed' ? <CheckCircle className="w-5 h-5 text-green-500" /> : <XCircle className="w-5 h-5 text-red-500" />}
              <span className="font-semibold">{scenario.title}</span>
            </div>
            {getStatusBadge(scenario.status)}
          </div>
        </AccordionTrigger>
        <AccordionContent className="p-4 bg-muted/50 rounded-b-md">
          <p className="text-sm text-muted-foreground mb-4">{scenario.description}</p>
          <div className="mb-4">
            <h4 className="font-semibold mb-2">Steps:</h4>
            <ul className="list-decimal list-inside text-sm space-y-1">
              {scenario.steps.map((step, i) => <li key={i}>{step}</li>)}
            </ul>
          </div>
          {scenario.error_message && (
            <Alert variant="destructive">
              <AlertTitle>Failure Reason</AlertTitle>
              <AlertDescription>{scenario.error_message}</AlertDescription>
            </Alert>
          )}
          {scenarioReport && (
            <div className="mt-4 border-t pt-4">
                <h4 className="font-semibold mb-2 flex items-center gap-2"><Lightbulb className="w-4 h-4" /> AI Analysis</h4>
                <p className="text-sm italic text-muted-foreground mb-2">{scenarioReport.summary}</p>
                {scenarioReport.issues?.length > 0 && <div className="mt-2">
                    <h5 className="font-semibold text-sm">Issues Found:</h5>
                    <ul className="list-disc list-inside text-sm text-red-600 dark:text-red-400">
                        {scenarioReport.issues.map((issue, i) => <li key={i}>{issue}</li>)}
                    </ul>
                </div>}
            </div>
          )}
        </AccordionContent>
      </AccordionItem>
    );
  };
  
  if (loading) return (
    <div className="flex items-center justify-center py-20"><Loader2 className="w-12 h-12 animate-spin" /></div>
  );
  if (error) return (
    <div className="flex items-center justify-center py-20"><Alert variant="destructive" className="max-w-md"><AlertTitle>Error</AlertTitle><AlertDescription>{error}</AlertDescription></Alert></div>
  );
  if (!session) return (
    <div className="flex items-center justify-center py-20"><Alert className="max-w-md"><AlertTitle>No Results Found</AlertTitle><AlertDescription>Session {sessionId} not found.</AlertDescription></Alert></div>
  );

  const passedScenarios = scenarios.filter(s => s.status === 'passed').length;
  const failedScenarios = scenarios.filter(s => s.status === 'failed').length;
  const overallProgress = scenarios.length > 0 ? Math.round(((passedScenarios + failedScenarios) / scenarios.length) * 100) : 0;
  const screenshotLogs = logs.filter(log => log.metadata?.screenshot);

  return (
    <div className="container mx-auto max-w-7xl px-4 py-8">
      {/* Header */}
      <div className="mb-8">
        <div className="flex justify-between items-center mb-4">
          <Link href="/" passHref><Button variant="ghost"><ArrowLeft className="w-4 h-4 mr-2" /> Back to Home</Button></Link>
          <Button onClick={handleDownloadReport} disabled={isDownloading}>
            {isDownloading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Download className="w-4 h-4 mr-2" />}
            Download PDF Report
          </Button>
        </div>
        <div className="flex items-center justify-between">
            <div>
                <h1 className="text-3xl font-bold tracking-tight">Test Run Results</h1>
                <p className="text-muted-foreground text-sm mt-1">
                    Tested <a href={session.url} className="font-medium text-primary hover:underline" target="_blank" rel="noreferrer">{session.url}</a> on {new Date(session.created_at).toLocaleString()}
                </p>
            </div>
            {getStatusBadge(session.status)}
        </div>
      </div>

      {/* Main Content */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2">
            {/* Summary Stats */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
                <StatCard title="Scenarios" value={`${passedScenarios} / ${scenarios.length}`} icon={<FileText className="w-4 h-4 text-muted-foreground" />} />
                <StatCard title="Passed" value={passedScenarios} icon={<CheckCircle className="w-4 h-4 text-muted-foreground" />} color="text-green-500" />
                <StatCard title="Failed" value={failedScenarios} icon={<XCircle className="w-4 h-4 text-muted-foreground" />} color="text-red-500" />
                <Card>
                    <CardHeader className="flex flex-row items-center justify-between pb-2"><CardTitle className="text-sm font-medium">Progress</CardTitle><Activity className="w-4 h-4 text-muted-foreground" /></CardHeader>
                    <CardContent>
                        <div className="text-2xl font-bold">{overallProgress}%</div>
                        <Progress value={overallProgress} className="h-2 mt-1" />
                    </CardContent>
                </Card>
            </div>
            
            {/* Scenarios List */}
            <Card>
              <CardHeader><CardTitle>Test Scenarios</CardTitle></CardHeader>
              <CardContent>
                <Accordion type="single" collapsible className="w-full">
                  {scenarios.map(renderScenarioItem)}
                </Accordion>
                {scenarios.length === 0 && <p className="text-center text-muted-foreground py-8">No scenarios were executed for this test run.</p>}
              </CardContent>
            </Card>
        </div>
        <div className="lg:col-span-1">
          <Tabs defaultValue="ai-analysis" className="sticky top-8">
            <TabsList className="grid w-full grid-cols-3">
              <TabsTrigger value="ai-analysis">AI Report</TabsTrigger>
              <TabsTrigger value="logs">Logs</TabsTrigger>
              <TabsTrigger value="media">Media</TabsTrigger>
            </TabsList>
            <TabsContent value="ai-analysis" className="mt-4">
              <Card>
                <CardHeader><CardTitle className="flex items-center gap-2"><Lightbulb className="w-5 h-5 text-primary" />AI Analysis</CardTitle></CardHeader>
                <CardContent className="space-y-4">
                  {report ? <>
                    <div>
                      <h3 className="font-semibold mb-1">Overall Summary</h3>
                      <p className="text-sm text-muted-foreground">{report.summary}</p>
                    </div>
                    <div>
                      <h3 className="font-semibold mb-1">Key Findings</h3>
                      <ul className="list-disc pl-5 text-sm space-y-1">
                        {report.key_findings?.map((f, i) => <li key={i}>{f}</li>)}
                      </ul>
                    </div>
                     <div>
                      <h3 className="font-semibold mb-1">Recommendations</h3>
                      <ul className="list-disc pl-5 text-sm space-y-1">
                        {report.recommendations?.map((r, i) => <li key={i}>{r}</li>)}
                      </ul>
                    </div>
                  </> : <p className="text-center text-muted-foreground py-8">AI analysis is not yet available.</p>}
                </CardContent>
              </Card>
            </TabsContent>
            <TabsContent value="logs" className="mt-4">
               <Card>
                <CardHeader><CardTitle className="flex items-center gap-2"><Monitor className="w-5 h-5" />Execution Logs</CardTitle></CardHeader>
                <CardContent>
                    <ScrollArea className="h-96">
                        {logs.map(log => (
                            <div key={log.id} className="text-xs font-mono py-1 border-b">
                                <span className={`mr-2 ${log.level === 'error' ? 'text-red-500' : log.level === 'success' ? 'text-green-500' : ''}`}>{log.level.toUpperCase()}</span>
                                {log.message}
                            </div>
                        ))}
                        {logs.length === 0 && <p className="text-center text-muted-foreground py-8">No logs for this session.</p>}
                    </ScrollArea>
                </CardContent>
               </Card>
            </TabsContent>
            <TabsContent value="media" className="mt-4">
              <Card>
                  <CardHeader><CardTitle className="flex items-center gap-2"><Camera className="w-5 h-5" />Media Gallery</CardTitle></CardHeader>
                  <CardContent>
                      {session.video_url && <div className="mb-4">
                          <h3 className="font-semibold mb-2 flex items-center gap-2"><Video className="w-4 h-4"/> Session Video</h3>
                          <video controls className="w-full rounded-lg">
                              <source src={`/api/videos/${session.video_url}`} type="video/webm" />
                          </video>
                      </div>}
                      <Separator />
                      <div className="mt-4">
                        <h3 className="font-semibold mb-2 flex items-center gap-2"><Camera className="w-4 h-4" /> Screenshots</h3>
                        <ScrollArea className="h-80">
                          <div className="grid grid-cols-2 gap-2">
                            {screenshotLogs.map((log) => (
                              <Image key={log.id} src={log.metadata!.screenshot!} alt={log.message} width={400} height={300} className="rounded-md" />
                            ))}
                          </div>
                        </ScrollArea>
                        {screenshotLogs.length === 0 && <p className="text-center text-muted-foreground py-8">No screenshots were captured.</p>}
                      </div>
                  </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </div>
  );
}
