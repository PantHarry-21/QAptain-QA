'use client';

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Loader2, Save, Bot, Trash2, PlusCircle } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { motion } from "framer-motion";

interface SavedScenario {
  id: string;
  title: string;
  user_story: string;
  steps: string[];
}

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.1,
    },
  },
};

const itemVariants = {
  hidden: { y: 20, opacity: 0 },
  visible: { y: 0, opacity: 1 },
};

export default function SavedScenariosPage() {
  const [title, setTitle] = useState("");
  const [userStory, setUserStory] = useState("");
  const [savedScenarios, setSavedScenarios] = useState<SavedScenario[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState("");
  const { toast } = useToast();

  const fetchSavedScenarios = async () => {
    setIsLoading(true);
    try {
      const response = await fetch('/api/saved-scenarios');
      if (!response.ok) throw new Error('Failed to fetch scenarios');
      const data = await response.json();
      setSavedScenarios(data.data || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An unknown error occurred');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchSavedScenarios();
  }, []);

  const handleCreateScenario = async () => {
    if (!title.trim() || !userStory.trim()) {
      setError("Scenario title and description are required.");
      return;
    }
    setIsSaving(true);
    setError("");
    try {
      const response = await fetch('/api/saved-scenarios', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, user_story: userStory }),
      });
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.details || 'Failed to save scenario.');
      }
      toast({ title: "Scenario Saved", description: "Your new scenario has been successfully saved." });
      setTitle("");
      setUserStory("");
      fetchSavedScenarios();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An unknown error occurred');
    } finally {
      setIsSaving(false);
    }
  };

  const handleUpdateScenario = async (scenario: SavedScenario) => {
    try {
      const response = await fetch('/api/saved-scenarios', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(scenario),
      });
      if (!response.ok) throw new Error('Failed to update scenario');
      toast({ title: "Scenario Updated", description: `"${scenario.title}" has been saved.` });
    } catch (err) {
      toast({ variant: 'destructive', title: 'Error', description: err instanceof Error ? err.message : 'Could not update scenario.' });
    }
  };

  const handleDeleteScenario = async (scenarioId: string) => {
    if (!confirm('Are you sure you want to delete this scenario? This action cannot be undone.')) {
      return;
    }

    try {
      const response = await fetch(`/api/saved-scenarios?id=${scenarioId}`, {
        method: 'DELETE',
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.details || 'Failed to delete scenario.');
      }

      toast({ title: "Scenario Deleted", description: "The scenario has been permanently removed." });
      fetchSavedScenarios(); // Refresh the list
    } catch (err) {
      toast({ variant: 'destructive', title: 'Error', description: err instanceof Error ? err.message : 'Could not delete scenario.' });
    }
  };

  const handleStepChange = (scenarioId: string, stepIndex: number, newValue: string) => {
    setSavedScenarios(prev => prev.map(sc => {
      if (sc.id === scenarioId) {
        const newSteps = [...sc.steps];
        newSteps[stepIndex] = newValue;
        return { ...sc, steps: newSteps };
      }
      return sc;
    }));
  };

  const handleAddStep = (scenarioId: string) => {
    setSavedScenarios(prev => prev.map(sc => {
      if (sc.id === scenarioId) {
        return { ...sc, steps: [...sc.steps, ""] };
      }
      return sc;
    }));
  };

  const handleDeleteStep = (scenarioId: string, stepIndex: number) => {
    setSavedScenarios(prev => prev.map(sc => {
      if (sc.id === scenarioId) {
        const newSteps = sc.steps.filter((_, i) => i !== stepIndex);
        return { ...sc, steps: newSteps };
      }
      return sc;
    }));
  };

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-slate-100 mb-2">Global Saved Scenarios</h1>
        <p className="text-slate-400">Manage and reuse your custom test scenarios across any test run.</p>
      </div>

      {error && <Alert variant="destructive" className="mb-6 bg-red-500/10 border-red-500/30 text-red-400"><AlertDescription>{error}</AlertDescription></Alert>}

      <Card className="mb-8">
        <CardHeader>
          <CardTitle>Add a New Scenario</CardTitle>
          <CardDescription>Manually add a new test scenario to your library.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <label htmlFor="title" className="text-sm font-medium text-slate-300 mb-2 block">Scenario Title</label>
            <Input id="title" placeholder="e.g., Successful Login" value={title} onChange={(e) => setTitle(e.target.value)} className="bg-transparent"/>
          </div>
          <div>
            <label htmlFor="user_story" className="text-sm font-medium text-slate-300 mb-2 block">Scenario Description / User Story</label>
            <Textarea id="user_story" placeholder="e.g., When a user enters valid credentials, they should be redirected to the dashboard." rows={3} value={userStory} onChange={(e) => setUserStory(e.target.value)} className="bg-transparent"/>
          </div>
          <Button onClick={handleCreateScenario} disabled={isSaving || !title.trim() || !userStory.trim()}>
            {isSaving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
            Save Manual Scenario
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Your Scenario Library</CardTitle>
          <CardDescription>Edit the steps of any scenario and save your changes.</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center justify-center h-40"><Loader2 className="w-8 h-8 animate-spin text-slate-400" /></div>
          ) : savedScenarios.length > 0 ? (
            <motion.div
              variants={containerVariants}
              initial="hidden"
              animate="visible"
            >
              <Accordion type="multiple" className="w-full">
                {savedScenarios.map((scenario) => (
                  <motion.div key={scenario.id} variants={itemVariants}>
                    <AccordionItem value={scenario.id}>
                      <AccordionTrigger>
                        <div className="flex items-center gap-2">
                          <Bot className="w-5 h-5 text-primary"/>
                          <span className="font-semibold text-left">{scenario.title}</span>
                        </div>
                      </AccordionTrigger>
                      <AccordionContent className="pl-8 pb-2 text-slate-400">
                        <p className="text-sm mb-3 italic">Original story: "{scenario.user_story}"</p>
                        <div className="space-y-2">
                          {scenario.steps.map((step, index) => (
                            <div key={index} className="flex items-center gap-2">
                              <Input type="text" value={step} onChange={(e) => handleStepChange(scenario.id, index, e.target.value)} placeholder="Enter a test step" className="flex-grow font-mono text-sm h-9 bg-transparent"/>
                              <Button variant="ghost" size="icon" onClick={() => handleDeleteStep(scenario.id, index)} aria-label="Delete step"><Trash2 className="w-4 h-4 text-red-500" /></Button>
                            </div>
                          ))}
                          <div className="flex items-center justify-between gap-2 pt-2">
                             <div>
                               <Button variant="outline" size="sm" onClick={() => handleAddStep(scenario.id)}><PlusCircle className="w-4 h-4 mr-2"/> Add Step</Button>
                               <Button size="sm" onClick={() => handleUpdateScenario(scenario)} className="ml-2"><Save className="w-4 h-4 mr-2"/> Save Changes</Button>
                             </div>
                             <Button variant="destructive" size="sm" onClick={() => handleDeleteScenario(scenario.id)}><Trash2 className="w-4 h-4 mr-2"/> Delete Scenario</Button>
                          </div>
                        </div>
                      </AccordionContent>
                    </AccordionItem>
                  </motion.div>
                ))}
              </Accordion>
            </motion.div>
          ) : (
            <p className="text-sm text-slate-500 text-center py-10">You haven't saved any scenarios yet.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}