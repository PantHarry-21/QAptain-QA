import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.goto('https://uat.ylims.com/login');
  await page.waitForLoadState('networkidle');
  console.log("URL:", page.url());
  
  const inputs = await page.locator('input, select, button, [role="combobox"]').evaluateAll(els => 
    els.map(el => ({ tag: el.tagName, name: el.getAttribute('name'), type: el.getAttribute('type'), text: el.textContent?.trim() }))
  );
  console.log("Inputs on initial load:", inputs);
  
  // Fill username and password
  await page.fill('input[name="username"]', 'admin');
  await page.fill('input[name="password"]', 'Password@123');
  await page.click('button:has-text("Sign in")');
  
  await page.waitForTimeout(3000);
  console.log("URL after first sign in:", page.url());
  
  const inputsAfter = await page.locator('input, select, button, [role="combobox"]').evaluateAll(els => 
    els.map(el => ({ tag: el.tagName, name: el.getAttribute('name'), type: el.getAttribute('type'), text: el.textContent?.trim() }))
  );
  console.log("Inputs after first sign in:", inputsAfter);
  
  await browser.close();
})();
