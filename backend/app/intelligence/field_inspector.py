"""
FieldInspector — AI-native dynamic field interaction engine.

Handles every modern web form field type intelligently:
  • Native <select>
  • Custom dropdown buttons  (Headless UI, Radix, custom React)
  • ARIA combobox / listbox
  • React-Select, Select2, Ant Design, Material UI, ShadCN, Mantine
  • Angular Material (mat-select, mat-autocomplete)
  • Portal-based dropdowns (options rendered outside parent DOM)
  • Virtualized / lazy-loaded lists (scroll to reveal more options)
  • Searchable dropdowns (type to filter)
  • Radio groups, checkbox groups

Interaction flow
  ─────────────────────────────────────────────────────────────────
  detect field type → identify trigger → click/open dropdown
  → observe DOM mutations → discover options globally
  → match option semantically → click → validate selection

Returns structured interaction metadata:
  {
    "fieldType": "dynamic_dropdown",
    "trigger": "...",
    "optionStrategy": "...",
    "selectionMethod": "semantic_text_match",
    "fallbacks": [...]
  }

Design goals
  ─────────────────────────────────────────────────────────────────
  Project-agnostic  — no assumptions about CSS class names or frameworks.
  Self-contained    — depends only on Selenium and Python stdlib.
  Composable        — ExploreEngine and PlanRunner both import it.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

log = structlog.get_logger()

# ── Container selectors — ordered by specificity ─────────────────────────────
_CONTAINER_SELECTORS = [
    # ARIA roles (framework-agnostic)
    '[role="listbox"]',
    '[role="menu"]',
    '[role="tree"]',
    '[role="combobox"][aria-expanded="true"]',
    # ── Custom portal data-attribute patterns (observed in the wild) ──────────
    '[data-select-portal]',
    '[data-select-portal="true"]',
    '[data-portal-dropdown]',
    '[data-portal-dropdown="true"]',
    '[data-dropdown-portal]',
    '[data-listbox-portal]',
    '[data-combobox-portal]',
    # Headless UI / Radix / Floating UI portals
    '[data-headlessui-state="open"]',
    '[data-radix-popper-content-wrapper]',
    '[data-floating-ui-portal]',
    '[data-state="open"]',
    # ShadCN / Radix
    '[cmdk-list]',
    '[data-radix-select-content]',
    # React Select
    '.react-select__menu',
    '.react-select__menu-list',
    '[class*="react-select__menu"]',
    # Angular Material
    '.mat-select-panel',
    '.mat-autocomplete-panel',
    '.mat-option',
    'mat-option',
    '.cdk-overlay-container .mat-select-panel',
    '.cdk-overlay-pane',
    '.cdk-overlay-container',
    # Ant Design
    '.ant-select-dropdown',
    '.ant-dropdown',
    # MUI
    '.MuiMenu-root',
    '.MuiPopover-root',
    '.MuiAutocomplete-popper',
    '.MuiPaper-root[role="presentation"]',
    # Bootstrap / general
    '.dropdown-menu.show',
    '.dropdown-menu[class*="show"]',
    '[class*="dropdown-menu"]:not([class*="btn"])',
    # Generic library patterns
    '.select2-dropdown',
    '[class*="popover-content"]',
    '[class*="menu-list"]',
    '[class*="options-list"]',
    '[class*="listbox"]',
    '[class*="options-container"]',
    '[class*="suggestion-list"]',
    '[class*="autocomplete"]',
    # Portal elements appended to <body>
    'body > [style*="position: absolute"]',
    'body > [style*="position:absolute"]',
    'body > [style*="position: fixed"]',
    'body > div[id]:not([id="root"]):not([id="app"])',
]

# ── Option item selectors ─────────────────────────────────────────────────────
_OPTION_SELECTORS = [
    # ARIA
    '[role="option"]',
    '[role="menuitem"]',
    '[role="treeitem"]',
    '[role="row"]',
    # ── Portal dropdown items (data-portal-dropdown pattern) ──────────────────
    '[data-portal-dropdown] > div',
    '[data-portal-dropdown="true"] > div',
    '[data-select-portal] div[class*="cursor-pointer"]',
    # Angular Material
    'mat-option',
    '.mat-option',
    '.mat-option-text',
    # React Select
    '.react-select__option',
    '[class*="react-select__option"]',
    # Ant Design
    '.ant-select-item-option',
    '.ant-select-item',
    # MUI
    '.MuiMenuItem-root',
    '.MuiListItem-root',
    '.MuiAutocomplete-option',
    # ShadCN / cmdk
    '[cmdk-item]',
    '[data-radix-select-item]',
    # Generic
    'li[class*="option"]',
    'li[class*="item"]',
    'li[class*="result"]',
    '[class*="option-item"]',
    '[class*="select-item"]',
    '[class*="list-item"]',
    '[class*="dropdown-item"]',
    '[class*="menu-item"]',
    '[class*="suggestion-item"]',
]

# Common UI noise and placeholder patterns
_NOISE: frozenset[str] = frozenset({
    "", "select", "choose", "pick", "search", "filter", "clear", "none",
    "cancel", "close", "ok", "yes", "no", "back", "next", "submit", "reset",
    "loading", "loading...", "no options", "no results", "no data",
    "-- select --", "-- choose --", "-- none --",
})

# Prefixes that mark placeholder/instruction text (not real option values)
_PLACEHOLDER_PREFIXES = (
    "select ", "choose ", "pick ", "-- select", "-- choose",
    "please select", "please choose", "search for", "type to search",
    "start typing",
)


def _is_placeholder(text: str) -> bool:
    """Return True if text looks like a UI placeholder rather than a real option."""
    t = text.strip().lower()
    if t in _NOISE:
        return True
    return any(t.startswith(p) for p in _PLACEHOLDER_PREFIXES)


@dataclass
class FieldOption:
    label: str
    value: str
    index: int
    element: Any = field(default=None, repr=False)
    is_placeholder: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "value": self.value,
            "index": self.index,
            "is_placeholder": self.is_placeholder,
        }


@dataclass
class DropdownInteraction:
    """Structured metadata about how a dropdown was interacted with."""
    field_type: str = "unknown"           # native_select | angular_material | react_select | mui | custom
    trigger_strategy: str = "unknown"    # click | aria_expand | keyboard
    option_strategy: str = "unknown"     # aria_option | li_item | portal | virtualized | searchable
    selection_method: str = "unknown"    # exact_match | partial_match | semantic_match
    fallbacks_used: list[str] = field(default_factory=list)
    options_found: int = 0
    selected_label: str = ""
    success: bool = False

    def to_dict(self) -> dict:
        return {
            "fieldType": self.field_type,
            "trigger": self.trigger_strategy,
            "optionStrategy": self.option_strategy,
            "selectionMethod": self.selection_method,
            "fallbacks": self.fallbacks_used,
            "optionsFound": self.options_found,
            "selectedLabel": self.selected_label,
            "success": self.success,
        }


class FieldInspector:
    """
    AI-native dynamic field interaction engine.
    Handles every type of modern web form field intelligently.
    """

    def __init__(self, driver: webdriver.Chrome):
        self.driver = driver

    # ── Public API ────────────────────────────────────────────────────────────

    def get_options(self, element) -> list[FieldOption]:
        """Return all options for a field element (opens dropdown if needed)."""
        try:
            ftype = self._detect_type(element)
            if ftype == "native_select":
                return self._native_options(element)
            if ftype == "radio_group":
                return self._radio_options(element)
            return self._smart_open_and_collect(element, close_after=True)
        except Exception as e:
            log.debug("FieldInspector.get_options failed", error=str(e))
            return []

    def select_option(self, element, label: str) -> bool:
        """
        Select option matching `label` in the given field.
        Returns True on success.
        """
        try:
            ftype = self._detect_type(element)
            if ftype == "native_select":
                return self._native_select(element, label)
            if ftype == "radio_group":
                return self._radio_select(element, label)
            result = self.smart_select(element, label)
            return result.success
        except Exception as e:
            log.debug("FieldInspector.select_option failed", label=label, error=str(e))
            return False

    def select_by_label_text(self, field_label: str, option_label: str) -> bool:
        """
        Convenience: find a field by its visible label text, then select an option.
        """
        trigger = self._find_trigger_by_label(field_label)
        if trigger is None:
            return False
        return self.select_option(trigger, option_label)

    def smart_select(self, trigger, label: str) -> DropdownInteraction:
        """
        Full AI-native interaction flow with structured result metadata.
        Strategy waterfall:
          1. Detect field type
          2. Open the dropdown using the best strategy
          3. Discover options (global DOM scan incl. portals)
          4. Match option semantically (exact → partial → semantic)
          5. Click and validate
        """
        interaction = DropdownInteraction()
        ftype = self._detect_type(trigger)
        interaction.field_type = ftype

        # --- Native select ---
        if ftype == "native_select":
            interaction.trigger_strategy = "native"
            interaction.option_strategy = "native_select"
            ok = self._native_select(trigger, label)
            if ok:
                interaction.selection_method = "native_text_match"
                interaction.selected_label = label
                interaction.success = True
            return interaction

        # --- Angular Material mat-select ---
        if ftype == "angular_material":
            interaction.trigger_strategy = "click"
            ok = self._angular_material_select(trigger, label, interaction)
            return interaction

        # --- React Select ---
        if ftype == "react_select":
            interaction.trigger_strategy = "click"
            ok = self._react_select_select(trigger, label, interaction)
            return interaction

        # --- Custom / generic ---
        interaction.trigger_strategy = "click"
        options = self._smart_open_and_collect(trigger, close_after=False)
        interaction.options_found = len(options)

        real_options = [o for o in options if not o.is_placeholder]

        # If no options appeared, try searchable dropdown (type label to filter)
        if not real_options:
            interaction.fallbacks_used.append("searchable_type")
            ok = self._try_searchable_select(trigger, label, interaction)
            if ok:
                return interaction

        matched = self._semantic_match(real_options, label)
        if matched:
            interaction.option_strategy = "semantic_match"
            ok = self._click_option(matched)
            if ok:
                interaction.selection_method = "semantic_text_match"
                interaction.selected_label = matched.label
                interaction.success = True
                return interaction

        # Fallback: JS text click (handles stale element refs)
        interaction.fallbacks_used.append("js_text_click")
        ok = self._js_click_by_text(label.lower().strip())
        if ok:
            interaction.selection_method = "js_text_match"
            interaction.selected_label = label
            interaction.success = True
            return interaction

        # Fallback: CDP accessibility tree
        interaction.fallbacks_used.append("cdp_accessibility")
        ok = self._cdp_click_text(label)
        if ok:
            interaction.selection_method = "cdp_accessibility"
            interaction.selected_label = label
            interaction.success = True
            return interaction

        self._close(trigger)
        return interaction

    def get_all_page_fields(self) -> list[dict[str, Any]]:
        """
        Scan the entire current page and return every interactive field
        with its type, label, and available options.
        """
        fields: list[dict[str, Any]] = []

        # 1. Native <select> elements
        for el in self._visible_elements("select"):
            opts = self._native_options(el)
            if opts:
                fields.append({
                    "type": "native_select",
                    "label": self._label_for(el),
                    "options": [o.to_dict() for o in opts],
                    "selector": self._css_selector(el),
                })

        # 2. Angular Material mat-select
        for el in self._visible_elements("mat-select, [class*='mat-select']"):
            lbl = self._label_for(el) or self._text(el)[:60]
            if not lbl:
                continue
            opts = self._smart_open_and_collect(el, close_after=True)
            if opts:
                fields.append({
                    "type": "angular_material",
                    "label": lbl,
                    "options": [o.to_dict() for o in opts if not o.is_placeholder],
                    "selector": self._css_selector(el),
                })

        # 3. Custom dropdown triggers (buttons / comboboxes / aria-haspopup elements)
        for trigger in self._find_custom_triggers():
            lbl = self._label_for(trigger) or self._text(trigger)[:60]
            if not lbl:
                continue
            opts = self._smart_open_and_collect(trigger, close_after=True)
            if opts:
                fields.append({
                    "type": "custom_dropdown",
                    "label": lbl,
                    "options": [o.to_dict() for o in opts if not o.is_placeholder],
                    "selector": self._css_selector(trigger),
                    "trigger_text": self._text(trigger)[:60],
                })

        # 4. Radio groups
        for group_label, options in self._collect_radio_groups().items():
            fields.append({
                "type": "radio_group",
                "label": group_label,
                "options": [
                    {"label": o, "value": o, "index": i} for i, o in enumerate(options)
                ],
                "selector": f'input[type="radio"][name="{group_label}"]',
            })

        return fields

    # ── Field-type detection ──────────────────────────────────────────────────

    def _detect_type(self, el) -> str:
        try:
            tag = el.tag_name.lower()
            role = (el.get_attribute("role") or "").lower()
            itype = (el.get_attribute("type") or "").lower()
            cls = (el.get_attribute("class") or "").lower()

            if tag == "select":
                return "native_select"
            if tag == "input" and itype == "radio":
                return "radio_group"
            # Angular Material
            if tag in ("mat-select",) or "mat-select" in cls or "mat-form-field" in cls:
                return "angular_material"
            # React Select
            if "react-select" in cls or el.get_attribute("data-react-select"):
                return "react_select"
            # MUI
            if "MuiSelect" in (el.get_attribute("class") or "") or "MuiInputBase" in (el.get_attribute("class") or ""):
                return "mui_select"
            # ARIA combobox/listbox
            if role in ("listbox", "combobox", "menu"):
                return "custom_dropdown"
            # Any trigger-like element
            if tag in ("button", "div", "span", "a") and (
                el.get_attribute("aria-haspopup")
                or el.get_attribute("aria-expanded") is not None
                or el.get_attribute("data-headlessui-state") is not None
                or el.get_attribute("data-state") is not None
            ):
                return "custom_dropdown"
        except Exception:
            pass
        return "custom_dropdown"

    # ── Smart open + collect ──────────────────────────────────────────────────

    def _smart_open_and_collect(self, trigger, close_after: bool = True) -> list[FieldOption]:
        """
        Full dynamic option discovery:
          1. Snapshot DOM state before open
          2. Click/open trigger using best strategy
          3. Poll up to 5s for DOM mutations — portal data-attrs first, then container diff
          4. Scan globally including portals and Angular CDK overlay
          5. Scroll to handle virtualized lists
          6. Close if requested
        """
        before_containers = self._visible_containers()
        before_ids = {self._el_id(e) for e in before_containers}

        # Open the trigger
        self._open_trigger(trigger)

        options: list[FieldOption] = []
        deadline = time.monotonic() + 5.0

        while time.monotonic() < deadline:
            time.sleep(0.15)

            # Priority 1: data-portal-dropdown attribute scan (handles YLIMS-style portals
            # and any custom framework that uses data-portal-dropdown on its container)
            portal_opts = self._scan_portal_data_attributes()
            if portal_opts:
                options = portal_opts
                break

            # Priority 2: new container detection (React Select, Material UI, etc.)
            after_containers = self._visible_containers()
            new_containers = [
                c for c in after_containers
                if self._el_id(c) not in before_ids
            ]

            if new_containers:
                opts = self._options_from_containers(new_containers)
                if opts:
                    options = self._scroll_to_load_more(new_containers, opts)
                    break

        # Global portal scan — catches Angular CDK overlay and body-appended portals
        if not options:
            options = self._scan_all_portals()

        # Angular CDK overlay (special case — appended to body, outside app root)
        if not options:
            options = self._scan_angular_cdk_overlay()

        # Last resort: full-page inline option scan (kept outside the loop to avoid
        # returning unrelated page elements while the dropdown is still rendering)
        if not options:
            options = self._inline_option_items()

        if close_after:
            self._close(trigger)

        return options

    def _open_trigger(self, trigger):
        """Open a dropdown trigger using the most appropriate strategy."""
        try:
            tag = trigger.tag_name.lower()
            role = (trigger.get_attribute("role") or "").lower()
        except Exception:
            self._click_safely(trigger)
            return

        # For Angular Material mat-select, click the trigger or panel open
        if tag == "mat-select" or "mat-select" in (trigger.get_attribute("class") or "").lower():
            self._click_safely(trigger)
            return

        # For ARIA combobox, try keyboard first (Down arrow opens many)
        if role == "combobox":
            try:
                trigger.click()
                time.sleep(0.1)
                trigger.send_keys(Keys.ARROW_DOWN)
                return
            except Exception:
                pass

        # Default: JS click (avoids scroll-to-view issues)
        self._click_safely(trigger)

    # ── Angular Material specific ─────────────────────────────────────────────

    def _angular_material_select(self, trigger, label: str, meta: DropdownInteraction) -> bool:
        """Handle Angular Material mat-select dropdowns."""
        self._click_safely(trigger)
        time.sleep(0.5)

        # Options appear inside .cdk-overlay-container as mat-option elements
        options: list[FieldOption] = []
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            time.sleep(0.15)
            options = self._collect_mat_options()
            if options:
                break

        if not options:
            options = self._scan_angular_cdk_overlay()

        meta.options_found = len(options)
        real = [o for o in options if not o.is_placeholder]

        matched = self._semantic_match(real, label)
        if matched:
            ok = self._click_option(matched)
            if ok:
                meta.option_strategy = "angular_mat_option"
                meta.selection_method = "semantic_text_match"
                meta.selected_label = matched.label
                meta.success = True
                return True

        self._close(trigger)
        return False

    def _collect_mat_options(self) -> list[FieldOption]:
        """Collect mat-option elements from the Angular CDK overlay."""
        raw = self.driver.execute_script("""
            const NOISE = arguments[0];
            const PLACEHOLDERS = arguments[1];
            const seen = new Set();
            const results = [];

            function isPlaceholder(t) {
                const tl = t.toLowerCase().trim();
                return NOISE.includes(tl) || PLACEHOLDERS.some(p => tl.startsWith(p));
            }

            // mat-option, .mat-option, [class*="mat-option"]
            const sels = [
                'mat-option', '.mat-option', '[class*="mat-option"]',
                '.mat-mdc-option', '[class*="mdc-list-item"]',
            ];
            for (const sel of sels) {
                try {
                    for (const el of document.querySelectorAll(sel)) {
                        const r = el.getBoundingClientRect();
                        const s = getComputedStyle(el);
                        if (r.width <= 0 || r.height <= 0) continue;
                        const text = (el.textContent || '').trim().replace(/\\s+/g, ' ');
                        if (!text || text.length > 200 || seen.has(text)) continue;
                        seen.add(text);
                        results.push({
                            label: text,
                            value: el.getAttribute('data-value') || el.getAttribute('ng-reflect-value') || text,
                            is_placeholder: isPlaceholder(text),
                        });
                    }
                } catch(e) {}
            }
            return results;
        """, list(_NOISE), list(_PLACEHOLDER_PREFIXES)) or []

        return [
            FieldOption(r["label"], r["value"], i, is_placeholder=r.get("is_placeholder", False))
            for i, r in enumerate(raw)
        ]

    def _scan_angular_cdk_overlay(self) -> list[FieldOption]:
        """Scan the Angular CDK overlay container for option items."""
        raw = self.driver.execute_script("""
            const NOISE = arguments[0];
            const PLACEHOLDERS = arguments[1];
            const seen = new Set();
            const results = [];

            function isPlaceholder(t) {
                const tl = t.toLowerCase().trim();
                return NOISE.includes(tl) || PLACEHOLDERS.some(p => tl.startsWith(p));
            }

            const overlayRoot = document.querySelector('.cdk-overlay-container');
            if (!overlayRoot) return results;

            // Try specific Angular option selectors first
            const optionSels = [
                'mat-option', '.mat-option', '[class*="mat-option"]',
                '[role="option"]', '[role="menuitem"]', 'li',
            ];
            for (const sel of optionSels) {
                try {
                    for (const el of overlayRoot.querySelectorAll(sel)) {
                        const r = el.getBoundingClientRect();
                        if (r.width <= 0 || r.height <= 0) continue;
                        const text = (el.textContent || '').trim().replace(/\\s+/g, ' ');
                        if (!text || text.length > 200 || seen.has(text)) continue;
                        seen.add(text);
                        results.push({
                            label: text,
                            value: el.getAttribute('data-value') || el.getAttribute('ng-reflect-value') || text,
                            is_placeholder: isPlaceholder(text),
                        });
                    }
                } catch(e) {}
            }
            return results;
        """, list(_NOISE), list(_PLACEHOLDER_PREFIXES)) or []

        return [
            FieldOption(r["label"], r["value"], i, is_placeholder=r.get("is_placeholder", False))
            for i, r in enumerate(raw)
        ]

    def _scan_portal_data_attributes(self) -> list[FieldOption]:
        """
        Scan visible [data-portal-dropdown] elements and extract their direct children
        as options. Handles YLIMS-style portals where items are <div> children with
        text inside a nested <span>, and any framework that uses [data-portal-dropdown]
        as a container attribute.
        """
        raw = self.driver.execute_script("""
            const NOISE = arguments[0];
            const PLACEHOLDERS = arguments[1];
            const seen = new Set();
            const results = [];

            function isPlaceholder(t) {
                const tl = t.toLowerCase().trim();
                return NOISE.includes(tl) || PLACEHOLDERS.some(p => tl.startsWith(p));
            }

            const portals = document.querySelectorAll(
                '[data-portal-dropdown], [data-portal-dropdown="true"]'
            );
            for (const portal of portals) {
                const pr = portal.getBoundingClientRect();
                const ps = getComputedStyle(portal);
                if (pr.width <= 0 || pr.height <= 0 ||
                    ps.display === 'none' || ps.visibility === 'hidden') continue;

                for (const item of portal.children) {
                    const ir = item.getBoundingClientRect();
                    if (ir.width <= 0 || ir.height <= 0) continue;

                    // Prefer innermost <span> text (YLIMS pattern: <div><span>Label</span></div>)
                    let text = '';
                    const spans = item.querySelectorAll('span');
                    for (const s of spans) {
                        const t = (s.textContent || '').trim().replace(/\\s+/g, ' ');
                        if (t && t.length < 200) { text = t; break; }
                    }
                    if (!text) {
                        text = (item.textContent || '').trim().replace(/\\s+/g, ' ');
                    }

                    if (!text || text.length > 200 || seen.has(text)) continue;
                    seen.add(text);
                    results.push({
                        label: text,
                        value: item.getAttribute('data-value') || item.getAttribute('data-id') || text,
                        is_placeholder: isPlaceholder(text),
                    });
                }
                if (results.length > 0) break; // use the first visible portal
            }
            return results;
        """, list(_NOISE), list(_PLACEHOLDER_PREFIXES)) or []

        return [
            FieldOption(r["label"], r["value"], i, is_placeholder=r.get("is_placeholder", False))
            for i, r in enumerate(raw)
        ]

    # ── React Select specific ─────────────────────────────────────────────────

    def _react_select_select(self, trigger, label: str, meta: DropdownInteraction) -> bool:
        """Handle React Select dropdowns."""
        self._click_safely(trigger)
        time.sleep(0.3)

        # React Select renders a menu with class react-select__menu
        options: list[FieldOption] = []
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            time.sleep(0.15)
            raw = self.driver.execute_script("""
                const seen = new Set(), results = [];
                const NOISE = arguments[0];
                const PLACEHOLDERS = arguments[1];
                function isPlaceholder(t) {
                    const tl = t.toLowerCase().trim();
                    return NOISE.includes(tl) || PLACEHOLDERS.some(p => tl.startsWith(p));
                }
                for (const el of document.querySelectorAll(
                    '.react-select__option, [class*="react-select__option"]'
                )) {
                    const r = el.getBoundingClientRect();
                    if (r.width <= 0 || r.height <= 0) continue;
                    const text = (el.textContent || '').trim().replace(/\\s+/g, ' ');
                    if (!text || seen.has(text)) continue;
                    seen.add(text);
                    results.push({ label: text, value: text, is_placeholder: isPlaceholder(text) });
                }
                return results;
            """, list(_NOISE), list(_PLACEHOLDER_PREFIXES)) or []
            if raw:
                options = [
                    FieldOption(r["label"], r["value"], i, is_placeholder=r.get("is_placeholder", False))
                    for i, r in enumerate(raw)
                ]
                break

        # If searchable React Select: type to filter
        if not options:
            meta.fallbacks_used.append("react_select_search")
            try:
                inputs = self.driver.find_elements(By.CSS_SELECTOR, '.react-select__input input, [class*="react-select__input"] input')
                if inputs:
                    inputs[0].send_keys(label)
                    time.sleep(0.8)
                    raw = self.driver.execute_script("""
                        const results = [];
                        for (const el of document.querySelectorAll('.react-select__option, [class*="react-select__option"]')) {
                            const text = (el.textContent || '').trim();
                            if (text) results.push({label: text, value: text});
                        }
                        return results;
                    """) or []
                    options = [FieldOption(r["label"], r["value"], i) for i, r in enumerate(raw)]
            except Exception:
                pass

        meta.options_found = len(options)
        real = [o for o in options if not o.is_placeholder]
        matched = self._semantic_match(real, label)
        if matched:
            ok = self._click_option(matched)
            if ok:
                meta.option_strategy = "react_select_option"
                meta.selection_method = "semantic_text_match"
                meta.selected_label = matched.label
                meta.success = True
                return True

        self._close(trigger)
        return False

    # ── Searchable dropdown ───────────────────────────────────────────────────

    def _try_searchable_select(self, trigger, label: str, meta: DropdownInteraction) -> bool:
        """
        For searchable dropdowns: type the label into the active input,
        wait for filtered results, then click the matching option.
        """
        try:
            # Find any text input that became active/visible after clicking trigger
            inputs = self.driver.find_elements(
                By.CSS_SELECTOR,
                'input[type="text"], input[type="search"], input:not([type])'
            )
            active_input = None
            for inp in inputs:
                try:
                    if inp.is_displayed() and inp.is_enabled():
                        active_input = inp
                        break
                except Exception:
                    continue

            if not active_input:
                return False

            active_input.clear()
            active_input.send_keys(label)
            time.sleep(0.8)

            # Options should have filtered — collect them
            after_options = self._smart_open_and_collect(trigger, close_after=False)
            real = [o for o in after_options if not o.is_placeholder]
            meta.options_found = len(real)

            matched = self._semantic_match(real, label)
            if matched:
                ok = self._click_option(matched)
                if ok:
                    meta.option_strategy = "searchable_dropdown"
                    meta.selection_method = "type_and_match"
                    meta.selected_label = matched.label
                    meta.success = True
                    return True

        except Exception as e:
            log.debug("searchable select failed", error=str(e))

        return False

    # ── Scrolling for virtualized lists ──────────────────────────────────────

    def _scroll_to_load_more(
        self, containers: list, current_options: list[FieldOption]
    ) -> list[FieldOption]:
        """
        Scroll inside list containers to trigger virtualized rendering.
        Stops when no new options appear after a scroll.
        """
        if not containers:
            return current_options

        all_labels = {o.label for o in current_options}
        options = list(current_options)
        container = containers[0]

        for _ in range(5):  # max 5 scroll steps
            prev_count = len(options)
            try:
                self.driver.execute_script(
                    "arguments[0].scrollTop += arguments[0].offsetHeight",
                    container
                )
            except Exception:
                break
            time.sleep(0.4)

            new_opts = self._options_from_containers([container])
            for opt in new_opts:
                if opt.label not in all_labels:
                    all_labels.add(opt.label)
                    options.append(opt)

            if len(options) == prev_count:
                break  # no new options appeared — done

        return options

    # ── Option matching ───────────────────────────────────────────────────────

    def _semantic_match(self, options: list[FieldOption], label: str) -> FieldOption | None:
        """
        Multi-pass semantic matching:
          1. Exact case-insensitive match
          2. Partial containment (label in option or option in label)
          3. Word-level overlap (≥ 50% of label words found in option)
        """
        target = label.lower().strip()
        if not target or not options:
            return None

        # Pass 1: exact
        for opt in options:
            if opt.label.lower().strip() == target:
                return opt

        # Pass 2: containment
        for opt in options:
            ol = opt.label.lower()
            if target in ol or ol in target:
                return opt

        # Pass 3: word overlap
        target_words = {w for w in target.split() if len(w) > 2}
        best: FieldOption | None = None
        best_score = 0.0
        for opt in options:
            opt_words = {w.lower() for w in opt.label.split() if len(w) > 2}
            if not opt_words:
                continue
            overlap = len(target_words & opt_words)
            ratio = overlap / len(opt_words)
            if ratio > best_score:
                best_score = ratio
                best = opt

        if best and best_score >= 0.5:
            return best

        return None

    # ── Native <select> ───────────────────────────────────────────────────────

    def _native_options(self, el) -> list[FieldOption]:
        from selenium.webdriver.support.ui import Select as SeleniumSelect
        try:
            sel = SeleniumSelect(el)
            return [
                FieldOption(
                    o.text.strip(),
                    o.get_attribute("value") or o.text.strip(),
                    i,
                    is_placeholder=_is_placeholder(o.text.strip()),
                )
                for i, o in enumerate(sel.options)
                if o.text.strip()
            ]
        except Exception:
            return []

    def _native_select(self, el, label: str) -> bool:
        from selenium.webdriver.support.ui import Select as SeleniumSelect
        try:
            sel = SeleniumSelect(el)
            try:
                sel.select_by_visible_text(label)
                return True
            except Exception:
                pass
            for opt in sel.options:
                if label.lower() in opt.text.strip().lower():
                    sel.select_by_visible_text(opt.text.strip())
                    return True
        except Exception as e:
            log.debug("native_select failed", error=str(e))
        return False

    # ── Radio groups ──────────────────────────────────────────────────────────

    def _radio_options(self, el) -> list[FieldOption]:
        name = el.get_attribute("name") or ""
        radios = (
            self.driver.find_elements(By.CSS_SELECTOR, f'input[type="radio"][name="{name}"]')
            if name else []
        )
        return [
            FieldOption(self._label_for(r) or r.get_attribute("value") or str(i),
                        r.get_attribute("value") or str(i), i)
            for i, r in enumerate(radios)
        ]

    def _radio_select(self, el, label: str) -> bool:
        name = el.get_attribute("name") or ""
        radios = self.driver.find_elements(By.CSS_SELECTOR, f'input[type="radio"][name="{name}"]')
        for r in radios:
            lbl = self._label_for(r) or r.get_attribute("value") or ""
            if label.lower() in lbl.lower():
                self.driver.execute_script("arguments[0].click()", r)
                return True
        return False

    def _collect_radio_groups(self) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for el in self.driver.find_elements(By.CSS_SELECTOR, 'input[type="radio"]'):
            if not self._is_visible(el):
                continue
            name = el.get_attribute("name") or "_unnamed"
            lbl = self._label_for(el) or el.get_attribute("value") or ""
            groups.setdefault(name, []).append(lbl)
        return groups

    # ── Container / option extraction ────────────────────────────────────────

    def _visible_containers(self) -> list:
        seen_ids: set[str] = set()
        result = []
        for css in _CONTAINER_SELECTORS:
            try:
                for el in self.driver.find_elements(By.CSS_SELECTOR, css):
                    eid = self._el_id(el)
                    if eid not in seen_ids and self._is_visible(el):
                        seen_ids.add(eid)
                        result.append(el)
            except Exception:
                pass
        return result

    def _options_from_containers(self, containers: list) -> list[FieldOption]:
        seen: set[str] = set()
        options: list[FieldOption] = []

        for container in containers:
            # Special case: this container IS a [data-portal-dropdown] element.
            # CSS selector '[data-portal-dropdown] > div' would look for the attribute
            # *within* the container and find nothing. Use XPath direct-child scan instead.
            try:
                if container.get_attribute("data-portal-dropdown") is not None:
                    for el in container.find_elements(By.XPATH, "./div | ./li"):
                        if not self._is_visible(el):
                            continue
                        text = self._text(el)
                        if not text or text in seen:
                            continue
                        seen.add(text)
                        val = el.get_attribute("data-value") or el.get_attribute("data-id") or text
                        options.append(FieldOption(text, val, len(options), el,
                                                    is_placeholder=_is_placeholder(text)))
                    if options:
                        continue  # got items from this portal container; skip generic scan
            except Exception:
                pass

            for css in _OPTION_SELECTORS:
                try:
                    for el in container.find_elements(By.CSS_SELECTOR, css):
                        if not self._is_visible(el):
                            continue
                        text = self._text(el)
                        if not text or text in seen:
                            continue
                        seen.add(text)
                        val = (
                            el.get_attribute("data-value")
                            or el.get_attribute("data-id")
                            or el.get_attribute("ng-reflect-value")
                            or el.get_attribute("value")
                            or text
                        )
                        options.append(FieldOption(text, val, len(options), el,
                                                    is_placeholder=_is_placeholder(text)))
                except Exception:
                    pass

            # Fallback: visible <li> in container
            if not options:
                try:
                    for el in container.find_elements(By.TAG_NAME, "li"):
                        if not self._is_visible(el):
                            continue
                        text = self._text(el)
                        if not text or text in seen:
                            continue
                        seen.add(text)
                        options.append(FieldOption(text, text, len(options), el,
                                                    is_placeholder=_is_placeholder(text)))
                except Exception:
                    pass

        return options

    def _inline_option_items(self) -> list[FieldOption]:
        """Find all currently visible option-like items in the entire document."""
        raw = self.driver.execute_script("""
            const NOISE = arguments[0];
            const PLACEHOLDERS = arguments[1];
            const seen = new Set();
            const results = [];
            const selectors = arguments[2];

            function isPlaceholder(t) {
                const tl = t.toLowerCase().trim();
                return NOISE.includes(tl) || PLACEHOLDERS.some(p => tl.startsWith(p));
            }

            for (const css of selectors) {
                try {
                    for (const el of document.querySelectorAll(css)) {
                        const r = el.getBoundingClientRect();
                        const s = getComputedStyle(el);
                        if (r.width <= 0 || r.height <= 0 || s.display === 'none' || s.visibility === 'hidden') continue;
                        const text = (el.textContent || '').trim().replace(/\\s+/g, ' ');
                        if (!text || text.length > 200 || seen.has(text)) continue;
                        seen.add(text);
                        results.push({
                            label: text,
                            value: el.getAttribute('data-value') || el.getAttribute('ng-reflect-value') || el.getAttribute('value') || text,
                            is_placeholder: isPlaceholder(text),
                        });
                        if (results.length >= 80) return results;
                    }
                } catch(e) {}
            }
            return results;
        """, list(_NOISE), list(_PLACEHOLDER_PREFIXES), _OPTION_SELECTORS)

        if not raw:
            return []
        return [
            FieldOption(r["label"], r["value"], i, is_placeholder=r.get("is_placeholder", False))
            for i, r in enumerate(raw or [])
        ]

    def _scan_all_portals(self) -> list[FieldOption]:
        """Scan every visible element appended to <body> (portal pattern)."""
        raw = self.driver.execute_script("""
            const NOISE = arguments[0];
            const PLACEHOLDERS = arguments[1];
            const seen = new Set();
            const results = [];

            function isPlaceholder(t) {
                const tl = t.toLowerCase().trim();
                return NOISE.includes(tl) || PLACEHOLDERS.some(p => tl.startsWith(p));
            }

            for (const el of document.body.children) {
                const s = getComputedStyle(el);
                if (s.display === 'none' || s.visibility === 'hidden') continue;
                const r = el.getBoundingClientRect();
                if (r.width <= 0 || r.height <= 0) continue;

                const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
                let node;
                while ((node = walker.nextNode()) && results.length < 80) {
                    const parent = node.parentElement;
                    if (!parent || ['SCRIPT','STYLE'].includes(parent.tagName)) continue;
                    const pr = parent.getBoundingClientRect();
                    if (pr.width <= 0 || pr.height <= 0) continue;
                    const text = (node.textContent || '').trim().replace(/\\s+/g, ' ');
                    if (!text || text.length > 200 || seen.has(text)) continue;
                    seen.add(text);
                    results.push({
                        label: text,
                        value: parent.getAttribute('data-value') || parent.getAttribute('ng-reflect-value') || text,
                        is_placeholder: isPlaceholder(text),
                    });
                }
            }
            return results;
        """, list(_NOISE), list(_PLACEHOLDER_PREFIXES))

        if not raw:
            return []
        return [
            FieldOption(r["label"], r["value"], i, is_placeholder=r.get("is_placeholder", False))
            for i, r in enumerate(raw or [])
        ]

    # ── Click helpers ─────────────────────────────────────────────────────────

    def _click_option(self, option: FieldOption) -> bool:
        """Click a FieldOption, falling back to JS and text-based click."""
        if option.element is not None:
            try:
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block:'nearest'}); arguments[0].click()",
                    option.element
                )
                time.sleep(0.3)
                return True
            except Exception:
                pass
        # Try portal container first — click exact-text child of [data-portal-dropdown]
        clicked = self.driver.execute_script("""
            const target = arguments[0];
            const portals = document.querySelectorAll('[data-portal-dropdown]');
            for (const portal of portals) {
                for (const item of portal.children) {
                    const t = (item.textContent || '').trim().replace(/\\s+/g, ' ').toLowerCase();
                    if (t === target || t.includes(target)) {
                        item.scrollIntoView({block: 'nearest'});
                        item.click();
                        return true;
                    }
                }
            }
            return false;
        """, option.label.lower().strip())
        if clicked:
            time.sleep(0.3)
            return True
        return self._js_click_by_text(option.label.lower().strip())

    def _js_click_by_text(self, text_lower: str) -> bool:
        """Click first visible element whose text matches, piercing Shadow DOM."""
        return bool(self.driver.execute_script("""
            const target = arguments[0];
            function tryRoot(root) {
                const SELS = [
                    'mat-option','[role="option"]','[role="menuitem"]',
                    '.react-select__option','[class*="react-select__option"]',
                    '.MuiMenuItem-root','.ant-select-item-option',
                    'li','button','div','span','a'
                ];
                for (const css of SELS) {
                    try {
                        for (const el of root.querySelectorAll(css)) {
                            const r = el.getBoundingClientRect();
                            if (r.width <= 0 && r.height <= 0) continue;
                            const t = (el.textContent || '').trim().toLowerCase().replace(/\\s+/g, ' ');
                            if (t === target || t.includes(target)) {
                                el.scrollIntoView({block:'nearest'});
                                el.click();
                                return true;
                            }
                        }
                    } catch(e) {}
                }
                for (const el of root.querySelectorAll('*')) {
                    if (el.shadowRoot && tryRoot(el.shadowRoot)) return true;
                }
                return false;
            }
            return tryRoot(document);
        """, text_lower))

    def _cdp_click_text(self, label: str) -> bool:
        """Last resort: use CDP accessibility tree to locate and click by text."""
        try:
            tree = self.driver.execute_cdp_cmd(
                "Accessibility.getFullAXTree", {"fetchRelatives": False}
            )
            label_lower = label.lower().strip()
            for node in tree.get("nodes", []):
                name_val = (node.get("name") or {}).get("value", "").lower()
                if label_lower in name_val or name_val == label_lower:
                    bid = node.get("backendDOMNodeId")
                    if not bid:
                        continue
                    try:
                        box = self.driver.execute_cdp_cmd(
                            "DOM.getBoxModel", {"backendNodeId": int(bid)}
                        )
                        content = box.get("model", {}).get("content", [])
                        if len(content) < 6:
                            continue
                        cx = (content[0] + content[2]) / 2
                        cy = (content[1] + content[5]) / 2
                        if cx <= 0 or cy <= 0:
                            continue
                        for ev in ("mouseMoved", "mousePressed", "mouseReleased"):
                            params: dict = {"type": ev, "x": cx, "y": cy, "modifiers": 0}
                            if ev != "mouseMoved":
                                params.update({"button": "left", "clickCount": 1})
                            self.driver.execute_cdp_cmd("Input.dispatchMouseEvent", params)
                        return True
                    except Exception:
                        continue
        except Exception as e:
            log.debug("CDP click failed", error=str(e))
        return False

    # ── Trigger discovery ─────────────────────────────────────────────────────

    def _find_custom_triggers(self) -> list:
        """Find all custom dropdown triggers on the current page."""
        return self.driver.execute_script("""
            function isVisible(el) {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
            }
            const seen = new Set();
            const results = [];

            const candidates = document.querySelectorAll(
                'mat-select, button[aria-haspopup], button[aria-expanded], ' +
                '[role="combobox"], [data-headlessui-state], [aria-haspopup="listbox"], ' +
                '[aria-haspopup="menu"], [data-state], .react-select__control'
            );
            for (const el of candidates) {
                if (!isVisible(el) || seen.has(el)) continue;
                seen.add(el);
                results.push(el);
            }
            // Any <button> with a chevron SVG (custom trigger pattern)
            for (const el of document.querySelectorAll('button')) {
                if (!isVisible(el) || seen.has(el)) continue;
                const svg = el.querySelector('svg');
                const text = (el.textContent || '').trim();
                if (svg && text && text.length < 80) {
                    seen.add(el);
                    results.push(el);
                }
            }
            return results.slice(0, 25);
        """) or []

    def _find_trigger_by_label(self, label: str) -> Any | None:
        """Find a dropdown trigger whose associated label text matches `label`."""
        label_lower = label.lower().strip()
        candidates = self._find_custom_triggers()
        for el in candidates:
            lbl = self._label_for(el)
            if lbl and label_lower in lbl.lower():
                return el
            txt = (self._text(el) or "").lower()
            if label_lower in txt:
                return el
        return None

    # ── Misc helpers ──────────────────────────────────────────────────────────

    def _click_safely(self, el):
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block:'nearest'})", el)
            self.driver.execute_script("arguments[0].click()", el)
        except Exception:
            try:
                el.click()
            except Exception:
                pass

    def _close(self, trigger=None):
        try:
            ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
        except Exception:
            try:
                self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            except Exception:
                pass
        time.sleep(0.2)

    def _is_visible(self, el) -> bool:
        try:
            r = el.rect
            return r["width"] > 0 and r["height"] > 0 and el.is_displayed()
        except Exception:
            return False

    def _text(self, el) -> str:
        try:
            return (el.text or "").strip().replace("\n", " ").replace("  ", " ")
        except Exception:
            return ""

    def _el_id(self, el) -> str:
        """Stable identity for an element (avoids fragile Python id())."""
        try:
            return el.id  # Selenium internal element ID
        except Exception:
            return str(id(el))

    def _label_for(self, el) -> str:
        """Return the human-readable label associated with a form control."""
        try:
            field_id = el.get_attribute("id")
            if field_id:
                try:
                    lbl = self.driver.find_element(By.CSS_SELECTOR, f'label[for="{field_id}"]')
                    if lbl:
                        return lbl.text.strip()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            aria = el.get_attribute("aria-label") or el.get_attribute("aria-labelledby") or ""
            if aria.strip():
                return aria.strip()
            placeholder = el.get_attribute("placeholder") or ""
            if placeholder.strip():
                return placeholder.strip()
            lbl = self.driver.execute_script("""
                const el = arguments[0];
                const prev = el.previousElementSibling;
                if (prev && ['LABEL','SPAN','P','H1','H2','H3','H4','DIV'].includes(prev.tagName)) {
                    const t = (prev.textContent || '').trim();
                    if (t.length > 0 && t.length < 80) return t;
                }
                const parent = el.parentElement;
                if (parent) {
                    const l = parent.querySelector('label, mat-label, [class*="label"]');
                    if (l) return (l.textContent || '').trim();
                }
                return '';
            """, el)
            return (lbl or "").strip()
        except Exception:
            return ""

    def _css_selector(self, el) -> str:
        try:
            eid = el.get_attribute("id")
            if eid:
                return f"#{eid}"
            name = el.get_attribute("name")
            if name:
                return f'{el.tag_name}[name="{name}"]'
        except Exception:
            pass
        return el.tag_name if hasattr(el, "tag_name") else "unknown"

    def _visible_elements(self, css: str) -> list:
        return [
            el for el in self.driver.find_elements(By.CSS_SELECTOR, css)
            if self._is_visible(el)
        ]
