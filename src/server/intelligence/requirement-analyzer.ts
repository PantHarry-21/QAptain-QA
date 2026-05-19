import { prisma } from '@/lib/prisma';
import { openAIService } from '@/lib/openai';
import { prompts } from '@/lib/prompts';

export type RequirementAnalysisResult = {
  summary: string;
  workflows: Array<{ name: string; steps: string[]; priority: string }>;
  testingMap: {
    modules: string[];
    criticalPaths: string[];
  };
  scenarios: Array<{
    title: string;
    type: 'positive' | 'negative' | 'edge';
    steps: string[];
  }>;
  validationRules: Array<{ field: string; rule: string }>;
};

/**
 * RequirementIntelligenceEngine (Phase 2)
 * Coordinates multiple agents to parse requirements into executable test suites.
 */
export class RequirementIntelligenceEngine {
  /**
   * Analyzes a raw requirement text and converts it into a structured testing plan.
   * @param workspaceId The workspace context.
   * @param text The requirement text (PRD, story, etc).
   */
  static async analyze(workspaceId: string, text: string): Promise<RequirementAnalysisResult> {
    try {
      console.log(`[Requirement Engine] Analyzing requirement for workspace ${workspaceId}...`);

      // 1. Gather Workspace Context (Modules, Fields)
      const modules = await prisma.module.findMany({
        where: { workspaceId },
        include: { routes: true },
      });

      const context = {
        modules: modules.map(m => ({
          name: m.name,
          routes: m.routes.map(r => r.path),
        })),
      };

      // 2. Multi-Agent Orchestration Flow

      // Agent 1: PRD Analysis (Business Context)
      console.log('[Requirement Engine] Agent 1: PRD Analyst starting...');
      const prdPrompt = prompts.prdAnalystAgent(text);
      const businessAnalysis = await openAIService['_generateAndParseJSON']<{
        personas: string[];
        workflows: any[];
        businessRules: string[];
      }>(prdPrompt);

      // Agent 2: Test Architecture (Scenario Strategy)
      console.log('[Requirement Engine] Agent 2: Test Architect starting...');
      const archPrompt = prompts.testArchitectAgent(businessAnalysis.workflows, context.modules);
      const strategy = await openAIService['_generateAndParseJSON']<{
        scenarios: any[];
      }>(archPrompt);

      // Agent 3: SDET (Step Generation with Workspace Intel)
      console.log('[Requirement Engine] Agent 3: SDET starting...');
      const finalScenarios: any[] = [];

      // Process in parallel for speed
      await Promise.all(strategy.scenarios.map(async (s: any) => {
        const sdetPrompt = prompts.sdetAgent(s, { modules: context.modules });
        const { steps } = await openAIService['_generateAndParseJSON']<{ steps: string[] }>(sdetPrompt);
        finalScenarios.push({
          ...s,
          steps,
        });
      }));

      const result: RequirementAnalysisResult = {
        summary: `Analyzed ${businessAnalysis.workflows.length} workflows and generated ${finalScenarios.length} test scenarios.`,
        workflows: businessAnalysis.workflows,
        testingMap: {
          modules: strategy.scenarios.map((s: any) => s.module),
          criticalPaths: businessAnalysis.workflows.map((w: any) => w.name),
        },
        scenarios: finalScenarios,
        validationRules: businessAnalysis.businessRules.map(r => ({ field: 'N/A', rule: r })),
      };

      return result;
    } catch (error) {
      console.error('[Requirement Engine] Multi-agent orchestration failed:', error);
      throw new Error('Agentic analysis failed: ' + (error instanceof Error ? error.message : String(error)));
    }
  }

  /**
   * Persists the analysis result by creating scenarios in the workspace.
   */
  static async commitToLibrary(workspaceId: string, result: RequirementAnalysisResult) {
    console.log(`[Requirement Engine] Committing ${result.scenarios.length} scenarios to workspace ${workspaceId}...`);
    
    for (const sc of result.scenarios) {
      await prisma.scenario.create({
        data: {
          workspaceId,
          title: sc.title,
          steps: sc.steps,
          description: `AI Generated from Requirement: ${sc.type} path.`,
          riskScore: sc.type === 'edge' ? 80 : sc.type === 'negative' ? 60 : 40,
        },
      });
    }
  }
}
