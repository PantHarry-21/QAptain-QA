"""
Self-Healing Engine
When selectors fail, QAptain uses semantic similarity + context to recover.
Recovery is principled — uses labels, roles, accessibility, and memory.
"""
from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Any

import structlog
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
    ElementNotInteractableException, ElementClickInterceptedException,
    StaleElementReferenceException, NoSuchElementException, TimeoutException,
)

log = structlog.get_logger()


@dataclass
class HealingAttempt:
    strategy: str
    selector_type: str
    selector_value: str
    success: bool
    reason: str
    duration_ms: int


class SelfHealingEngine:
    """
    Ranked healing strategies for finding elements when primary selectors fail.

    Strategy hierarchy:
    1. Exact label match (aria-label, label[for], placeholder)
    2. Semantic role + label combination
    3. Visible text content
    4. XPath text match
    5. Fuzzy label match
    6. Context-based (nearby elements, form context)
    7. AI-assisted (triggered only after all deterministic strategies fail)
    """

    MAX_ATTEMPTS_PER_STRATEGY = 3
    STRATEGY_TIMEOUT = 3.0   # reduced from 5s — 8 strategies × 3s = 24s max per lookup

    def __init__(self, driver):
        self.driver = driver

    def find_element(
        self,
        semantic_label: str,
        element_type: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> Any | None:
        """
        Find an element using cascading healing strategies.
        Returns (element, strategy_used, attempts) or None.
        """
        strategies = self._build_strategies(semantic_label, element_type)
        attempts = []

        # Fast-path: try all strategies with 0 wait first (DOM snapshot check).
        # If the element is already rendered we find it instantly instead of
        # burning STRATEGY_TIMEOUT per strategy just to confirm it exists.
        for strategy_name, by, value in strategies:
            try:
                elements = self.driver.find_elements(by, value)
                for el in elements:
                    try:
                        if el.is_displayed() or el.is_enabled():
                            attempts.append(HealingAttempt(
                                strategy=f"{strategy_name}_fast",
                                selector_type=by,
                                selector_value=value,
                                success=True,
                                reason="Instant DOM hit",
                                duration_ms=0,
                            ))
                            log.debug("Element found (fast path)", strategy=strategy_name, label=semantic_label)
                            return el, strategy_name, attempts
                    except Exception:
                        continue
            except Exception:
                continue

        for strategy_name, by, value in strategies:
            start = time.monotonic()
            try:
                element = WebDriverWait(self.driver, self.STRATEGY_TIMEOUT).until(
                    EC.presence_of_element_located((by, value))
                )
                # Accept if visible OR if enabled (Angular Material hides actual inputs
                # behind mat-form-field while keeping them interactable via JS).
                visible = False
                try:
                    visible = element.is_displayed()
                except Exception:
                    pass
                enabled = False
                try:
                    enabled = element.is_enabled()
                except Exception:
                    pass

                if visible or enabled:
                    duration = int((time.monotonic() - start) * 1000)
                    attempts.append(HealingAttempt(
                        strategy=strategy_name,
                        selector_type=by,
                        selector_value=value,
                        success=True,
                        reason="Located and interactable",
                        duration_ms=duration,
                    ))
                    log.debug("Element found", strategy=strategy_name, label=semantic_label)
                    return element, strategy_name, attempts
            except (TimeoutException, NoSuchElementException):
                duration = int((time.monotonic() - start) * 1000)
                attempts.append(HealingAttempt(
                    strategy=strategy_name,
                    selector_type=by,
                    selector_value=value,
                    success=False,
                    reason="Not found",
                    duration_ms=duration,
                ))
            except Exception as e:
                attempts.append(HealingAttempt(
                    strategy=strategy_name,
                    selector_type=by,
                    selector_value=value,
                    success=False,
                    reason=str(e)[:100],
                    duration_ms=0,
                ))

        log.warning("All healing strategies failed", label=semantic_label, attempts=len(attempts))
        return None, None, attempts

    def find_element_any(
        self,
        labels: list[str],
        element_type: str | None = None,
    ) -> tuple:
        """
        Find an element matching ANY of the given labels.

        Builds combined XPath selectors covering all variants at once so the
        cost is O(strategies) rather than O(labels × strategies × timeout).
        Designed for login-button detection where the exact text ("Sign In" vs
        "Log In" vs "Login") is unpredictable.
        """
        xl = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        xs = "abcdefghijklmnopqrstuvwxyz"
        ci_body = f'translate(., "{xl}", "{xs}")'
        ci_aria = f'translate(@aria-label, "{xl}", "{xs}")'

        def or_text(lbs: list[str]) -> str:
            return " or ".join(f'contains({ci_body}, "{lb.lower().strip()}")' for lb in lbs)

        def or_aria(lbs: list[str]) -> str:
            return " or ".join(f'contains({ci_aria}, "{lb.lower().strip()}")' for lb in lbs)

        ot = or_text(labels)
        oa = or_aria(labels)

        combined = [
            ("button_any",       By.XPATH,        f'//button[{ot}]'),
            ("submit_input",     By.CSS_SELECTOR, 'button[type="submit"], input[type="submit"]'),
            ("link_any",         By.XPATH,        f'//a[{ot}]'),
            ("aria_any",         By.XPATH,        f'//*[{oa}]'),
            ("role_btn_any",     By.XPATH,        f'//*[@role="button"][{ot}]'),
            ("span_in_btn_any",  By.XPATH,        f'//button[.//*[{ot}]]'),
        ]

        # Fast path: instant DOM snapshot — no wait
        for strat, by, val in combined:
            try:
                for el in self.driver.find_elements(by, val):
                    try:
                        if el.is_displayed() or el.is_enabled():
                            log.debug("Element found (find_element_any fast)", strategy=strat, labels=labels)
                            return el, strat, []
                    except Exception:
                        continue
            except Exception:
                continue

        # Slow path: single wait per combined selector (O(strategies), not O(labels×strategies))
        for strat, by, val in combined:
            start = time.monotonic()
            try:
                element = WebDriverWait(self.driver, self.STRATEGY_TIMEOUT).until(
                    EC.presence_of_element_located((by, val))
                )
                try:
                    if element.is_displayed() or element.is_enabled():
                        log.debug("Element found (find_element_any)", strategy=strat, labels=labels)
                        return element, strat, []
                except Exception:
                    pass
            except (TimeoutException, NoSuchElementException):
                continue
            except Exception:
                continue

        log.warning("find_element_any: all labels failed", labels=labels)
        return None, None, []

    def click_with_healing(
        self,
        element,
        fallback_js: bool = True,
    ) -> tuple[bool, str]:
        """
        Click an element with multiple fallback strategies.
        Returns (success, method_used).
        """
        # Standard click
        try:
            element.click()
            return True, "standard_click"
        except ElementClickInterceptedException:
            pass
        except ElementNotInteractableException:
            pass

        # Scroll into view then click
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            time.sleep(0.3)
            element.click()
            return True, "scroll_then_click"
        except Exception:
            pass

        # JavaScript click fallback
        if fallback_js:
            try:
                self.driver.execute_script("arguments[0].click();", element)
                return True, "js_click"
            except Exception as e:
                return False, f"all_failed: {e}"

        return False, "all_strategies_failed"

    def _build_strategies(
        self,
        label: str,
        element_type: str | None,
    ) -> list[tuple[str, str, str]]:
        """
        Build ordered list of (strategy_name, by, selector) tuples.
        Semantic strategies first, technical last.
        Angular Material strategies are interleaved throughout because
        mat-label / mat-form-field don't use standard HTML label[for] binding.
        """
        label_lower = label.lower().strip()
        label_escaped = label.replace('"', '\\"')
        xl = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        xs = "abcdefghijklmnopqrstuvwxyz"
        ci = f'translate(., "{xl}", "{xs}")'          # normalize case on text()
        ca = f'translate(@aria-label, "{xl}", "{xs}")'  # normalize case on aria-label

        strategies = []

        # 1. Aria-label exact match (works for many Angular components)
        strategies.append((
            "aria_label_exact",
            By.CSS_SELECTOR,
            f'[aria-label="{label_escaped}"]',
        ))

        # 2. Aria-label contains (case-insensitive)
        strategies.append((
            "aria_label_contains",
            By.XPATH,
            f'//*[contains({ca}, "{label_lower}")]',
        ))

        # 3. Angular Material: mat-form-field containing a mat-label or label with matching text
        #    Returns the actual input/textarea/mat-select inside that field.
        #    This is the PRIMARY strategy for all Angular Material form inputs.
        strategies.append((
            "mat_form_field_input",
            By.XPATH,
            f'//mat-form-field[.//*[contains({ci}, "{label_lower}")]]//input',
        ))
        strategies.append((
            "mat_form_field_textarea",
            By.XPATH,
            f'//mat-form-field[.//*[contains({ci}, "{label_lower}")]]//textarea',
        ))
        strategies.append((
            "mat_form_field_select",
            By.XPATH,
            f'//mat-form-field[.//*[contains({ci}, "{label_lower}")]]//mat-select',
        ))

        # 4. Standard label[for] match (HTML5 forms)
        strategies.append((
            "label_text",
            By.XPATH,
            f'//label[contains({ci}, "{label_lower}")]//following::input[1]',
        ))

        # 5. Placeholder match
        strategies.append((
            "placeholder",
            By.XPATH,
            f'//*[contains(translate(@placeholder, "{xl}", "{xs}"), "{label_lower}")]',
        ))

        # 6. Button/link text match (Angular Material buttons render text in inner <span>)
        if not element_type or element_type in ("button", "link", "element", None):
            strategies.append((
                "button_text",
                By.XPATH,
                f'//button[contains({ci}, "{label_lower}")]',
            ))
            strategies.append((
                "mat_button",
                By.XPATH,
                f'//*[@mat-button or @mat-raised-button or @mat-flat-button or @mat-stroked-button or @mat-icon-button]'
                f'[contains({ci}, "{label_lower}")]',
            ))
            strategies.append((
                "link_text",
                By.XPATH,
                f'//a[contains({ci}, "{label_lower}")]',
            ))

        # 7. Any interactive element with matching text
        strategies.append((
            "text_content",
            By.XPATH,
            f'//*[contains({ci}, "{label_lower}") and '
            f'(self::button or self::a or self::span or self::div or self::input or self::mat-select)]',
        ))

        # 8. Angular Material list/nav items (sidebar links, menu items)
        strategies.append((
            "mat_list_item",
            By.XPATH,
            f'//mat-list-item[contains({ci}, "{label_lower}")] | '
            f'//*[@role="menuitem"][contains({ci}, "{label_lower}")] | '
            f'//*[@role="option"][contains({ci}, "{label_lower}")]',
        ))

        # 9. Name attribute
        strategies.append((
            "name_attr",
            By.XPATH,
            f'//*[contains(translate(@name, "{xl}", "{xs}"), "{label_lower}")]',
        ))

        # 10. Title / data-testid attribute
        strategies.append((
            "title_attr",
            By.XPATH,
            f'//*[contains(translate(@title, "{xl}", "{xs}"), "{label_lower}")] | '
            f'//*[contains(translate(@data-testid, "{xl}", "{xs}"), "{label_lower}")]',
        ))

        # Type-specific fallback strategies
        if element_type == "textbox":
            # For textarea fields (Angular Material and standard)
            strategies.append((
                "mat_form_field_any_input",
                By.XPATH,
                f'//mat-form-field[.//*[contains({ci}, "{label_lower}")]]'
                f'//*[self::input or self::textarea]',
            ))
            strategies.append(("input_any", By.CSS_SELECTOR,
                                "input:not([type='hidden']):not([type='submit']):not([type='checkbox']):not([type='radio'])"))
        elif element_type in ("dropdown", "combobox"):
            strategies.append(("mat_select_any", By.CSS_SELECTOR, "mat-select"))
            strategies.append(("select_any", By.CSS_SELECTOR, "select"))
            strategies.append(("combobox_role", By.CSS_SELECTOR, '[role="combobox"]'))
        elif element_type == "file_upload":
            strategies.append(("file_input", By.CSS_SELECTOR, 'input[type="file"]'))

        return strategies

    def wait_for_dynamic_content(
        self,
        after_action_label: str,
        timeout: float = 8.0,
    ) -> dict[str, Any]:
        """
        After an action, wait for meaningful UI change.
        Returns info about what changed.
        """
        initial_url = self.driver.current_url
        initial_count = self.driver.execute_script(
            "return document.querySelectorAll('input, button, select, a[href]').length;"
        ) or 0

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(0.3)
            current_url = self.driver.current_url
            current_count = self.driver.execute_script(
                "return document.querySelectorAll('input, button, select, a[href]').length;"
            ) or 0

            if current_url != initial_url:
                return {"type": "navigation", "new_url": current_url}

            if abs(current_count - initial_count) >= 3:
                return {
                    "type": "dynamic_render",
                    "elements_delta": current_count - initial_count,
                    "interpretation": "New UI elements appeared" if current_count > initial_count else "UI elements removed",
                }

        return {"type": "no_change", "timeout": timeout}
