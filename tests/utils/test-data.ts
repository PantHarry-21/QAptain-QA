export const testData = {
  validCredentials: {
    email: 'test@example.com',
    password: 'Test@123',
    firstName: 'Test',
    lastName: 'User',
  },

  invalidCredentials: {
    email: 'invalid@example.com',
    password: 'wrongpassword',
  },

  workspaceData: {
    name: 'E2E Test Workspace',
    description: 'Automated testing workspace',
    baseUrl: 'https://test.example.com',
  },

  authProfileData: {
    name: 'Primary Admin',
    username: 'admin',
    password: 'Password@123',
    labName: 'Test Lab',
    roleHint: 'ADMIN',
  },

  // Generate unique email for each test run
  generateUniqueEmail: (prefix = 'test') => {
    const timestamp = Date.now();
    const random = Math.random().toString(36).substring(7);
    return `${prefix}${timestamp}${random}@mailinator.com`;
  },

  // Generate unique workspace name
  generateUniqueWorkspaceName: (prefix = 'workspace') => {
    const timestamp = Date.now();
    return `${prefix}_${timestamp}`;
  },
};

export const testUrls = {
  login: '/login',
  signup: '/signup',
  workspaces: '/workspaces',
  createWorkspace: '/workspaces/new',
  dashboard: '/dashboard',
};

export const testSelectors = {
  // Common
  loadingSpinner: '[role="status"]',
  errorMessage: '.text-red-400, .error, [role="alert"]',
  successMessage: '.text-emerald-400, .success',

  // Auth
  emailInput: '#email',
  passwordInput: '#password',
  submitButton: 'button[type="submit"]',

  // Workspace
  workspaceCard: '[data-testid="workspace-card"], .workspace-card',
  modulesList: 'table tbody tr',
};
