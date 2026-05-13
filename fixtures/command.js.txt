// cypress/support/commands.js

const ROLE_CREDENTIALS = {
  admin:               { username: Cypress.env('ADMIN_USERNAME'),              password: Cypress.env('ADMIN_PASSWORD') },
  reception:           { username: Cypress.env('RECEPTION_USERNAME'),          password: Cypress.env('RECEPTION_PASSWORD') },
  booking_personel:    { username: Cypress.env('BOOKING_PERSONEL_USERNAME'),   password: Cypress.env('BOOKING_PERSONEL_PASSWORD') },
  master_personel:     { username: Cypress.env('MASTER_PERSONEL_USERNAME'),    password: Cypress.env('MASTER_PERSONEL_PASSWORD') },
  master_controler:    { username: Cypress.env('MASTER_CONTROLER_USERNAME'),   password: Cypress.env('MASTER_CONTROLER_PASSWORD') },
  analyst:             { username: Cypress.env('ANALYST_USERNAME'),            password: Cypress.env('ANALYST_PASSWORD') },
  department_reviewer: { username: Cypress.env('DEPARTMENT_REVIEWER_USERNAME'),password: Cypress.env('DEPARTMENT_REVIEWER_PASSWORD') },
  department_head:     { username: Cypress.env('DEPARTMENT_HEAD_USERNAME'),    password: Cypress.env('DEPARTMENT_HEAD_PASSWORD') },
  compilation:         { username: Cypress.env('COMPILATION_USERNAME'),        password: Cypress.env('COMPILATION_PASSWORD') },
  reviewer:            { username: Cypress.env('REVIEWER_USERNAME'),           password: Cypress.env('REVIEWER_PASSWORD') },
  person_incharge:     { username: Cypress.env('PERSON_INCHARGE_USERNAME'),    password: Cypress.env('PERSON_INCHARGE_PASSWORD') },
  customer_coordinator:{ username: Cypress.env('CUSTOMER_COORDINATOR_USERNAME'),password: Cypress.env('CUSTOMER_COORDINATOR_PASSWORD') },
  sales_personel_am:   { username: Cypress.env('SALES_PERSONEL_AM_USERNAME'),  password: Cypress.env('SALES_PERSONEL_AM_PASSWORD') },
  accountant_admin:    { username: Cypress.env('ACCOUNTANT_ADMIN_USERNAME'),   password: Cypress.env('ACCOUNTANT_ADMIN_PASSWORD') },
  accountant_crm:      { username: Cypress.env('ACCOUNTANT_CRM_USERNAME'),     password: Cypress.env('ACCOUNTANT_CRM_PASSWORD') },
  quality_personel:    { username: Cypress.env('QUALITY_PERSONEL_USERNAME'),   password: Cypress.env('QUALITY_PERSONEL_PASSWORD') },
  quality_manger:      { username: Cypress.env('QUALITY_MANGER_USERNAME'),     password: Cypress.env('QUALITY_MANGER_PASSWORD') },
};

// ─── Primary login command ────────────────────────────────────────────────────
// labName: optional override. Falls back to LAB_NAME env var (set per environment).
//
// Login flow (two possible paths after credentials):
//   Path A — location picker appears  → select lab → click Sign In → dashboard
//   Path B — no picker (single-lab)   → already on dashboard
//
// The session is only saved once cy.url() confirms '/dashboard',
// so an incomplete session (stuck on picker) can never slip through.
Cypress.Commands.add('loginAs', (roleKey, labName) => {
  const creds = ROLE_CREDENTIALS[roleKey];
  if (!creds) throw new Error(`No credentials configured for role_key="${roleKey}"`);

  const lab = labName || Cypress.env('LAB_NAME');
  // Session key includes lab so switching orgs always produces a separate session.
  const sessionId = lab ? `${roleKey}__${lab}` : roleKey;

  cy.session(sessionId, () => {
    cy.intercept('**/stimulsoft*.js', { body: '/* stubbed */' });

    cy.visit('/login', { timeout: 120000 });
    cy.get('[name="username"]', { timeout: 30000 }).should('be.visible').clear().type(creds.username);
    cy.get('[name="password"]').should('be.visible').clear().type(creds.password);
    cy.contains('button', 'Sign in').click();

    // After the first Sign In, two outcomes are possible:
    //   A) Location picker appears ON the same /login page → select lab → click Sign In again
    //   B) App redirects directly to /dashboard (single-lab accounts, no picker shown)
    //
    // We wait (retrying every 50 ms) until EITHER:
    //   • the "Choose your location" text appears in the body  (picker rendered → case A)
    //   • the username field disappears from the body          (redirect started → case B)
    // Throwing inside a .should() callback signals "not yet" and triggers a retry.
    cy.get('body', { timeout: 20000 }).should($body => {
      const hasPicker   = $body.find(':contains("Choose your location")').length > 0;
      const formPresent = $body.find('[name="username"]').length > 0;
      if (formPresent && !hasPicker) throw new Error('Waiting for app to respond to Sign In');
    }).then($body => {
      if ($body.find(':contains("Choose your location")').length > 0) {
        // Case A — location picker visible
        cy.contains('Choose your location').click();
        if (lab) {
          cy.contains('span', lab, { timeout: 10000 }).should('be.visible').click();
        } else {
          cy.get('span[class*="cursor-pointer"], li').first().click();
        }
        cy.contains('button', 'Sign in').click();
      }
      // Case B — form already gone, redirect in progress; fall through to URL gate below.
    });

    // Hard gate: session is only saved once we reach the dashboard.
    // Prevents silently caching a broken/incomplete session.
    cy.url({ timeout: 60000 }).should('include', '/dashboard');
  });
});

// ─── Clear all saved Cypress sessions ────────────────────────────────────────
// Use before switching roles in dynamic permission tests so the next loginAs
// always does a real login and picks up the latest server-side permissions.
Cypress.Commands.add('clearAllSessions', () => {
  Cypress.session.clearAllSavedSessions();
  cy.clearCookies();
  cy.clearLocalStorage();
});

// ─── Convenience: wipe sessions then login fresh ─────────────────────────────
Cypress.Commands.add('freshLoginAs', (roleKey, labName) => {
  cy.clearAllSessions();
  cy.loginAs(roleKey, labName);
});

Cypress.Commands.add('getRolePermissions', (roleKey) => {
  return cy.fixture('roles-permissions.json').then(fx => {
    return fx.roles.find(r => r.role_key === roleKey);
  });
});
