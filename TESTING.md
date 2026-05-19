# QAPtain Playwright Testing Framework

Complete Playwright automation framework for QAPtain application testing.

## 📋 Overview

This testing framework provides comprehensive end-to-end (E2E) testing for the QAPtain automation testing platform. It includes:

- ✅ **Authentication Tests** - Login, Signup, credential validation
- ✅ **Workspace Management** - Create, view, and manage workspaces
- ✅ **Complete User Flows** - Full journey testing
- ✅ **UI Elements Tests** - Component visibility and interaction
- ✅ **Accessibility Tests** - WCAG compliance, keyboard navigation
- ✅ **Page Object Model** - Maintainable test structure
- ✅ **Reusable Fixtures** - Authentication fixtures for secured tests

## 🚀 Quick Start

### Installation

```bash
# Install dependencies
npm install

# Dependencies are already included in package.json
```

### Running Tests

```bash
# Run all tests
npm test

# Run with UI (recommended)
npm run test:ui

# Run specific test suite
npm run test:auth
npm run test:workspaces
npm run test:complete
npm run test:ui-elements
npm run test:accessibility

# Run in headed mode (see browser)
npm run test:headed

# Debug mode
npm run test:debug

# View test report
npm run test:report
```

### Browser-Specific Testing

```bash
# Test on Chromium only
npm run test:chromium

# Test on Firefox only
npm run test:firefox

# Test on WebKit (Safari) only
npm run test:webkit
```

## 📁 Project Structure

```
tests/
├── fixtures/
│   └── auth.fixture.ts          # Authentication fixtures for secured tests
├── pages/
│   ├── base.page.ts             # Base page class with common methods
│   ├── login.page.ts            # Login page object
│   ├── signup.page.ts           # Signup page object
│   ├── workspaces.page.ts       # Workspaces list page object
│   ├── create-workspace.page.ts # Create workspace page object
│   └── workspace-details.page.ts # Workspace details page object
├── specs/
│   ├── auth.spec.ts             # Authentication tests
│   ├── workspaces.spec.ts       # Workspace management tests
│   ├── complete-flow.spec.ts    # End-to-end flow tests
│   ├── ui-elements.spec.ts      # UI component tests
│   └── accessibility.spec.ts    # Accessibility tests
└── utils/
    ├── test-data.ts             # Test data and constants
    ├── helpers.ts               # Helper functions
    └── .gitignore              # Ignore test artifacts

playwright.config.ts             # Playwright configuration
```

## 🎯 Page Object Model

Each page has a corresponding Page Object class that encapsulates:

- **Selectors** - All CSS/XPath selectors for the page
- **Actions** - Methods to interact with page elements
- **Assertions** - Methods to verify page state

### Example: LoginPage

```typescript
import { LoginPage } from '../pages/login.page';

test('should login successfully', async ({ page }) => {
  const loginPage = new LoginPage(page);
  
  await loginPage.goto();
  await loginPage.login('test@example.com', 'password');
  await loginPage.loginAndWait('test@example.com', 'password');
  
  expect(page.url()).toContain('/workspaces');
});
```

## 🔐 Authentication Fixtures

For tests that require authentication, use the custom fixtures:

```typescript
import { test, expect } from '../fixtures/auth.fixture';
import { WorkspacesPage } from '../pages/workspaces.page';

test('authenticated user can create workspace', async ({ authenticatedPage }) => {
  const workspacesPage = new WorkspacesPage(authenticatedPage);
  await workspacesPage.goto();
  
  const count = await workspacesPage.getWorkspacesCount();
  expect(count).toBeGreaterThanOrEqual(0);
});
```

Available fixtures:
- `authenticatedPage` - Automatically logs in before test
- `login()` - Function to login with custom credentials
- `signup()` - Function to signup with custom credentials

## 🧪 Test Suites

### 1. Authentication Tests (`auth.spec.ts`)

Tests for user registration and login flows:

- Login page elements and visibility
- Signup page form validation
- Error handling for invalid credentials
- Navigation between auth pages
- Field requirement validation

### 2. Workspace Tests (`workspaces.spec.ts`)

Tests for workspace management:

- Display workspaces list
- Create new workspace
- Multi-step workspace creation
- Application details form
- Authentication profile setup
- Discovery job initiation

### 3. Complete Flow Tests (`complete-flow.spec.ts`)

End-to-end user journeys:

- Full signup to workspace creation flow
- Navigation between pages
- Form validation across pages
- Browser back button handling
- URL structure validation

### 4. UI Elements Tests (`ui-elements.spec.ts`)

Component and UI verification:

- Form element visibility
- Input field types
- Button text and state
- Links and navigation
- Responsive design (mobile, tablet, desktop)
- Form interactions

### 5. Accessibility Tests (`accessibility.spec.ts`)

WCAG compliance and accessibility:

- Heading structure
- Label associations
- Color contrast
- Keyboard navigation
- ARIA attributes
- Screen reader support
- Page title and language attributes

## 📊 Configuration

### `playwright.config.ts`

Key configurations:

```typescript
{
  testDir: './tests',           // Test directory
  baseURL: 'http://localhost:3000', // Application URL
  timeout: 30000,              // Test timeout
  retries: 2,                  // Retry failed tests
  workers: undefined,          // Parallel workers
  
  projects: [
    'chromium',
    'firefox',
    'webkit'
  ],
  
  reporter: [
    'html',                    // HTML report
    'json',                    // JSON results
    'junit',                   // JUnit XML
    'list'                     // Console output
  ]
}
```

## 🛠️ Test Utilities

### TestHelpers Class

```typescript
import { TestHelpers } from '../utils/helpers';

// Wait for element
await TestHelpers.waitForElement(page, '#selector');

// Check visibility
const isVisible = await TestHelpers.isElementVisible(page, '#selector');

// Get text content
const text = await TestHelpers.getElementText(page, '#selector');

// Fill form
await TestHelpers.fillForm(page, {
  '#email': 'test@example.com',
  '#password': 'password'
});

// Take screenshot
await TestHelpers.screenshot(page, 'test-name');

// Check page load time
const loadTime = await TestHelpers.checkPageLoadTime(page);

// Wait for condition
await TestHelpers.waitUntil(
  () => page.isVisible('#element'),
  10000
);
```

### Test Data

```typescript
import { testData } from '../utils/test-data';

// Use pre-defined test data
const email = testData.generateUniqueEmail('user');
const workspaceName = testData.generateUniqueWorkspaceName();

console.log(testData.validCredentials);      // { email, password, firstName, lastName }
console.log(testData.invalidCredentials);    // { email, password }
console.log(testData.workspaceData);         // { name, description, baseUrl }
```

## 📈 Test Reports

### HTML Report

After running tests, view the detailed HTML report:

```bash
npm run test:report
```

This opens an interactive report showing:
- ✅ Passed tests
- ❌ Failed tests
- ⏱️ Execution time
- 📸 Screenshots
- 🎥 Video recordings (on failure)
- Traces for debugging

### Console Output

Tests output a summary to the console:

```
✓ authentication.spec.ts (5 tests)
✓ workspaces.spec.ts (8 tests)
✓ complete-flow.spec.ts (4 tests)
✓ ui-elements.spec.ts (6 tests)
✓ accessibility.spec.ts (7 tests)

30 passed (2m 15s)
```

## 🎨 Selectors Used

### Login Page

| Element | Selector |
|---------|----------|
| Email | `#email` |
| Password | `#password` |
| Submit | `button[type="submit"]` |
| Signup Link | `a:has-text("Sign up")` |
| Error Message | `p.text-red-400` |

### Signup Page

| Element | Selector |
|---------|----------|
| First Name | `#firstName` |
| Last Name | `#lastName` |
| Email | `#email` |
| Password | `#password` |
| Submit | `button[type="submit"]` |
| Login Link | `a:has-text("Log in")` |

### Create Workspace Page

| Element | Selector |
|---------|----------|
| App Name | `input[placeholder*="e.g. Acme"]` |
| Description | `textarea` |
| Base URL | `input[placeholder*="https://app"]` |
| Auth Name | `input[value="Primary"]` |
| Username | `input[autocomplete="off"]` |
| Password | `input[type="password"]` |
| Lab Name | `input[placeholder*="For multi-step"]` |
| Start Discovery | `button:has-text("Start discovery")` |

## 🐛 Debugging

### Debug Mode

```bash
npm run test:debug
```

Opens the Playwright Inspector to step through tests.

### Headed Mode

```bash
npm run test:headed
```

Runs tests in headed mode (see browser window).

### Trace Viewer

```bash
npx playwright show-trace test-results/trace.zip
```

Replay test execution with full DOM snapshots.

## ✅ Best Practices

1. **Page Object Model** - Use page objects for all page interactions
2. **Explicit Waits** - Use `waitForURL`, `waitForSelector` instead of `waitForTimeout`
3. **Unique Test Data** - Generate unique emails/names for each test run
4. **Assertions** - Use `expect()` for all validations
5. **Error Handling** - Properly handle error scenarios
6. **Screenshots** - Capture on failure for debugging
7. **Parallel Execution** - Tests run in parallel by default
8. **Retries** - Failed tests automatically retry on CI

## 🔄 CI/CD Integration

### GitHub Actions Example

```yaml
name: E2E Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '18'
      
      - run: npm install
      - run: npm run build
      - run: npx playwright install
      - run: npm test
      
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: playwright-report
          path: test-results/playwright-report/
```

## 📝 Writing New Tests

### Basic Test Structure

```typescript
import { test, expect } from '@playwright/test';
import { YourPage } from '../pages/your.page';

test.describe('Your Feature', () => {
  test('should do something', async ({ page }) => {
    const yourPage = new YourPage(page);
    
    // Arrange
    await yourPage.goto();
    
    // Act
    await yourPage.performAction();
    
    // Assert
    expect(await yourPage.getResult()).toBe('expected');
  });
});
```

### Adding New Page Objects

1. Create file in `tests/pages/` (e.g., `new-page.page.ts`)
2. Extend `BasePage` class
3. Define all selectors as properties
4. Add action methods
5. Import and use in tests

## 🤝 Contributing

When adding new tests:

1. Follow existing naming conventions
2. Group related tests using `test.describe()`
3. Use meaningful test names
4. Add comments for complex test logic
5. Keep selectors updated if UI changes
6. Run all tests before committing

## 📞 Support

For issues or questions:

1. Check the Playwright documentation: https://playwright.dev
2. Review existing test examples
3. Check test reports for failures
4. Use debug mode to troubleshoot

## 📚 Resources

- [Playwright Documentation](https://playwright.dev)
- [Best Practices](https://playwright.dev/docs/best-practices)
- [API Reference](https://playwright.dev/docs/api/class-page)
- [Selectors](https://playwright.dev/docs/selectors)
- [Test Configuration](https://playwright.dev/docs/test-configuration)

---

**Last Updated**: May 2026  
**Framework Version**: 1.0.0  
**Playwright Version**: 1.56.0+
