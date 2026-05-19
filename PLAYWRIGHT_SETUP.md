# Playwright Test Framework Setup Guide

## ✅ Quick Setup (5 minutes)

### 1. Install Dependencies

```bash
npm install
```

This installs all Playwright dependencies including:
- `@playwright/test` - Test framework
- `playwright` - Browser automation
- `playwright-core` - Core engine

### 2. Verify Installation

```bash
npx playwright --version
```

You should see version 1.56.0 or higher.

### 3. Start the Application

In one terminal:

```bash
npm run dev
```

The application will be available at `http://localhost:3000`

### 4. Run Tests

In another terminal:

```bash
npm test
```

## 🎯 Test Execution

### Running All Tests

```bash
npm test
```

### Running Tests with UI

```bash
npm run test:ui
```

This opens an interactive test runner where you can:
- ▶️ Run individual tests
- ⏸️ Step through execution
- 📸 View screenshots
- 🎥 Watch video recordings
- 🔍 Inspect DOM elements

### Running Specific Test Suites

```bash
# Authentication tests only
npm run test:auth

# Workspace tests only
npm run test:workspaces

# End-to-end flow tests
npm run test:complete

# UI element tests
npm run test:ui-elements

# Accessibility tests
npm run test:accessibility
```

### Running in Headed Mode

See the browser as tests run:

```bash
npm run test:headed
```

### Debug Mode

Step through tests with debugging tools:

```bash
npm run test:debug
```

### Target Specific Browser

```bash
# Chromium only
npm run test:chromium

# Firefox only
npm run test:firefox

# WebKit (Safari) only
npm run test:webkit
```

## 📊 Viewing Test Reports

After running tests, view the HTML report:

```bash
npm run test:report
```

Or manually:

```bash
npx playwright show-report test-results/playwright-report
```

## 🔧 Configuration

### `playwright.config.ts` Key Settings

```typescript
baseURL: 'http://localhost:3000'  // Your app URL
timeout: 30000                     // Test timeout
retries: 2                         // Retry failed tests
workers: 4                         // Parallel workers (leave undefined for auto)
```

### Modifying Configuration

Edit `playwright.config.ts` to:
- Change base URL (if app runs on different port)
- Adjust timeouts
- Add/remove browsers
- Configure reporters
- Set up web server startup

## 🌍 Environment Setup

### For Local Development

1. Ensure app is running on `http://localhost:3000`
2. Create test accounts or use existing ones
3. Database should be seeded with test data

### For CI/CD

```yaml
# GitHub Actions example
- name: Run Playwright tests
  run: |
    npm install
    npx playwright install
    npm test
```

## 📝 Test Account Setup

### Create Test Account

1. Navigate to `http://localhost:3000/signup`
2. Fill in form with test data:
   - First Name: `Test`
   - Last Name: `User`
   - Email: `testuser@mailinator.com`
   - Password: `Test@123`
3. Complete signup process
4. Verify account activation

### Use in Tests

Tests can use these credentials:

```typescript
const email = 'testuser@mailinator.com';
const password = 'Test@123';

await loginPage.login(email, password);
```

Or generate unique accounts for each test:

```typescript
const uniqueEmail = testData.generateUniqueEmail('test');
// Results in: test1234567890abc@mailinator.com
```

## 🔐 Authentication in Tests

### Automatic Authentication

Use the auth fixture for automatic login:

```typescript
import { test } from '../fixtures/auth.fixture';

test('authenticated test', async ({ authenticatedPage }) => {
  // Already logged in before test
  await authenticatedPage.goto('/workspaces');
});
```

### Manual Authentication

```typescript
import { test } from '@playwright/test';
import { LoginPage } from '../pages/login.page';

test('manual auth', async ({ page }) => {
  const loginPage = new LoginPage(page);
  await loginPage.loginAndWait('test@example.com', 'Test@123');
  
  // Now logged in and ready for next steps
});
```

## 🐛 Troubleshooting

### Tests Can't Connect to App

**Problem**: `Error: connect ECONNREFUSED 127.0.0.1:3000`

**Solution**: 
1. Ensure app is running: `npm run dev`
2. Check it's accessible: `http://localhost:3000`
3. Wait for startup (may take 10+ seconds)

### Tests Fail with "Timeout"

**Problem**: `Timeout of 30000ms exceeded`

**Solution**:
1. Increase timeout in `playwright.config.ts`
2. Check if selectors are correct
3. Verify page is loading
4. Use debug mode: `npm run test:debug`

### Selectors Not Found

**Problem**: `locator.click: Target page, context or browser has been closed`

**Solution**:
1. Verify selector exists on page
2. Check selector syntax
3. Use browser dev tools to inspect
4. Use `--headed` mode to see actual page

### Tests Pass Locally but Fail in CI

**Common Issues**:
- Different environment variables
- Missing environment setup
- Timing issues (use explicit waits)
- Browser not installed

**Solutions**:
```bash
# Ensure browsers are installed
npx playwright install

# Check environment variables
echo $DATABASE_URL

# Run with more detailed output
npm test -- --debug
```

### Tests Run Very Slowly

**Optimization**:
```bash
# Run in parallel (default)
npm test

# Increase workers
npx playwright test --workers=8

# Use faster browser (Chromium)
npm run test:chromium
```

## 📚 Learning Resources

### Official Documentation
- [Playwright Docs](https://playwright.dev)
- [Test API](https://playwright.dev/docs/api/class-test)
- [Best Practices](https://playwright.dev/docs/best-practices)

### Key Concepts
- **Locators**: Find elements with `page.locator()`
- **Page Objects**: Encapsulate page interactions
- **Fixtures**: Reusable test setup
- **Assertions**: Use `expect()` for validations

### Example Tests
Check `tests/specs/example.spec.ts` for 15 comprehensive examples.

## 🚀 Advanced Setup

### Custom Baseconfig

Create `playwright.local.ts` for local overrides:

```typescript
import config from './playwright.config';

export default {
  ...config,
  baseURL: 'http://localhost:3001', // Different port
  webServer: {
    command: 'npm run dev:custom',
  },
};
```

Use it with:
```bash
npx playwright test --config=playwright.local.ts
```

### Multiple Environments

```bash
# Development
npx playwright test --config=playwright.dev.ts

# Staging
npx playwright test --config=playwright.staging.ts

# Production (read-only tests only)
npx playwright test --config=playwright.prod.ts
```

### Custom Reporters

Add to `playwright.config.ts`:

```typescript
reporter: [
  ['html'],
  ['json', { outputFile: 'results.json' }],
  ['junit', { outputFile: 'results.xml' }],
  ['github'],  // GitHub Actions
]
```

## ✨ Pro Tips

1. **Use `--headed` mode** while debugging tests
2. **Take screenshots** on failure: Already configured
3. **Record videos** on failure: Already configured
4. **Use `test.only()`** to run single test
5. **Use `test.skip()`** to skip test
6. **Use `test.describe.only()`** to run single suite
7. **Check traces**: `playwright show-trace test-results/trace.zip`

## 📋 Checklist Before Running Tests

- [ ] Node.js v18+ installed
- [ ] `npm install` completed
- [ ] App running on `http://localhost:3000`
- [ ] Database is seeded with test data
- [ ] Test accounts created or unique generation used
- [ ] All selectors verified in browser
- [ ] `playwright.config.ts` correct URL
- [ ] No other services using port 3000

## 🔄 Continuous Integration

### GitHub Actions Setup

Add `.github/workflows/tests.yml`:

```yaml
name: Playwright Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '18'
      
      - run: npm ci
      - run: npm run build
      - run: npx playwright install
      - run: npm test
      
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: playwright-report
          path: test-results/playwright-report/
```

## 📞 Getting Help

1. **Read error messages carefully** - They're very descriptive
2. **Use debug mode** - `npm run test:debug`
3. **Check Playwright docs** - https://playwright.dev
4. **Review example tests** - `tests/specs/example.spec.ts`
5. **Use headed mode** - See what's happening: `npm run test:headed`

---

**Last Updated**: May 2026  
**Playwright Version**: 1.56.0+
