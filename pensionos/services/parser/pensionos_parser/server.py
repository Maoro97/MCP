"""שירות HTTP פנימי של מנוע הפענוח.

מממש את החוזה שב-`docs/insurance-agent-saas/04-tech-stack.md §4`.

⚠️ שירות פנימי בלבד. בייצור הוא יושב ב-subnet פרטי, מאזין רק ל-VPC,
   ומאמת mTLS. הוא לעולם לא נחשף ל-Internet — הוא מעבד קלט לא-מהימן.

הרצה מקומית:
    uvicorn pensionos_parser.server:app --port 8081
"""

from __future__ import annotations

import base64
import os
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .models import PARSER_VERSION, ParseResult
from .pipeline import parse_bytes

# מגבלת גודל הבקשה — הגנה ראשונה לפני שנוגעים בתוכן
MAX_UPLOAD_BYTES = int(os.getenv("PARSER_MAX_UPLOAD_BYTES", 200 * 1024 * 1024))

# סוד משותף בין ה-API למנוע. בייצור: mTLS + IAM, לא header.
INTERNAL_TOKEN = os.getenv("PARSER_INTERNAL_TOKEN", "")

app = FastAPI(
    title="PensionOS Parser",
    version=PARSER_VERSION,
    description="מנוע פענוח קבצי המסלקה הפנסיונית — שירות פנימי",
    docs_url="/internal/docs",
)


def require_internal_auth(
    x_internal_token: Annotated[str | None, Header()] = None,
) -> None:
    if not INTERNAL_TOKEN:
        return  # פיתוח מקומי ללא סוד מוגדר
    if x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")


class ParseOptions(BaseModel):
    file_id: str | None = None
    expected_national_id_hash: str | None = Field(
        default=None,
        description="HMAC-SHA256 hex של ת\"ז הלקוח שעבורו נשלחה הבקשה. "
        "אי-התאמה מעבירה את הקובץ להסגר כאירוע אבטחה.",
    )
    hmac_key_b64: str | None = Field(
        default=None, description="מפתח ה-HMAC של ה-tenant, בבסיס 64"
    )


class HealthResponse(BaseModel):
    status: str
    parser_version: str


@app.get("/internal/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", parser_version=PARSER_VERSION)


@app.post(
    "/internal/parse",
    response_model=ParseResult,
    response_model_exclude_none=False,
    dependencies=[Depends(require_internal_auth)],
)
async def parse(
    file: UploadFile,
    file_id: str | None = None,
    expected_national_id_hash: str | None = None,
    hmac_key_b64: str | None = None,
) -> ParseResult:
    """מפענח קובץ מסלקה בודד.

    לעולם מחזיר 200 עם תוצאה: כשל פענוח הוא `status` בגוף התשובה ולא
    שגיאת HTTP. קוד 4xx שמור לבעיות בבקשה עצמה, כדי שקריאה כושלת לא
    תסתיר תוצאה תקפה-חלקית.
    """
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file exceeds size limit")
    if not raw:
        raise HTTPException(status_code=400, detail="empty file")

    hmac_key = base64.b64decode(hmac_key_b64) if hmac_key_b64 else None
    if expected_national_id_hash and not hmac_key:
        raise HTTPException(
            status_code=400,
            detail="expected_national_id_hash requires hmac_key_b64",
        )

    return parse_bytes(
        raw,
        file_id=file_id or file.filename,
        expected_national_id_hash=expected_national_id_hash,
        hmac_key=hmac_key,
    )
