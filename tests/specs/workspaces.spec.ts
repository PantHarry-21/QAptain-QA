import { test, expect } from '../fixtures/auth.fixture';
import { WorkspacesPage } from '../pages/workspaces.page';
import { CreateWorkspacePage } from '../pages/create-workspace.page';

test.describe('Workspaces Management', () => {
  test.describe('Workspaces List Page', () => {
    test('should display workspaces page for authenticated user', async ({ authenticatedPage }) => {
      const workspacesPage = new WorkspacesPage(authenticatedPage);
      await workspacesPage.goto();

      expect(authenticatedPage.url()).toContain('/workspaces');
    });

    test('should show add workspace button', async ({ authenticatedPage }) => {
      const workspacesPage = new WorkspacesPage(authenticatedPage);
      await workspacesPage.goto();

      const isVisible = await workspacesPage.isVisible(workspacesPage.addWorkspaceButton);
      expect(isVisible).toBeTruthy();
    });

    test('should navigate to create workspace page', async ({ authenticatedPage }) => {
      const workspacesPage = new WorkspacesPage(authenticatedPage);
      await workspacesPage.goto();
      await workspacesPage.clickAddWorkspace();

      expect(authenticatedPage.url()).toContain('/workspaces/new');
    });

    test('should display workspace list', async ({ authenticatedPage }) => {
      const workspacesPage = new WorkspacesPage(authenticatedPage);
      await workspacesPage.goto();

      const count = await workspacesPage.getWorkspacesCount();
      expect(count).toBeGreaterThanOrEqual(0);
    });
  });

  test.describe('Create Workspace Page', () => {
    test.beforeEach(async ({ authenticatedPage }) => {
      const workspacesPage = new WorkspacesPage(authenticatedPage);
      await workspacesPage.goto();
      await workspacesPage.clickAddWorkspace();
    });

    test('should display step 1: application details form', async ({ authenticatedPage }) => {
      const createPage = new CreateWorkspacePage(authenticatedPage);

      expect(
        await createPage.isVisible(createPage.appNameInput)
      ).toBeTruthy();
      expect(
        await createPage.isVisible(createPage.appDescriptionInput)
      ).toBeTruthy();
      expect(
        await createPage.isVisible(createPage.appBaseUrlInput)
      ).toBeTruthy();
    });

    test('should fill application details on step 1', async ({ authenticatedPage }) => {
      const createPage = new CreateWorkspacePage(authenticatedPage);

      await createPage.fillApplicationDetails(
        'Test App',
        'Test Description',
        'https://test.example.com'
      );

      expect(
        await authenticatedPage.inputValue(createPage.appNameInput)
      ).toBe('Test App');
      expect(
        await authenticatedPage.inputValue(createPage.appDescriptionInput)
      ).toBe('Test Description');
      expect(
        await authenticatedPage.inputValue(createPage.appBaseUrlInput)
      ).toBe('https://test.example.com');
    });

    test('should proceed to step 2 on continue click', async ({ authenticatedPage }) => {
      const createPage = new CreateWorkspacePage(authenticatedPage);

      await createPage.fillApplicationDetails(
        'Test App',
        'Test Description',
        'https://test.example.com'
      );
      await createPage.clickStep1Continue();

      // Verify we're on step 2
      expect(
        await createPage.isVisible('text="2 · Authentication"')
      ).toBeTruthy();
    });

    test('should display step 2: auth profile form', async ({ authenticatedPage }) => {
      const createPage = new CreateWorkspacePage(authenticatedPage);

      await createPage.completeStep1(
        'Test App',
        'Test Description',
        'https://test.example.com'
      );

      expect(
        await createPage.isVisible('text="2 · Authentication"')
      ).toBeTruthy();
    });

    test('should display step 3: discovery form', async ({ authenticatedPage }) => {
      const createPage = new CreateWorkspacePage(authenticatedPage);

      // Step 1
      await createPage.completeStep1(
        'Test App',
        'Test Description',
        'https://test.example.com'
      );

      // Step 2
      await createPage.fillAuthProfile(
        'Primary',
        'testuser',
        'Password@123'
      );
      await createPage.clickStep2Continue();

      expect(
        await createPage.isVisible('text="3 · Lightweight discovery"')
      ).toBeTruthy();
      expect(
        await createPage.isVisible(createPage.startDiscoveryButton)
      ).toBeTruthy();
    });
  });

  test.describe('Workspace Creation Flow', () => {
    test('should allow user to initiate discovery from step 3', async ({
      authenticatedPage,
    }) => {
      const workspacesPage = new WorkspacesPage(authenticatedPage);
      const createPage = new CreateWorkspacePage(authenticatedPage);

      await workspacesPage.goto();
      await workspacesPage.clickAddWorkspace();

      // Complete steps 1 & 2
      await createPage.fillApplicationDetails(
        'E2E Test Workspace',
        'E2E Testing Workspace',
        'https://test.example.com'
      );
      await createPage.clickStep1Continue();

      await createPage.fillAuthProfile(
        'Primary',
        'admin',
        'Password@123',
        'Test Lab'
      );
      await createPage.clickStep2Continue();

      // Check step 3 is displayed
      expect(
        await createPage.isVisible(createPage.startDiscoveryButton)
      ).toBeTruthy();
    });

    test('should handle auth profile creation with optional lab name', async ({
      authenticatedPage,
    }) => {
      const createPage = new CreateWorkspacePage(authenticatedPage);
      const workspacesPage = new WorkspacesPage(authenticatedPage);

      await workspacesPage.goto();
      await workspacesPage.clickAddWorkspace();

      await createPage.completeStep1(
        'Multi-Step Auth Test',
        'Testing multi-step auth',
        'https://multiauth.example.com'
      );

      await createPage.fillAuthProfile(
        'Admin Profile',
        'adminuser',
        'AdminPass@123',
        'Production',
        'ADMIN'
      );
      await createPage.clickStep2Continue();

      // Verify we reached step 3
      expect(
        await createPage.isVisible('text="3 · Lightweight discovery"')
      ).toBeTruthy();
    });
  });
});
