import { NextRequest, NextResponse } from 'next/server';
import jsPDF from 'jspdf';
import html2canvas from 'html2canvas';

export const dynamic = 'force-dynamic';

interface TestResult {
  status: 'completed' | 'failed' | 'running';
  startTime: string;
  endTime: string;
  duration: number;
  totalScenarios: number;
  passedScenarios: number;
  failedScenarios: number;
  totalSteps: number;
  passedSteps: number;
  failedSteps: number;
}

interface TestLog {
  id: string;
  timestamp: string;
  level: 'info' | 'success' | 'error' | 'warning';
  message: string;
  step?: string;
  screenshot?: string;
}

interface ScenarioResult {
  id: string;
  title: string;
  status: 'passed' | 'failed';
  duration: number;
  steps: string[];
}

interface AIAnalysis {
  summary: string;
  keyFindings: string[];
  recommendations: string[];
  riskAssessment: {
    level: 'low' | 'medium' | 'high';
    issues: string[];
  };
  performanceMetrics: {
    averageStepTime: number;
    fastestStep: string;
    slowestStep: string;
    totalExecutionTime: number;
  };
}

interface PDFRequest {
  sessionId: string;
  testResult: TestResult;
  logs: TestLog[];
  scenarioResults: ScenarioResult[];
  aiAnalysis: AIAnalysis;
  url: string;
}

export async function POST(request: NextRequest) {
  try {
    const { sessionId, testResult, logs, scenarioResults, aiAnalysis, url }: PDFRequest = await request.json();

    if (!sessionId || !testResult) {
      return NextResponse.json({ 
        error: 'Session ID and test result are required' 
      }, { status: 400 });
    }

    // Generate PDF
    const pdfBuffer = await generatePDFReport({
      sessionId,
      testResult,
      logs,
      scenarioResults,
      aiAnalysis,
      url
    });

    // Return PDF as response
    return new NextResponse(pdfBuffer, {
      headers: {
        'Content-Type': 'application/pdf',
        'Content-Disposition': `attachment; filename="test-report-${sessionId}.pdf"`
      }
    });

  } catch (error) {
    console.error('PDF Generation Error:', error);
    return NextResponse.json(
      { 
        error: 'Failed to generate PDF report',
        details: error instanceof Error ? error.message : 'Unknown error'
      },
      { status: 500 }
    );
  }
}

async function generatePDFReport(data: {
  sessionId: string;
  testResult: TestResult;
  logs: TestLog[];
  scenarioResults: ScenarioResult[];
  aiAnalysis: AIAnalysis;
  url: string;
}): Promise<Buffer> {
  // Create PDF document
  const pdf = new jsPDF();
  const pageWidth = pdf.internal.pageSize.getWidth();
  const pageHeight = pdf.internal.pageSize.getHeight();
  let yPosition = 20;

  // Helper function to add a new page if needed
  const checkPageSpace = (neededSpace: number) => {
    if (yPosition + neededSpace > pageHeight - 20) {
      pdf.addPage();
      yPosition = 20;
    }
  };

  // Helper function to add text with word wrap
  const addText = (text: string, x: number, fontSize: number = 12, isBold: boolean = false) => {
    pdf.setFontSize(fontSize);
    if (isBold) {
      pdf.setFont('helvetica', 'bold');
    } else {
      pdf.setFont('helvetica', 'normal');
    }

    const lines = pdf.splitTextToSize(text, pageWidth - 40);
    lines.forEach((line: string) => {
      checkPageSpace(8);
      pdf.text(line, x, yPosition);
      yPosition += 6;
    });
  };

  // Title Page
  pdf.setFontSize(24);
  pdf.setFont('helvetica', 'bold');
  pdf.text('AI-Powered Test Execution Report', pageWidth / 2, yPosition, { align: 'center' });
  yPosition += 20;

  pdf.setFontSize(16);
  pdf.text(`Session ID: ${data.sessionId}`, pageWidth / 2, yPosition, { align: 'center' });
  yPosition += 15;

  pdf.setFontSize(12);
  pdf.setFont('helvetica', 'normal');
  pdf.text(`Generated: ${new Date(data.testResult.endTime).toLocaleString()}`, pageWidth / 2, yPosition, { align: 'center' });
  yPosition += 15;

  pdf.text(`Target URL: ${data.url}`, pageWidth / 2, yPosition, { align: 'center' });
  yPosition += 30;

  // Executive Summary
  checkPageSpace(80);
  addText('Executive Summary', 20, 18, true);
  yPosition += 10;

  const successRate = data.testResult.totalScenarios > 0 ? Math.round((data.testResult.passedScenarios / data.testResult.totalScenarios) * 100) : 0;
  addText(`Overall Status: ${data.testResult.status?.toUpperCase() || 'N/A'}`, 20, 14, true);
  addText(`Success Rate: ${successRate}%`, 20, 12);
  addText(`Total Scenarios: ${data.testResult.totalScenarios || 0}`, 20, 12);
  addText(`Passed: ${data.testResult.passedScenarios || 0}`, 20, 12);
  addText(`Failed: ${data.testResult.failedScenarios || 0}`, 20, 12);
  addText(`Duration: ${formatDuration(data.testResult.duration || 0)}`, 20, 12);
  addText(`Execution Time: ${formatTime(data.testResult.startTime)}`, 20, 12);

  yPosition += 20;

  // Test Results Overview
  checkPageSpace(60);
  addText('Test Results Overview', 20, 18, true);
  yPosition += 10;

  // Create a simple table for results
  const tableStartY = yPosition;
  const tableData = [
    ['Metric', 'Value'],
    ['Total Scenarios', data.testResult.totalScenarios.toString()],
    ['Passed Scenarios', data.testResult.passedScenarios.toString()],
    ['Failed Scenarios', data.testResult.failedScenarios.toString()],
    ['Total Steps', data.testResult.totalSteps.toString()],
    ['Passed Steps', data.testResult.passedSteps.toString()],
    ['Failed Steps', data.testResult.failedSteps.toString()],
    ['Success Rate', `${successRate}%`],
    ['Duration', formatDuration(data.testResult.duration)]
  ];

  // Draw table
  const tableColWidth = [60, 40];
  const tableRowHeight = 8;
  const tableWidth = 100;

  tableData.forEach((row, rowIndex) => {
    checkPageSpace(tableRowHeight);
    
    // Draw row background for header
    if (rowIndex === 0) {
      pdf.setFillColor(240, 240, 240);
      pdf.rect(20, yPosition, tableWidth, tableRowHeight, 'F');
    }
    
    // Draw row content
    row.forEach((cell, colIndex) => {
      pdf.setFontSize(10);
      if (rowIndex === 0) {
        pdf.setFont('helvetica', 'bold');
      } else {
        pdf.setFont('helvetica', 'normal');
      }
      pdf.text(cell, 25 + colIndex * tableColWidth[1], yPosition + 5);
    });
    
    yPosition += tableRowHeight;
  });

  yPosition += 20;

  // Scenario Details
  checkPageSpace(40);
  addText('Scenario Details', 20, 18, true);
  yPosition += 10;

  data.scenarioResults.forEach((scenario, index) => {
    checkPageSpace(40);
    
    addText(`${index + 1}. ${scenario.title}`, 20, 14, true);
    addText(`Status: ${scenario.status?.toUpperCase() || 'N/A'}`, 25, 12);
    addText(`Duration: ${formatDuration(scenario.duration || 0)}`, 25, 12);
    addText(`Steps: ${scenario.steps.length || 0}`, 25, 12);
    
    yPosition += 10;
    
    // Add step details
    scenario.steps.forEach((step, stepIndex) => {
      checkPageSpace(20);
      addText(`Step ${stepIndex + 1}: ${step}`, 30, 10);
      yPosition += 5;
    });
    
    yPosition += 15;
  });

  // AI Analysis
  if (data.aiAnalysis) {
    checkPageSpace(40);
    addText('AI Analysis', 20, 18, true);
    yPosition += 10;

    addText('Summary:', 20, 14, true);
    addText(data.aiAnalysis.summary, 20, 10);
    yPosition += 15;

    addText('Key Findings:', 20, 14, true);
    data.aiAnalysis.keyFindings.forEach((finding, index) => {
      checkPageSpace(15);
      addText(`• ${finding}`, 25, 10);
    });
    yPosition += 15;

    addText('Recommendations:', 20, 14, true);
    data.aiAnalysis.recommendations.forEach((recommendation, index) => {
      checkPageSpace(15);
      addText(`• ${recommendation}`, 25, 10);
    });
    yPosition += 15;

    if (data.aiAnalysis.riskAssessment) {
      addText('Risk Assessment:', 20, 14, true);
      addText(`Risk Level: ${data.aiAnalysis.riskAssessment.level.toUpperCase()}`, 25, 12);
      data.aiAnalysis.riskAssessment.issues.forEach((issue, index) => {
        checkPageSpace(15);
        addText(`• ${issue}`, 25, 10);
      });
    }
  }

  // Execution Logs (Summary)
  checkPageSpace(40);
  addText('Execution Logs Summary', 20, 18, true);
  yPosition += 10;

  const logSummary = {
    info: data.logs.filter(log => log.level === 'info').length,
    success: data.logs.filter(log => log.level === 'success').length,
    warning: data.logs.filter(log => log.level === 'warning').length,
    error: data.logs.filter(log => log.level === 'error').length
  };

  addText(`Info Messages: ${logSummary.info}`, 20, 12);
  addText(`Success Messages: ${logSummary.success}`, 20, 12);
  addText(`Warning Messages: ${logSummary.warning}`, 20, 12);
  addText(`Error Messages: ${logSummary.error}`, 20, 12);

  // Add recent error logs
  const errorLogs = data.logs.filter(log => log.level === 'error').slice(0, 5);
  if (errorLogs.length > 0) {
    yPosition += 15;
    addText('Recent Errors:', 20, 14, true);
    errorLogs.forEach((log, index) => {
      checkPageSpace(20);
      addText(`• ${log.message}`, 25, 10);
    });
  }

  // Footer
  const pageCount = pdf.internal.getNumberOfPages();
  for (let i = 1; i <= pageCount; i++) {
    pdf.setPage(i);
    pdf.setFontSize(8);
    pdf.setFont('helvetica', 'normal');
    pdf.text(
      `AI-Powered Test Runner - Page ${i} of ${pageCount}`,
      pageWidth / 2,
      pageHeight - 10,
      { align: 'center' }
    );
  }

  // Return PDF as buffer
  const arrayBuffer = pdf.output('arraybuffer');
  return Buffer.from(arrayBuffer);
}

// Helper functions
function formatDuration(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  
  if (hours > 0) {
    return `${hours}h ${minutes % 60}m ${seconds % 60}s`;
  } else if (minutes > 0) {
    return `${minutes}m ${seconds % 60}s`;
  } else {
    return `${seconds}s`;
  }
}

function formatTime(dateString: string): string {
  return new Date(dateString).toLocaleString();
}