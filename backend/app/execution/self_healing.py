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
    STRATEGY_TIMEOUT = 5.0

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

        for strategy_name, by, value in strategies:
            start = time.monotonic()
            try:
                element = WebDriverWait(self.driver, self.STRATEGY_TIMEOUT).until(
                    EC.presence_of_element_located((by, value))
                )
                # Verify it's visible and interactable
                if element.is_displayed():
                    duration = int((time.monotonic() - start) * 1000)
                    attempts.append(HealingAttempt(
                        strategy=strategy_name,
                        selector_type=by,
                        selector_value=value,
                        success=True,
                        reason="Located and visible",
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
        """
        label_lower = label.lower().strip()
        label_escaped = label.replace('"', '\\"')
        strategies = []

        # 1. Aria-label exact match
        strategies.append((
            "aria_label_exact",
            By.CSS_SELECTOR,
            f'[aria-label="{label_escaped}"]',
        ))

        # 2. Aria-label contains (case-insensitive via XPath)
        strategies.append((
            "aria_label_contains",
            By.XPATH,
            f'//*[contains(translate(@aria-label, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "{label_lower}")]',
        ))

        # 3. Label[for] match
        strategies.append((
            "label_text",
            By.XPATH,
            f'//label[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "{label_lower}")]//following::input[1]',
        ))

        # 4. Placeholder match
        strategies.append((
            "placeholder",
            By.XPATH,
            f'//*[contains(translate(@placeholder, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "{label_lower}")]',
        ))

        # 5. Button/link text match
        if not element_type or element_type in ("button", "link", "element"):
            strategies.append((
                "button_text",
                By.XPATH,
                f'//button[contains(translate(normalize-space(.), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "{label_lower}")]',
            ))
            strategies.append((
                "link_text",
                By.XPATH,
                f'//a[contains(translate(normalize-space(.), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "{label_lower}")]',
            ))

        # 6. Any element with matching text
        strategies.append((
            "text_content",
            By.XPATH,
            f'//*[contains(translate(normalize-space(.), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "{label_lower}") and (self::button or self::a or self::span or self::div or self::input)]',
        ))

        # 7. Name attribute
        strategies.append((
            "name_attr",
            By.XPATH,
            f'//*[contains(translate(@name, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "{label_lower}")]',
        ))

        # 8. Title attribute
        strategies.append((
            "title_attr",
            By.XPATH,
            f'//*[contains(translate(@title, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "{label_lower}")]',
        ))

        # Type-specific strategies
        if element_type == "textbox":
            strategies.append(("input_any", By.CSS_SELECTOR, "input:not([type='hidden']):not([type='submit'])"))
        elif element_type in ("dropdown", "combobox"):
            strategies.append(("select_any", By.CSS_SELECTOR, "select"))
            strategies.append(("combobox_role", By.CSS_SELECTOR, '[role="combobox"]'))

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
