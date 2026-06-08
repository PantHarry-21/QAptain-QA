"""
File Upload Capability Engine — File upload workflow testing.

Covers: valid file upload, type validation, size limits, upload verification,
re-upload, and filename security checks.
"""
from __future__ import annotations
from app.capabilities.base_engine import BaseCapabilityEngine
from app.capabilities.contracts import CapabilityContext, RecoveryStep, RecoveryAction


class FileUploadEngine(BaseCapabilityEngine):
    engine_id = "file_upload"
    workflow_types = ["FILE_UPLOAD"]

    def generate_positive_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        entity = ctx.entity_name or "File"

        return [
            self._step("screenshot", "Capture upload form initial state",
                      "UPLOAD_SETUP", "Baseline before file upload", engine_id=e),
            self._step("assert_visible", "Verify upload control is present",
                      "UPLOAD_SETUP", "Upload button or drop zone must be visible",
                      target="upload|choose file|browse|select file|drop|attach|import",
                      engine_id=e),

            # Upload a valid file
            self._step("upload", "Select a valid file for upload",
                      "UPLOAD_VALID", "Upload a properly formatted file",
                      target="file input|upload|choose|browse|attach",
                      value="test_file.csv", engine_id=e),
            self._step("screenshot", "Capture file selected state",
                      "UPLOAD_VALID", "Evidence of file selection", engine_id=e, on_fail="skip"),
            self._step("click", "Click Upload / Submit to start upload",
                      "UPLOAD_SUBMIT", "Initiate file upload process",
                      target="Upload|Submit|Import|Attach|Send|OK|Confirm",
                      engine_id=e, on_fail="skip"),
            self._wait_network("Wait for upload to complete", "UPLOAD_SUBMIT"),
            self._step("assert_visible", "Verify upload success message appears",
                      "UPLOAD_VERIFY",
                      "System must confirm successful file upload with a success message",
                      target="success|uploaded|complete|imported|accepted|file received",
                      timeout_ms=15000, checkpoint=True, on_fail="skip", engine_id=e),
            self._step("screenshot", "Capture post-upload success state",
                      "UPLOAD_VERIFY", "Upload success evidence", engine_id=e),
            self._step("assert_visible", f"Verify uploaded {entity} appears in the list",
                      "UPLOAD_VERIFY",
                      "Uploaded file or record must be visible in the listing",
                      target=f"test_file|uploaded|{entity}",
                      on_fail="skip", checkpoint=True, engine_id=e),
        ]

    def generate_negative_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id

        return [
            # Submit without selecting a file
            self._step("click", "Click Upload without selecting a file",
                      "UPLOAD_NO_FILE", "System must require a file before upload",
                      target="Upload|Submit|Import|Attach",
                      engine_id=e, test_category="negative", on_fail="skip"),
            self._step("assert_visible", "Verify file-required error appears",
                      "UPLOAD_NO_FILE", "User must be told to select a file first",
                      target="please select|no file|required|choose a file|select a file",
                      on_fail="skip", checkpoint=True, engine_id=e, test_category="negative"),
            self._step("screenshot", "Capture no-file error state",
                      "UPLOAD_NO_FILE", "No-file validation evidence",
                      on_fail="skip", engine_id=e, test_category="negative"),

            # Upload wrong file type
            self._step("upload", "Attempt to upload an invalid file type",
                      "UPLOAD_WRONG_TYPE", "System must validate accepted file formats",
                      target="file input|upload|choose|browse",
                      value="invalid_type.exe", engine_id=e, test_category="negative", on_fail="skip"),
            self._step("click", "Submit invalid file type",
                      "UPLOAD_WRONG_TYPE", "Trigger file type validation",
                      target="Upload|Submit|Import",
                      engine_id=e, test_category="negative", on_fail="skip"),
            self._step("assert_visible", "Verify file type error appears",
                      "UPLOAD_WRONG_TYPE",
                      "System must reject unsupported file types with a clear message",
                      target="invalid|unsupported|format|type|not allowed|only|accepted",
                      on_fail="skip", checkpoint=True, engine_id=e, test_category="negative"),
            self._step("screenshot", "Capture wrong file type error",
                      "UPLOAD_WRONG_TYPE", "File type validation evidence",
                      on_fail="skip", engine_id=e, test_category="negative"),
        ]

    def generate_edge_case_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        return [
            # Upload same file twice
            self._step("upload", "Upload the same file a second time",
                      "UPLOAD_DUPLICATE", "System must handle duplicate upload gracefully",
                      target="file input|upload|choose|browse",
                      value="test_file.csv", engine_id=e, test_category="edge_case", on_fail="skip"),
            self._step("click", "Submit duplicate file",
                      "UPLOAD_DUPLICATE", "Test duplicate upload handling",
                      target="Upload|Submit|Import",
                      engine_id=e, test_category="edge_case", on_fail="skip"),
            self._step("screenshot", "Capture duplicate upload result",
                      "UPLOAD_DUPLICATE", "Duplicate upload edge case evidence",
                      on_fail="skip", engine_id=e, test_category="edge_case"),
        ]

    def generate_security_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        return [
            # Upload file with XSS payload in filename (OS permitting)
            self._step("upload", "Attempt upload of file with XSS in name",
                      "UPLOAD_SECURITY", "Filename must be sanitized to prevent XSS",
                      target="file input|upload|choose|browse",
                      value="<script>alert(1)</script>.pdf",
                      engine_id=e, test_category="security", on_fail="skip"),
            self._step("screenshot", "Capture XSS filename handling",
                      "UPLOAD_SECURITY", "Filename security evidence",
                      on_fail="skip", engine_id=e, test_category="security"),
        ]

    def get_recovery_steps(self, failed_action: str, error_context: dict) -> list[RecoveryStep]:
        return [
            RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll file input into view", priority=1),
            RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait for upload dialog to render", priority=2),
            RecoveryStep(RecoveryAction.WAIT_NETWORK, "Wait for upload operation to complete", priority=3),
        ]
