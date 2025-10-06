import { NextRequest, NextResponse } from 'next/server';
import { supabase } from '@/lib/supabase';
import { azureAIService } from '@/lib/azure-ai';
import { TestScenario, TestSession } from '@/lib/supabase';

interface PageInfo {
  title: string;
  metaDescription: string;
  metaKeywords: string;
  url: string;
  domain: string;
  forms: any[];
  navLinks: any[];
  buttons: any[];
  links: any[];
  images: any[];
  headings: any[];
  hasLoginForm: boolean;
  hasContactForm: boolean;
  hasSearchForm: boolean;
}

export async function POST(request: NextRequest) {
  try {
    const { pageInfo, sessionId, existingScenarios = [] } = await request.json();

    if (!pageInfo || !sessionId) {
      return NextResponse.json({ error: 'Page information and session ID are required' }, { status: 400 });
    }

    // First, create the parent test session record
    const { error: sessionError } = await supabase
      .from('test_sessions')
      .insert({
        id: sessionId,
        url: pageInfo.url,
        status: 'pending',
        created_at: new Date().toISOString(),
      });

    if (sessionError) {
      console.error('Failed to create test session:', sessionError);
      throw new Error('Could not create the parent test session.');
    }

    // Generate enhanced test scenarios using Azure AI
    let aiScenarios;
    try {
      aiScenarios = await azureAIService.generateTestScenarios(pageInfo, existingScenarios);
    } catch (aiError) {
      console.error('AI scenario generation failed:', aiError);
      aiScenarios = generateBasicTestScenarios(pageInfo);
    }

    // Convert AI scenarios to database format
    const scenariosToInsert: Partial<TestScenario>[] = aiScenarios.map((scenario, index) => ({
      session_id: sessionId,
      title: scenario.title,
      description: scenario.description,
      priority: scenario.priority,
      category: scenario.category,
      steps: scenario.steps,
      estimated_time: scenario.estimatedTime,
      status: 'pending' as const,
      is_custom: false
    }));

    // Save scenarios to Supabase
    const { data: savedScenarios, error: scenariosError } = await supabase
      .from('test_scenarios')
      .insert(scenariosToInsert)
      .select();

    if (scenariosError) {
      console.error('Failed to save scenarios:', scenariosError);
      // Even if saving scenarios fails, we proceed to avoid blocking the user
    }

    // Update session with scenario count
    await supabase
      .from('test_sessions')
      .update({ 
        total_scenarios: scenariosToInsert.length,
        updated_at: new Date().toISOString()
      })
      .eq('id', sessionId);

    // Format response for frontend
    const formattedScenarios = aiScenarios.map((scenario, index) => ({
      id: savedScenarios?.[index]?.id || `scenario_${index}`,
      title: scenario.title,
      description: scenario.description,
      priority: scenario.priority,
      category: scenario.category,
      steps: scenario.steps,
      estimatedTime: scenario.estimatedTime,
      reasoning: scenario.reasoning
    }));

    return NextResponse.json({
      success: true,
      data: {
        scenarios: formattedScenarios,
        sessionId,
        generatedAt: new Date().toISOString()
      }
    });

  } catch (error) {
    console.error('Scenario Generation Error:', error);
    return NextResponse.json(
      { 
        error: 'Failed to generate test scenarios',
        details: error instanceof Error ? error.message : 'Unknown error'
      },
      { status: 500 }
    );
  }
}

// Fallback basic scenario generation if AI fails
function generateBasicTestScenarios(pageInfo: PageInfo) {
  const scenarios = [];
  
  // Basic page load test
  scenarios.push({
    id: 'scenario_1',
    title: 'Verify homepage loads successfully',
    description: 'Check if the homepage loads correctly and displays the main content',
    priority: 'high',
    category: 'basic',
    steps: [
      'Navigate to the homepage',
      'Verify page title is displayed',
      'Check if main content is visible',
      'Verify page loads without errors'
    ],
    estimatedTime: '30 seconds'
  });

  // Navigation tests
  if (pageInfo.navLinks.length > 0) {
    scenarios.push({
      id: 'scenario_2',
      title: 'Check navigation links functionality',
      description: 'Test all navigation links to ensure they work correctly',
      priority: 'high',
      category: 'navigation',
      steps: [
        'Click on each navigation link',
        'Verify each link navigates to the correct page',
        'Check if browser URL updates correctly',
        'Verify page content matches the navigation item'
      ],
      estimatedTime: '2 minutes'
    });
  }

  // Form interaction tests
  if (pageInfo.forms.length > 0) {
    pageInfo.forms.forEach((form, index) => {
      const isLogin = pageInfo.hasLoginForm && (
        form.inputs.some((input: any) => 
          input.type === 'email' || input.type === 'password' || 
          input.name.toLowerCase().includes('user') || 
          input.name.toLowerCase().includes('login') ||
          input.name.toLowerCase().includes('pass')
        )
      );

      const isContact = pageInfo.hasContactForm && (
        form.inputs.some((input: any) => 
          input.type === 'email' || input.type === 'tel' || 
          input.name.toLowerCase().includes('email') || 
          input.name.toLowerCase().includes('phone') ||
          input.name.toLowerCase().includes('message') ||
          input.name.toLowerCase().includes('contact')
        )
      );

      const isSearch = pageInfo.hasSearchForm && (
        form.inputs.some((input: any) => 
          input.type === 'search' || 
          input.name.toLowerCase().includes('search') || 
          input.placeholder.toLowerCase().includes('search')
        )
      );

      if (isLogin) {
        scenarios.push({
          id: `scenario_${3 + index}`,
          title: 'Test login form functionality',
          description: 'Verify the login form works correctly with valid and invalid inputs',
          priority: 'high',
          category: 'authentication',
          steps: [
            'Enter valid username/email',
            'Enter valid password',
            'Click login button',
            'Verify successful login or appropriate error message'
          ],
          estimatedTime: '1 minute'
        });
      } else if (isContact) {
        scenarios.push({
          id: `scenario_${3 + index}`,
          title: 'Test contact form submission',
          description: 'Verify the contact form accepts input and submits successfully',
          priority: 'medium',
          category: 'forms',
          steps: [
            'Fill in contact form fields',
            'Enter valid email address',
            'Add message content',
            'Submit form and verify success message'
          ],
          estimatedTime: '1.5 minutes'
        });
      } else if (isSearch) {
        scenarios.push({
          id: `scenario_${3 + index}`,
          title: 'Test search functionality',
          description: 'Verify the search form returns relevant results',
          priority: 'medium',
          category: 'search',
          steps: [
            'Enter search query in search field',
            'Submit search form',
            'Verify search results are displayed',
            'Check if results are relevant to search query'
          ],
          estimatedTime: '1 minute'
        });
      } else {
        scenarios.push({
          id: `scenario_${3 + index}`,
          title: `Test form ${index + 1} functionality`,
          description: `Verify the form accepts input and processes correctly`,
          priority: 'medium',
          category: 'forms',
          steps: [
            'Fill in all required form fields',
            'Enter valid test data',
            'Submit form',
            'Verify form submission is successful'
          ],
          estimatedTime: '1 minute'
        });
      }
    });
  }

  // Button interaction tests
  if (pageInfo.buttons.length > 0) {
    scenarios.push({
      id: `scenario_${3 + pageInfo.forms.length + 1}`,
      title: 'Test button interactions',
      description: 'Verify all clickable buttons work as expected',
      priority: 'medium',
      category: 'interaction',
      steps: [
        'Click each button on the page',
        'Verify button actions trigger correctly',
        'Check for any visual feedback',
        'Verify no JavaScript errors occur'
      ],
      estimatedTime: '2 minutes'
    });
  }

  // Link validation tests
  if (pageInfo.links.length > 0) {
    scenarios.push({
      id: `scenario_${3 + pageInfo.forms.length + 2}`,
      title: 'Verify all links are working',
      description: 'Check if all links on the page are valid and accessible',
      priority: 'medium',
      category: 'links',
      steps: [
        'Click on each link',
        'Verify link destination loads',
        'Check for broken links (404 errors)',
        'Verify external links open in new tabs if required'
      ],
      estimatedTime: '3 minutes'
    });
  }

  // Image loading tests
  if (pageInfo.images.length > 0) {
    scenarios.push({
      id: `scenario_${3 + pageInfo.forms.length + 3}`,
      title: 'Verify images load correctly',
      description: 'Check if all images on the page load without errors',
      priority: 'low',
      category: 'media',
      steps: [
        'Check each image loads successfully',
        'Verify image alt text is present',
        'Check image dimensions are appropriate',
        'Verify no broken image icons appear'
      ],
      estimatedTime: '1 minute'
    });
  }

  // Responsive design tests
  scenarios.push({
    id: `scenario_${3 + pageInfo.forms.length + 4}`,
    title: 'Test responsive design',
    description: 'Verify the page displays correctly on different screen sizes',
    priority: 'medium',
    category: 'responsive',
    steps: [
      'Test page on desktop viewport (1920x1080)',
      'Test page on tablet viewport (768x1024)',
      'Test page on mobile viewport (375x667)',
      'Verify layout adapts correctly to each size'
    ],
    estimatedTime: '2 minutes'
  });

  // Performance test
  scenarios.push({
    id: `scenario_${3 + pageInfo.forms.length + 5}`,
    title: 'Check page performance',
    description: 'Verify the page loads within acceptable time limits',
    priority: 'medium',
    category: 'performance',
    steps: [
      'Measure page load time',
      'Check time to first byte (TTFB)',
      'Verify DOM content loaded time',
      'Check if page is interactive within 3 seconds'
    ],
    estimatedTime: '30 seconds'
  });

  // SEO verification
  if (pageInfo.metaDescription || pageInfo.metaKeywords) {
    scenarios.push({
      id: `scenario_${3 + pageInfo.forms.length + 6}`,
      title: 'Verify SEO elements',
      description: 'Check if SEO meta tags and elements are properly implemented',
      priority: 'low',
      category: 'seo',
      steps: [
        'Verify page title is present and descriptive',
        'Check meta description exists',
        'Verify proper heading structure (H1, H2, etc.)',
        'Check if images have alt attributes'
      ],
      estimatedTime: '30 seconds'
    });
  }

  return scenarios.slice(0, 10); // Limit to 10 scenarios max
}