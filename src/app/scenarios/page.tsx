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
import { Loader2, ArrowLeft, Wand2, Target, PlusCircle, Bot, User, Trash2, Bookmark } from "lucide-react";
import { v4 as uuidv4 } from 'uuid';
import { useToast } from "@/hooks/use-toast";

// --- Type Definitions ---
interface Scenario {
  id: string;
  title: string;
  description: string;
  steps: string[];
  type: 'ai' | 'manual' | 'saved';
}

interface SavedScenario extends Omit<Scenario, 'type'> {
  user_story: string;
}

export default function ScenariosPage() {
  const [url, setUrl] = useState("");
  const [pageAnalysis, setPageAnalysis] = useState(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const { toast } = useToast();

  // State for scenarios
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selectedScenarioIds, setSelectedScenarioIds] = useState<Set<string>>(new Set());

  // State for manual scenario input
  const [manualStory, setManualStory] = useState("");
  const [isInterpreting, setIsInterpreting] = useState(false);

  // State for saved scenarios modal
  const [savedScenarios, setSavedScenarios] = useState<SavedScenario[]>([]);
  const [isLoadingSaved, setIsLoadingSaved] = useState(false);
  const [selectedSaved, setSelectedSaved] = useState<Set<string>>(new Set());

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
      if (!response.ok) throw new Error('Failed to interpret scenario');
      const data = await response.json();
      const newManualScenario: Scenario = {
        id: uuidv4(),
        title: manualStory.split('\n')[0],
        description: 'A custom scenario added by the user.',
        steps: data.steps,
        type: 'manual',
      };
      setScenarios(prev => [...prev, newManualScenario]);
      setSelectedScenarioIds(prev => new Set(prev).add(newManualScenario.id));
      setManualStory("");
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An unknown error occurred');
    } finally {
      setIsInterpreting(false);
    }
  };

  const handleSelectionChange = (checked: boolean, scenarioId: string) => {
    setSelectedScenarioIds(prev => {
      const newSet = new Set(prev);
      if (checked) newSet.add(scenarioId);
      else newSet.delete(scenarioId);
      return newSet;
    });
  };

  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedScenarioIds(new Set(scenarios.map(sc => sc.id)));
    } else {
      setSelectedScenarioIds(new Set());
    }
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
      await fetch('/api/history', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sessionId: newSessionId, url, scenarios: scenariosToRun }),
      });
      sessionStorage.setItem('selectedScenarios', JSON.stringify(scenariosToRun));
      sessionStorage.setItem('targetUrl', url);
      router.push(`/test-execution/${newSessionId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An unknown error occurred');
      setIsLoading(false);
    }
  };

  const fetchSavedScenarios = async () => {
    setIsLoadingSaved(true);
    try {
      const response = await fetch(`/api/saved-scenarios?url=${encodeURIComponent(url)}`);
      if (!response.ok) throw new Error('Failed to fetch saved scenarios.');
      const data = await response.json();
      setSavedScenarios(data.data || []);
    } catch (err) {
      toast({ variant: 'destructive', title: 'Error', description: err instanceof Error ? err.message : 'Could not fetch saved scenarios.' });
    } finally {
      setIsLoadingSaved(false);
    }
  };

  const handleAddSavedScenarios = () => {
    const scenariosToAdd = savedScenarios
      .filter(ss => selectedSaved.has(ss.id))
      .map(ss => ({ ...ss, id: uuidv4(), type: 'saved' as const }));
    
    setScenarios(prev => [...prev, ...scenariosToAdd]);
    setSelectedScenarioIds(prev => new Set([...prev, ...scenariosToAdd.map(s => s.id)]));
    setSelectedSaved(new Set());
    toast({ title: 'Scenarios Added', description: `${scenariosToAdd.length} saved scenarios have been added to the current test run.` });
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

  const allSelected = scenarios.length > 0 && selectedScenarioIds.size === scenarios.length;
  const isIndeterminate = selectedScenarioIds.size > 0 && selectedScenarioIds.size < scenarios.length;

  // --- Render ---
  return (
    <div className="container mx-auto px-4 py-8">
      <div className="mb-8">
        <Button variant="ghost" className="mb-4" onClick={() => router.push('/')}>
          <ArrowLeft className="w-4 h-4 mr-2" />
          Back to URL Input
        </Button>
        <div>
          <h1 className="text-3xl font-bold text-slate-100 mb-2">Generated Test Scenarios</h1>
          <p className="text-slate-400">URL: <span className="font-mono">{url}</span></p>
        </div>
      </div>

      {error && <Alert variant="destructive" className="mb-6 bg-red-500/10 border-red-500/30 text-red-400"><AlertDescription>{error}</AlertDescription></Alert>}

      <Card>
        <CardHeader className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div>
            <CardTitle>Review & Select Scenarios</CardTitle>
            <CardDescription>The AI has generated scenarios. You can edit, add, or import scenarios before running.</CardDescription>
          </div>
          <div className="flex gap-2">
            <Dialog>
              <DialogTrigger asChild>
                <Button variant="outline" onClick={fetchSavedScenarios}><Bookmark className="w-4 h-4 mr-2"/> Use Saved Scenarios</Button>
              </DialogTrigger>
              <DialogContent className="max-w-3xl">
                <DialogHeader><DialogTitle>Select Saved Scenarios for "{url}"</DialogTitle></DialogHeader>
                {isLoadingSaved ? <Loader2 className="w-6 h-6 animate-spin mx-auto my-8"/> : (
                  <div className="max-h-[60vh] overflow-y-auto space-y-2 p-1">
                    {savedScenarios.length > 0 ? savedScenarios.map(ss => (
                      <div key={ss.id} className="flex items-center gap-3 p-3 rounded-md bg-white/5 hover:bg-white/10">
                        <Checkbox id={ss.id} onCheckedChange={(checked) => setSelectedSaved(prev => new Set(prev.has(ss.id) ? (prev.delete(ss.id), prev) : prev.add(ss.id)))} />
                        <Label htmlFor={ss.id} className="flex-1 cursor-pointer font-semibold">{ss.title}</Label>
                      </div>
                    )) : <p className="text-center text-slate-400 py-8">No scenarios saved for this URL yet.</p>}
                  </div>
                )}
                <DialogFooter>
                  <DialogClose asChild>
                    <Button onClick={handleAddSavedScenarios} disabled={selectedSaved.size === 0}>Add Selected Scenarios</Button>
                  </DialogClose>
                </DialogFooter>
              </DialogContent>
            </Dialog>
            <Dialog>
              <DialogTrigger asChild><Button variant="outline"><PlusCircle className="w-4 h-4 mr-2"/> Add Manual</Button></DialogTrigger>
              <DialogContent>
                <DialogHeader><DialogTitle>Add a Manual Scenario</DialogTitle></DialogHeader>
                <Textarea placeholder="e.g., Login with invalid credentials..." rows={8} value={manualStory} onChange={(e) => setManualStory(e.target.value)} className="bg-transparent"/>
                <DialogFooter>
                  <DialogClose asChild>
                    <Button onClick={handleAddManualScenario} disabled={isInterpreting || !manualStory.trim()}>{isInterpreting ? <Loader2 className="w-4 h-4 mr-2 animate-spin"/> : <Wand2 className="w-4 h-4 mr-2"/>}Interpret & Add</Button>
                  </DialogClose>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center justify-center h-64"><Loader2 className="w-8 h-8 animate-spin text-slate-400" /><p className="ml-4 text-slate-500">AI is generating scenarios...</p></div>
          ) : scenarios.length > 0 ? (
            <>
              <div className="flex items-center gap-3 p-2 mb-2">
                <Checkbox id="select-all" checked={allSelected} indeterminate={isIndeterminate} onCheckedChange={handleSelectAll} />
                <Label htmlFor="select-all" className="font-semibold">{allSelected ? 'Unselect All' : 'Select All'}</Label>
              </div>
              <Accordion type="multiple" className="w-full" defaultValue={scenarios.map(s => s.id)}>
                {scenarios.map((scenario) => (
                  <AccordionItem value={scenario.id} key={scenario.id}>
                    <div className="flex items-center gap-3 p-2 hover:bg-white/5 rounded-lg">
                      <Checkbox id={scenario.id} checked={selectedScenarioIds.has(scenario.id)} onCheckedChange={(checked) => handleSelectionChange(!!checked, scenario.id)} />
                      <Label htmlFor={scenario.id} className="flex-1 cursor-pointer">
                        <AccordionTrigger className="p-1 hover:no-underline">
                          <div className="flex items-center gap-2">
                            {scenario.type === 'ai' && <Bot className="w-5 h-5 text-primary"/>}
                            {scenario.type === 'manual' && <User className="w-5 h-5 text-green-400"/>}
                            {scenario.type === 'saved' && <Bookmark className="w-5 h-5 text-yellow-400"/>}
                            <span className="font-semibold text-left">{scenario.title}</span>
                          </div>
                        </AccordionTrigger>
                      </Label>
                    </div>
                    <AccordionContent className="pl-12 pb-2 text-slate-400">
                      <p className="text-sm mb-2">{scenario.description}</p>
                      <div className="space-y-2">
                        {scenario.steps.map((step, index) => (
                          <div key={index} className="flex items-center gap-2">
                            <Input type="text" value={step} onChange={(e) => handleStepChange(scenario.id, index, e.target.value)} placeholder="Enter a test step" className="flex-grow font-mono text-sm h-9 bg-transparent"/>
                            <Button variant="ghost" size="icon" onClick={() => handleDeleteStep(scenario.id, index)} aria-label="Delete step"><Trash2 className="w-4 h-4 text-red-500" /></Button>
                          </div>
                        ))}
                        <Button variant="outline" size="sm" onClick={() => handleAddStep(scenario.id)} className="mt-2"><PlusCircle className="w-4 h-4 mr-2"/> Add Step</Button>
                      </div>
                    </AccordionContent>
                  </AccordionItem>
                ))}
              </Accordion>
            </>
          ) : (
            <p className="text-sm text-slate-500 text-center py-10">The AI could not generate any scenarios for this URL.</p>
          )}
        </CardContent>
      </Card>

      {scenarios.length > 0 && (
        <div className="sticky bottom-0 left-0 right-0 p-4 bg-background/80 backdrop-blur-sm border-t border-white/10 mt-8">
          <div className="container mx-auto flex items-center justify-between">
            <div className="font-semibold">{selectedScenarioIds.size} scenario(s) selected</div>
            <Button onClick={handleStartTest} disabled={isLoading || selectedScenarioIds.size === 0} size="lg">
              {isLoading ? <Loader2 className="w-5 h-5 mr-2 animate-spin" /> : <Target className="w-5 h-5 mr-2" />}Run Test(s)
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
