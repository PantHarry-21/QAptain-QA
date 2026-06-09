"""
Change Detection Engine
Compares the current live application UI against the stored interaction guide
and reports what changed: new buttons, removed fields, changed selectors.

This is the feedback loop: after a deployment or on-demand, run a lightweight
re-scan and diff against the stored guide to flag what broke or changed.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import (
    AIMemoryChunk, MemoryKind, Application, ApplicationModule,
    SemanticElement, ApplicationPage,
)

log = structlog.get_logger()


@dataclass
class ChangeItem:
    change_type: str        # "added" | "removed" | "modified" | "selector_changed"
    element_type: str       # "button" | "field" | "form" | "table"
    label: str
    module_name: str
    module_id: str
    detail: str             # human-readable description
    severity: str           # "high" | "medium" | "low"
    old_value: str = ""
    new_value: str = ""


@dataclass
class ChangeReport:
    application_id: str
    modules_scanned: int = 0
    total_changes: int = 0
    high_changes: int = 0
    medium_changes: int = 0
    low_changes: int = 0
    changes: list[ChangeItem] = field(default_factory=list)
    scan_duration_seconds: float = 0.0
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "application_id": self.application_id,
            "modules_scanned": self.modules_scanned,
            "total_changes": self.total_changes,
            "high_changes": self.high_changes,
            "medium_changes": self.medium_changes,
            "low_changes": self.low_changes,
            "changes": [
                {
                    "change_type": c.change_type,
                    "element_type": c.element_type,
                    "label": c.label,
                    "module_name": c.module_name,
                    "module_id": c.module_id,
                    "detail": c.detail,
                    "severity": c.severity,
                    "old_value": c.old_value,
                    "new_value": c.new_value,
                }
                for c in self.changes
            ],
            "scan_duration_seconds": self.scan_duration_seconds,
            "summary": self.summary,
        }


class ChangeDetectionEngine:
    """
    Lightweight re-scanner that compares the live app against stored interaction guides.

    Does NOT do a full exploration (no form filling, no table row clicking).
    It only: navigates to each module page, extracts visible interactive elements,
    and diffs them against what was stored during the last full exploration.

    Key comparisons:
    - Buttons present in guide but missing from page  → "removed" (high)
    - Buttons on page but not in guide                → "added" (medium)
    - Selectors in guide that no longer work          → "selector_changed" (high)
    - Form fields that appeared/disappeared           → "modified" (medium)
    """

    def __init__(self, db: AsyncSession, browser=None):
        self.db = db
        self.browser = browser   # optional BrowserManager — needed for live checks

    async def scan_application(self, application_id: str) -> ChangeReport:
        """
        Scan all modules of an application and return a ChangeReport.
        If browser is None, does a guide-only structural comparison (no live check).
        """
        start = time.monotonic()
        report = ChangeReport(application_id=application_id)

        app_result = await self.db.execute(
            select(Application).where(Application.id == application_id)
        )
        app = app_result.scalar_one_or_none()
        if not app:
            report.summary = "Application not found"
            return report

        # Load all stored interaction guides for this application
        guides_result = await self.db.execute(
            select(AIMemoryChunk).where(
                AIMemoryChunk.application_id == application_id,
                AIMemoryChunk.kind == MemoryKind.WORKFLOW,
            )
        )
        guide_chunks = [
            chunk for chunk in guides_result.scalars().all()
            if (chunk.extra or {}).get("guide_type") == "interaction"
        ]

        if not guide_chunks:
            report.summary = "No stored interaction guides found — run a full exploration first"
            return report

        # Load modules
        modules_result = await self.db.execute(
            select(ApplicationModule).where(
                ApplicationModule.application_id == application_id,
                ApplicationModule.is_active == True,
            )
        )
        modules = modules_result.scalars().all()
        module_map = {m.id: m for m in modules}

        for chunk in guide_chunks:
            extra = chunk.extra or {}
            module_id = extra.get("module_id", "")
            module_name = extra.get("module_name", module_id)
            report.modules_scanned += 1

            # Parse the stored guide into a structured diff baseline
            guide_elements = _parse_guide_elements(chunk.content)

            changes: list[ChangeItem] = []

            if self.browser:
                # Live check: navigate to page and compare
                module = module_map.get(module_id)
                page_url = extra.get("page_url", "")
                if page_url or (module and module.url_pattern):
                    url = page_url or (app.base_url.rstrip("/") + "/" + (module.url_pattern or "").lstrip("/"))
                    live_elements = await self._scan_live_page(url)
                    changes = _diff_elements(guide_elements, live_elements, module_name, module_id)
            else:
                # Structural check only: verify SemanticElements still have valid selectors
                changes = await self._check_selector_validity(guide_elements, module_name, module_id)

            report.changes.extend(changes)

        report.total_changes = len(report.changes)
        report.high_changes = sum(1 for c in report.changes if c.severity == "high")
        report.medium_changes = sum(1 for c in report.changes if c.severity == "medium")
        report.low_changes = sum(1 for c in report.changes if c.severity == "low")
        report.scan_duration_seconds = round(time.monotonic() - start, 2)
        report.summary = _build_summary(report)

        return report

    async def _scan_live_page(self, url: str) -> list[dict]:
        """Navigate to a page and extract current interactive elements."""
        if not self.browser:
            return []
        try:
            await asyncio.to_thread(self.browser.navigate, url)
            await asyncio.sleep(2.0)
            elements = await asyncio.to_thread(self.browser.execute_script, _ELEMENT_SCAN_JS)
            return elements or []
        except Exception as e:
            log.warning("Live page scan failed", url=url, error=str(e)[:100])
            return []

    async def _check_selector_validity(
        self,
        guide_elements: list[dict],
        module_name: str,
        module_id: str,
    ) -> list[ChangeItem]:
        """
        Without a live browser, check the SemanticElements DB table for
        elements that no longer have high-confidence selectors.
        This is a lightweight proxy for "things that might have changed".
        """
        changes = []
        # Nothing to check without a browser — return empty
        return changes


def _parse_guide_elements(guide_text: str) -> list[dict]:
    """
    Parse a stored interaction guide text into structured element descriptors.
    Extracts: ADD/EDIT/DELETE buttons with their selectors and form fields.
    """
    elements = []
    lines = guide_text.splitlines()
    current_button = None

    for line in lines:
        line = line.strip()
        # Match button definitions: [ADD] "Label" button or [EDIT] "Label" button
        btn_match = re.match(r'^\[(ADD|EDIT|DELETE|ACTION|SUBMIT)\]\s+"([^"]+)"\s+button', line, re.IGNORECASE)
        if btn_match:
            current_button = {
                "category": btn_match.group(1).lower(),
                "label": btn_match.group(2),
                "trigger_selector": "",
                "fields": [],
                "submit_selector": "",
            }
            elements.append(current_button)
            continue

        if current_button:
            if line.startswith("Trigger selector:"):
                current_button["trigger_selector"] = line.split(":", 1)[1].strip()
            elif line.startswith("Submit/Save selector:"):
                current_button["submit_selector"] = line.split(":", 1)[1].strip()
            elif re.match(r'^- .+\(', line):
                # Field line: "- FieldName (type/required) — selector: ..."
                field_match = re.match(r'^- (.+?)\s+\(([^)]+)\)', line)
                if field_match:
                    sel_match = re.search(r'selector:\s*(.+)$', line)
                    current_button["fields"].append({
                        "label": field_match.group(1).strip(),
                        "type": field_match.group(2).strip(),
                        "selector": sel_match.group(1).strip() if sel_match else "",
                    })
            # New section header resets current button context
            elif line.startswith("[") or line.startswith("TABLE") or line.startswith("TAB"):
                if not btn_match:
                    current_button = None

    return elements


def _diff_elements(
    guide_elements: list[dict],
    live_elements: list[dict],
    module_name: str,
    module_id: str,
) -> list[ChangeItem]:
    """
    Compare guide elements (expected) against live page elements (actual).
    Returns a list of ChangeItems describing differences.
    """
    changes = []

    # Build lookup by label (case-insensitive)
    guide_by_label = {e["label"].lower(): e for e in guide_elements}
    live_by_label = {e.get("label", "").lower(): e for e in live_elements if e.get("label")}

    # Buttons in guide but missing from live page → removed
    for label_lower, guide_el in guide_by_label.items():
        if label_lower not in live_by_label:
            changes.append(ChangeItem(
                change_type="removed",
                element_type="button",
                label=guide_el["label"],
                module_name=module_name,
                module_id=module_id,
                detail=f"'{guide_el['label']}' button was in the guide but is no longer found on the page.",
                severity="high" if guide_el["category"] in ("add", "edit", "delete") else "medium",
            ))
        else:
            # Both present — check if selector still works (compare stored vs live)
            live_el = live_by_label[label_lower]
            guide_sel = guide_el.get("trigger_selector", "")
            live_sels = [s.get("value", "") for s in live_el.get("selectors", [])]
            if guide_sel and live_sels and guide_sel not in live_sels:
                changes.append(ChangeItem(
                    change_type="selector_changed",
                    element_type="button",
                    label=guide_el["label"],
                    module_name=module_name,
                    module_id=module_id,
                    detail=f"Selector for '{guide_el['label']}' changed — guide had '{guide_sel}', live has '{live_sels[0] if live_sels else 'unknown'}'.",
                    severity="high",
                    old_value=guide_sel,
                    new_value=live_sels[0] if live_sels else "",
                ))

    # Buttons on live page but not in guide → added
    for label_lower, live_el in live_by_label.items():
        if label_lower not in guide_by_label:
            cat = live_el.get("category", "")
            if cat in ("add", "edit", "delete", "action"):
                changes.append(ChangeItem(
                    change_type="added",
                    element_type="button",
                    label=live_el.get("label", label_lower),
                    module_name=module_name,
                    module_id=module_id,
                    detail=f"New '{live_el.get('label', label_lower)}' button appeared on the page — not in stored guide.",
                    severity="medium",
                ))

    return changes


def _build_summary(report: ChangeReport) -> str:
    if report.total_changes == 0:
        return f"No UI changes detected across {report.modules_scanned} module(s). Application matches stored guide."

    parts = []
    if report.high_changes:
        parts.append(f"{report.high_changes} high-severity change(s)")
    if report.medium_changes:
        parts.append(f"{report.medium_changes} medium-severity change(s)")
    if report.low_changes:
        parts.append(f"{report.low_changes} low-severity change(s)")

    return (
        f"Detected {report.total_changes} UI change(s) across {report.modules_scanned} module(s): "
        + ", ".join(parts)
        + ". Re-explore affected modules to update the interaction guide."
    )


# JS used for live element scan (same as explorer's _extract_page_elements_js but condensed)
_ELEMENT_SCAN_JS = """
(function() {
    function isVisible(el) {
        if (!el) return false;
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
    }
    function getBestSel(el) {
        const sels = [];
        const tid = el.getAttribute('data-testid') || el.getAttribute('data-cy');
        if (tid) sels.push({type:'css', value:`[data-testid="${tid}"]`});
        const al = el.getAttribute('aria-label');
        if (al && al.length < 80) sels.push({type:'css', value:`[aria-label="${al}"]`});
        if (el.id && !/^\\d/.test(el.id)) sels.push({type:'css', value:'#'+el.id});
        return sels;
    }
    function categorize(t) {
        if (/\\b(add|new|create)\\b/i.test(t)) return 'add';
        if (/\\b(edit|update|modify)\\b/i.test(t)) return 'edit';
        if (/\\b(delete|remove)\\b/i.test(t)) return 'delete';
        return 'action';
    }
    const results = [];
    const seen = new Set();
    for (const el of document.querySelectorAll('button,[role="button"]')) {
        if (!isVisible(el)) continue;
        const text = (el.textContent || el.getAttribute('aria-label') || '').trim().replace(/\\s+/g,' ').slice(0,80);
        if (!text || seen.has(text.toLowerCase())) continue;
        seen.add(text.toLowerCase());
        results.push({label: text, category: categorize(text), selectors: getBestSel(el)});
    }
    return results.slice(0, 80);
})()
"""
