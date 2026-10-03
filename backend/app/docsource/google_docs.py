"""Google Docs document source (read-only).

Talks to the Docs REST API directly with httpx and mints an access token from a
service-account key, which avoids pulling in the full google-api-python-client
stack for a single GET.

Setup:
  1. Create a service account, download the JSON key.
  2. Share both Docs with the service account's email as Viewer.
  3. Set GOOGLE_SERVICE_ACCOUNT_JSON to the raw JSON or a path to the file,
     PROMPT_DOC_ID / GROUNDING_DOC_ID to the Doc IDs, DOC_PROVIDER=google_docs.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from app.docsource.base import DocumentFetchError

_SCOPE = "https://www.googleapis.com/auth/documents.readonly"
_API = "https://docs.googleapis.com/v1/documents"

_HEADING_LEVELS = {
    "HEADING_1": "#",
    "HEADING_2": "##",
    "HEADING_3": "###",
    "HEADING_4": "####",
    "HEADING_5": "#####",
    "HEADING_6": "######",
    "TITLE": "#",
    "SUBTITLE": "##",
}


class GoogleDocsSource:
    name = "google_docs"

    def __init__(self, service_account_json: str, timeout: float = 20.0) -> None:
        if not service_account_json:
            raise DocumentFetchError("GOOGLE_SERVICE_ACCOUNT_JSON is not set")
        self._raw_key = service_account_json
        self._timeout = timeout
        self._credentials: Any | None = None
        self._lock = asyncio.Lock()

    async def fetch(self, ref: str) -> str:
        token = await self._access_token()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                response = await client.get(
                    f"{_API}/{ref}",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"suggestionsViewMode": "PREVIEW_WITHOUT_SUGGESTIONS"},
                )
            except httpx.HTTPError as exc:
                raise DocumentFetchError(f"Docs API transport error: {exc}") from exc

        if response.status_code == 404:
            raise DocumentFetchError(
                f"Doc {ref} not found — check the ID and that it is shared with the service account"
            )
        if response.status_code == 403:
            raise DocumentFetchError(f"Doc {ref} is not shared with the service account")
        if response.status_code >= 400:
            raise DocumentFetchError(f"Docs API returned {response.status_code}: {response.text[:200]}")

        text = flatten_document(response.json())
        if not text.strip():
            raise DocumentFetchError(f"Doc {ref} is empty")
        return text.strip()

    async def _access_token(self) -> str:
        # google-auth is an optional dependency; only required on this path.
        from google.auth.transport.requests import Request  # noqa: PLC0415
        from google.oauth2 import service_account  # noqa: PLC0415

        async with self._lock:
            if self._credentials is None:
                self._credentials = service_account.Credentials.from_service_account_info(
                    self._load_key(), scopes=[_SCOPE]
                )
            creds = self._credentials
            if not creds.valid:
                await asyncio.to_thread(creds.refresh, Request())
            return creds.token

    def _load_key(self) -> dict[str, Any]:
        raw = self._raw_key.strip()
        if raw.startswith("{"):
            return json.loads(raw)
        path = Path(raw)
        if not path.is_file():
            raise DocumentFetchError(f"service account key not found at {path}")
        return json.loads(path.read_text(encoding="utf-8"))


def flatten_document(doc: dict[str, Any]) -> str:
    """Render a Docs API document to markdown-ish text.

    Headings are preserved as `#` prefixes because the grounding chunker splits
    on them — losing heading structure would collapse the reference doc into one
    undifferentiated blob and make retrieval useless.
    """
    lines: list[str] = []
    for element in doc.get("body", {}).get("content", []):
        paragraph = element.get("paragraph")
        if paragraph:
            lines.append(_render_paragraph(paragraph))
            continue
        table = element.get("table")
        if table:
            lines.extend(_render_table(table))
    # collapse runs of blank lines
    out: list[str] = []
    for line in lines:
        if not line.strip() and out and not out[-1].strip():
            continue
        out.append(line.rstrip())
    return "\n".join(out)


def _paragraph_text(paragraph: dict[str, Any]) -> str:
    parts = [
        el["textRun"].get("content", "")
        for el in paragraph.get("elements", [])
        if "textRun" in el
    ]
    return "".join(parts).replace("\x0b", "\n").strip()


def _render_paragraph(paragraph: dict[str, Any]) -> str:
    text = _paragraph_text(paragraph)
    if not text:
        return ""
    style = paragraph.get("paragraphStyle", {}).get("namedStyleType", "NORMAL_TEXT")
    prefix = _HEADING_LEVELS.get(style)
    if prefix:
        return f"\n{prefix} {text}"
    if "bullet" in paragraph:
        return f"- {text}"
    return text


def _render_table(table: dict[str, Any]) -> list[str]:
    rows: list[str] = []
    for row in table.get("tableRows", []):
        cells: list[str] = []
        for cell in row.get("tableCells", []):
            cell_text = " ".join(
                _paragraph_text(c["paragraph"])
                for c in cell.get("content", [])
                if "paragraph" in c
            )
            cells.append(cell_text.strip())
        if any(cells):
            rows.append(" | ".join(cells))
    return rows
