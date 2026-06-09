"""
GuideSelectorCache — runtime bridge between exploration and execution.

During exploration, the explorer discovers EXACT CSS selectors for every
button, field, icon, tab, and pattern on each page, and stores them in
the interaction guide (AIMemoryChunk kind=WORKFLOW guide_type=interaction).

During execution, the PlanRunner uses this cache to look up a step's
semantic target label against the stored selectors, bypassing the
10-strategy self-healing cascade when a match is found.

Flow:
  Exploration  →  interaction guide text  →  AIMemoryChunk (DB)
  Execution    →  GuideSelectorCache.from_guide_text()  →  PlanRunner._guide_selector()
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


_FILLER_SUFFIX = re.compile(
    r'\s+(button|field|input|tab|icon|link|checkbox|dropdown|select|list)\s*$',
    re.IGNORECASE,
)


def _normalize(label: str) -> str:
    return re.sub(r'\s+', ' ', label.strip().lower())


def _add(entries: dict, label: str, selector: str) -> None:
    if selector and selector.strip() and label:
        entries[_normalize(label)] = selector.strip()


def _parse_guide_selectors(guide_text: str) -> dict[str, str]:
    """
    Parse all selector hints from an interaction guide into {normalized_label: css_selector}.

    Handles every section produced by _store_interaction_guide:
      [ADD/EDIT/DELETE] "Label" button
        Trigger selector: …
        Form fields:
          - Field (type) — selector: …
        Submit/Save selector: …
        Cancel selector: …
      ACTION COLUMN ICONS:
        EDIT: "Edit" — selector: …
      STATUS WORKFLOW TABS:
        Tab: "Pending" — selector: …
      BULK DELETE PATTERN:
        Step [click_checkbox]: … — selector: …
      APPROVAL WORKFLOW:
        Approve action: "Approve" — selector: …
      SEARCH NO-RESULTS STATE:
        Search input selector: …
        Search button selector: …
    """
    entries: dict[str, str] = {}

    section = "none"      # which top-level section we're in
    current_btn_label = ""
    in_fields = False

    for line in guide_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        # ── Detect section header changes ──────────────────────────────────
        if stripped.startswith("ACTION COLUMN ICONS"):
            section = "icons"; in_fields = False; continue
        if stripped.startswith("STATUS WORKFLOW TABS"):
            section = "tabs"; in_fields = False; continue
        if stripped.startswith("BULK DELETE PATTERN"):
            section = "bulk_delete"; in_fields = False; continue
        if stripped.startswith("APPROVAL WORKFLOW"):
            section = "approve"; in_fields = False; continue
        if stripped.startswith("SEARCH NO-RESULTS STATE"):
            section = "search"; in_fields = False; continue

        # [ADD/EDIT/DELETE] "Label" button — starts a new button block
        btn_m = re.match(
            r'^\[(ADD|EDIT|DELETE|ACTION|SUBMIT)\]\s+"([^"]+)"\s+button',
            stripped, re.IGNORECASE,
        )
        if btn_m:
            section = "button"
            current_btn_label = btn_m.group(2)
            in_fields = False
            continue

        # ── Button block inner lines ───────────────────────────────────────
        if section == "button":
            if stripped.startswith("Trigger selector:"):
                sel = stripped.split(":", 1)[1].strip()
                _add(entries, current_btn_label, sel)
                _add(entries, current_btn_label + " button", sel)

            elif stripped.startswith("Submit/Save selector:"):
                sel = stripped.split(":", 1)[1].strip()
                for lbl in ("save", "submit", "save button", "submit button",
                            "create button", "confirm", "confirm button", "ok", "ok button", "apply"):
                    _add(entries, lbl, sel)

            elif stripped.startswith("Cancel selector:"):
                sel = stripped.split(":", 1)[1].strip()
                _add(entries, "cancel", sel)
                _add(entries, "cancel button", sel)
                _add(entries, "close", sel)

            elif stripped == "Form fields:":
                in_fields = True

            elif stripped.startswith(("Validation rules", "Opens:", "SUCCESS INDICATOR",
                                       "AFTER CREATE", "NOTE:")):
                in_fields = False

            elif in_fields and stripped.startswith("- "):
                # "- FieldName (type, required) validation-error='…' — selector: …"
                field_m = re.match(r'^- (.+?)\s+\(', stripped)
                sel_m = re.search(r'selector:\s*(.+)$', stripped)
                if field_m and sel_m:
                    lbl = field_m.group(1).strip()
                    sel = sel_m.group(1).strip()
                    _add(entries, lbl, sel)
                    _add(entries, lbl + " field", sel)
                    _add(entries, lbl + " input", sel)

            # Any new section header resets
            elif stripped.startswith("[") or stripped.startswith("TABLE") or stripped.startswith("TAB:"):
                section = "none"; in_fields = False

        # ── ACTION COLUMN ICONS ───────────────────────────────────────────
        elif section == "icons":
            # "  EDIT: "Edit" — selector: [aria-label="Edit"]"
            icon_m = re.match(
                r'^(EDIT|DELETE|APPROVE|VIEW|REJECT):\s+"([^"]+)"(?:\s*[—-]\s*selector:\s*(.+))?$',
                stripped, re.IGNORECASE,
            )
            if icon_m:
                action_type = icon_m.group(1).lower()
                label = icon_m.group(2)
                sel = (icon_m.group(3) or "").strip()
                if sel:
                    for lbl in (action_type, action_type + " button", action_type + " icon", label):
                        _add(entries, lbl, sel)

        # ── STATUS WORKFLOW TABS ──────────────────────────────────────────
        elif section == "tabs":
            # "  Tab: "Pending" — selector: …"
            tab_m = re.match(
                r'^Tab:\s+"([^"]+)"(?:\s*[—-]\s*selector:\s*(.+))?',
                stripped, re.IGNORECASE,
            )
            if tab_m:
                label = tab_m.group(1)
                sel = (tab_m.group(2) or "").strip()
                if sel:
                    _add(entries, label, sel)
                    _add(entries, label + " tab", sel)

        # ── BULK DELETE PATTERN ───────────────────────────────────────────
        elif section == "bulk_delete":
            # "  Step [click_checkbox]: … — selector: …"
            step_m = re.match(
                r'^Step\s+\[([^\]]+)\]:\s+.*?[—-]\s*selector:\s*(.+)$',
                stripped, re.IGNORECASE,
            )
            if step_m:
                action_key = step_m.group(1).lower()
                sel = step_m.group(2).strip()
                if "checkbox" in action_key:
                    for lbl in ("row checkbox", "checkbox", "select row", "select checkbox"):
                        _add(entries, lbl, sel)
                elif "button" in action_key or "click_button" in action_key:
                    for lbl in ("actions", "actions button", "bulk actions", "actions menu"):
                        _add(entries, lbl, sel)
                elif "menu" in action_key or "item" in action_key:
                    for lbl in ("bulk delete", "delete from menu", "delete menu item"):
                        _add(entries, lbl, sel)

        # ── APPROVAL WORKFLOW ─────────────────────────────────────────────
        elif section == "approve":
            # "  Approve action: "Approve" — selector: …"
            appr_m = re.match(
                r'^Approve action:\s+"([^"]+)"(?:\s*[—-]\s*selector:\s*(.+))?',
                stripped, re.IGNORECASE,
            )
            if appr_m:
                label = appr_m.group(1)
                sel = (appr_m.group(2) or "").strip()
                if sel:
                    for lbl in ("approve", "approve button", "accept", "accept button", label):
                        _add(entries, lbl, sel)

        # ── SEARCH NO-RESULTS STATE ───────────────────────────────────────
        elif section == "search":
            if stripped.startswith("Search input selector:"):
                sel = stripped.split(":", 1)[1].strip()
                for lbl in ("search", "search input", "search field", "search bar",
                            "filter", "filter input", "find input"):
                    _add(entries, lbl, sel)
            elif stripped.startswith("Search button selector:"):
                sel = stripped.split(":", 1)[1].strip()
                _add(entries, "search button", sel)
                _add(entries, "go button", sel)

    return entries


@dataclass
class GuideSelectorCache:
    """
    Fast {label → CSS selector} lookup built from exploration interaction guides.

    Build once per test run:
        cache = GuideSelectorCache.from_multiple(list_of_guide_texts)

    Use in PlanRunner:
        sel = cache.lookup("Delete button")   # → "[aria-label='Delete']" or None
    """
    _entries: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_guide_text(cls, guide_text: str) -> GuideSelectorCache:
        obj = cls()
        obj._entries = _parse_guide_selectors(guide_text)
        return obj

    @classmethod
    def from_multiple(cls, guide_texts: list[str]) -> GuideSelectorCache:
        obj = cls()
        for text in guide_texts:
            obj._entries.update(_parse_guide_selectors(text))
        return obj

    def lookup(self, target: str) -> str | None:
        """
        Return a CSS selector for the given semantic target label.
        Tries: exact → without filler suffix → substring match.
        Returns None if no match (caller falls back to self-healing).
        """
        if not target or not self._entries:
            return None

        norm = _normalize(target)

        # 1. Exact match
        if norm in self._entries:
            return self._entries[norm]

        # 2. Strip common trailing filler words
        stripped = _FILLER_SUFFIX.sub("", norm).strip()
        if stripped and stripped != norm and stripped in self._entries:
            return self._entries[stripped]

        # 3. Partial: target label is contained in a stored key or vice-versa
        for key, sel in self._entries.items():
            if norm in key or key in norm:
                return sel

        return None

    def __len__(self) -> int:
        return len(self._entries)

    def __bool__(self) -> bool:
        return bool(self._entries)
