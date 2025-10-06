"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";
import { Loader2, ArrowLeft, Plus, Edit, Save, X, Clock, Target, CheckCircle } from "lucide-react";

interface Scenario {
  id: string;
  title: string;
  description: string;
  priority: 'high' | 'medium' | 'low';
  category: string;
  steps: string[];
  estimatedTime: string;
}

interface CustomScenario {
  id: string;
  title: string;
  description: string;
  steps: string[];
}

export default function ScenariosPage() {
  const [url, setUrl] = useState("");
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selectedScenarios, setSelectedScenarios] = useState<string[]>([]);
  const [customScenarios, setCustomScenarios] = useState<CustomScenario[]>([]);
  const [newCustomScenario, setNewCustomScenario] = useState({
    title: "",
    description: "",
    steps: ""
  });
  const [editingScenario, setEditingScenario] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  const router = useRouter();

  useEffect(() => {
    const storedUrl = sessionStorage.getItem('targetUrl');
    if (!storedUrl) {
      router.push('/');
      return;
    }
    setUrl(storedUrl);
    analyzeUrlAndGenerateScenarios(storedUrl);
  }, [router]);

  const analyzeUrlAndGenerateScenarios = async (targetUrl: string) => {
    setLoading(true);
    setError("");

    try {
      // Step 1: Analyze URL
      const analyzeResponse = await fetch('/api/analyze-url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: targetUrl })
      });

      if (!analyzeResponse.ok) {
        throw new Error('Failed to analyze URL');
      }

      const analyzeData = await analyzeResponse.json();

      // Step 2: Generate scenarios
      const generateResponse = await fetch('/api/generate-scenarios', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pageInfo: analyzeData.data.pageInfo })
      });

      if (!generateResponse.ok) {
        throw new Error('Failed to generate scenarios');
      }

      const generateData = await generateResponse.json();
      setScenarios(generateData.data.scenarios);
      
      // Auto-select high priority scenarios
      const highPriorityScenarios = generateData.data.scenarios
        .filter((s: Scenario) => s.priority === 'high')
        .map((s: Scenario) => s.id);
      setSelectedScenarios(highPriorityScenarios);

    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to analyze URL and generate scenarios');
    } finally {
      setLoading(false);
    }
  };

  const handleScenarioToggle = (scenarioId: string) => {
    setSelectedScenarios(prev => 
      prev.includes(scenarioId) 
        ? prev.filter(id => id !== scenarioId)
        : [...prev, scenarioId]
    );
  };

  const handleAddCustomScenario = () => {
    if (!newCustomScenario.title.trim() || !newCustomScenario.steps.trim()) {
      return;
    }

    const steps = newCustomScenario.steps
      .split('\n')
      .map(step => step.trim())
      .filter(step => step);

    const customScenario: CustomScenario = {
      id: `custom_${Date.now()}`,
      title: newCustomScenario.title,
      description: newCustomScenario.description,
      steps
    };

    setCustomScenarios(prev => [...prev, customScenario]);
    setSelectedScenarios(prev => [...prev, customScenario.id]);
    
    setNewCustomScenario({ title: "", description: "", steps: "" });
  };

  const handleEditScenario = (scenarioId: string, currentTitle: string) => {
    setEditingScenario(scenarioId);
    setEditText(currentTitle);
  };

  const handleSaveEdit = (scenarioId: string) => {
    if (!editText.trim()) return;

    setScenarios(prev => prev.map(scenario => 
      scenario.id === scenarioId 
        ? { ...scenario, title: editText }
        : scenario
    ));
    setEditingScenario(null);
    setEditText("");
  };

  const handleGenerateAndRun = async () => {
    if (selectedScenarios.length === 0) {
      setError('Please select at least one test scenario');
      return;
    }

    setGenerating(true);
    setError("");

    try {
      // Combine selected AI scenarios and custom scenarios
      const allScenarios = [
        ...scenarios.filter(s => selectedScenarios.includes(s.id)),
        ...customScenarios.filter(s => selectedScenarios.includes(s.id))
      ];

      // Store scenarios in sessionStorage
      sessionStorage.setItem('selectedScenarios', JSON.stringify(allScenarios));
      sessionStorage.setItem('targetUrl', url);

      // Generate session ID and navigate to test execution
      const sessionId = `session_${Date.now()}`;
      router.push(`/test-execution/${sessionId}`);

    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start test execution');
    } finally {
      setGenerating(false);
    }
  };

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case 'high': return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200';
      case 'medium': return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200';
      case 'low': return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200';
      default: return 'bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-200';
    }
  };

  const getCategoryColor = (category: string) => {
    const colors: { [key: string]: string } = {
      basic: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
      navigation: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
      authentication: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200',
      forms: 'bg-teal-100 text-teal-800 dark:bg-teal-900 dark:text-teal-200',
      search: 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-200',
      interaction: 'bg-pink-100 text-pink-800 dark:bg-pink-900 dark:text-pink-200',
      links: 'bg-cyan-100 text-cyan-800 dark:bg-cyan-900 dark:text-cyan-200',
      media: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200',
      responsive: 'bg-violet-100 text-violet-800 dark:bg-violet-900 dark:text-violet-200',
      performance: 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200',
      seo: 'bg-lime-100 text-lime-800 dark:bg-lime-900 dark:text-lime-200'
    };
    return colors[category] || 'bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-200';
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-900 dark:to-slate-800 flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="w-12 h-12 animate-spin mx-auto mb-4" />
          <p className="text-lg">Analyzing URL and generating test scenarios...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-900 dark:to-slate-800">
      <div className="container mx-auto px-4 py-8">
        {/* Header */}
        <div className="mb-8">
          <Button
            variant="ghost"
            className="mb-4"
            onClick={() => router.push('/')}
          >
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back to URL Input
          </Button>
          
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold text-slate-900 dark:text-slate-100 mb-2">
                Test Scenarios
              </h1>
              <p className="text-slate-600 dark:text-slate-400">
                URL: <span className="font-mono">{url}</span>
              </p>
            </div>
            
            <div className="text-right">
              <p className="text-sm text-slate-600 dark:text-slate-400 mb-2">
                {selectedScenarios.length} of {scenarios.length + customScenarios.length} scenarios selected
              </p>
              <Button
                onClick={handleGenerateAndRun}
                disabled={selectedScenarios.length === 0 || generating}
                className="px-6"
              >
                {generating ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Preparing...
                  </>
                ) : (
                  <>
                    <Target className="mr-2 h-4 w-4" />
                    Generate & Run Tests
                  </>
                )}
              </Button>
            </div>
          </div>
        </div>

        {error && (
          <Alert variant="destructive" className="mb-6">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <div className="grid lg:grid-cols-3 gap-6">
          {/* AI-Generated Scenarios */}
          <div className="lg:col-span-2">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <CheckCircle className="w-5 h-5" />
                  AI-Generated Test Scenarios
                </CardTitle>
                <CardDescription>
                  Select the test scenarios you want to run. You can also edit scenario titles.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {scenarios.map((scenario) => (
                  <Card key={scenario.id} className="border-slate-200 dark:border-slate-700">
                    <CardContent className="p-4">
                      <div className="flex items-start gap-3">
                        <Checkbox
                          checked={selectedScenarios.includes(scenario.id)}
                          onCheckedChange={() => handleScenarioToggle(scenario.id)}
                          className="mt-1"
                        />
                        
                        <div className="flex-1 space-y-2">
                          <div className="flex items-start justify-between gap-2">
                            <div className="flex-1">
                              {editingScenario === scenario.id ? (
                                <div className="flex gap-2">
                                  <Input
                                    value={editText}
                                    onChange={(e) => setEditText(e.target.value)}
                                    className="flex-1"
                                  />
                                  <Button
                                    size="sm"
                                    onClick={() => handleSaveEdit(scenario.id)}
                                  >
                                    <Save className="w-4 h-4" />
                                  </Button>
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={() => setEditingScenario(null)}
                                  >
                                    <X className="w-4 h-4" />
                                  </Button>
                                </div>
                              ) : (
                                <div className="flex items-center gap-2">
                                  <h3 className="font-semibold text-lg">{scenario.title}</h3>
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={() => handleEditScenario(scenario.id, scenario.title)}
                                  >
                                    <Edit className="w-4 h-4" />
                                  </Button>
                                </div>
                              )}
                            </div>
                            
                            <div className="flex gap-2">
                              <Badge className={getPriorityColor(scenario.priority)}>
                                {scenario.priority}
                              </Badge>
                              <Badge className={getCategoryColor(scenario.category)}>
                                {scenario.category}
                              </Badge>
                            </div>
                          </div>
                          
                          <p className="text-slate-600 dark:text-slate-400 text-sm">
                            {scenario.description}
                          </p>
                          
                          <div className="flex items-center gap-4 text-sm text-slate-500 dark:text-slate-400">
                            <div className="flex items-center gap-1">
                              <Clock className="w-4 h-4" />
                              {scenario.estimatedTime}
                            </div>
                            <div>
                              {scenario.steps.length} steps
                            </div>
                          </div>
                          
                          <div className="space-y-1">
                            <p className="text-sm font-medium">Steps:</p>
                            <ul className="text-sm text-slate-600 dark:text-slate-400 space-y-1">
                              {scenario.steps.map((step, index) => (
                                <li key={index} className="flex items-start gap-2">
                                  <span className="text-slate-400">•</span>
                                  {step}
                                </li>
                              ))}
                            </ul>
                          </div>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </CardContent>
            </Card>
          </div>

          {/* Custom Scenarios */}
          <div className="space-y-6">
            {/* Add Custom Scenario */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Plus className="w-5 h-5" />
                  Add Custom Scenario
                </CardTitle>
                <CardDescription>
                  Create your own test scenario in plain English
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <label className="text-sm font-medium mb-2 block">Title</label>
                  <Input
                    placeholder="Enter scenario title"
                    value={newCustomScenario.title}
                    onChange={(e) => setNewCustomScenario(prev => ({ ...prev, title: e.target.value }))}
                  />
                </div>
                
                <div>
                  <label className="text-sm font-medium mb-2 block">Description (Optional)</label>
                  <Input
                    placeholder="Brief description"
                    value={newCustomScenario.description}
                    onChange={(e) => setNewCustomScenario(prev => ({ ...prev, description: e.target.value }))}
                  />
                </div>
                
                <div>
                  <label className="text-sm font-medium mb-2 block">Steps (one per line)</label>
                  <Textarea
                    placeholder="Enter test steps&#10;One step per line&#10;e.g., Navigate to login page&#10;Enter username&#10;Enter password&#10;Click login button"
                    value={newCustomScenario.steps}
                    onChange={(e) => setNewCustomScenario(prev => ({ ...prev, steps: e.target.value }))}
                    rows={6}
                  />
                </div>
                
                <Button
                  onClick={handleAddCustomScenario}
                  disabled={!newCustomScenario.title.trim() || !newCustomScenario.steps.trim()}
                  className="w-full"
                >
                  <Plus className="mr-2 h-4 w-4" />
                  Add Custom Scenario
                </Button>
              </CardContent>
            </Card>

            {/* Custom Scenarios List */}
            {customScenarios.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle>Custom Scenarios</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  {customScenarios.map((scenario) => (
                    <Card key={scenario.id} className="border-slate-200 dark:border-slate-700">
                      <CardContent className="p-3">
                        <div className="flex items-start gap-2">
                          <Checkbox
                            checked={selectedScenarios.includes(scenario.id)}
                            onCheckedChange={() => handleScenarioToggle(scenario.id)}
                            className="mt-1"
                          />
                          
                          <div className="flex-1 space-y-1">
                            <h4 className="font-medium text-sm">{scenario.title}</h4>
                            {scenario.description && (
                              <p className="text-xs text-slate-600 dark:text-slate-400">
                                {scenario.description}
                              </p>
                            )}
                            <p className="text-xs text-slate-500">
                              {scenario.steps.length} steps
                            </p>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                </CardContent>
              </Card>
            )}

            {/* Summary */}
            <Card>
              <CardHeader>
                <CardTitle>Test Summary</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex justify-between text-sm">
                  <span>Total Scenarios:</span>
                  <span className="font-medium">{scenarios.length + customScenarios.length}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span>Selected Scenarios:</span>
                  <span className="font-medium">{selectedScenarios.length}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span>High Priority:</span>
                  <span className="font-medium">
                    {scenarios.filter(s => s.priority === 'high' && selectedScenarios.includes(s.id)).length}
                  </span>
                </div>
                <Separator />
                <div className="text-sm text-slate-600 dark:text-slate-400">
                  Estimated total time: {selectedScenarios.length * 2} minutes
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}