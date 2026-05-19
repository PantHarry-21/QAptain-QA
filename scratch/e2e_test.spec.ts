import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  
  console.log("Navigating to http://localhost:3000/login");
  await page.goto('http://localhost:3000/login');
  
  // Navigate to Sign up
  await page.click('a:has-text("Sign up")');
  await page.waitForURL('**/signup');
  
  await page.fill('input[type="text"], input[name="name"]', 'Harry');
  await page.fill('input[type="email"]', 'pant@mailinator.com');
  await page.fill('input[type="password"]', 'Harry@123');
  await page.click('button:has-text("Sign up"), button:has-text("Create account")');
  
  // Wait for login or dashboard
  await page.waitForURL('**/workspaces**');
  console.log("Registered and logged into QAPtain.");

  // Navigate to create workspace
  await page.click('a:has-text("Add workspace")');
  await page.waitForURL('**/workspaces/new');
  
  console.log("Creating workspace...");
  // Step 1: Application
  await page.fill('input[placeholder="e.g. Acme ERP"]', 'YLIMS UAT E2E');
  await page.fill('textarea', 'UAT Testing for YLIMS E2E flow');
  await page.fill('input[placeholder="https://app.example.com"]', 'https://uat.ylims.com/');
  await page.click('button:has-text("Continue")');
  
  // Step 2: Auth Profile
  await page.waitForSelector('text="2 · Authentication profile"');
  await page.fill('input[value="Primary"]', 'Admin Profile');
  await page.fill('input[autocomplete="off"]', 'admin');
  await page.fill('input[type="password"]', 'Password@123');
  await page.fill('input[placeholder="For multi-step admin login"]', 'Arbro - delhi');
  // Role hint is already ADMIN by default in the dropdown
  await page.click('button:has-text("Continue")');

  // Step 3: Discovery
  console.log("Triggering discovery...");
  await page.waitForSelector('text="3 · Lightweight discovery"');
  await page.click('button:has-text("Start discovery job")');
  
  // Wait for it to redirect to the workspace page with discovery status
  await page.waitForURL(/.*workspaces\/[^\?]+\?discovery=.*/);
  console.log("Discovery job started. URL:", page.url());

  // Wait for discovery to complete
  console.log("Waiting for discovery to complete...");
  await page.waitForTimeout(10000); // Initial wait
  
  for (let i = 0; i < 30; i++) {
     const statusText = await page.textContent('.bg-violet-50\\/80, .bg-violet-950\\/40');
     console.log(`[Status check ${i+1}]`, statusText?.replace(/\s+/g, ' ').trim());
     
     if (statusText?.includes('Analysis complete') || statusText?.includes('Complete') || !statusText?.includes('discovery=')) {
        break;
     }
     await page.waitForTimeout(5000);
  }

  console.log("Navigating to Application Map...");
  await page.click('button[role="tab"]:has-text("Modules")');
  await page.waitForTimeout(2000);

  const modules = await page.locator('table tbody tr').evaluateAll(rows => rows.map(r => r.innerText.replace(/\n/g, ' ')));
  console.log("Modules discovered:", modules);

  await browser.close();
})();
