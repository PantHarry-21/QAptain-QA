/** Lightweight page / workflow classification from URL + title (no deep DOM). */
export function classifyPageType(pathname: string, title: string): {
  pageType: string;
  workflowHints: string[];
  formClassification: string;
} {
  const p = pathname.toLowerCase();
  const t = title.toLowerCase();
  const blob = `${p} ${t}`;
  let pageType = 'generic';
  const workflowHints: string[] = [];
  let formClassification = 'unknown';

  if (/\/(dash|home|overview)\b/i.test(p) || /\bdashboard\b/.test(blob)) {
    pageType = 'dashboard';
    formClassification = 'filters_optional';
  } else if (/\breport|analytics|export\b/i.test(blob)) {
    pageType = 'reports';
    formClassification = 'filters_date_range';
  } else if (/\bconfig|setting|preference|admin\b/i.test(blob)) {
    pageType = 'configuration';
    formClassification = 'settings_form';
  } else if (/\bapprov|workflow|pending\b/i.test(blob)) {
    pageType = 'approval_workflow';
    workflowHints.push('multi_step_review');
    formClassification = 'action_form';
  } else if (/\bwizard|step\s*\d|onboarding\b/i.test(blob)) {
    pageType = 'wizard_flow';
    workflowHints.push('sequential_steps');
    formClassification = 'wizard';
  } else if (/\b(create|add|new|edit)\b/i.test(blob) && /\b(po|order|invoice|batch|record)\b/i.test(blob)) {
    pageType = 'crud_page';
    formClassification = 'entity_form';
  } else if (/\b(list|search|grid|index)\b/i.test(blob)) {
    pageType = 'crud_page';
    formClassification = 'list_filters';
  }

  return { pageType, workflowHints, formClassification };
}
