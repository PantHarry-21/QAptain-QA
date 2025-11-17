'use client';

import { useState, useEffect, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import Image from 'next/image';
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { 
  Loader2, 
  ArrowLeft, 
  Monitor, 
  Play, 
  Pause, 
  Square, 
  CheckCircle, 
  XCircle, 
  Clock,
  Activity,
  Maximize2,
  Minimize2
} from "lucide-react";
import { io, Socket } from "socket.io-client";

interface TestLog {
  id: string;
  timestamp: string;
  level: 'info' | 'success' | 'error' | 'warning';
  message: string;
  step?: string;
  screenshot?: string;
}

interface TestProgress {
  currentScenario: number;
  totalScenarios: number;
  currentStep: number;
  totalSteps: number;
  currentScenarioTitle: string;
  currentStepDescription: string;
  status: 'running' | 'paused' | 'completed' | 'failed';
  startTime: string;
  estimatedEndTime?: string;
}

export default function TestExecutionPage() {
  const params = useParams();
  const router = useRouter();
  const sessionId = params.sessionId as string;
  
  const [socket, setSocket] = useState<Socket | null>(null);
  const [logs, setLogs] = useState<TestLog[]>([]);
  const [progress, setProgress] = useState<TestProgress | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [testStatus, setTestStatus] = useState<'idle' | 'running' | 'paused' | 'completed' | 'failed'>('idle');
  const [browserView, setBrowserView] = useState<string | null>(null);
  const [targetUrl, setTargetUrl] = useState<string>('');
  const logsEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const url = sessionStorage.getItem('targetUrl') || '';
    setTargetUrl(url);

    const newSocket = io(process.env.NEXT_PUBLIC_SOCKET_URL || 'http://localhost:3000', {
      path: '/api/socketio',
      transports: ['websocket', 'polling']
    });

    newSocket.on('connect', () => {
      setIsConnected(true);
      newSocket.emit('join-session', { sessionId });
    });

    newSocket.on('disconnect', () => {
      setIsConnected(false);
    });

    newSocket.on('test-progress', (data: TestProgress) => {
      setProgress(data);
      setTestStatus(data.status);
    });

    newSocket.on('test-log', (log: TestLog) => {
      setLogs(prev => [...prev, log]);
    });

    newSocket.on('browser-view-update', (data: string) => {
      setBrowserView(data);
    });

    newSocket.on('test-completed', (data: { sessionId: string, results: any }) => {
      setTestStatus('completed');
      setProgress(prev => prev ? { 
        ...prev, 
        status: 'completed',
        currentScenario: data.results.totalScenarios,
        currentStep: data.results.totalSteps,
        ...data.results
      } : null);
    });

    newSocket.on('test-failed', (data: any) => {
      setTestStatus('failed');
      setProgress(prev => prev ? { ...prev, status: 'failed' } : null);
    });

    setSocket(newSocket);

    return () => {
      newSocket.disconnect();
    };
  }, [sessionId]);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  const handleStartTest = () => {
    const scenarios = JSON.parse(sessionStorage.getItem('selectedScenarios') || '[]');
    
    if (scenarios.length === 0 || !targetUrl) {
      router.push('/scenarios');
      return;
    }
    setTestStatus('running');
    socket?.emit('start-test', {
      sessionId,
      scenarios,
      url: targetUrl
    });
  };

  const handleViewResults = () => {
    router.push(`/results/${sessionId}`);
  };

  const formatTime = (dateString: string) => new Date(dateString).toLocaleTimeString();

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
      case 'running': return 'bg-blue-500';
      case 'paused': return 'bg-yellow-500';
      case 'completed': return 'bg-green-500';
      case 'failed': return 'bg-red-500';
      default: return 'bg-gray-500';
    }
  };

  const calculateProgress = () => {
    if (!progress || !progress.totalSteps) return 0;
    return Math.round((progress.currentStep / progress.totalSteps) * 100);
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-900 dark:to-slate-800">
      <div className="container mx-auto px-4 py-8">
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-4">
              <Button variant="ghost" onClick={() => router.push('/scenarios')}>
                <ArrowLeft className="w-4 h-4 mr-2" />
                Back
              </Button>
              <div>
                <h1 className="text-3xl font-bold text-slate-900 dark:text-slate-100">Test Execution</h1>
                <p className="text-slate-600 dark:text-slate-400">Session ID: {sessionId}</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-2">
                <div className={`w-3 h-3 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`} />
                <span className="text-sm text-slate-600 dark:text-slate-400">
                  {isConnected ? 'Connected' : 'Disconnected'}
                </span>
              </div>
              {/* {testStatus === 'completed' && (
                <Button onClick={handleViewResults}>View Resultsss</Button>
              )} */}
            </div>
          </div>
        </div>

        <Card className="mb-8 h-25 flex flex-col justify-center px-6 py-4">
          <div className="flex items-center justify-between w-full">
            {/* LEFT SIDE: Title + Buttons */}
            <div className="flex flex-col items-start gap-4">
              <CardTitle className="flex items-center gap-2 text-lg font-semibold">
                <Monitor className="w-5 h-5" />
                Test Control
              </CardTitle>

              <div className="flex items-center gap-4">
                {testStatus === 'idle' && (
                  <Button
                    onClick={handleStartTest}
                    disabled={!isConnected || testStatus === 'running'}
                  >
                    {testStatus === 'running' ? (
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    ) : (
                      <Play className="w-4 h-4 mr-2" />
                    )}
                    {testStatus === 'running' ? 'Starting...' : 'Start Test'}
                  </Button>
                )}

                {(testStatus === 'completed' || testStatus === 'failed') && (
                  <Button onClick={handleViewResults}>
                    <CheckCircle className="w-4 h-4 mr-2" />
                    View Results
                  </Button>
                )}
              </div>
               <div className="text-sm text-slate-600 dark:text-slate-400 mt-2">
                  <p><strong>Testing URL:</strong> {targetUrl || 'Not set'}</p>
                  <p className="text-xs mt-1">Note: This URL must be a running application for the test to succeed.</p>
              </div>
            </div>

            {/* RIGHT SIDE: Badge */}
            <Badge variant="outline" className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${getStatusColor(testStatus)}`} />
              {testStatus.charAt(0).toUpperCase() + testStatus.slice(1)}
            </Badge>
          </div>
        </Card>

        {/* Progress Overview */}
        {progress && (
          <Card className="mb-6">
            <CardHeader><CardTitle>Test Progress</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <div>
                <div className="flex justify-between text-sm mb-2"><span>Overall Progress</span><span>{calculateProgress()}%</span></div>
                <Progress value={calculateProgress()} className="h-2" />
              </div>
              <div className="grid md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <div className="flex justify-between text-sm"><span>Scenario Progress</span><span>{progress.currentScenario} / {progress.totalScenarios}</span></div>
                  <Progress value={(progress.currentScenario / progress.totalScenarios) * 100} className="h-2" />
                </div>
                <div className="space-y-2">
                  <div className="flex justify-between text-sm"><span>Step Progress</span><span>{progress.currentStep} / {progress.totalSteps}</span></div>
                  <Progress value={(progress.currentStep / progress.totalSteps) * 100} className="h-2" />
                </div>
              </div>
              <Separator />
              <div className="space-y-2">
                <p className="font-medium">Current Scenario:</p>
                <p className="text-lg font-semibold">{progress.currentScenarioTitle}</p>
                <p className="text-slate-600 dark:text-slate-400">{progress.currentStepDescription}</p>
              </div>
              <div className="flex items-center gap-4 text-sm text-slate-600 dark:text-slate-400">
                <div className="flex items-center gap-1"><Clock className="w-4 h-4" />Started: {formatTime(progress.startTime)}</div>
                {progress.estimatedEndTime && (
                  <div className="flex items-center gap-1"><Clock className="w-4 h-4" />Est. End: {formatTime(progress.estimatedEndTime)}</div>
                )}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Main Content */}
        <div className="grid lg:grid-cols-2 gap-6">
          {/* Live Browser View */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="flex items-center gap-2"><Monitor className="w-5 h-5" />Live Browser View</CardTitle>
                <Button variant="ghost" size="sm" onClick={() => setIsFullscreen(!isFullscreen)}>
                  {isFullscreen ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
                </Button>
              </div>
              <CardDescription>Real-time view of the browser during test execution</CardDescription>
            </CardHeader>
            <CardContent>
              <div className={`bg-slate-200 dark:bg-slate-800 rounded-lg overflow-hidden ${isFullscreen ? 'fixed inset-0 z-50 m-0' : 'aspect-video'}`}>
                {browserView ? (
                  <Image src={browserView} alt="Live browser view" width={1920} height={1080} className="w-full h-full object-contain" />
                ) : (
                  <div className="flex items-center justify-center h-full">
                    <div className="text-center">
                      <Monitor className="w-12 h-12 mx-auto mb-4 text-slate-400" />
                      <p className="text-slate-600 dark:text-slate-400">
                        {testStatus === 'idle' ? 'Click "Start Test" to begin execution' : 'Waiting for browser view...'}
                      </p>
                    </div>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Test Logs */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2"><Activity className="w-5 h-5" />Test Logs</CardTitle>
              <CardDescription>Real-time logs and test execution details</CardDescription>
            </CardHeader>
            <CardContent>
              <ScrollArea className="h-96 w-full">
                <div className="space-y-2">
                  {logs.length === 0 ? (
                    <div className="text-center py-8 text-slate-500">No logs yet. Start the test to see execution logs.</div>
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
                            {log.step && (
                              <p className="text-xs opacity-80">Step: {log.step}</p>
                            )}
                          </div>
                        </div>
                      </div>
                    ))
                  )}
                  <div ref={logsEndRef} />
                </div>
              </ScrollArea>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
