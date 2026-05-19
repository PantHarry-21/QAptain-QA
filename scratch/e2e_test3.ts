import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  
  console.log("Navigating to http://localhost:3000/login");
  await page.goto('http://localhost:3000/login');
  
  await page.fill('input[type="email"]', 'pant@mailinator.com');
  await page.fill('input[type="password"]', 'Harry@123');
  await page.click('button:has-text("Login")');
  
  await page.waitForTimeout(3000);
  console.log("URL after login:", page.url());
  const bodyText = await page.locator('body').innerText();
  console.log("Body text snippet:", bodyText.substring(0, 300));
  
  await browser.close();
})();
