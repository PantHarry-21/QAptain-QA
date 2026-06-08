"""
Semantic UI Extractor
Converts raw DOM + accessibility tree into compressed semantic UI state.
NEVER sends full raw HTML to the LLM.
"""
from __future__ import annotations
import re
from typing import Any

from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By


# Element type inference from role + tag + attributes
_ROLE_MAP = {
    "button": "button", "link": "link", "textbox": "textbox",
    "searchbox": "textbox", "combobox": "dropdown", "listbox": "dropdown",
    "checkbox": "checkbox", "radio": "radio", "switch": "toggle",
    "tab": "tab", "tabpanel": "panel", "dialog": "modal",
    "alert": "alert", "alertdialog": "modal", "grid": "table",
    "table": "table", "row": "table_row", "cell": "table_cell",
    "columnheader": "table_header", "menu": "menu", "menuitem": "menu_item",
    "navigation": "navigation", "main": "main_content",
}

_TAG_MAP = {
    "input": "textbox", "textarea": "textbox", "select": "dropdown",
    "button": "button", "a": "link", "table": "table",
    "form": "form", "img": "image",
}

_INPUT_TYPE_MAP = {
    "text": "textbox", "email": "textbox", "password": "password_field",
    "number": "number_input", "tel": "phone_input", "date": "date_picker",
    "datetime-local": "datetime_picker", "checkbox": "checkbox",
    "radio": "radio", "file": "file_upload", "submit": "button",
    "search": "textbox",
}


class SemanticUIExtractor:
    """
    Extracts a compressed semantic representation of the current page.
    This is what gets sent to the AI — NOT raw HTML.
    """

    def __init__(self, driver: WebDriver):
        self.driver = driver

    def extract_page_state(self) -> dict[str, Any]:
        """
        Returns the full compressed semantic state of the current page.
        Structure:
            {
                "url": "...",
                "title": "...",
                "page": "inferred page name",
                "workflow_stage": "inferred stage",
                "visible_elements": [...],
                "dynamic_changes": [...],
                "navigation": {...},
            }
        """
        url = self.driver.current_url
        title = self.driver.title

        visible_elements = self._extract_interactive_elements()
        page_text_summary = self._extract_page_text_summary()
        nav_items = self._extract_navigation()

        return {
            "url": url,
            "title": title,
            "page": self._infer_page_name(url, title, visible_elements),
            "workflow_stage": self._infer_workflow_stage(url, title, visible_elements),
            "visible_elements": visible_elements,
            "page_text_summary": page_text_summary,
            "navigation": nav_items,
        }

    def _extract_interactive_elements(self) -> list[dict[str, Any]]:
        """Extract all interactive elements with semantic labels."""
        elements = []
        seen_labels: set[str] = set()

        # Use JavaScript to extract elements with semantic context
        js_result = self.driver.execute_script("""
            const results = [];
            const seen = new Set();

            function getLabel(el) {
                // Try: aria-label > label[for] > placeholder > title > text content
                if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
                if (el.id) {
                    const lbl = document.querySelector('label[for="' + el.id + '"]');
                    if (lbl) return lbl.textContent.trim();
                }
                if (el.getAttribute('placeholder')) return el.getAttribute('placeholder');
                if (el.getAttribute('title')) return el.getAttribute('title');
                if (el.name) return el.name.replace(/[-_]/g, ' ');
                const text = el.textContent.trim().substring(0, 80);
                return text || null;
            }

            function getRole(el) {
                const explicit = el.getAttribute('role');
                if (explicit) return explicit;
                const tag = el.tagName.toLowerCase();
                if (tag === 'input') return el.type || 'textbox';
                if (tag === 'button') return 'button';
                if (tag === 'a' && el.href) return 'link';
                if (tag === 'select') return 'combobox';
                if (tag === 'textarea') return 'textbox';
                return tag;
            }

            function isVisible(el) {
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) return false;
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                
                const navSels = ['nav', '[role="navigation"]', 'aside', '[role="menubar"]', '[class*="sidebar" i]', '[class*="sider" i]', '[class*="menu-bar" i]'];
                if (el.closest(navSels.join(', '))) return false;
                
                return true;
            }

            const selectors = [
                'input:not([type="hidden"])', 'textarea', 'select',
                'button', 'a[href]', '[role="button"]', '[role="combobox"]',
                '[role="textbox"]', '[role="checkbox"]', '[role="radio"]',
                '[role="tab"]', '[role="menuitem"]',
            ];

            for (const sel of selectors) {
                for (const el of document.querySelectorAll(sel)) {
                    if (!isVisible(el)) continue;
                    const label = getLabel(el);
                    const role = getRole(el);
                    if (!label) continue;
                    const key = role + ':' + label.toLowerCase();
                    if (seen.has(key)) continue;
                    seen.add(key);
                    results.push({
                        type: role,
                        label: label,
                        tag: el.tagName.toLowerCase(),
                        input_type: el.type || null,
                        is_required: el.required || el.getAttribute('aria-required') === 'true',
                        is_disabled: el.disabled || el.getAttribute('aria-disabled') === 'true',
                        value: el.value || null,
                        options: el.tagName === 'SELECT'
                            ? Array.from(el.options).map(o => ({text: o.text, value: o.value}))
                            : null,
                    });
                    if (results.length >= 50) break;
                }
            }
            return results;
        """)

        for item in (js_result or []):
            label = item.get("label", "").strip()
            if not label or label in seen_labels:
                continue
            seen_labels.add(label)

            element_type = self._normalize_type(item.get("type", ""), item.get("input_type"), item.get("tag"))
            semantic = {
                "type": element_type,
                "label": label,
            }
            if item.get("is_required"):
                semantic["required"] = True
            if item.get("is_disabled"):
                semantic["disabled"] = True
            if item.get("options"):
                semantic["options"] = [o["text"] for o in item["options"][:20]]
            if item.get("value") and element_type not in ("password_field",):
                semantic["current_value"] = item["value"][:100]
            elements.append(semantic)

        return elements

    def _extract_page_text_summary(self) -> str:
        """Extract key visible text from headings, alerts, and prominent elements."""
        try:
            text_items = self.driver.execute_script("""
                const items = [];
                for (const sel of ['h1', 'h2', 'h3', '[role="alert"]', '[role="status"]', '.breadcrumb']) {
                    for (const el of document.querySelectorAll(sel)) {
                        const t = el.textContent.trim();
                        if (t && t.length < 200) items.push(t);
                        if (items.length >= 10) break;
                    }
                }
                return items;
            """)
            return " | ".join(text_items or [])
        except Exception:
            return ""

    def _extract_navigation(self) -> dict[str, Any]:
        """Extract navigation structure."""
        try:
            nav = self.driver.execute_script("""
                const items = [];
                const selectors = ['nav a', '[role="navigation"] a', '.sidebar a', '.menu a'];
                for (const sel of selectors) {
                    for (const el of document.querySelectorAll(sel)) {
                        const text = el.textContent.trim();
                        if (text && text.length < 50) {
                            items.push({text, href: el.getAttribute('href') || ''});
                            if (items.length >= 20) break;
                        }
                    }
                    if (items.length > 0) break;
                }
                return items;
            """)
            return {"items": nav or []}
        except Exception:
            return {"items": []}

    def _normalize_type(self, role: str, input_type: str | None, tag: str | None) -> str:
        if role in _ROLE_MAP:
            return _ROLE_MAP[role]
        if input_type and input_type in _INPUT_TYPE_MAP:
            return _INPUT_TYPE_MAP[input_type]
        if tag and tag in _TAG_MAP:
            return _TAG_MAP[tag]
        return role or "element"

    def _infer_page_name(self, url: str, title: str, elements: list) -> str:
        """Infer human-readable page name from URL + title."""
        # Prefer title if meaningful
        if title and title not in ("", "QAptain", "Loading..."):
            return title.split(" | ")[0].split(" - ")[0].strip()
        # Parse URL path
        path = url.split("?")[0].rstrip("/")
        parts = [p for p in path.split("/") if p and not re.match(r'^[0-9a-f-]+$', p)]
        if parts:
            return parts[-1].replace("-", " ").replace("_", " ").title()
        return "Application Page"

    def _infer_workflow_stage(self, url: str, title: str, elements: list) -> str:
        """Infer the current workflow stage from available context."""
        element_labels = {e.get("label", "").lower() for e in elements}
        element_types = {e.get("type", "") for e in elements}

        # Login patterns
        if any(l in element_labels for l in ["username", "email", "password", "sign in", "log in"]):
            if "password" in element_labels or "password_field" in element_types:
                return "Credential Authentication"

        # Location/context selection patterns
        if any(l in element_labels for l in ["location", "branch", "site", "department"]):
            if "dropdown" in element_types or "combobox" in element_types:
                return "Context Selection"

        # Form submission
        if any(l in element_labels for l in ["save", "submit", "create", "add", "update"]):
            return "Form Submission"

        # Search/filter
        if any(l in element_labels for l in ["search", "filter", "find"]):
            return "Search & Filter"

        # Dashboard/overview
        if "dashboard" in url.lower() or "home" in url.lower():
            return "Dashboard Overview"

        return "Application Interaction"

    def detect_dynamic_changes(self, before_state: dict, after_state: dict) -> list[dict[str, Any]]:
        """
        Compare two semantic states to detect meaningful UI changes.
        This is how QAptain understands multi-stage workflows on the same page.
        """
        changes = []

        before_labels = {e["label"] for e in before_state.get("visible_elements", [])}
        after_labels = {e["label"] for e in after_state.get("visible_elements", [])}

        new_elements = after_labels - before_labels
        removed_elements = before_labels - after_labels

        if new_elements:
            changes.append({
                "type": "elements_appeared",
                "elements": list(new_elements),
                "interpretation": f"New UI elements appeared: {', '.join(list(new_elements)[:5])}",
            })

        if removed_elements:
            changes.append({
                "type": "elements_removed",
                "elements": list(removed_elements),
                "interpretation": f"UI elements disappeared: {', '.join(list(removed_elements)[:5])}",
            })

        # Stage transition
        before_stage = before_state.get("workflow_stage")
        after_stage = after_state.get("workflow_stage")
        if before_stage != after_stage:
            changes.append({
                "type": "workflow_stage_transition",
                "from": before_stage,
                "to": after_stage,
                "interpretation": f"Workflow advanced from '{before_stage}' to '{after_stage}'",
            })

        # URL change
        if before_state.get("url") != after_state.get("url"):
            changes.append({
                "type": "navigation",
                "from_url": before_state.get("url"),
                "to_url": after_state.get("url"),
                "interpretation": "Browser navigated to new page",
            })

        return changes
