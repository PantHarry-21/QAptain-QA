# 🚀 QAPtain Playwright Framework - Quick Reference Card

## ⚡ Essential Commands

```bash
# DEVELOPMENT
npm run dev                    # Start application (localhost:3000)

# TESTING
npm test                       # Run all tests (fastest)
npm run test:ui               # Run with visual UI (RECOMMENDED)
npm run test:headed           # See browser while testing
npm run test:debug            # Step-through debugging

# SPECIFIC TEST SUITES
npm run test:auth             # Authentication tests
npm run test:workspaces       # Workspace tests
npm run test:complete         # End-to-end flows
npm run test:ui-elements      # UI component tests
npm run test:accessibility    # Accessibility tests

# BROWSERS
npm run test:chromium         # Test on Chromium only
npm run test:firefox          # Test on Firefox only
npm run test:webkit           # Test on WebKit (Safari)

# REPORTS
npm run test:report           # View HTML test report
```

---

## 📁 File Structure

```
tests/
├── pages/              # Page Objects (for selectors & actions)
├── specs/              # Test files (actual tests)
├── fixtures/           # Authentication setup
└── utils/              # Helpers & test data
```

---

## 📝 Writing Tests - Basic Template

```typescript
import { test, expect } from '@playwright/test';
import { LoginPage } from '../pages/login.page';

test.describe('Feature Name', () => {
  test('should do something', async ({ page }) => {
    const loginPage = new LoginPage(page);
    
    await loginPage.goto();
    await loginPage.login('email@example.com', 'password');
    
    expect(page.url()).toContain('/workspaces');
  });
});
```

---

## 🔐 Authenticated Tests

```typescript
import { test } from '../fixtures/auth.fixture';
import { WorkspacesPage } from '../pages/workspaces.page';

test('should work for logged-in user', async ({ authenticatedPage }) => {
  const workspacesPage = new WorkspacesPage(authenticatedPage);
  await workspacesPage.goto();
  
  const count = await workspacesPage.getWorkspacesCount();
  expect(count).toBeGreaterThanOrEqual(0);
});
```

---

## 🎯 Common Page Actions

```typescript
const page = new LoginPage(page);

// Navigation
await page.goto();
await page.goto('/login');

// Interactions
await page.click(selector);
await page.fill(selector, 'text');
await page.getText(selector);

// Visibility
await page.isVisible(selector);
await page.waitForSelector(selector);

// Screenshots
await page.screenshot('test-name');
```

---

## 📊 Common Assertions

```typescript
// URL checks
expect(page.url()).toContain('/login');
expect(page.url()).toBe('http://localhost:3000/login');

// Element checks
expect(await loginPage.isEmailInputVisible()).toBeTruthy();
expect(await loginPage.isPasswordInputVisible()).toBeTruthy();

// Value checks
expect(await page.inputValue('#email')).toBe('test@example.com');

// Count checks
expect(await page.locator('table tr').count()).toBeGreaterThan(0);

// Text checks
expect(await page.textContent('#heading')).toContain('Welcome');
```

---

## 🧪 Test Data

```typescript
import { testData } from '../utils/test-data';

// Pre-defined data
testData.validCredentials
testData.invalidCredentials
testData.workspaceData
testData.authProfileData

// Generate unique values
testData.generateUniqueEmail('prefix')           // prefix1234567@mailinator.com
testData.generateUniqueWorkspaceName('workspace') // workspace_1234567890

// URLs
testData.login
testData.signup
testData.workspaces
testData.createWorkspace
```

---

## 🛠️ Helper Functions

```typescript
import { TestHelpers } from '../utils/helpers';

// Wait for element
await TestHelpers.waitForElement(page, '#selector', 5000);

// Check visibility
const visible = await TestHelpers.isElementVisible(page, '#selector');

// Get text
const text = await TestHelpers.getElementText(page, '#selector');

// Fill multiple fields
await TestHelpers.fillForm(page, {
  '#email': 'test@example.com',
  '#password': 'password123'
});

// Screenshot
await TestHelpers.screenshot(page, 'screenshot-name');

// Check page load time
const loadTime = await TestHelpers.checkPageLoadTime(page);

// Wait for condition
await TestHelpers.waitUntil(
  () => page.isVisible('#element'),
  10000  // timeout
);

// Count assertions
await TestHelpers.expectElementCount(page, 'tr', 5);

// Text assertions
await TestHelpers.expectElementContainsText(page, '#heading', 'Welcome');
```

---

## 🔍 Key Selectors

### Login Page
```
#email                    Email input
#password                 Password input
button[type="submit"]     Submit button
a:has-text("Sign up")     Sign up link
```

### Signup Page
```
#firstName                First name input
#lastName                 Last name input
#email                    Email input
#password                 Password input
```

### Workspaces
```
a:has-text("Add workspace")    Add button
table tbody tr                  Workspace rows
```

### Create Workspace
```
input[placeholder*="Acme"]     App name
textarea                       Description
input[placeholder*="https"]    Base URL
```

---

## 🐛 Debugging Tips

| Problem | Solution |
|---------|----------|
| Test fails at selector | Use `npm run test:ui` to see page |
| Need to step through | Use `npm run test:debug` |
| Want to see browser | Use `npm run test:headed` |
| Check selector exists | Open browser dev tools (F12) |
| View test report | Use `npm run test:report` |
| Test runs slowly | Use `npm run test:chromium` (faster) |

---

## 📋 Test Execution Flow

### 1. One-Time Setup
```bash
npm install          # Install dependencies
npm run dev          # Start app in terminal 1
```

### 2. Run Tests (Terminal 2)
```bash
npm test             # Quick test run
npm run test:ui      # Visual test runner (best)
npm run test:report  # See results
```

### 3. Common Workflows

**Debugging Single Test**
```bash
npm run test:debug -g "test name"
```

**Running Specific Suite**
```bash
npm run test:auth
npm run test:workspaces
```

**Viewing Results**
```bash
npm run test:report
```

---

## 🎯 Test Coverage

| Area | Tests | Status |
|------|-------|--------|
| Authentication | 12 | ✅ |
| Workspaces | 10 | ✅ |
| Complete Flows | 8 | ✅ |
| UI Elements | 12 | ✅ |
| Accessibility | 11 | ✅ |
| Examples | 15 | ✅ |
| **TOTAL** | **68+** | **✅** |

---

## 📚 Documentation

| File | Purpose | Size |
|------|---------|------|
| `TESTING.md` | Complete guide | 400+ lines |
| `PLAYWRIGHT_SETUP.md` | Setup & troubleshooting | 300+ lines |
| `FRAMEWORK_IMPLEMENTATION_SUMMARY.md` | Implementation overview | 400+ lines |
| `QUICK_REFERENCE.md` | This file | Quick lookup |

---

## 🔗 Useful Links

- **Playwright Docs**: https://playwright.dev
- **API Reference**: https://playwright.dev/docs/api
- **Best Practices**: https://playwright.dev/docs/best-practices
- **Selectors**: https://playwright.dev/docs/selectors

---

## ✅ Pre-Test Checklist

- [ ] App running (`npm run dev`)
- [ ] Terminal is in project root
- [ ] Dependencies installed (`npm install`)
- [ ] Port 3000 is accessible
- [ ] Internet connectivity (for test data)

---

## 🚨 Common Issues

### Tests fail with "Cannot connect to localhost:3000"
```bash
npm run dev  # Start application first
```

### Selector not found
```bash
npm run test:ui          # See the page
# Or check browser DevTools (F12)
```

### Tests running slow
```bash
npm run test:chromium    # Use single browser
# Remove other apps using resources
```

### Need full debugging
```bash
npm run test:debug
# Inspect page with DevTools
# Step through code execution
```

---

## 💡 Pro Tips

1. Use `npm run test:ui` for 90% of work
2. Use `npm run test:headed` to see browser
3. Use `npm run test:debug` to step through
4. Check `test-results/screenshots/` for failure images
5. Check `test-results/playwright-report/` for details
6. Use `.only()` to run single test: `test.only('name')`
7. Use `.skip()` to skip test: `test.skip('name')`

---

## 📞 Quick Help

```bash
# See all available tests
npm test -- --list

# Run tests matching pattern
npm test -- -g "auth"

# Run tests with specific config
npm test -- --config=playwright.config.ts

# See detailed help
npm test -- --help
```

---

## 📊 Test Report Access

After running tests:

```bash
npm run test:report        # Opens HTML report
# OR manually access
test-results/playwright-report/index.html
```

Report includes:
- ✅ Passed tests
- ❌ Failed tests
- ⏱️ Execution time
- 📸 Screenshots
- 🎥 Videos (on failure)

---

## 🎓 Example Test

```typescript
import { test, expect } from '@playwright/test';
import { LoginPage } from '../pages/login.page';
import { testData } from '../utils/test-data';

test.describe('Login Tests', () => {
  test('should login with valid credentials', async ({ page }) => {
    // Arrange
    const loginPage = new LoginPage(page);
    
    // Act
    await loginPage.goto();
    await loginPage.login(
      testData.validCredentials.email,
      testData.validCredentials.password
    );
    
    // Assert
    expect(page.url()).toContain('/workspaces');
  });
});
```

---

**Framework Status**: ✅ Production Ready  
**Last Updated**: May 2026  
**Playwright Version**: 1.56.0+

Start with: `npm run test:ui` 🚀
