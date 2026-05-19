import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  
  console.log("Navigating to http://localhost:3000/login");
  await page.goto('http://localhost:3000/login');
  
  // Dump inputs and buttons
  const elements = await page.locator('input, button').evaluateAll(els => 
    els.map(el => ({ tag: el.tagName, text: el.textContent?.trim(), type: el.getAttribute('type'), name: el.getAttribute('name') }))
  );
  console.log("Login elements:", elements);
  
  await browser.close();
})();
