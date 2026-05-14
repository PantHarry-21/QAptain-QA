export { cn } from './utils.client';

import { Page } from 'playwright-core';

export async function getDomContextSelector(page: Page): Promise<string> {
  return await page.evaluate(() => {
    const modalSelectors = [
      '[role="dialog"]',
      '.modal-content',
      '.dialog-container',
      '.chakra-modal__content',
      '.ant-modal-content',
      '.MuiDialog-paper',
    ];

    for (const selector of modalSelectors) {
      const modal = document.querySelector(selector);
      if (
        modal &&
        window.getComputedStyle(modal).display !== 'none' &&
        window.getComputedStyle(modal).visibility !== 'hidden'
      ) {
        return selector;
      }
    }
    return 'body';
  });
}
