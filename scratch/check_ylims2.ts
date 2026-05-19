import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();
  
  await page.goto('https://uat.ylims.com/login', { waitUntil: 'networkidle' });
  
  await page.fill('input[name="username"]', 'admin');
  await page.fill('input[name="password"]', 'Password@123');
  
  console.log("Filled username and password.");
  
  // Dump inputs on the page
  const inputs = await page.locator('input, select, button, [role="combobox"]').evaluateAll(els => 
    els.map(el => ({ tag: el.tagName, name: el.getAttribute('name'), type: el.getAttribute('type'), text: el.textContent?.trim() }))
  );
  console.log("Inputs before location select:", inputs);
  
  // Try to find lab location dropdown
  const combo = page.locator('.ant-select-selection-search-input, [role="combobox"]').first();
  if (await combo.count() > 0 && await combo.isVisible()) {
      console.log("Found combobox, clicking it...");
      await combo.click();
      await page.waitForTimeout(1000);
      
      const option = page.locator('.ant-select-item-option-content').getByText(/Arbro - delhi/i).first();
      if (await option.count() > 0 && await option.isVisible()) {
          console.log("Found location option, clicking it...");
          await option.click();
      } else {
          console.log("Location option not visible.");
      }
  } else {
      console.log("Location combobox not visible.");
  }
  
  await page.click('button:has-text("Sign in")');
  await page.waitForTimeout(5000);
  
  console.log("FINAL URL:", page.url());
  
  await browser.close();
})();
