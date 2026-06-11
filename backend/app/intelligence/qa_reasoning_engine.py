"""
QA Reasoning Engine
The AI brain of QAptain's test executor.

Transforms a scenario title + description into a comprehensive, intelligent
execution plan — exactly as a senior human QA engineer would design it.

AI is called ONCE per scenario. The plan it returns is then executed
deterministically by the Selenium layer.

Workflow Classification:
  CRUD             → Create + Read + Update + Delete + Form Validation + Edge Cases
  SEARCH_FILTER    → Search (exact/partial/case/empty/special) + Filter + Clear + Reset
  PAGINATION       → Next/Prev/First/Last + page number + items-per-page change
  SORTING          → Ascending + Descending + multiple columns + indicator verification
  FORM_VALIDATION  → Empty submit + invalid data + max/min length + security inputs
  AUTH             → Valid login + invalid credentials + empty fields + session + logout
  ROLE_ACCESS      → Allowed access + restricted access + permission boundaries
  FILE_UPLOAD      → Valid upload + invalid type + size limit + preview + delete
  EXPORT           → CSV/Excel/PDF + filtered export + empty export + file download
  NAVIGATION       → Navigate to module + verify key page elements loaded
  BUSINESS_WORKFLOW→ Custom multi-step business process
"""
from __future__ import annotations
import asyncio
import json
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import (
    Application, ApplicationModule, ApplicationPage, ApplicationWorkflow,
    SemanticElement, Scenario, AIMemoryChunk, MemoryKind,
)
from app.intelligence.ai_client import get_ai_client

log = structlog.get_logger()

# ─── Prompt ───────────────────────────────────────────────────────────────────

QA_SYSTEM_PROMPT = """You are QAptain's AI QA Intelligence Engine — a SENIOR QA ENGINEER with deep enterprise testing expertise.

MISSION: Transform any test scenario into a COMPLETE, INTELLIGENT execution plan covering positive paths, negative tests, edge cases, validations, and business rules — exactly as an experienced human QA engineer would.

════════════════════════════════════════
INTELLIGENCE MANDATE — READ FIRST
════════════════════════════════════════
You are NOT a simple script runner. You THINK like a QA engineer.

For EVERY scenario you MUST automatically infer and include:
  ▸ POSITIVE paths — happy path, successful operations
  ▸ NEGATIVE tests — invalid inputs, empty fields, wrong data, bad credentials
  ▸ EDGE CASES — max length, special characters, empty state, boundary values
  ▸ UI VALIDATIONS — error messages, success toasts, spinners, disabled buttons
  ▸ BUSINESS VALIDATIONS — duplicate prevention, data integrity, referential checks
  ▸ SECURITY CHECKS — SQL injection text in fields (e.g. "Robert'); DROP TABLE--"),
                       script tags (e.g. "<script>alert(1)</script>"), XSS patterns

DO NOT execute only the happy path.
DO NOT only validate UI visibility.
INFER complete QA coverage from the scenario title and description.

════════════════════════════════════════
WORKFLOW TYPE CLASSIFICATION
════════════════════════════════════════
Pick the BEST matching type from this list:

CRUD          — "test CRUD", "all operations", "create/edit/delete", "add and verify", "test [module]"
SEARCH_FILTER — "search", "filter", "find records", "query", "list records"
PAGINATION    — "pagination", "next page", "previous page", "paging", "page numbers", "items per page"
SORTING       — "sort", "column sort", "ascending", "descending", "order by", "sortable"
FORM_VALIDATION — "validation", "required fields", "error messages", "mandatory", "invalid input"
AUTH          — "login", "sign in", "authentication", "credentials", "session", "logout"
ROLE_ACCESS   — "access", "permission", "role", "restricted", "unauthorized", "only X can"
FILE_UPLOAD   — "upload", "attach file", "import file", "document upload", "file preview"
EXPORT        — "export", "download", "CSV export", "Excel export", "PDF export", "generate report"
NAVIGATION    — "navigate", "access module", "open page", "go to", "can access"
BUSINESS_WORKFLOW — any multi-step process not matching above categories

════════════════════════════════════════
CRUD — FULL EXPANSION (ALL PHASES REQUIRED)
════════════════════════════════════════
When workflow_type = CRUD, generate ALL phases in this ORDER:

PHASE 1 — SETUP
  screenshot (initial state)
  navigate to exact Module URL (keep full hash: http://server/app/#/route)
  wait_ms 2000
  assert_visible module heading or table (confirm correct page loaded)

PHASE 2 — FORM_VALIDATION (empty submit negative test)
  screenshot
  click "Add" / "Create" / "New" button
  screenshot (form opened)
  click "Save" / "Submit" WITHOUT filling any fields
  assert_visible required field error messages on mandatory fields
  screenshot (error state)
  click "Cancel" / close form (reset for next phase)
  wait_ms 500

PHASE 3 — DUPLICATE / UNIQUE VALIDATION (if applicable)
  [Only if the module has unique fields like Name, Code, Email]
  click "Add" button
  fill the unique field with a value that ALREADY EXISTS in the system (use a realistic existing name)
  fill other required fields
  click "Save"
  assert_visible duplicate/already-exists error message
  click "Cancel" / close form
  wait_ms 500

PHASE 4 — CREATE (happy path with realistic test data)
  click "Add" / "Create" / "New" button
  fill ALL required fields with realistic, business-appropriate test data
    → Names should be real-looking: "Test Record QA-001", "Sample Entry 2024"
    → Dates should be today or near future
    → Numbers should be valid for the field's purpose
  screenshot (before submit)
  click "Save" / "Submit" / "Create"
  wait_network
  assert_visible success message / toast / confirmation
  screenshot (after create — success state)

PHASE 5 — VERIFY_CREATED
  assert_visible the newly created record name in the list / table
  screenshot (record visible in list)
  [checkpoint: record_created]

PHASE 6 — UPDATE
  click "Edit" / pencil icon / "Modify" on the created record
  screenshot (edit form opened with existing values)
  assert_visible existing field values are pre-populated (proves edit loads current data)
  clear one or two fields and fill updated values
  screenshot (before save)
  click "Save" / "Update"
  wait_network
  assert_visible success message / toast
  screenshot (after update)

PHASE 7 — VERIFY_UPDATED
  assert_visible the updated value in the list / detail view
  [checkpoint: value_updated]

PHASE 8 — CANCEL DELETE (negative test for delete)
  click "Delete" / trash icon on the record
  assert_visible confirmation dialog / prompt
  click "Cancel" / "No" (do NOT confirm deletion)
  assert_visible the record is STILL in the table (cancel preserved the record)
  screenshot (record still exists after cancel)

PHASE 9 — DELETE (confirmed)
  click "Delete" / trash icon on the record
  assert_visible confirmation dialog / prompt
  click "Confirm" / "Yes" / "OK" to confirm
  wait_network
  screenshot (after delete)

PHASE 10 — VERIFY_DELETED
  assert_not_text the deleted record name (it must be gone from the list)
  screenshot (final state — list without deleted record)
  [checkpoint: record_deleted]

AUTO-INFER THESE ADDITIONAL NEGATIVE/EDGE CASES for CRUD:
  • Max length: try filling a text field with 500+ characters → verify truncation or error
  • Special characters: fill name with "Test & Record <2024>" → verify accepted or rejected gracefully
  • Whitespace only: fill a required field with only spaces → verify trimmed/rejected
  • SQL injection: fill a text field with "Test'); DROP TABLE--" → verify saved as literal text, NOT executed

════════════════════════════════════════
SEARCH_FILTER — FULL EXPANSION
════════════════════════════════════════
When workflow_type = SEARCH_FILTER, generate these phases:

PHASE 1 — SETUP
  navigate to module URL + wait_ms 2000 + assert_visible table/list

PHASE 2 — VERIFY_INITIAL_DATA
  assert_visible at least one record in the list (baseline)
  screenshot (full list baseline)

PHASE 3 — EXACT_MATCH_SEARCH
  click search input / "Search" field
  type a known value that EXISTS in the data (use realistic term from module context)
  wait_ms 800 (debounce)
  assert_visible the matching record in results
  screenshot (search results)
  [checkpoint: search_found_results]

PHASE 4 — PARTIAL_MATCH_SEARCH
  clear search field
  type first 3-4 characters of the same term (partial match)
  wait_ms 800
  assert_visible partial match results (records containing those characters)
  screenshot

PHASE 5 — CASE_INSENSITIVE_SEARCH
  clear search field
  type the same term in UPPERCASE (e.g., if "glucose" → type "GLUCOSE")
  wait_ms 800
  assert_visible same results as lowercase search
  screenshot

PHASE 6 — NO_RESULTS_SEARCH
  clear search field
  type "zzz_no_match_xyz_999" (guaranteed non-existent term)
  wait_ms 800
  assert_visible "no results" / "no records" / "0 records" message OR empty table
  screenshot (empty results state)
  [checkpoint: no_results_shown]

PHASE 7 — CLEAR_SEARCH
  clear search field (click X or select all and delete)
  wait_ms 500
  assert_visible full list restored (same record count as baseline)
  screenshot (list restored)

PHASE 8 — FILTER_APPLY (if filters exist — dropdown, checkbox, date range)
  apply a relevant filter (e.g., Status = "Active", Date range, Category dropdown)
  wait_ms 800
  assert_visible filtered results (fewer records than full list, or matching criteria)
  screenshot (filtered state)
  [checkpoint: filter_applied]

PHASE 9 — FILTER_RESET
  click "Reset" / "Clear Filters" / "Clear All"
  wait_ms 500
  assert_visible full unfiltered list restored
  screenshot (filters cleared)

AUTO-INFER THESE for SEARCH:
  • Search with spaces: "  glucose  " (leading/trailing spaces)
  • Special characters: "test@#$" → verify graceful handling
  • Very long search term: 100+ characters → verify no crash

════════════════════════════════════════
PAGINATION — FULL EXPANSION
════════════════════════════════════════
When workflow_type = PAGINATION, generate these phases (REAL clicks required):

PHASE 1 — SETUP
  navigate to module URL + wait_ms 2000 + assert_visible table heading

PHASE 2 — VERIFY_DATA_LOADED
  assert_visible at least one data row (page 1 populated)
  screenshot (page 1 baseline)

PHASE 3 — NEXT_PAGE
  click "Next" / ">" / "Next Page" button in pagination controls
  wait_ms 800
  screenshot (after Next)
  assert_visible page 2 indicator ("2" active in pagination, or "11-20 of N" row range)
  [checkpoint: page_changed]

PHASE 4 — VERIFY_PAGE_CHANGED
  assert_visible page number "2" is highlighted/active

PHASE 5 — PREV_PAGE
  click "Previous" / "<" / "Prev" button
  wait_ms 800
  screenshot (after Prev)
  assert_visible page 1 indicator ("1" active, or "1-10 of N" range)
  [checkpoint: returned_to_page1]

PHASE 6 — GOTO_SPECIFIC_PAGE
  click page number "3" in pagination (if visible) OR click "Last" button
  wait_ms 800
  screenshot
  assert_visible target page number indicator

PHASE 7 — ITEMS_PER_PAGE
  locate "Items per page" / "Show" / "Rows per page" selector
  change selection to a different value (e.g., 25 or 50)
  wait_ms 800
  assert_visible updated row count in table
  screenshot (different items-per-page)

PHASE 8 — BOUNDARY_CHECK
  click "Last" page button (if present)
  wait_ms 800
  assert_visible "Next" button is disabled (can't go past last page)
  screenshot (last page state)

════════════════════════════════════════
SORTING — FULL EXPANSION
════════════════════════════════════════
When workflow_type = SORTING:

PHASE 1 — SETUP
  navigate + wait_ms 2000 + assert_visible table with column headers

PHASE 2 — VERIFY_DEFAULT_ORDER
  screenshot (note initial order of first few rows)
  assert_visible at least one data row

PHASE 3 — SORT_ASCENDING
  click a sortable column header (use the most meaningful column: Name, Date, Code, Status)
  wait_ms 800
  screenshot (after first click — should sort ascending)
  assert_visible ascending sort indicator (↑ arrow on column header)
  [checkpoint: sorted_ascending] — verify first row value is alphabetically/numerically first

PHASE 4 — VERIFY_ASC_ORDER
  assert_visible sort indicator arrow on the column
  assert_visible the first record in sorted order (e.g., record starting with "A" or lowest number)

PHASE 5 — SORT_DESCENDING
  click the SAME column header again (toggles to descending)
  wait_ms 800
  screenshot (descending order)
  assert_visible descending sort indicator (↓ arrow on column header)
  [checkpoint: sorted_descending] — verify first row is now last in ascending order

PHASE 6 — VERIFY_DESC_ORDER
  assert_visible the first record is now what was previously LAST in ascending order

PHASE 7 — SORT_ANOTHER_COLUMN
  click a DIFFERENT column header (e.g., if first was Name, now click Date or Status)
  wait_ms 800
  screenshot
  assert_visible sort indicator moved to new column
  assert_visible data reordered by new column

PHASE 8 — SORT_WITH_SEARCH (verify sorting works with active search)
  type a partial search term in search field
  wait_ms 500
  click a column to sort the filtered results
  wait_ms 500
  assert_visible sorted indicator + filtered results still shown
  screenshot

════════════════════════════════════════
FORM_VALIDATION — FULL EXPANSION
════════════════════════════════════════
When workflow_type = FORM_VALIDATION:

PHASE 1 — SETUP + OPEN_FORM
  navigate + wait_ms 2000 + open create/edit form

PHASE 2 — SUBMIT_EMPTY
  click "Save" without filling anything
  assert_visible required field error messages on ALL mandatory fields
  screenshot (all errors shown)

PHASE 3 — INVALID_FORMAT
  fill email field with "notanemail" → assert email format error
  fill phone with "abc" → assert numeric/format error
  fill date with "99/99/9999" → assert invalid date error
  screenshot (format errors)

PHASE 4 — MAX_LENGTH
  fill a text field with 500 characters (paste long string)
  assert_visible max length error OR verify input is capped at max allowed chars
  screenshot

PHASE 5 — SECURITY_INPUTS
  fill text field with: "Robert'); DROP TABLE users;--"
  assert_visible it is treated as plain text (saved literally, no SQL error, no crash)
  clear and fill with: "<script>alert('xss')</script>"
  assert_visible treated as plain text or rejected gracefully
  screenshot

PHASE 6 — VALID_SUBMIT
  clear all fields + fill all required fields with valid data
  click "Save" / "Submit"
  wait_network
  assert_visible success message / toast
  screenshot (success state)
  [checkpoint: form_valid_submitted]

PHASE 7 — ERROR_CLEARING
  click back into a field that had an error and correct it
  assert_visible error message clears/disappears as user types correct value
  screenshot (error cleared inline)

════════════════════════════════════════
AUTH — FULL EXPANSION
════════════════════════════════════════
When workflow_type = AUTH:

PHASE 1 — VALID_LOGIN
  navigate to login page + screenshot
  fill valid username + valid password
  click "Sign In" / "Login" / "Submit"
  wait_network
  assert_visible dashboard or home page element (proves login succeeded)
  screenshot (logged in state)
  [checkpoint: auth_success]

PHASE 2 — INVALID_PASSWORD
  navigate to login page (if not already there) OR logout first
  fill valid username + WRONG password
  click "Sign In"
  wait_network
  assert_visible error message ("Invalid credentials" / "Incorrect password")
  screenshot (error state)
  [checkpoint: auth_rejected]

PHASE 3 — INVALID_USERNAME
  fill non-existent username + any password
  click "Sign In"
  wait_network
  assert_visible error message
  screenshot

PHASE 4 — EMPTY_SUBMIT
  clear both fields
  click "Sign In"
  assert_visible required field validation messages
  screenshot

PHASE 5 — SESSION_CHECK (if applicable)
  after valid login: assert_visible user name / avatar in header
  verify URL changed to dashboard (not stuck on login page)

════════════════════════════════════════
FILE_UPLOAD — FULL EXPANSION
════════════════════════════════════════
When workflow_type = FILE_UPLOAD:

PHASE 1 — SETUP
  navigate + wait_ms 2000 + assert_visible upload button / drop zone

PHASE 2 — VALID_UPLOAD
  click "Upload" / "Attach" / "Choose File"
  select a valid file (appropriate type for the module: PDF, DOCX, Excel, image)
  assert_visible file name shown in upload area / preview
  click "Upload" / "Submit" / "Save"
  wait_network
  assert_visible success message + uploaded file in list
  screenshot (file uploaded)
  [checkpoint: file_uploaded]

PHASE 3 — INVALID_FILE_TYPE
  click "Upload"
  attempt to upload a disallowed type (e.g., .exe, .bat, or wrong type)
  assert_visible file type rejection error message
  screenshot (rejected)

PHASE 4 — FILE_PREVIEW
  click on the uploaded file name or preview icon
  assert_visible preview modal or inline preview opens
  screenshot (file preview)

PHASE 5 — FILE_DOWNLOAD
  click "Download" on the uploaded file
  assert_visible download initiated (button responds, no error)
  screenshot

PHASE 6 — DELETE_UPLOADED_FILE
  click "Delete" / "Remove" on the uploaded file
  assert_visible confirmation prompt (if any)
  confirm deletion
  assert_not_text the deleted file name (removed from list)
  screenshot (file removed)

════════════════════════════════════════
EXPORT — FULL EXPANSION
════════════════════════════════════════
When workflow_type = EXPORT:

PHASE 1 — SETUP
  navigate + wait_ms 2000 + assert_visible data table with records

PHASE 2 — EXPORT_ALL
  click "Export" / "Download" / "Export to CSV" / "Export to Excel"
  wait_ms 2000 (file download initiates)
  assert_visible download success indicator OR absence of error message
  screenshot (export triggered)
  [checkpoint: export_triggered]

PHASE 3 — EXPORT_WITH_SEARCH
  apply a search filter (type partial term in search)
  wait_ms 500
  click "Export" again
  assert_visible export with filtered data (fewer records in file context)
  screenshot (filtered export)

PHASE 4 — EXPORT_WITH_FILTER
  apply a status/category filter
  click "Export"
  assert_visible export action completed
  screenshot (filtered export)

PHASE 5 — EXPORT_FORMAT_OPTIONS (if multiple formats offered)
  if CSV button exists: click it → verify CSV download
  if Excel button exists: click it → verify Excel download
  if PDF button exists: click it → verify PDF download
  screenshot (format options used)

PHASE 6 — EMPTY_EXPORT
  apply a filter that results in NO records
  click "Export"
  assert_visible either: empty file warning OR export still completes gracefully
  screenshot (empty export behavior)

════════════════════════════════════════
NAVIGATION — FULL EXPANSION
════════════════════════════════════════
When workflow_type = NAVIGATION OR the scenario involves selecting items, listing views, or module access:

PHASE 1 — SETUP
  navigate to module URL + wait_ms 2000
  assert_visible page heading / module title (prove correct page loaded)
  screenshot (initial state)

PHASE 2 — VERIFY_PAGE_LOADED
  assert_visible main content area (table, list, form, or grid)
  assert_visible key UI elements relevant to this module (buttons, search, filters)
  screenshot (page loaded with data)
  [checkpoint: page_accessible]

PHASE 3 — INTERACT_WITH_LISTING (if listing/table present)
  If the scenario mentions "selection" or "multiple" or "select":
    click first item's checkbox / selection control
    assert_visible item is marked as selected (checkbox ticked, row highlighted)
    screenshot (one item selected)
    click second item's checkbox
    assert_visible two items selected (count badge / "2 selected" indicator)
    screenshot (multiple selected)
    if "Select All" / "Select All on page" button exists:
      click it
      assert_visible all items selected
      screenshot (all selected)
    click "Clear" / "Deselect All" / uncheck all
    assert_visible selection cleared
    screenshot (deselected)
  Else:
    click on first row / item to open detail view
    assert_visible detail panel or page opened with correct data
    screenshot (detail view)
    click "Back" / breadcrumb to return to listing
    assert_visible listing page again
    screenshot (back to list)

PHASE 4 — VERIFY_BULK_ACTIONS (if selection was tested)
  After selecting one or more items:
  assert_visible bulk action toolbar / buttons become enabled (Delete, Export, Assign, etc.)
  click one bulk action button to verify it works (or just verify it's clickable)
  screenshot (bulk action available)

PHASE 5 — EMPTY_STATE (if applicable)
  apply a search / filter that produces zero results
  assert_visible empty state message ("No records found", "No data available")
  screenshot (empty state)
  clear the filter to restore full listing
  assert_visible records appear again

═══ NOTE: For NAVIGATION scenarios, generate 8–15 steps minimum. ═══

════════════════════════════════════════
BUSINESS_WORKFLOW — FULL EXPANSION
════════════════════════════════════════
When workflow_type = BUSINESS_WORKFLOW (complex multi-step processes):

PHASE 1 — SETUP
  navigate to start URL + wait_ms 2000 + screenshot + assert_visible starting state

PHASE 2 — INITIATE_WORKFLOW
  click the action that starts the workflow (button, menu item, wizard trigger)
  assert_visible first step / form / wizard of the workflow
  screenshot (workflow started)

PHASE 3 — STEP_THROUGH_WORKFLOW
  For each step in the process:
    fill required fields with realistic test data
    screenshot (step N in progress)
    click "Next" / "Continue" / action button
    assert_visible next step OR success indicator
    [checkpoint: step_N_completed]

PHASE 4 — VERIFY_COMPLETION
  assert_visible workflow completion message / success state
  assert_visible that final state reflects the workflow outcome (record updated, status changed, etc.)
  screenshot (workflow complete)
  [checkpoint: workflow_complete]

PHASE 5 — NEGATIVE_TESTS
  Restart the workflow
  Try to proceed without filling required fields → assert_visible validation errors
  Try invalid data in key fields → assert_visible appropriate error messages
  screenshot (validation errors)

PHASE 6 — VERIFY_AUDITABILITY (if applicable)
  Navigate to audit log / history section
  assert_visible the workflow action was recorded
  screenshot (audit trail)

═══ NOTE: For BUSINESS_WORKFLOW, generate 10–20 steps minimum. ═══

════════════════════════════════════════
SEMANTIC TARGET RULES
════════════════════════════════════════
Use EXACT text from the DISCOVERED FORMS, KNOWN UI ELEMENTS, and DISCOVERED WORKFLOWS
sections in the user prompt below — the executor matches your target strings against the
live DOM. Inventing a label that doesn't exist in the UI will cause the step to fail.

Priority order:
  1. If a form field is listed in DISCOVERED FORMS → use EXACTLY that label text.
  2. If a button/link is in KNOWN UI ELEMENTS or DISCOVERED WORKFLOWS → use EXACTLY that text.
  3. If not found in context → use a human-readable description: "Save button", "Name field".

DO NOT use CSS selectors or XPaths: "#btn-save", "input[name='fname']" are wrong.
DO NOT invent button labels like "Add Employee" if the context says the button is "+ New".

Examples (use what exploration found):
  • DISCOVERED FORMS says field "First Name" → target: "First Name"
  • DISCOVERED WORKFLOWS entry_point trigger "Add Job Opening" → target: "Add Job Opening"
  • No context available → target: "Save button" (descriptive fallback)

════════════════════════════════════════
STEP WRITING RULES
════════════════════════════════════════
  • First step = screenshot (initial state)
  • Last step = screenshot (final evidence)
  • After every form save/submit → wait_network THEN assert_visible success
  • After every delete → assert_not_text the deleted item's name
  • After every navigation → assert_visible key element proving correct page loaded
  • After every sort/filter/search action → wait_ms 800 THEN assert_visible expected change
  • Set checkpoint: true on key business verifications (created, updated, deleted, found, sorted)
  • Use on_fail: "skip" for screenshots, on_fail: "fail" for ALL assertions and actions
  • Set business_intent to explain WHY the step exists and what business rule it validates

════════════════════════════════════════
NAVIGATION RULES (CRITICAL)
════════════════════════════════════════
RULES:
  1. ALWAYS use the exact Module URL from context (include full path and hash if present)
  2. Only use "navigate" action in the SETUP phase — do NOT navigate mid-test unless required by the workflow
  3. For moving WITHIN a module, prefer "click" on nav links/tabs over a fresh "navigate"
  4. For SPAs (React/Angular/Vue): after any navigate step → add wait_ms 2000 for the route to render
  5. NEVER navigate to "/" or base URL mid-test — the user is already authenticated

════════════════════════════════════════
OUTPUT — Return ONLY valid JSON (no markdown, no explanation)
════════════════════════════════════════
{
  "workflow": "SCREAMING_SNAKE_CASE_WORKFLOW_NAME",
  "workflow_type": "CRUD|SEARCH_FILTER|PAGINATION|SORTING|FORM_VALIDATION|AUTH|ROLE_ACCESS|FILE_UPLOAD|EXPORT|NAVIGATION|BUSINESS_WORKFLOW",
  "goal": "One sentence: what business behavior this test proves",
  "qa_reasoning": "3-5 sentences explaining: what you understood, testing approach, validations included, negative tests, edge cases covered",
  "test_strategy": {
    "phases": ["SETUP", "FORM_VALIDATION", "CREATE", "VERIFY_CREATED", "..."],
    "primary_operation": "main operation being tested",
    "validations": ["list of all validations included"],
    "negative_tests": ["negative/invalid input tests included"],
    "edge_cases": ["boundary/edge conditions covered"]
  },
  "steps": [
    {
      "action": "screenshot|navigate|click|fill|clear|select|key_press|hover|assert_visible|assert_text|assert_not_text|assert_url|assert_count|wait_network|wait_element|wait_ms|scroll|upload",
      "description": "Business-readable description of what this step does",
      "target": "Semantic human-readable element label",
      "value": "",
      "url": "",
      "text": "",
      "key": "",
      "ms": 0,
      "timeout_ms": 10000,
      "on_fail": "fail",
      "checkpoint": false,
      "business_intent": "Why this step exists — what business rule it validates",
      "phase": "SETUP|FORM_VALIDATION|CREATE|VERIFY_CREATED|UPDATE|VERIFY_UPDATED|DELETE|VERIFY_DELETED|NEGATIVE_TESTS|EDGE_CASES|etc"
    }
  ],
  "checkpoint_validations": [
    {
      "after_description": "exact description of the step after which this validation fires",
      "validation_type": "record_created|record_deleted|value_updated|form_success|form_error|auth_success|access_denied|navigation_success|search_results|page_changed|sort_applied|file_uploaded|export_triggered",
      "description": "What to semantically verify at this checkpoint",
      "semantic_check": "Visible evidence confirming outcome (e.g. 'Record name appears in table row', 'Success toast visible')",
      "critical": true
    }
  ],
  "success_criteria": ["Business-level pass conditions"],
  "failure_indicators": ["Business-level fail indicators"],
  "semantic_intent": {
    "module": "module name being tested",
    "operation": "create|read|update|delete|search|filter|sort|paginate|login|upload|export|navigate|validate|authorize",
    "pass_criteria": "Business pass condition in plain English",
    "fail_criteria": "Business fail condition in plain English"
  }
}"""


# ─── Engine ───────────────────────────────────────────────────────────────────

class QAReasoningEngine:
    """
    Builds a comprehensive QA execution plan from a scenario using AI reasoning.

    Performance design:
    - AI called ONCE per scenario (not per step)
    - Application memory loaded before reasoning (modules, selectors, URLs)
    - Plan cached as ExecutionPlan record — reused on re-runs unless force_regenerate
    """

    # Max steps by mode — CRUD with full coverage needs 40-60 steps
    MODE_MAX_STEPS = {
        "smoke":            10,
        "functional":       30,
        "validation_heavy": 40,
        "regression":       60,
        "workflow_heavy":   80,
    }

    # AI token budget — reasoning models (gpt-5-mini, o3-mini) consume internal thinking
    # tokens BEFORE writing output. With a ~8k-token system+user prompt, gpt-5-mini uses
    # roughly 6,000-10,000 reasoning tokens internally, leaving the rest for the plan JSON.
    # A 20-step plan JSON is ~3,000-5,000 tokens, so 24k gives comfortable headroom.
    MODE_MAX_TOKENS = {
        "smoke":            3000,
        "functional":       5000,
        "validation_heavy": 6000,
        "regression":       7000,
        "workflow_heavy":   8000,
    }

    def __init__(self, db: AsyncSession):
        self.db = db
        self.ai = get_ai_client()

    async def build_plan(
        self,
        scenario: Scenario,
        execution_mode: str = "functional",
    ) -> dict[str, Any]:
        """
        Core reasoning method.
        Returns a rich plan dict ready to be stored as ExecutionPlan.plan_data.
        """
        max_steps = self.MODE_MAX_STEPS.get(execution_mode, 50)
        max_tokens = self.MODE_MAX_TOKENS.get(execution_mode, 4000)
        app_context = await self._load_application_context(scenario)

        user_prompt = self._build_user_prompt(scenario, app_context, max_steps, execution_mode)

        log.info("QA reasoning started",
            scenario_id=scenario.id,
            title=scenario.title[:60],
            mode=execution_mode,
        )

        # Resolve module URL now so the fallback can navigate to the right place
        _module_url = "/"
        if app_context.get("scenario_module"):
            _module_url = app_context["scenario_module"].get("url") or "/"

        plan_data: dict | None = None
        last_error: str = ""

        # Allow up to 180s: two consecutive Azure 429s each add 30s backoff +
        # ~13s min-interval wait = ~86s just for retries; the actual AI call
        # takes 10-20s on top. 90s timed out exactly at the start of the 3rd
        # attempt — 180s guarantees a full 3-retry window.
        try:
            response = await asyncio.wait_for(
                self.ai.complete(
                    system=QA_SYSTEM_PROMPT,
                    user=user_prompt,
                    json_mode=True,
                    max_tokens=max_tokens,
                ),
                timeout=180.0,
            )
            if response.content.strip():
                plan_data = response.json()
            else:
                last_error = "AI returned empty content"
                log.warning("QA reasoning empty response", content_len=0)
        except (Exception, asyncio.CancelledError) as e:
            last_error = f"{type(e).__name__}: {str(e)[:200]}"
            log.warning("QA reasoning AI call failed — raising for caller to use fallback",
                        error=last_error, module_url=_module_url)
            raise RuntimeError(f"QA reasoning failed: {last_error}") from e

        if not plan_data:
            raise RuntimeError(f"QA reasoning returned no data: {last_error}")

        # Post-process: sanitize + cap + enforce screenshots
        plan_data = self._post_process(plan_data, max_steps)

        log.info("QA reasoning complete",
            workflow=plan_data.get("workflow"),
            workflow_type=plan_data.get("workflow_type"),
            steps=len(plan_data.get("steps", [])),
            checkpoints=len(plan_data.get("checkpoint_validations", [])),
        )

        return plan_data

    # ─── Context Loading ──────────────────────────────────────────────────────

    async def _load_application_context(self, scenario: Scenario) -> dict[str, Any]:
        """Load application memory: modules, explored pages, known selectors."""
        # Application
        app_result = await self.db.execute(
            select(Application).where(Application.id == scenario.application_id)
        )
        app = app_result.scalar_one_or_none()

        # All modules
        mods_result = await self.db.execute(
            select(ApplicationModule).where(
                ApplicationModule.application_id == scenario.application_id
            )
        )
        modules = mods_result.scalars().all()

        # Module for this scenario (if set)
        scenario_module = None
        if scenario.module_id:
            for m in modules:
                if m.id == scenario.module_id:
                    scenario_module = m
                    break

        # Semantic elements from the scenario's module (selectors, labels)
        known_elements: list[dict] = []
        if scenario.module_id:
            el_result = await self.db.execute(
                select(SemanticElement)
                .join(ApplicationPage, SemanticElement.page_id == ApplicationPage.id)
                .where(ApplicationPage.module_id == scenario.module_id)
                .order_by(SemanticElement.confidence.desc())
                .limit(20)
            )
            for el in el_result.scalars().all():
                if el.semantic_label:
                    _css = next(
                        (s.get("value", "") for s in (el.selectors or []) if s.get("type") == "css"),
                        "",
                    )
                    known_elements.append({
                        "label": el.semantic_label,
                        "type": el.element_type,
                        "css": _css,
                    })

        # Pages for the scenario module — with full form field details
        module_pages: list[dict] = []
        module_forms: list[dict] = []   # full form definitions including all fields
        if scenario.module_id:
            pages_result = await self.db.execute(
                select(ApplicationPage)
                .where(ApplicationPage.module_id == scenario.module_id)
                .limit(8)
            )
            for p in pages_result.scalars().all():
                module_pages.append({
                    "title": p.title,
                    "url": p.url,
                    "type": p.page_type,
                    "forms": [f.get("name", "") for f in (p.forms or [])[:3]],
                    "tables": [
                        {
                            "name": t.get("name", ""),
                            "columns": [c.get("name", "") for c in t.get("columns", [])[:8]],
                            "row_actions": t.get("row_actions", [])[:5],
                            "has_search": t.get("has_search", False),
                            "has_filter": t.get("has_filter", False),
                        }
                        for t in (p.tables or [])[:3]
                    ],
                })
                # Collect full form definitions with field details
                for form in (p.forms or [])[:3]:
                    fields = form.get("fields", [])
                    if not fields:
                        continue
                    module_forms.append({
                        "name": form.get("name", ""),
                        "purpose": form.get("purpose", ""),
                        "entity": form.get("entity", ""),
                        "page_title": p.title,
                        "page_url": p.url,
                        "fields": [
                            {
                                "label": f.get("label", ""),
                                "type": f.get("type", "text"),
                                "required": bool(f.get("required", False)),
                                "validation": f.get("validation", ""),
                                "options": (f.get("options") or [])[:6],
                                "depends_on": f.get("depends_on"),
                            }
                            for f in fields[:25]
                            if f.get("label")
                        ],
                        "submit_action": form.get("submit_action", ""),
                        "success_message": form.get("success_message", ""),
                        "cancel_action": form.get("cancel_action", ""),
                    })

        # Workflows for the scenario module
        module_workflows: list[dict] = []
        if scenario.module_id:
            wf_result = await self.db.execute(
                select(ApplicationWorkflow)
                .where(ApplicationWorkflow.module_id == scenario.module_id)
                .limit(6)
            )
            for wf in wf_result.scalars().all():
                module_workflows.append({
                    "name": wf.name,
                    "type": wf.workflow_type or "",
                    "description": wf.description or "",
                    "entry_point": wf.entry_point or {},
                    "stages": (wf.stages or [])[:8],
                    "success_indicators": (wf.success_indicators or [])[:3],
                })

        # Load interaction guide built during exploration for this module
        # This contains exact selectors, dialog fields, submit/cancel buttons — enables
        # the AI to generate precise execution steps with real selectors.
        interaction_guide: str = ""
        if scenario.module_id:
            guides_result = await self.db.execute(
                select(AIMemoryChunk).where(
                    AIMemoryChunk.application_id == scenario.application_id,
                    AIMemoryChunk.kind == MemoryKind.WORKFLOW,
                )
            )
            guide_chunks = [
                chunk.content
                for chunk in guides_result.scalars().all()
                if (chunk.extra or {}).get("guide_type") == "interaction"
                and (chunk.extra or {}).get("module_id") == scenario.module_id
            ]
            if guide_chunks:
                interaction_guide = "\n\n---\n\n".join(guide_chunks)

        return {
            "app_name": app.name if app else "Application",
            "app_description": app.description if app else "",
            "base_url": app.base_url if app else "",
            "scenario_module": {
                "name": scenario_module.name if scenario_module else "",
                "url": scenario_module.url_pattern if scenario_module else "",
                "description": scenario_module.description if scenario_module else "",
            } if scenario_module else None,
            "all_modules": [
                {"name": m.name, "url": m.url_pattern or ""}
                for m in modules[:10]
            ],
            "known_elements": known_elements[:15],
            "module_pages": module_pages,
            "module_forms": module_forms,
            "module_workflows": module_workflows,
            "interaction_guide": interaction_guide,  # Exploration-built interaction knowledge
        }

    # ─── Prompt Construction ──────────────────────────────────────────────────

    def _build_capability_context(
        self,
        scenario: Scenario,
        workflow_type: str,
        execution_mode: str,
        app_context: dict | None = None,
    ) -> str:
        """
        Build capability engine context injected into the AI prompt.

        Pulls module_name, module_url, and actual form field labels from the
        already-loaded app_context so the capability engines produce entity-specific
        step descriptions (e.g. "Fill 'Name' field" instead of "Fill Name|Title|Code").

        Provides the AI with:
        1. A mandatory step checklist (phases + what to test) from the capability engine
        2. Critical assertions — what business outcomes MUST be verified at checkpoints
        3. Deterministic test data names consistent with EntityTracker convention
        """
        try:
            from app.capabilities.engine_registry import get_engine_registry
            registry = get_engine_registry()

            # Pull module context from the already-loaded app_context (avoids a second DB call)
            module_name = ""
            module_url = ""
            form_fields: list[str] = []
            if app_context:
                sm = app_context.get("scenario_module") or {}
                module_name = sm.get("name", "") or ""
                module_url = sm.get("url", "") or ""
                # Collect unique field labels from discovered forms — these become step hints
                seen: set[str] = set()
                for form in app_context.get("module_forms", [])[:4]:
                    for fld in form.get("fields", [])[:10]:
                        lbl = (fld.get("label") or "").strip()
                        if lbl and lbl not in seen:
                            seen.add(lbl)
                            form_fields.append(lbl)

            cap_ctx = registry.build_capability_context(
                scenario_title=scenario.title,
                scenario_description=scenario.description or "",
                workflow_type=workflow_type,
                module_name=module_name,
                module_url=module_url,
                execution_mode=execution_mode,
            )
            # Inject real form fields — enables field-specific step hints in engines
            cap_ctx.form_fields = form_fields

            assertion_ctx = registry.get_assertion_context(cap_ctx)
            entity = cap_ctx.entity_name

            lines = [
                "\n════════════════════════════════════",
                "CAPABILITY ENGINE — MANDATORY COVERAGE",
                "════════════════════════════════════",
                f"Primary Entity: {entity}",
                f"Module: {module_name or 'N/A'}",
                f"Module URL: {module_url or 'use the URL from MODULE context above'}",
                f"Workflow: {workflow_type}",
                f"Test Data: use 'Test{entity}001' for creation, 'Updated{entity}001' for update",
                "",
            ]

            # ── Inject coverage checklist from capability engine steps ──────────
            steps_by_cat = registry.generate_capability_steps(cap_ctx)
            positive_steps = steps_by_cat.get("positive", [])
            negative_steps = steps_by_cat.get("negative", [])
            edge_steps     = steps_by_cat.get("edge_case", [])
            security_steps = steps_by_cat.get("security", [])

            if positive_steps:
                lines.append("MANDATORY POSITIVE FLOW — your plan MUST cover these phases in order:")
                last_phase = None
                for s in positive_steps:
                    phase = s.get("phase", "")
                    desc  = s.get("description", "")
                    action = s.get("action", "")
                    if not desc:
                        continue
                    if phase != last_phase:
                        lines.append(f"  [{phase}]")
                        last_phase = phase
                    lines.append(f"    {action}: {desc}")

            if negative_steps:
                lines.append("")
                lines.append("REQUIRED NEGATIVE TESTS (must be in plan):")
                for s in negative_steps:
                    desc = s.get("description", "")
                    if desc:
                        lines.append(f"  ✗ {desc}")

            if edge_steps:
                lines.append("")
                lines.append("REQUIRED EDGE CASES (must be in plan):")
                for s in edge_steps[:5]:
                    desc = s.get("description", "")
                    if desc:
                        lines.append(f"  △ {desc}")

            if security_steps:
                lines.append("")
                lines.append("REQUIRED SECURITY CHECKS (must be in plan):")
                for s in security_steps[:4]:
                    desc = s.get("description", "")
                    if desc:
                        lines.append(f"  ⚡ {desc}")

            # ── Checkpoint assertions ────────────────────────────────────────────
            critical = assertion_ctx.get("critical_assertions", [])
            if critical:
                lines.append("")
                lines.append("CHECKPOINT ASSERTIONS — include these in checkpoint_validations:")
                for a in critical[:5]:
                    lines.append(f"  ✓ {a}")

            lines.append("════════════════════════════════════")
            return "\n".join(lines)

        except Exception as e:
            log.warning("Capability context build failed", error=str(e))
            return ""

    def _build_user_prompt(
        self, scenario: Scenario, ctx: dict[str, Any], max_steps: int,
        execution_mode: str = "functional",
    ) -> str:
        module_block = ""
        if ctx.get("scenario_module"):
            m = ctx["scenario_module"]
            module_block = f"""
TARGET MODULE: {m['name']}
Module URL: {m['url']}
Module Description: {m['description'] or 'N/A'}
"""

        elements_block = ""
        if ctx.get("known_elements"):
            elements_block = "\nKNOWN UI ELEMENTS (from exploration memory):\n" + "\n".join(
                f"  - [{e['type']}] {e['label']}"
                for e in ctx["known_elements"]
            )

        pages_block = ""
        if ctx.get("module_pages"):
            lines = ["\nEXPLORED PAGES:"]
            for p in ctx["module_pages"]:
                tables_info = ""
                for t in p.get("tables", []):
                    cols = ", ".join(t.get("columns", []))
                    acts = ", ".join(t.get("row_actions", []))
                    tables_info += f"\n      TABLE '{t['name']}': columns=[{cols}] row_actions=[{acts}]"
                lines.append(
                    f"  - {p['title']} ({p['url']}) forms={p['forms']}{tables_info}"
                )
            pages_block = "\n".join(lines)

        forms_block = ""
        if ctx.get("module_forms"):
            lines = ["\nDISCOVERED FORMS WITH FIELDS (use these exact field names in your plan):"]
            for form in ctx["module_forms"][:4]:
                lines.append(
                    f"\n  FORM: \"{form['name']}\" on {form['page_title']}"
                )
                if form.get("purpose"):
                    lines.append(f"  Purpose: {form['purpose']}")
                if form.get("entity"):
                    lines.append(f"  Entity: {form['entity']}")
                if form.get("submit_action"):
                    lines.append(f"  Submit button: \"{form['submit_action']}\"")
                if form.get("success_message"):
                    lines.append(f"  Success indicator: \"{form['success_message']}\"")
                lines.append("  Fields:")
                for f in form.get("fields", []):
                    req = " [REQUIRED]" if f.get("required") else ""
                    val = f" — {f['validation']}" if f.get("validation") else ""
                    opts_list = f.get("options") or []
                    opts = f" options=[{', '.join(str(o) for o in opts_list[:5])}]" if opts_list else ""
                    lines.append(f"    • \"{f['label']}\" ({f['type']}){req}{val}{opts}")
            forms_block = "\n".join(lines)

        workflows_block = ""
        if ctx.get("module_workflows"):
            lines = ["\nDISCOVERED WORKFLOWS (from exploration):"]
            for wf in ctx["module_workflows"][:4]:
                lines.append(f"\n  WORKFLOW: \"{wf['name']}\" ({wf.get('type', '')})")
                if wf.get("description"):
                    lines.append(f"  Description: {wf['description']}")
                ep = wf.get("entry_point") or {}
                if ep.get("trigger"):
                    lines.append(f"  Entry trigger: \"{ep['trigger']}\"")
                for stage in wf.get("stages", [])[:6]:
                    step_n = stage.get("step") or stage.get("stage", "?")
                    action = stage.get("action", stage.get("description", ""))
                    expected = stage.get("expected_result", "")
                    if action:
                        suffix = f" → {expected}" if expected else ""
                        lines.append(f"    Step {step_n}: {action}{suffix}")
                for si in wf.get("success_indicators", [])[:2]:
                    lines.append(f"  ✓ Success: {si}")
            workflows_block = "\n".join(lines)

        # Import operation intent extractor — single source of truth for CRUD scoping
        from app.intelligence.scenario_planner import _detect_workflow_type, _extract_operation_intent
        inferred_workflow = _detect_workflow_type(scenario.title, scenario.description or "")
        op_intent = _extract_operation_intent(scenario.title, scenario.description or "")

        capability_ctx = self._build_capability_context(
            scenario, inferred_workflow, execution_mode, app_context=ctx
        )

        interaction_guide_block = ""
        if ctx.get("interaction_guide"):
            interaction_guide_block = f"""
DISCOVERED UI INTERACTIONS (built during live exploration — HIGHEST PRIORITY):
This guide describes every action available on this module's page. Use it to:
  1. Know WHICH actions exist (Add, Edit, Delete, Approve, bulk delete, status tabs, search)
  2. Know WHAT happens when you trigger them (dialog title, form fields, success indicator)
  3. Reference action labels exactly as written (e.g. "Add Product button", "Delete icon", "Pending tab")
     The executor resolves these labels to CSS selectors automatically — do NOT put raw CSS in target.
{ctx['interaction_guide']}
"""

        # Operation scope override — ensures AI doesn't generate phases outside the intent.
        # e.g. "Test Add scenarios" → AI told to skip update/delete phases entirely.
        op_scope_block = ""
        if op_intent.get("scope_note"):
            op_scope_block = f"""
════════════════════════════════════
OPERATION SCOPE — MANDATORY
════════════════════════════════════
{op_intent['scope_note']}
Test variants required: {', '.join(op_intent.get('test_variants', ['positive', 'negative']))}

This overrides the default CRUD expansion. Only generate phases relevant to the
scoped operation above. For example, if scope is "create only": generate SETUP +
FORM_VALIDATION + CREATE + VERIFY_CREATED. Do NOT generate UPDATE or DELETE phases.
════════════════════════════════════
"""

        return f"""APPLICATION: {ctx['app_name']}
Description: {ctx['app_description'] or 'Enterprise business application'}
Base URL: {ctx['base_url']}
{module_block}
SCENARIO TITLE: {scenario.title}
SCENARIO DESCRIPTION: {scenario.description or 'N/A'}
Priority: {scenario.priority.value if scenario.priority else 'MEDIUM'}
Execution max steps: {max_steps}
{op_scope_block}
ALL MODULES:
{json.dumps(ctx['all_modules'], indent=1)}
{elements_block}
{pages_block}
{forms_block}
{workflows_block}
{interaction_guide_block}
INSTRUCTIONS:
1. Classify this scenario into the correct workflow_type.
2. Generate the execution plan scoped to the OPERATION SCOPE above (if provided).
3. MANDATORY: Include negative tests, edge cases, and validations — not just the happy path.
4. CRITICAL — USE EXACT LABELS: Use the EXACT field labels, button text, and entry point names from DISCOVERED FORMS, KNOWN UI ELEMENTS, and DISCOVERED WORKFLOWS above. Do NOT invent names. If DISCOVERED FORMS says the field is "Job Title", write target: "Job Title" — not "Title field". If the entry point trigger is "+ Add Job", write target: "+ Add Job".
5. Every assertion must verify a REAL observable change — not trivially pass.
6. For CRUD scoped to CREATE only: generate SETUP + FORM_VALIDATION + CREATE + VERIFY_CREATED phases. Stop there.
7. For CRUD scoped to full lifecycle: generate ALL 10 phases including form validation, duplicate check, cancel-delete, confirmed delete.
8. For SEARCH: include exact match, partial match, case-insensitive, no-results, clear.
9. For PAGINATION: real Next/Prev/Goto clicks with page number verification.
10. For SORTING: real column header clicks with ascending/descending indicator verification.
11. Think like a senior QA engineer covering the scoped feature — comprehensive within the defined scope.
12. CRITICAL: For the navigate step, use the exact Module URL from context. NEVER navigate to "/" — use the module's specific URL.
13. If DISCOVERED FORMS are provided, reference the exact field names and the submit button label in your steps.
14. If DISCOVERED UI INTERACTIONS are provided: reference the action labels exactly (e.g. "Add Product button", "Approve icon", "Pending tab", "Name field") — the executor resolves these to real elements automatically. Do NOT put CSS selectors in target fields.
{capability_ctx}"""

    # ─── Post-processing ──────────────────────────────────────────────────────

    ALLOWED_ACTIONS = frozenset([
        "navigate", "click", "fill", "clear", "select", "key_press", "hover",
        "assert_visible", "assert_text", "assert_not_text", "assert_url",
        "assert_count", "wait_network", "wait_element", "wait_ms",
        "scroll", "upload", "screenshot", "assert_ai_semantic",
    ])

    def _post_process(self, plan: dict, max_steps: int) -> dict:
        steps = plan.get("steps", [])

        # Filter unknown actions
        steps = [s for s in steps if s.get("action") in self.ALLOWED_ACTIONS]

        # Cap steps
        steps = steps[:max_steps]

        # Ensure each step has required fields
        for i, step in enumerate(steps):
            step.setdefault("timeout_ms", 10000)
            step.setdefault("on_fail", "fail")
            step.setdefault("checkpoint", False)
            step.setdefault("business_intent", "")
            step.setdefault("phase", "")
            step.setdefault("description", f"{step.get('action', 'step')} #{i+1}")
            if step.get("action") == "screenshot":
                step["on_fail"] = "skip"

        # Guarantee first + last screenshots
        if steps and steps[0].get("action") != "screenshot":
            steps.insert(0, {
                "action": "screenshot",
                "description": "Capture initial page state",
                "timeout_ms": 5000,
                "on_fail": "skip",
                "checkpoint": False,
                "business_intent": "Baseline evidence before test starts",
                "phase": "SETUP",
            })
        if steps and steps[-1].get("action") != "screenshot":
            steps.append({
                "action": "screenshot",
                "description": "Capture final page state as test evidence",
                "timeout_ms": 5000,
                "on_fail": "skip",
                "checkpoint": False,
                "business_intent": "Final evidence after all test steps",
                "phase": "TEARDOWN",
            })

        plan["steps"] = steps

        # Ensure checkpoint_validations is a list
        if "checkpoint_validations" not in plan or not isinstance(plan["checkpoint_validations"], list):
            plan["checkpoint_validations"] = []

        # Ensure semantic_intent
        plan.setdefault("semantic_intent", {})
        plan.setdefault("qa_reasoning", "")
        plan.setdefault("test_strategy", {})
        plan.setdefault("workflow_type", "BUSINESS_WORKFLOW")
        plan.setdefault("goal", scenario_title_to_goal(plan.get("workflow", "")))
        plan.setdefault("success_criteria", [])
        plan.setdefault("failure_indicators", [])

        return plan

    # ─── Fallback ─────────────────────────────────────────────────────────────

    def _fallback_plan(self, scenario: Scenario, module_url: str = "/") -> dict:
        """
        Minimal but executable fallback plan used when AI reasoning fails.
        Uses the module URL when available so the test at least opens the right page.
        """
        nav_url = module_url or "/"
        # assert_visible needs a non-empty text/target; use a page-agnostic heading check
        return {
            "workflow": "BASIC_NAVIGATE",
            "workflow_type": "NAVIGATION",
            "goal": f"Verify {scenario.title} works as expected",
            "qa_reasoning": "Fallback plan — AI reasoning unavailable. Basic navigation and page load verification.",
            "test_strategy": {
                "phases": ["NAVIGATE", "VERIFY_LOADED"],
                "primary_operation": "navigate",
                "validations": ["Page loads without errors"],
                "negative_tests": [],
                "edge_cases": [],
            },
            "steps": [
                {"action": "screenshot", "description": "Capture initial state", "timeout_ms": 5000,
                 "on_fail": "skip", "checkpoint": False, "business_intent": "Initial evidence", "phase": "SETUP"},
                {"action": "navigate", "description": f"Open {scenario.title}", "url": nav_url,
                 "timeout_ms": 15000, "on_fail": "fail", "checkpoint": False,
                 "business_intent": "Navigate to target module", "phase": "NAVIGATE"},
                {"action": "wait_ms", "description": "Wait for Angular SPA to render", "ms": 2000,
                 "timeout_ms": 5000, "on_fail": "skip", "checkpoint": False,
                 "business_intent": "Allow SPA route change to complete", "phase": "NAVIGATE"},
                {"action": "screenshot", "description": "Capture page after navigation", "timeout_ms": 5000,
                 "on_fail": "skip", "checkpoint": True, "business_intent": "Evidence page loaded", "phase": "VERIFY_LOADED"},
                {"action": "screenshot", "description": "Capture final state", "timeout_ms": 5000,
                 "on_fail": "skip", "checkpoint": False, "business_intent": "Final evidence", "phase": "TEARDOWN"},
            ],
            "checkpoint_validations": [],
            "success_criteria": ["Application loads and is accessible"],
            "failure_indicators": ["Application fails to load"],
            "semantic_intent": {
                "module": "",
                "operation": "navigate",
                "pass_criteria": "Application is accessible",
                "fail_criteria": "Application does not load",
            },
        }


def scenario_title_to_goal(workflow_name: str) -> str:
    return workflow_name.replace("_", " ").title()
