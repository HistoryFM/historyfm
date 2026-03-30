"""Pipeline enforcement errors."""

from __future__ import annotations


class ContractEnforcementError(RuntimeError):
    """Raised when strict chapter/scene contract enforcement fails."""

    def __init__(
        self,
        message: str,
        *,
        chapter_number: int | None = None,
        stage_name: str | None = None,
        error_code: str = "contract_enforcement_failed",
    ) -> None:
        super().__init__(message)
        self.chapter_number = chapter_number
        self.stage_name = stage_name
        self.error_code = error_code

