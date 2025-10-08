import { TestSession, TestScenario, TestLog, TestReport } from './supabase'; // Assuming these types are available
import jsPDF from 'jspdf';
import html2canvas from 'html2canvas'; // html2canvas is not actually used in generatePDFReport, but it's imported in the original file. I'll keep it for now.

interface ScenarioResult {
  id: string;
  title: string;
  status: 'passed' | 'failed';
  duration: number;
  steps: string[];
}

interface PDFRequest {
  sessionId: string;
  testResult: {
    status: string;
    startTime: string;
    endTime: string;
    duration: number;
    totalScenarios: number;
    passedScenarios: number;
    failedScenarios: number;
    totalSteps: number;
    passedSteps: number;
    failedSteps: number;
  };
  logs: TestLog[];
  scenarioResults: ScenarioResult[];
  aiAnalysis: TestReport | null; // Assuming TestReport is the correct type for aiAnalysis
  url: string;
}

// Helper functions (copied from results page)
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

export async function generatePDFReportClient({
  sessionId,
  testResult,
  logs,
  scenarioResults,
  aiAnalysis,
  url,
}: PDFRequest): Promise<void> {
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
  pdf.text(`Session ID: ${sessionId}`, pageWidth / 2, yPosition, { align: 'center' });
  yPosition += 15;

  pdf.setFontSize(12);
  pdf.setFont('helvetica', 'normal');
  pdf.text(`Generated: ${formatTime(testResult.endTime)}`, pageWidth / 2, yPosition, { align: 'center' });
  yPosition += 15;

  pdf.text(`Target URL: ${url}`, pageWidth / 2, yPosition, { align: 'center' });
  yPosition += 30;

  // Executive Summary
  checkPageSpace(80);
  addText('Executive Summary', 20, 18, true);
  yPosition += 10;

  const successRate = testResult.totalScenarios > 0 ? Math.round((testResult.passedScenarios / testResult.totalScenarios) * 100) : 0;
  addText(`Overall Status: ${testResult.status?.toUpperCase() || 'N/A'}`, 20, 14, true);
  addText(`Success Rate: ${successRate}%`, 20, 12);
  addText(`Total Scenarios: ${testResult.totalScenarios || 0}`, 20, 12);
  addText(`Passed: ${testResult.passedScenarios || 0}`, 20, 12);
  addText(`Failed: ${testResult.failedScenarios || 0}`, 20, 12);
  addText(`Duration: ${formatDuration(testResult.duration || 0)}`, 20, 12);
  addText(`Execution Time: ${formatTime(testResult.startTime)}`, 20, 12);

  yPosition += 20;

  // Test Results Overview
  checkPageSpace(60);
  addText('Test Results Overview', 20, 18, true);
  yPosition += 10;

  // Create a simple table for results
  const tableData = [
    ['Metric', 'Value'],
    ['Total Scenarios', testResult.totalScenarios.toString()],
    ['Passed Scenarios', testResult.passedScenarios.toString()],
    ['Failed Scenarios', testResult.failedScenarios.toString()],
    ['Total Steps', testResult.totalSteps.toString()],
    ['Passed Steps', testResult.passedSteps.toString()],
    ['Failed Steps', testResult.failedSteps.toString()],
    ['Success Rate', `${successRate}%`],
    ['Duration', formatDuration(testResult.duration)]
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
    row.forEach((cell: string, colIndex: number) => {
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

  scenarioResults.forEach((scenario, index) => {
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
  if (aiAnalysis) {
    checkPageSpace(40);
    addText('AI Analysis', 20, 18, true);
    yPosition += 10;

    addText('Summary:', 20, 14, true);
    addText(aiAnalysis.summary, 20, 10);
    yPosition += 15;

    addText('Key Findings:', 20, 14, true);
    aiAnalysis.key_findings.forEach((finding, index) => {
      checkPageSpace(15);
      addText(`• ${finding}`, 25, 10);
    });
    yPosition += 15;

    addText('Recommendations:', 20, 14, true);
    aiAnalysis.recommendations.forEach((recommendation, index) => {
      checkPageSpace(15);
      addText(`• ${recommendation}`, 25, 10);
    });
    yPosition += 15;

    if (aiAnalysis.risk_level) {
      addText('Risk Assessment:', 20, 14, true);
      addText(`Risk Level: ${aiAnalysis.risk_level.toUpperCase()}`, 25, 12);
      if (aiAnalysis.risk_assessment_issues && aiAnalysis.risk_assessment_issues.length > 0) {
        aiAnalysis.risk_assessment_issues.forEach((issue, index) => {
          checkPageSpace(15);
          addText(`• ${issue}`, 25, 10);
        });
      }
    }
  }

  // Execution Logs (Summary)
  checkPageSpace(40);
  addText('Execution Logs Summary', 20, 18, true);
  yPosition += 10;

  const logSummary = {
    info: logs.filter(log => log.level === 'info').length,
    success: logs.filter(log => log.level === 'success').length,
    warning: logs.filter(log => log.level === 'warning').length,
    error: logs.filter(log => log.level === 'error').length
  };

  addText(`Info Messages: ${logSummary.info}`, 20, 12);
  addText(`Success Messages: ${logSummary.success}`, 20, 12);
  addText(`Warning Messages: ${logSummary.warning}`, 20, 12);
  addText(`Error Messages: ${logSummary.error}`, 20, 12);

  // Add recent error logs
  const errorLogs = logs.filter(log => log.level === 'error').slice(0, 5);
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

  // Save the PDF directly, letting jsPDF handle the download
  pdf.save(`test-report-${sessionId}.pdf`);
}
