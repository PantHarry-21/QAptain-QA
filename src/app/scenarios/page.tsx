'use client';

import { useState, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter, DialogClose } from "@/components/ui/dialog";
import { Loader2, ArrowLeft, Wand2, Target, PlusCircle, Bot, User, Trash2 } from "lucide-react";
import { v4 as uuidv4 } from 'uuid';

// --- Type Definitions ---
interface Scenario {
  id: string;
  title: string;
  description: string;
  steps: string[];
  type: 'ai' | 'manual';
}

export default function ScenariosPage() {
  const [url, setUrl] = useState("");
  const [pageAnalysis, setPageAnalysis] = useState(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  // State for scenarios
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selectedScenarioIds, setSelectedScenarioIds] = useState<Set<string>>(new Set());

  // State for manual scenario input
  const [manualStory, setManualStory] = useState("");
  const [isInterpreting, setIsInterpreting] = useState(false);

  const router = useRouter();

  // --- Effects ---
  useEffect(() => {
    const storedUrl = sessionStorage.getItem('targetUrl');
    const storedAnalysis = sessionStorage.getItem('pageAnalysis');
    if (!storedUrl || !storedAnalysis) {
      router.push('/');
      return;
    }
    
    const analysis = JSON.parse(storedAnalysis);
    setUrl(storedUrl);
    setPageAnalysis(analysis);

    const generateInitialScenarios = async () => {
      setIsLoading(true);
      try {
        const response = await fetch('/api/generate-scenarios', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pageContext: analysis }),
        });

        if (!response.ok) {
          const errorData = await response.json();
          throw new Error(errorData.details || 'Failed to generate scenarios.');
        }

        const data: { scenarios: Omit<Scenario, 'id' | 'type'>[] } = await response.json();
        const scenariosWithIds = data.scenarios.map(sc => ({
          ...sc,
          id: uuidv4(),
          type: 'ai' as const
        }));
        
        setScenarios(scenariosWithIds);
        // Automatically select all generated scenarios by default
        setSelectedScenarioIds(new Set(scenariosWithIds.map(sc => sc.id)));

      } catch (err) {
        setError(err instanceof Error ? err.message : 'An unknown error occurred while generating scenarios.');
      } finally {
        setIsLoading(false);
      }
    };

    generateInitialScenarios();
  }, [router]);

  // --- Handlers ---
  const handleAddManualScenario = async () => {
    if (!manualStory.trim()) return;
    
    setIsInterpreting(true);
    setError("");

    try {
      const response = await fetch('/api/interpret-scenario', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, userStory: manualStory, pageContext: pageAnalysis }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.details || 'Failed to interpret scenario.');
      }

      const data: { steps: string[] } = await response.json();
      if (!data.steps || data.steps.length === 0) {
        throw new Error("The AI couldn't determine any steps from your description.");
      }

      const newManualScenario: Scenario = {
        id: uuidv4(),
        title: manualStory.split('\n')[0],
        description: 'A custom scenario added by the user.',
        steps: data.steps,
        type: 'manual',
      };

      setScenarios(prev => [...prev, newManualScenario]);
      setSelectedScenarioIds(prev => new Set(prev).add(newManualScenario.id));
      setManualStory(""); // Clear input field

    } catch (err) {
      setError(err instanceof Error ? err.message : 'An unknown error occurred');
    } finally {
      setIsInterpreting(false);
    }
  };

  const handleSelectionChange = (checked: boolean, scenarioId: string) => {
    setSelectedScenarioIds(prev => {
      const newSet = new Set(prev);
      if (checked) {
        newSet.add(scenarioId);
      } else {
        newSet.delete(scenarioId);
      }
      return newSet;
    });
  };

  const handleStartTest = async () => {
    const scenariosToRun = scenarios.filter(sc => selectedScenarioIds.has(sc.id));

    if (scenariosToRun.length === 0) {
      setError("Please select at least one scenario to run.");
      return;
    }
    
    if (scenariosToRun.some(sc => sc.steps.some(s => !s.trim()))) {
        setError("Cannot start test with empty steps. Please fill in or remove any empty steps.");
        return;
    }

    setIsLoading(true);
    setError("");
    const newSessionId = uuidv4();

    try {
      const response = await fetch('/api/history', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sessionId: newSessionId, url, scenarios: scenariosToRun }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.details || 'Failed to create test session.');
      }

      sessionStorage.setItem('selectedScenarios', JSON.stringify(scenariosToRun));
      sessionStorage.setItem('targetUrl', url);
      
      router.push(`/test-execution/${newSessionId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An unknown error occurred while starting the test.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleStepChange = (scenarioId: string, stepIndex: number, newValue: string) => {
    setScenarios(prev => prev.map(sc => {
      if (sc.id === scenarioId) {
        const newSteps = [...sc.steps];
        newSteps[stepIndex] = newValue;
        return { ...sc, steps: newSteps };
      }
      return sc;
    }));
  };

  const handleAddStep = (scenarioId: string) => {
    setScenarios(prev => prev.map(sc => {
      if (sc.id === scenarioId) {
        return { ...sc, steps: [...sc.steps, ""] };
      }
      return sc;
    }));
  };

  const handleDeleteStep = (scenarioId: string, stepIndex: number) => {
    setScenarios(prev => prev.map(sc => {
      if (sc.id === scenarioId) {
        const newSteps = sc.steps.filter((_, i) => i !== stepIndex);
        return { ...sc, steps: newSteps };
      }
      return sc;
    }));
  };

  const selectedCount = selectedScenarioIds.size;

  // --- Render ---
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-900 dark:to-slate-800">
      <div className="container mx-auto px-4 py-8">
        <div className="mb-8">
          <Button variant="ghost" className="mb-4" onClick={() => router.push('/')}>
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back to URL Input
          </Button>
          <div>
            <h1 className="text-3xl font-bold text-slate-900 dark:text-slate-100 mb-2">Generated Test Scenarios</h1>
            <p className="text-slate-600 dark:text-slate-400">URL: <span className="font-mono">{url}</span></p>
          </div>
        </div>

        {error && <Alert variant="destructive" className="mb-6"><AlertDescription>{error}</AlertDescription></Alert>}

        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle>Review & Select Scenarios</CardTitle>
              <CardDescription>The AI has generated the following test scenarios. You can edit any scenario before running.</CardDescription>
            </div>
            <Dialog>
              <DialogTrigger asChild>
                <Button variant="outline"><PlusCircle className="w-4 h-4 mr-2"/> Add Manual Scenario</Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Add a Manual Scenario</DialogTitle>
                </DialogHeader>
                <Textarea 
                  placeholder="e.g., Login with invalid credentials..." 
                  rows={8}
                  value={manualStory}
                  onChange={(e) => setManualStory(e.target.value)}
                />
                <DialogFooter>
                  <DialogClose asChild>
                    <Button 
                      onClick={handleAddManualScenario} 
                      disabled={isInterpreting || !manualStory.trim()}
                    >
                      {isInterpreting ? <Loader2 className="w-4 h-4 mr-2 animate-spin"/> : <Wand2 className="w-4 h-4 mr-2"/>}
                      Interpret & Add
                    </Button>
                  </DialogClose>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="flex items-center justify-center h-64"><Loader2 className="w-8 h-8 animate-spin text-slate-400" /><p className="ml-4 text-slate-500">AI is generating scenarios...</p></div>
            ) : scenarios.length > 0 ? (
              <Accordion type="multiple" className="w-full">
                {scenarios.map((scenario) => (
                  <AccordionItem value={scenario.id} key={scenario.id}>
                    <div className="flex items-center gap-3 p-2 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg">
                      <Checkbox 
                        id={scenario.id}
                        checked={selectedScenarioIds.has(scenario.id)}
                        onCheckedChange={(checked) => handleSelectionChange(!!checked, scenario.id)}
                      />
                      <Label htmlFor={scenario.id} className="flex-1 cursor-pointer">
                        <AccordionTrigger className="p-1 hover:no-underline">
                          <div className="flex items-center gap-2">
                            {scenario.type === 'ai' ? <Bot className="w-5 h-5 text-blue-500"/> : <User className="w-5 h-5 text-green-500"/>}
                            <span className="font-semibold">{scenario.title}</span>
                          </div>
                        </AccordionTrigger>
                      </Label>
                    </div>
                    <AccordionContent className="pl-12 pb-2 text-slate-600 dark:text-slate-400">
                      <p className="text-sm mb-2">{scenario.description}</p>
                      <div className="space-y-2">
                        {scenario.steps.map((step, index) => (
                          <div key={index} className="flex items-center gap-2">
                            <Input
                              type="text"
                              value={step}
                              onChange={(e) => handleStepChange(scenario.id, index, e.target.value)}
                              placeholder="Enter a test step"
                              className="flex-grow font-mono text-sm h-9"
                            />
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => handleDeleteStep(scenario.id, index)}
                              aria-label="Delete step"
                            >
                              <Trash2 className="w-4 h-4 text-red-500" />
                            </Button>
                          </div>
                        ))}
                        <Button variant="outline" size="sm" onClick={() => handleAddStep(scenario.id)} className="mt-2">
                            <PlusCircle className="w-4 h-4 mr-2"/> Add Step
                        </Button>
                      </div>
                    </AccordionContent>
                  </AccordionItem>
                ))}
              </Accordion>
            ) : (
              <p className="text-sm text-slate-500 text-center py-10">The AI could not generate any scenarios for this URL.</p>
            )}
          </CardContent>
        </Card>

        {scenarios.length > 0 && (
            <div className="sticky bottom-0 left-0 right-0 p-4 bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm border-t mt-8">
                <div className="container mx-auto flex items-center justify-between">
                    <div className="font-semibold">
                        {selectedCount} scenario(s) selected
                    </div>
                    <Button onClick={handleStartTest} disabled={isLoading || selectedCount === 0} size="lg">
                        {isLoading ? <Loader2 className="w-5 h-5 mr-2 animate-spin" /> : <Target className="w-5 h-5 mr-2" />}
                        Run Test(s)
                    </Button>
                </div>
            </div>
        )}
      </div>
    </div>
  );
}