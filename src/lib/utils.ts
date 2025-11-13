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
            // Add more common modal selectors as needed
        ];

        for (const selector of modalSelectors) {
            const modal = document.querySelector(selector);
            if (modal && window.getComputedStyle(modal).display !== 'none' && window.getComputedStyle(modal).visibility !== 'hidden') {
                // Return the selector of the first visible modal found
                return selector;
            }
        }
        return 'body'; // Default to main document body
    });
}
