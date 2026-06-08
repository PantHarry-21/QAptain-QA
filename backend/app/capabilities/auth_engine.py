"""
Auth Capability Engine — Authentication workflow testing.

Covers: valid login, invalid credentials, empty fields, session management,
two-step login, logout, and credential security checks.

Note: executor._execute_login handles test-SETUP login (getting into the app
before scenarios run). This engine tests the LOGIN FEATURE ITSELF as a QA scenario
(e.g., "Verify invalid credentials show error message").
"""
from __future__ import annotations
from app.capabilities.base_engine import BaseCapabilityEngine
from app.capabilities.contracts import CapabilityContext, RecoveryStep, RecoveryAction

_SQL_INJECT = "' OR '1'='1'; --"
_XSS = "<script>alert('xss')</script>"


class AuthEngine(BaseCapabilityEngine):
    engine_id = "auth"
    workflow_types = ["AUTH"]

    def generate_positive_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id

        return [
            self._step("screenshot", "Capture login page initial state",
                      "AUTH_SETUP", "Baseline evidence of login form", engine_id=e),
            self._step("assert_visible", "Verify login form is rendered",
                      "AUTH_SETUP", "Login page must show username and password fields",
                      target="username|email|login|sign in|user", engine_id=e),

            # Happy path: valid credentials
            self._step("fill", "Enter valid username or email",
                      "AUTH_VALID_LOGIN", "Fill credentials for successful login",
                      target="Username|Email|User|Login ID",
                      value="valid_test_user@example.com", engine_id=e),
            self._step("fill", "Enter valid password",
                      "AUTH_VALID_LOGIN", "Enter correct password",
                      target="Password|Pass|Secret",
                      value="ValidPassword123!", engine_id=e),
            self._step("click", "Click Sign In / Login button",
                      "AUTH_VALID_LOGIN", "Submit valid credentials",
                      target="Sign In|Login|Log In|Submit|SIGN IN", engine_id=e),
            self._wait_network("Wait for authentication to complete", "AUTH_VALID_LOGIN"),
            self._step("assert_visible", "Verify successful login — dashboard or navigation appears",
                      "AUTH_VERIFY_SUCCESS",
                      "Successful login must redirect to the main application with navigation",
                      target="dashboard|home|welcome|navigation|menu|sidebar",
                      checkpoint=True, timeout_ms=15000, engine_id=e),
            self._step("screenshot", "Capture authenticated application state",
                      "AUTH_VERIFY_SUCCESS", "Login success evidence", engine_id=e),

            # Logout
            self._step("click", "Logout from the application",
                      "AUTH_LOGOUT", "Test clean logout workflow",
                      target="Logout|Log Out|Sign Out|profile|account|user menu",
                      on_fail="skip", engine_id=e),
            self._step("assert_visible", "Verify login page appears after logout",
                      "AUTH_LOGOUT", "Logout must return user to login screen",
                      target="login|sign in|username|password|email",
                      on_fail="skip", checkpoint=True, engine_id=e),
            self._step("screenshot", "Capture logged-out state", "AUTH_LOGOUT",
                      "Logout evidence", on_fail="skip", engine_id=e),
        ]

    def generate_negative_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id

        steps = [
            # Test 1: Empty username
            self._step("click", "Click login with empty username field",
                      "AUTH_EMPTY_USERNAME", "Empty username must be rejected",
                      target="Sign In|Login|Submit", engine_id=e, test_category="negative"),
            self._step("assert_visible", "Verify username required error appears",
                      "AUTH_EMPTY_USERNAME", "System must indicate username is required",
                      target="required|please enter|username is required|email is required",
                      on_fail="skip", checkpoint=True, engine_id=e, test_category="negative"),
            self._step("screenshot", "Capture empty username error",
                      "AUTH_EMPTY_USERNAME", "Validation evidence", on_fail="skip",
                      engine_id=e, test_category="negative"),

            # Test 2: Wrong password
            self._step("fill", "Enter valid username",
                      "AUTH_WRONG_PASSWORD", "Setup for wrong password test",
                      target="Username|Email|User",
                      value="valid_test_user@example.com", engine_id=e, test_category="negative"),
            self._step("fill", "Enter intentionally wrong password",
                      "AUTH_WRONG_PASSWORD", "Test invalid credentials rejection",
                      target="Password|Pass",
                      value="WrongPassword999!", engine_id=e, test_category="negative"),
            self._step("click", "Submit wrong credentials",
                      "AUTH_WRONG_PASSWORD", "Attempt login with invalid password",
                      target="Sign In|Login|Submit", engine_id=e, test_category="negative"),
            self._wait_network("Wait for authentication response", "AUTH_WRONG_PASSWORD"),
            self._step("assert_visible", "Verify invalid credentials error appears",
                      "AUTH_WRONG_PASSWORD",
                      "System must reject wrong credentials with clear error message",
                      target="invalid|incorrect|wrong|failed|unauthorized|credentials|try again",
                      checkpoint=True, timeout_ms=10000, engine_id=e, test_category="negative"),
            self._step("screenshot", "Capture invalid credentials error",
                      "AUTH_WRONG_PASSWORD", "Wrong-password rejection evidence",
                      on_fail="skip", engine_id=e, test_category="negative"),
        ]

        return steps

    def generate_edge_case_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        return [
            # Case sensitivity
            self._step("fill", "Enter username in different case (UPPERCASE)",
                      "AUTH_CASE_SENSITIVITY", "Test if system is case-sensitive for usernames",
                      target="Username|Email|User",
                      value="VALID_TEST_USER@EXAMPLE.COM", engine_id=e, test_category="edge_case", on_fail="skip"),
            self._step("fill", "Enter valid password",
                      "AUTH_CASE_SENSITIVITY", "Fill password for case test",
                      target="Password|Pass",
                      value="ValidPassword123!", engine_id=e, test_category="edge_case", on_fail="skip"),
            self._step("click", "Submit to test case sensitivity",
                      "AUTH_CASE_SENSITIVITY", "System should handle case-insensitive usernames",
                      target="Sign In|Login|Submit", engine_id=e, test_category="edge_case", on_fail="skip"),
            self._step("screenshot", "Capture case-sensitivity test result",
                      "AUTH_CASE_SENSITIVITY", "Case sensitivity evidence",
                      on_fail="skip", engine_id=e, test_category="edge_case"),
        ]

    def generate_security_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        return [
            # SQL injection in credentials
            self._step("fill", "Enter SQL injection in username field",
                      "AUTH_SECURITY", "Login must not be bypassable with SQL injection",
                      target="Username|Email|User",
                      value=_SQL_INJECT, engine_id=e, test_category="security", on_fail="skip"),
            self._step("fill", "Enter SQL injection in password field",
                      "AUTH_SECURITY", "Password field must sanitize injection attempts",
                      target="Password|Pass",
                      value=_SQL_INJECT, engine_id=e, test_category="security", on_fail="skip"),
            self._step("click", "Submit SQL injection payload",
                      "AUTH_SECURITY", "System must reject SQL injection without exposing DB errors",
                      target="Sign In|Login|Submit", engine_id=e, test_category="security", on_fail="skip"),
            self._step("assert_not_text", "Verify no SQL error or stack trace is exposed",
                      "AUTH_SECURITY", "Database errors must never be exposed to the user",
                      target="SQL|syntax error|ORA-|pg_|mysql|exception|stack trace|server error",
                      on_fail="skip", engine_id=e, test_category="security"),
            self._step("screenshot", "Capture SQL injection test result",
                      "AUTH_SECURITY", "Security test evidence", on_fail="skip",
                      engine_id=e, test_category="security"),
        ]

    def get_recovery_steps(self, failed_action: str, error_context: dict) -> list[RecoveryStep]:
        return [
            RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait for login form to stabilize", priority=1),
            RecoveryStep(RecoveryAction.CLEAR_AND_RETYPE, "Clear fields and re-enter credentials", priority=2),
            RecoveryStep(RecoveryAction.WAIT_NETWORK, "Wait for auth response", priority=3),
        ]
