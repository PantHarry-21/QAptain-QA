/**
 * @fileoverview
 * This file defines the AI service for QAptain.
 * NOTE: The filename is a misnomer. This service uses the standard OpenAI API, not the Azure OpenAI API.
 * The class has been renamed to OpenAIService to reflect this.
 */

import OpenAI from 'openai';
import { TestLog } from './supabase';
import { prompts } from './prompts';

// --- Configuration ---

const apiKey = process.env.OPENAI_API_KEY;
const modelName = process.env.OPENAI_MODEL_NAME || 'gpt-4-turbo';

if (!apiKey) {
  throw new Error('Missing OPENAI_API_KEY environment variable');
}

const client = new OpenAI({ apiKey });

// --- Type Definitions ---

interface AICompletionConfig {
  temperature?: number;
  maxTokens?: number;
  topP?: number;
}

// Interfaces for method arguments
interface PageContext {
  visibleButtons?: string[];
  visibleLinks?: string[];
  formInputs?: { label?: string; name?: string; placeholder?: string }[];
}

interface Scenario {
  title: string;
  description: string;
  status: 'passed' | 'failed';
  duration: number;
  steps: string[];
}

interface TestResults {
  status: string;
  totalScenarios: number;
  passedScenarios: number;
  failedScenarios: number;
}

// Interfaces for method return types
interface WebPageAnalysis {
  summary: string;
  keyElements: string[];
  suggestedTests: string[];
  complexity: 'simple' | 'medium' | 'complex';
}

interface WorkflowPlan {
  plan: {
    skill: 'CLICK' | 'NAVIGATE' | 'FILL_FORM_HAPPY_PATH' | 'TEST_FORM_VALIDATION';
    target?: string;
    url?: string;
  }[];
}

interface ScenarioAnalysis {
  summary: string;
  issues: string[];
  recommendations: string[];
}

interface InterpretedScenario {
  steps: string[];
}

interface TestAnalysis {
  summary: string;
  keyFindings: string[];
  recommendations: string[];
  riskAssessment: {
    level: 'low' | 'medium' | 'high';
    issues: string[];
  };
  qualityScore: number;
}

// --- Service Class ---

export class OpenAIService {
  private readonly defaultConfig: AICompletionConfig = {
    temperature: 0.7,
    maxTokens: 2000,
    topP: 0.9,
  };

  /**
   * A private helper to generate a JSON completion from a prompt.
   * @param prompt The user prompt for the AI.
   * @param config Optional configuration for the completion.
   * @returns A promise that resolves to the parsed JSON object.
   */
  private async _generateAndParseJSON<T>(
    prompt: string,
    config: Partial<AICompletionConfig> = {}
  ): Promise<T> {
    const finalConfig = { ...this.defaultConfig, ...config };

    try {
      const completion = await client.chat.completions.create({
        model: modelName,
        messages: [
          { role: 'system', content: 'You are a helpful AI assistant designed to output JSON.' },
          { role: 'user', content: prompt },
        ],
        response_format: { type: 'json_object' },
        max_tokens: finalConfig.maxTokens,
        temperature: finalConfig.temperature,
        top_p: finalConfig.topP,
      });

      const content = completion.choices[0]?.message?.content;
      if (!content) {
        throw new Error('AI returned an empty response.');
      }

      return JSON.parse(content) as T;
    } catch (error) {
      console.error('OpenAI API or JSON parsing error:', error);
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      throw new Error(`Failed to generate or parse AI completion: ${errorMessage}`);
    }
  }

  /**
   * Interprets a user's natural language story into executable steps.
   * @param userStory The natural language description of the test.
   * @param pageContext The context of the current web page.
   * @returns A promise that resolves to an object containing the steps.
   */
  async interpretScenario(userStory: string, pageContext: PageContext): Promise<InterpretedScenario> {
    const prompt = prompts.interpretScenario(userStory, pageContext);
    return this._generateAndParseJSON<InterpretedScenario>(prompt, { maxTokens: 2000 });
  }

  /**
   * Creates a high-level workflow plan from a user command.
   * @param userCommand The high-level command from the user.
   * @param context The context of the current web page.
   * @returns A promise that resolves to the generated plan.
   */
  async createWorkflowPlan(userCommand: string, context: PageContext): Promise<WorkflowPlan> {
    const prompt = prompts.createWorkflowPlan(userCommand, context);
    return this._generateAndParseJSON<WorkflowPlan>(prompt, { maxTokens: 1000 });
  }

  /**
   * Generates Faker.js mappings for a given form.
   * @param formInputs The array of input fields from the form.
   * @returns A promise that resolves to a JSON object mapping field names to Faker methods.
   */
  async generateFakerMappings(formInputs: any[]): Promise<any> {
    const prompt = prompts.generateFakerMappings(formInputs);
    return this._generateAndParseJSON<any>(prompt, { temperature: 0.2, maxTokens: 2000 });
  }

  /**
   * Analyzes a single executed test scenario and its logs.
   * @param scenario The scenario that was executed.
   * @param logs The logs generated during the scenario execution.
   * @returns A promise that resolves to the AI's analysis.
   */
  async analyzeScenario(scenario: Scenario, logs: TestLog[]): Promise<ScenarioAnalysis> {
    const prompt = prompts.analyzeScenario(scenario, logs);
    return this._generateAndParseJSON<ScenarioAnalysis>(prompt, { maxTokens: 1500 });
  }

  /**
   * Generates a final analysis report for a full test session.
   * @param testResults The final results of the test session.
   * @returns A promise that resolves to the final analysis report.
   */
  async generateTestAnalysis(testResults: TestResults): Promise<TestAnalysis> {
    const prompt = prompts.generateTestAnalysis(testResults);
    return this._generateAndParseJSON<TestAnalysis>(prompt, { maxTokens: 3000 });
  }

  /**
   * Generates a list of test scenarios based on page context.
   * @param pageContext The context of the current web page.
   * @returns A promise that resolves to an object containing the generated scenarios.
   */
  async generateScenarios(pageContext: PageContext): Promise<{ scenarios: { title: string; description: string; steps: string[] }[] }> {
    const prompt = prompts.generateScenarios(pageContext);
    return this._generateAndParseJSON<{ scenarios: { title: string; description: string; steps: string[] }[] }>(prompt, { maxTokens: 4000 });
  }
  
  /**
   * Analyzes the structure of a web page.
   * @param pageInfo Information about the page (title, URL).
   * @returns A promise that resolves to the AI's analysis of the page.
   */
  async analyzeWebPage(pageInfo: { title: string; url: string }): Promise<WebPageAnalysis> {
    const prompt = prompts.analyzeWebPage(pageInfo);
    return this._generateAndParseJSON<WebPageAnalysis>(prompt);
  }
}

export const azureAIService = new OpenAIService();
