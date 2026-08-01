from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# ת"ז סינתטית של "דנה כהן" בקורפוס (עוברת ספרת ביקורת, אינה של אדם אמיתי)
CLIENT_ID = "039472519"
HMAC_KEY = b"test-tenant-key-do-not-use-in-prod"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    if not FIXTURES.exists() or not any(FIXTURES.glob("*.xml")):
        pytest.fail(
            "קורפוס הבדיקות חסר. הרץ: python tools/make_fixtures.py",
            pytrace=False,
        )
    return FIXTURES


@pytest.fixture
def load(fixtures_dir: Path):
    def _load(name: str) -> bytes:
        matches = sorted(fixtures_dir.glob(f"*{name}*"))
        assert matches, f"fixture matching {name!r} not found"
        return matches[0].read_bytes()

    return _load
