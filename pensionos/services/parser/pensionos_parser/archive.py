"""פתיחת מכולות ZIP מהמסלקה, עם הגנה מפני ZIP-bomb ו-path traversal.

תשובת המסלקה מגיעה כ-ZIP שמכיל קובץ XML לכל יצרן. הארכיון מגיע מגורם
חיצוני ולכן מטופל כקלט עוין: מגבלות על יחס דחיסה, גודל מפוענח ומספר קבצים.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass

MAX_FILES = 200
MAX_TOTAL_UNCOMPRESSED = 500 * 1024 * 1024  # 500MB
MAX_COMPRESSION_RATIO = 100  # יחס גבוה מזה הוא ZIP-bomb, לא קובץ לגיטימי


class ArchiveLimitError(ValueError):
    pass


@dataclass
class ArchiveMember:
    name: str
    data: bytes


def _is_safe_name(name: str) -> bool:
    return not (
        name.startswith(("/", "\\"))
        or ".." in name.replace("\\", "/").split("/")
        or name.endswith("/")
    )


def iter_zip_members(
    blob: bytes,
    *,
    max_files: int = MAX_FILES,
    max_total: int = MAX_TOTAL_UNCOMPRESSED,
    max_ratio: int = MAX_COMPRESSION_RATIO,
) -> Iterator[ArchiveMember]:
    """מחזיר את קבצי ה-XML שבארכיון, אחד-אחד, בתוך המגבלות."""
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        infos = [i for i in zf.infolist() if _is_safe_name(i.filename)]
        if len(infos) > max_files:
            raise ArchiveLimitError(f"{len(infos)} files > limit {max_files}")

        declared_total = sum(i.file_size for i in infos)
        if declared_total > max_total:
            raise ArchiveLimitError(f"{declared_total} bytes > limit {max_total}")

        compressed_total = sum(i.compress_size for i in infos) or 1
        if declared_total / compressed_total > max_ratio:
            raise ArchiveLimitError(
                f"compression ratio {declared_total / compressed_total:.0f}:1 "
                f"> limit {max_ratio}:1"
            )

        extracted = 0
        for info in infos:
            with zf.open(info) as fh:
                # קוראים עם תקרה קשיחה — file_size המוצהר אינו מהימן
                data = fh.read(max_total - extracted + 1)
            extracted += len(data)
            if extracted > max_total:
                raise ArchiveLimitError(f"extracted bytes exceeded limit {max_total}")
            yield ArchiveMember(name=info.filename, data=data)
