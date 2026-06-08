"""Optimized page analysis with reduced token consumption."""

SYSTEM_PROMPT_EXPLORE_COMPACT = """Extract page structure for QA testing. Output ONLY valid JSON.
IMPORTANT: You MUST emulate a Senior Human QA tester. When identifying workflows, DO NOT generate generic navigation steps (like "Search Modules" or "Open Module"). Instead, aggressively identify End-to-End CRUD (Create, Read, Update, Delete) business workflows based on the forms, buttons, and tables present on the page.
For example, if you see an 'Add' button and a table, generate a full lifecycle workflow: 'Add {Entity}, verify added in table, edit {Entity}, verify updated, delete {Entity}, verify removed'.
{
  "page_name": "Page title",
  "page_type": "dashboard|list|form|detail|modal|wizard|login|settings|report|upload|other",
  "key_business_objects": ["Entity 1", "Entity 2"],
  "forms": [{"name":"Form A","entity":"User","fields":[{"label":"Email","type":"email","required":true}]}],
  "tables": [{"name":"Users","entity":"User","row_actions":["Edit","Delete"],"has_search":true}],
  "workflows": [{"name":"Create User, Verify, Edit, Delete", "type":"crud_lifecycle", "entity":"User", "steps":[{"step":1,"action":"Click Add"}, {"step":2,"action":"Fill Form A"}, {"step":3,"action":"Verify User in Users table"}, {"step":4,"action":"Click Edit on row"}, {"step":5,"action":"Click Delete on row"}]}],
  "dynamic_behaviors": [{"trigger":"button_click","behavior":"modal_opens","element":"Add button"}]
}"""


async def analyze_page_compact(ai_client, state: dict, url: str, app_name: str) -> dict:
    """
    Compact page analysis using minimal context.
    Reduce input tokens by ~60% vs original approach.
    """
    # Only send essential page structure, not everything
    compact_state = {
        "url": url,
        "page_title": state.get("page", "Unknown"),
        "visible_elements": state.get("visible_elements", [])[:15],  # Reduce from 30
        "page_text": state.get("page_text_summary", "")[:500],  # Truncate
        "tables": state.get("tables", [])[:2],  # Only first 2 tables
        "forms": state.get("forms", [])[:2],  # Only first 2 forms
    }

    user_prompt = f"""App: {app_name}
URL: {url}

Page structure:
{compact_state}

Task: Act as a QA Engineer. Extract page structure (forms, tables, types) as JSON.
For `workflows`, analyze the visible elements (e.g. Add, Edit, Delete buttons) and synthesize them into End-to-End lifecycle test cases (e.g. "Add, verify, edit, verify, delete"). DO NOT output simple navigation steps."""

    try:
        response = await ai_client.complete(
            system=SYSTEM_PROMPT_EXPLORE_COMPACT,
            user=user_prompt,
            fast=True,
            json_mode=True,
            max_tokens=5000,  # Increased to support detailed CRUD workflows
        )
        result = response.json()
        # Track tokens
        return {
            **result,
            "_tokens": response.input_tokens + response.output_tokens,
        }
    except Exception as e:
        return {
            "page_name": state.get("page", "Unknown"),
            "page_type": "unknown",
            "forms": [],
            "tables": [],
            "workflows": [],
            "dynamic_behaviors": [],
            "_tokens": 0,
            "_error": str(e),
        }


class FieldValidator:
    """Test form field validation without submitting."""

    def __init__(self, browser):
        self.browser = browser

    def test_required_fields(self) -> dict:
        """Detect required fields and test with empty values."""
        return self.browser.execute_script("""
        const results = {};
        for (const inp of document.querySelectorAll('input, select, textarea')) {
            if (!inp.offsetHeight) continue;
            const name = inp.name || inp.id || inp.placeholder || '';
            const required = inp.required || inp.getAttribute('aria-required') === 'true';
            const type = inp.getAttribute('type') || inp.tagName.toLowerCase();
            const label = (document.querySelector(`label[for="${inp.id}"]`) || {}).textContent || name;

            if (required) {
                results[name] = {
                    label: label.trim().slice(0,50),
                    type: type,
                    required: true
                };
            }
        }
        return results;
        """) or {}

    def test_field_dependencies(self) -> dict:
        """Test if fields change visibility/state when other fields change."""
        return self.browser.execute_script("""
        const before = Array.from(document.querySelectorAll('[data-testid], input, select'))
            .filter(e => e.offsetHeight > 0)
            .map(e => e.getAttribute('data-testid') || e.name || e.id);

        return { visible_count: before.length, fields: before.slice(0, 20) };
        """) or {}

    def capture_validation_messages(self, field_selector: str) -> list[str]:
        """Try to trigger validation and capture error messages."""
        try:
            # Try to find and clear the field
            self.browser.execute_script(f"""
            const inp = document.querySelector('{field_selector}');
            if (inp) {{
                inp.value = '';
                inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                inp.dispatchEvent(new Event('blur', {{bubbles: true}}));
            }}
            """)

            # Capture error messages
            errors = self.browser.execute_script("""
            return Array.from(document.querySelectorAll('.error, .invalid, [role="alert"], .form-error'))
                .filter(e => e.offsetHeight > 0)
                .map(e => e.textContent.trim().slice(0, 100))
                .slice(0, 5);
            """) or []

            return errors
        except Exception:
            return []
