import { openAIService } from '@/lib/openai';
import { prompts } from '@/lib/prompts';
import { prisma } from '@/lib/prisma';
import type { Page } from 'playwright';

export interface RcaResult {
  category: 'Bug' | 'Script' | 'Environment' | 'Flaky';
  summary: string;
  rootCause: string;
  impact: string;
  remediation: string;
  isHealable: boolean;
  confidence: number;
}

export class RcaEngine {
  /**
   * Performs an AI-driven Root Cause Analysis for a failed execution step.
   */
  static async analyzeFailure(
    page: Page,
    step: any,
    error: string,
    executionMode: string,
    runId: string,
    screenshotBase64?: string
  ): Promise<RcaResult> {
    console.log(`[RCA Engine] Analyzing failure for run ${runId}...`);

    // 1. Capture DOM Snapshot (lightweight)
    const domSummary = await page.evaluate(() => {
      const visible = Array.from(document.querySelectorAll('button, a, input, [role="button"], h1, h2, .error, .message, [aria-label]'))
        .filter(el => {
          const style = window.getComputedStyle(el);
          return style.display !== 'none' && style.visibility !== 'hidden' && el.getBoundingClientRect().width > 0;
        })
        .slice(0, 60)
        .map(el => {
          return {
            tag: el.tagName,
            text: (el.textContent || '').trim().slice(0, 80),
            placeholder: (el as HTMLInputElement).placeholder || undefined,
            id: el.id || undefined,
            disabled: (el as HTMLButtonElement).disabled || undefined,
            ariaLabel: (el as HTMLElement).ariaLabel || undefined,
          };
        });

      return JSON.stringify(visible, null, 2);
    });

    // 2. Prepare Prompt
    const prompt = prompts.analyzeRootCause({
      step,
      error,
      domSummary,
      consoleLogs: [], // TODO: Integrate with console log collector
      networkFailures: [], // TODO: Integrate with network collector
      executionMode,
    });

    try {
      let rca: RcaResult;

      // 3. Perform Analysis (Vision if screenshot is available, otherwise Text)
      if (screenshotBase64) {
        console.log('[RCA Engine] Performing Vision-based analysis...');
        rca = await openAIService.analyzeImage<RcaResult>(prompt, screenshotBase64);
      } else {
        console.log('[RCA Engine] Performing Text-based analysis...');
        rca = await openAIService['_generateAndParseJSON']<RcaResult>(prompt, {
          temperature: 0.1,
          maxTokens: 1000,
        });
      }

      // 4. Persist analysis to the execution step
      await prisma.executionStep.updateMany({
        where: { runId, action: step.action, status: 'failed' },
        data: {
          rcaAnalysis: rca as any,
          screenshotPath: screenshotBase64 ? 'embedded' : undefined, // Placeholder
        },
      });

      return rca;
    } catch (e) {
      console.error('[RCA Engine] AI Analysis failed:', e);
      return {
        category: 'Flaky',
        summary: 'Failed to perform AI RCA',
        rootCause: 'AI Service Error: ' + (e instanceof Error ? e.message : String(e)),
        impact: 'Unknown',
        remediation: 'Check logs and retry',
        isHealable: false,
        confidence: 0,
      };
    }
  }
}
