
import { NextRequest, NextResponse } from 'next/server';
import { chromium as playwrightCore, Browser } from 'playwright-core';
import chromium from '@sparticuz/chromium';
import { supabase } from '@/lib/supabase';
import { azureAIService } from '@/lib/azure-ai';
import { TestSession } from '@/lib/supabase';

export async function POST(request: NextRequest) {
  let browser: Browser | null = null;
  try {
    const { url } = await request.json();

    if (!url) {
      return NextResponse.json({ error: 'URL is required' }, { status: 400 });
    }

    // Validate URL format
    try {
      new URL(url);
    } catch {
      return NextResponse.json({ error: 'Invalid URL format' }, { status: 400 });
    }

    // Launch browser
    browser = await playwrightCore.launch({
      args: chromium.args,
      executablePath: await chromium.executablePath(),
      headless: chromium.headless,
    });

    const context = await browser.newContext({
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36'
    });
    const page = await context.newPage();
    
    // Set viewport and user agent
    await page.setViewportSize({ width: 1920, height: 1080 });

    // Navigate to URL with timeout
    await page.goto(url, { 
      waitUntil: 'load',
      timeout: 30000 
    });

    // Extract page information
    const pageInfo = await page.evaluate(() => {
      const title = document.title;
      const metaDescription = document.querySelector('meta[name="description"]')?.getAttribute('content') || '';
      const metaKeywords = document.querySelector('meta[name="keywords"]')?.getAttribute('content') || '';
      
      // Extract forms
      const forms = Array.from(document.querySelectorAll('form')).map((form, index) => {
        const inputs = Array.from(form.querySelectorAll('input, textarea, select')).map(input => ({
          type: input.getAttribute('type') || 'text',
          name: input.getAttribute('name') || input.getAttribute('id') || `input_${index}`,
          placeholder: input.getAttribute('placeholder') || '',
          required: input.hasAttribute('required')
        }));

        const submitButton = form.querySelector('button[type="submit"], input[type="submit"]');
        
        return {
          id: `form_${index}`,
          action: form.getAttribute('action') || '',
          method: form.getAttribute('method') || 'GET',
          inputs,
          hasSubmitButton: !!submitButton,
          submitButtonText: submitButton?.textContent || 'Submit'
        };
      });

      // Extract navigation links
      const navLinks = Array.from(document.querySelectorAll('nav a, header a, .navigation a')).map((link, index) => ({
        id: `nav_link_${index}`,
        text: link.textContent?.trim() || '',
        href: link.getAttribute('href') || '',
        isExternal: link.getAttribute('target') === '_blank'
      })).filter(link => link.text && link.href);

      // Extract buttons
      const buttons = Array.from(document.querySelectorAll('button')).map((button, index) => ({
        id: `button_${index}`,
        text: button.textContent?.trim() || '',
        type: button.getAttribute('type') || 'button',
        isDisabled: button.hasAttribute('disabled')
      })).filter(button => button.text);

      // Extract links
      const links = Array.from(document.querySelectorAll('a[href]')).map((link, index) => ({
        id: `link_${index}`,
        text: link.textContent?.trim() || '',
        href: link.getAttribute('href') || '',
        isExternal: link.getAttribute('target') === '_blank'
      })).filter(link => link.text && link.href);

      // Extract images
      const images = Array.from(document.querySelectorAll('img')).map((img, index) => ({
        id: `img_${index}`,
        src: img.getAttribute('src') || '',
        alt: img.getAttribute('alt') || '',
        width: (img as HTMLImageElement).naturalWidth,
        height: (img as HTMLImageElement).naturalHeight
      })).filter(img => img.src);

      // Extract headings
      const headings = Array.from(document.querySelectorAll('h1, h2, h3, h4, h5, h6')).map((heading, index) => ({
        id: `heading_${index}`,
        level: heading.tagName.toLowerCase(),
        text: heading.textContent?.trim() || ''
      })).filter(heading => heading.text);

      return {
        title,
        metaDescription,
        metaKeywords,
        url: window.location.href,
        domain: window.location.hostname,
        forms,
        navLinks,
        buttons,
        links,
        images,
        headings,
        hasLoginForm: forms.some(form => 
          form.inputs.some(input => 
            input.type === 'email' || input.type === 'password' || 
            input.name.toLowerCase().includes('user') || 
            input.name.toLowerCase().includes('login') ||
            input.name.toLowerCase().includes('pass')
          )
        ),
        hasContactForm: forms.some(form => 
          form.inputs.some(input => 
            input.type === 'email' || input.type === 'tel' || 
            input.name.toLowerCase().includes('email') || 
            input.name.toLowerCase().includes('phone') ||
            input.name.toLowerCase().includes('message') ||
            input.name.toLowerCase().includes('contact')
          )
        ),
        hasSearchForm: forms.some(form => 
          form.inputs.some(input => 
            input.type === 'search' || 
            input.name.toLowerCase().includes('search') || 
            input.placeholder.toLowerCase().includes('search')
          )
        )
      };
    });

    // Take screenshot
    const screenshot = await page.screenshot({ 
      type: 'jpeg', 
      quality: 80,
      fullPage: false 
    });

    // Convert screenshot to base64
    const screenshotBase64 = `data:image/jpeg;base64,${screenshot.toString('base64')}`;

    // Enhanced AI Analysis
    let aiAnalysis;
    try {
      aiAnalysis = await azureAIService.analyzeWebPage(pageInfo);
    } catch (aiError) {
      console.error('AI Analysis failed:', aiError);
      aiAnalysis = {
        summary: 'AI analysis unavailable',
        keyElements: [],
        suggestedTests: [],
        complexity: 'medium' as const
      };
    }

    // Create test session in Supabase
    const sessionData: Partial<TestSession> = {
      url,
      status: 'pending',
      total_scenarios: 0,
      passed_scenarios: 0,
      failed_scenarios: 0,
      total_steps: 0,
      passed_steps: 0,
      failed_steps: 0,
      page_analysis: pageInfo,
      ai_analysis: aiAnalysis
    };

    const { data: session, error: sessionError } = await supabase
      .from('test_sessions')
      .insert([sessionData])
      .select()
      .single();

    if (sessionError) {
      console.error('Failed to create test session:', sessionError);
    }

    return NextResponse.json({
      success: true,
      data: {
        pageInfo,
        screenshot: screenshotBase64,
        aiAnalysis,
        sessionId: session?.id,
        analyzedAt: new Date().toISOString()
      }
    });

  } catch (error) {
    console.error('URL Analysis Error:', error);
    return NextResponse.json(
      { 
        error: 'Failed to analyze URL',
        details: error instanceof Error ? error.message : 'Unknown error'
      },
      { status: 500 }
    );
  } finally {
    if (browser) {
      await browser.close();
    }
  }
}
