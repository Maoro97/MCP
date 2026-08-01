"""קטלוג חריגי פענוח.

כל חריג נושא קוד יציב (לניטור ולבדיקות) והודעה בעברית לתצוגה לסוכן.
המסך "מרכז חריגים" מציג את ההודעה בלבד — קודי שגיאה לא נחשפים למשתמש.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCKER = "blocker"


class Code(StrEnum):
    # --- קידוד ותקינות הקובץ ---
    ENCODING_MISMATCH = "ENCODING_MISMATCH"
    ILLEGAL_CHARS = "ILLEGAL_CHARS"
    TRUNCATED_XML = "TRUNCATED_XML"
    MALFORMED_XML = "MALFORMED_XML"
    UNKNOWN_STANDARD_VERSION = "UNKNOWN_STANDARD_VERSION"
    ARCHIVE_LIMIT_EXCEEDED = "ARCHIVE_LIMIT_EXCEEDED"

    # --- מבנה ותוכן ---
    MISSING_FIELD = "MISSING_FIELD"
    UNMAPPED_FIELD = "UNMAPPED_FIELD"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    BAD_FORMAT = "BAD_FORMAT"
    AMBIGUOUS_PERCENT = "AMBIGUOUS_PERCENT"
    UNKNOWN_CODE_VALUE = "UNKNOWN_CODE_VALUE"
    NO_ACCOUNTS = "NO_ACCOUNTS"
    NO_DATA_RESPONSE = "NO_DATA_RESPONSE"

    # --- זהות ואבטחה ---
    SUBJECT_MISMATCH = "SUBJECT_MISMATCH"
    INVALID_NATIONAL_ID = "INVALID_NATIONAL_ID"
    MISSING_SUBJECT = "MISSING_SUBJECT"

    # --- איחוד ---
    DUPLICATE_ACCOUNT = "DUPLICATE_ACCOUNT"
    UNKNOWN_PRODUCT_TYPE = "UNKNOWN_PRODUCT_TYPE"


class Issue(BaseModel):
    severity: Severity
    code: Code
    message_he: str
    canonical_field: str | None = None
    xpath: str | None = None
    raw_value: str | None = None
    entity_ref: str | None = Field(
        default=None,
        description="מזהה הישות שאליה קשור החריג, למשל policy:5512340",
    )
    context: dict[str, Any] = Field(default_factory=dict)

    def __str__(self) -> str:  # pragma: no cover - נוחות דיבוג בלבד
        return f"[{self.severity}] {self.code}: {self.message_he}"


class IssueCollector:
    """אוסף חריגים לאורך ה-Pipeline ומחשב את סטטוס העבודה הכולל."""

    def __init__(self) -> None:
        self._issues: list[Issue] = []

    def add(
        self,
        severity: Severity,
        code: Code,
        message_he: str,
        **kwargs: Any,
    ) -> Issue:
        issue = Issue(severity=severity, code=code, message_he=message_he, **kwargs)
        self._issues.append(issue)
        return issue

    def info(self, code: Code, message_he: str, **kw: Any) -> Issue:
        return self.add(Severity.INFO, code, message_he, **kw)

    def warning(self, code: Code, message_he: str, **kw: Any) -> Issue:
        return self.add(Severity.WARNING, code, message_he, **kw)

    def error(self, code: Code, message_he: str, **kw: Any) -> Issue:
        return self.add(Severity.ERROR, code, message_he, **kw)

    def blocker(self, code: Code, message_he: str, **kw: Any) -> Issue:
        return self.add(Severity.BLOCKER, code, message_he, **kw)

    @property
    def issues(self) -> list[Issue]:
        return list(self._issues)

    def has(self, code: Code) -> bool:
        return any(i.code == code for i in self._issues)

    def count(self, severity: Severity) -> int:
        return sum(1 for i in self._issues if i.severity == severity)

    def worst(self) -> Severity | None:
        order = [Severity.BLOCKER, Severity.ERROR, Severity.WARNING, Severity.INFO]
        for sev in order:
            if self.count(sev):
                return sev
        return None
