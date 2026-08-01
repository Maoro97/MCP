"""Mapping Registry — מיפוי מונחה-דאטה.

היצרנים סוטים מהתקן, וכל סטייה שנפתרת בקוד הופכת לחוב נצחי. לכן המיפוי
הוא נתונים: כאן הוא נטען מ-YAML, ובייצור מטבלת `clearing.field_mappings`
עם גרסאות ותאריכי תחולה. שינוי מיפוי אינו מצריך Deploy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

OnMissing = Literal["null", "flag_for_review", "reject"]

DEFAULT_MAPPING_DIR = Path(__file__).resolve().parent.parent / "mappings"


@dataclass(frozen=True)
class FieldSpec:
    canonical: str
    xpath: str
    type: str = "string"
    fallback_xpaths: tuple[str, ...] = ()
    args: dict[str, Any] = field(default_factory=dict)
    code_table: str | None = None
    default: Any = None
    minimum: float | None = None
    maximum: float | None = None
    on_missing: OnMissing = "null"
    required_for: tuple[str, ...] = ()
    label_he: str = ""

    @property
    def all_xpaths(self) -> tuple[str, ...]:
        return (self.xpath, *self.fallback_xpaths)

    @property
    def is_required(self) -> bool:
        """שדה שנדרש לחישוב בהנמקה — חוסר בו יחסום הפקת מסמך."""
        return bool(self.required_for) or self.on_missing == "reject"


@dataclass(frozen=True)
class SectionSpec:
    root: str | None
    iterate: str | None
    tag: str | None
    fields: tuple[FieldSpec, ...]
    children: dict[str, SectionSpec] = field(default_factory=dict)


def _field_from_dict(d: dict[str, Any]) -> FieldSpec:
    rng = d.get("range") or {}
    return FieldSpec(
        canonical=d["canonical"],
        xpath=d["xpath"],
        type=d.get("type", "string"),
        fallback_xpaths=tuple(d.get("fallback_xpaths") or ()),
        args=dict(d.get("args") or {}),
        code_table=d.get("code_table"),
        default=d.get("default"),
        minimum=rng.get("min"),
        maximum=rng.get("max"),
        on_missing=d.get("on_missing", "null"),
        required_for=tuple(d.get("required_for") or ()),
        label_he=d.get("label_he", ""),
    )


def _section_from_dict(d: dict[str, Any]) -> SectionSpec:
    return SectionSpec(
        root=d.get("root"),
        iterate=d.get("iterate"),
        tag=d.get("tag"),
        fields=tuple(_field_from_dict(f) for f in d.get("fields", [])),
        children={
            name: _section_from_dict(sub) for name, sub in (d.get("children") or {}).items()
        },
    )


class MappingRegistry:
    """מיפוי לגרסת תקן אחת, עם דריסות ברמת יצרן."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.version: str = data["version"]
        self.standard_version: str = str(data["standard_version"])
        self.codes: dict[str, dict[str, str]] = {
            name: {str(k): v for k, v in table.items()}
            for name, table in (data.get("codes") or {}).items()
        }
        self._sections = {
            name: _section_from_dict(spec) for name, spec in data["sections"].items()
        }
        self._provider_overrides: dict[str, dict[str, dict[str, FieldSpec]]] = {}
        for provider_code, sections in (data.get("providers") or {}).items():
            per_section: dict[str, dict[str, FieldSpec]] = {}
            for section_name, spec in sections.items():
                per_section[section_name] = {
                    f["canonical"]: _field_from_dict(f) for f in spec.get("fields", [])
                }
            self._provider_overrides[str(provider_code)] = per_section

    # -- טעינה ---------------------------------------------------------

    @classmethod
    def load(
        cls, standard_version: str = "2.9", mapping_dir: Path | None = None
    ) -> MappingRegistry:
        directory = mapping_dir or DEFAULT_MAPPING_DIR
        path = directory / f"standard-{standard_version}.yaml"
        if not path.exists():
            raise UnknownStandardVersionError(standard_version)
        with path.open(encoding="utf-8") as fh:
            return cls(yaml.safe_load(fh))

    @classmethod
    def available_versions(cls, mapping_dir: Path | None = None) -> list[str]:
        directory = mapping_dir or DEFAULT_MAPPING_DIR
        return sorted(
            p.stem.removeprefix("standard-") for p in directory.glob("standard-*.yaml")
        )

    # -- שאילתות -------------------------------------------------------

    def section(self, name: str, provider_code: str | None = None) -> SectionSpec:
        """הסקציה כפי שהיא חלה על יצרן מסוים, אחרי החלת דריסות."""
        base = self._sections[name]
        overrides = self._provider_overrides.get(str(provider_code or ""), {}).get(name)
        if not overrides:
            return base
        merged = tuple(overrides.get(f.canonical, f) for f in base.fields)
        # שדות שקיימים רק אצל יצרן זה
        extra = tuple(
            spec
            for canonical, spec in overrides.items()
            if canonical not in {f.canonical for f in base.fields}
        )
        return SectionSpec(
            root=base.root,
            iterate=base.iterate,
            tag=base.tag,
            fields=merged + extra,
            children=base.children,
        )

    def code_table(self, name: str | None) -> dict[str, str]:
        return self.codes.get(name or "", {})

    @property
    def stream_tags(self) -> tuple[str, ...]:
        """התגים שעליהם ה-Parser עושה streaming, לפי סדר הופעתם בקובץ."""
        tags = [s.tag for s in self._sections.values() if s.tag]
        return tuple(dict.fromkeys(tags))

    def required_fields(self, section: str = "product") -> tuple[FieldSpec, ...]:
        return tuple(f for f in self._sections[section].fields if f.is_required)


class UnknownStandardVersionError(ValueError):
    """גרסת מבנה אחיד שאין לה מיפוי.

    זה מצב Quarantine מכוון: ניחוש מיפוי על גרסה לא מוכרת מסוכן יותר
    מאשר להשבית את הקובץ ולהתריע לצוות.
    """

    def __init__(self, version: str) -> None:
        super().__init__(f"no mapping registry for standard version {version!r}")
        self.version = version


def detect_standard_version(text: str, default: str = "2.9") -> str | None:
    """חילוץ גרסת המבנה האחיד מכותרת הקובץ."""
    import re

    for pattern in (
        r"<GIRSAT-MIVNE-ACHID>([^<]+)</GIRSAT-MIVNE-ACHID>",
        r"<MISPAR-GIRSA>([^<]+)</MISPAR-GIRSA>",
    ):
        if m := re.search(pattern, text[:4000]):
            return m.group(1).strip()
    return default
