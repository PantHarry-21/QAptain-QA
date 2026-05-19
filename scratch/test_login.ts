import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  
  page.on('console', msg => console.log('BROWSER CONSOLE:', msg.text()));
  
  await page.goto('http://localhost:3000/login');
  await page.fill('input[type="email"]', 'pant@mailinator.com');
  await page.fill('input[type="password"]', 'Harry@123');
  await page.click('button:has-text("Sign In")');
  
  await page.waitForTimeout(3000);
  const errorText = await page.locator('.text-red-400').textContent().catch(()=>null);
  console.log("Error text on page:", errorText);
  console.log("Final URL:", page.url());
  
  await browser.close();
})();
