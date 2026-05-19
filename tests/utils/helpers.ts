import { Page, expect } from '@playwright/test';

export class TestHelpers {
  static async waitForElement(page: Page, selector: string, timeout = 5000) {
    try {
      await page.waitForSelector(selector, { timeout });
      return true;
    } catch {
      return false;
    }
  }

  static async isElementVisible(page: Page, selector: string): Promise<boolean> {
    try {
      return await page.isVisible(selector);
    } catch {
      return false;
    }
  }

  static async getElementText(page: Page, selector: string): Promise<string> {
    const text = await page.textContent(selector);
    return text || '';
  }

  static async fillForm(
    page: Page,
    fields: Record<string, string>
  ): Promise<void> {
    for (const [selector, value] of Object.entries(fields)) {
      await page.fill(selector, value);
    }
  }

  static async screenshot(
    page: Page,
    filename: string,
    path = 'test-results/screenshots'
  ) {
    await page.screenshot({ path: `${path}/${filename}.png` });
  }

  static async checkPageLoadTime(page: Page): Promise<number> {
    const navigationTiming = await page.evaluate(() => {
      const timing = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming;
      return timing.loadEventEnd - timing.fetchStart;
    });

    return navigationTiming;
  }

  static async checkConsoleErrors(page: Page): Promise<string[]> {
    const errors: string[] = [];

    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        errors.push(msg.text());
      }
    });

    return errors;
  }

  static async waitForNavigation(
    page: Page,
    action: () => Promise<void>,
    timeout = 5000
  ) {
    await Promise.all([page.waitForNavigation({ timeout }), action()]);
  }

  static async expectUrlContains(page: Page, expectedUrl: string) {
    expect(page.url()).toContain(expectedUrl);
  }

  static async expectUrlEquals(page: Page, expectedUrl: string) {
    expect(page.url()).toBe(expectedUrl);
  }

  static async clearInput(page: Page, selector: string) {
    await page.click(selector, { clickCount: 3 });
    await page.press(selector, 'Delete');
  }

  static async scrollToElement(page: Page, selector: string) {
    const element = await page.$(selector);
    if (element) {
      await element.scrollIntoViewIfNeeded();
    }
  }

  static async hoverElement(page: Page, selector: string) {
    await page.hover(selector);
  }

  static async doubleClickElement(page: Page, selector: string) {
    await page.dblclick(selector);
  }

  static async typeSlowly(page: Page, selector: string, text: string, delay = 100) {
    await page.fill(selector, '');
    await page.locator(selector).type(text, { delay });
  }

  static async expectElementCount(
    page: Page,
    selector: string,
    expectedCount: number
  ) {
    const count = await page.locator(selector).count();
    expect(count).toBe(expectedCount);
  }

  static async expectElementContainsText(
    page: Page,
    selector: string,
    text: string
  ) {
    const element = page.locator(selector);
    await expect(element).toContainText(text);
  }

  static async waitUntil(
    condition: () => Promise<boolean>,
    timeout = 10000,
    interval = 500
  ): Promise<void> {
    const startTime = Date.now();

    while (Date.now() - startTime < timeout) {
      if (await condition()) {
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, interval));
    }

    throw new Error('Condition not met within timeout');
  }
}
