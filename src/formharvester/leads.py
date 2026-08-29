"""Local lead records and audit persistence.

The desktop application is intentionally local-first.  Campaign configuration
remains in the existing JSON files, while operational lead state lives in one
small SQLite database so runs can be resumed and submissions can be made
idempotent.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

__all__ = ["LeadRecord", "LeadRepository", "lead_id"]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def lead_id(campaign: str, domain: str) -> str:
    """Return a stable identifier for one campaign/domain pair."""
    value = f"{campaign.strip().casefold()}\0{domain.strip().casefold()}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


@dataclass(slots=True)
class LeadRecord:
    """The durable, user-facing state of one discovered site."""

    id: str
    campaign: str
    domain: str
    url: str
    query: str = ""
    status: str = "DISCOVERED"
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    technologies: list[dict[str, Any]] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    form_found: bool = False
    submitted: bool = False
    draft_subject: str = ""
    draft_message: str = ""
    provider: str = ""
    model: str = ""
    error: str = ""
    created_at: str = ""
    updated_at: str = ""
    last_attempt_at: str | None = None
    attempt_count: int = 0
    suppressed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LeadRepository:
    """SQLite-backed repository for local lead and audit state."""

    def __init__(self, directory: str | Path) -> None:
        path = Path(directory)
        self.path = path if path.suffix == ".sqlite3" else path / "leads.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS leads (
                    id TEXT PRIMARY KEY,
                    campaign TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    url TEXT NOT NULL,
                    query TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'DISCOVERED',
                    score REAL NOT NULL DEFAULT 0,
                    reasons TEXT NOT NULL DEFAULT '[]',
                    technologies TEXT NOT NULL DEFAULT '[]',
                    emails TEXT NOT NULL DEFAULT '[]',
                    form_found INTEGER NOT NULL DEFAULT 0,
                    submitted INTEGER NOT NULL DEFAULT 0,
                    draft_subject TEXT NOT NULL DEFAULT '',
                    draft_message TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_attempt_at TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    suppressed INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(campaign, domain)
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lead_id TEXT NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_leads_campaign_status
                    ON leads(campaign, status, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_audit_lead_event
                    ON audit_events(lead_id, event_type, created_at DESC);
                """
            )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> LeadRepository:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @staticmethod
    def _decode(value: str, fallback: Any) -> Any:
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return fallback

    @classmethod
    def _row_to_record(cls, row: sqlite3.Row) -> LeadRecord:
        return LeadRecord(
            id=row["id"],
            campaign=row["campaign"],
            domain=row["domain"],
            url=row["url"],
            query=row["query"],
            status=row["status"],
            score=float(row["score"]),
            reasons=cls._decode(row["reasons"], []),
            technologies=cls._decode(row["technologies"], []),
            emails=cls._decode(row["emails"], []),
            form_found=bool(row["form_found"]),
            submitted=bool(row["submitted"]),
            draft_subject=row["draft_subject"],
            draft_message=row["draft_message"],
            provider=row["provider"],
            model=row["model"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_attempt_at=row["last_attempt_at"],
            attempt_count=int(row["attempt_count"]),
            suppressed=bool(row["suppressed"]),
        )

    def get(self, campaign: str, domain: str) -> LeadRecord | None:
        row = self._connection.execute(
            "SELECT * FROM leads WHERE campaign = ? AND domain = ?",
            (campaign, domain),
        ).fetchone()
        return self._row_to_record(row) if row else None

    def get_by_id(self, record_id: str) -> LeadRecord | None:
        row = self._connection.execute("SELECT * FROM leads WHERE id = ?", (record_id,)).fetchone()
        return self._row_to_record(row) if row else None

    def _require(self, record_id: str) -> LeadRecord:
        record = self.get_by_id(record_id)
        if record is None:
            raise LookupError(f"Lead '{record_id}' was not found.")
        return record

    def upsert_discovered(self, campaign: str, domain: str, *, url: str | None = None, query: str = "") -> LeadRecord:
        """Create a discovered lead, preserving any later enrichment state."""
        now = _utc_now()
        record_id = lead_id(campaign, domain)
        url = url or domain
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO leads (id, campaign, domain, url, query, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(campaign, domain) DO UPDATE SET
                    url = excluded.url,
                    query = CASE WHEN excluded.query != '' THEN excluded.query ELSE leads.query END,
                    updated_at = excluded.updated_at
                """,
                (record_id, campaign, domain, url, query, now, now),
            )
            self._event(record_id, "DISCOVERED", {"query": query, "url": url}, now=now)
        return self._require(record_id)

    def update_enrichment(
        self,
        campaign: str,
        domain: str,
        *,
        status: str,
        score: float,
        reasons: Iterable[str],
        technologies: Iterable[dict[str, Any]],
        emails: Iterable[str],
        form_found: bool,
        url: str | None = None,
        draft_subject: str = "",
        draft_message: str = "",
        provider: str = "",
        model: str = "",
        error: str = "",
    ) -> LeadRecord:
        current = self.upsert_discovered(campaign, domain, url=url)
        now = _utc_now()
        with self._connection:
            self._connection.execute(
                """
                UPDATE leads
                SET status = ?, score = ?, reasons = ?, technologies = ?, emails = ?,
                    form_found = ?, draft_subject = ?, draft_message = ?, provider = ?,
                    model = ?, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    max(0.0, min(100.0, float(score))),
                    _json(list(reasons)),
                    _json(list(technologies)),
                    _json(sorted(set(emails))),
                    int(form_found),
                    draft_subject,
                    draft_message,
                    provider,
                    model,
                    error,
                    now,
                    current.id,
                ),
            )
            self._event(current.id, "ENRICHED", {"status": status, "score": score}, now=now)
        return self._require(current.id)

    def record_attempt(self, record_id: str, status: str, *, detail: dict[str, Any] | None = None) -> LeadRecord:
        now = _utc_now()
        submitted = status == "SUBMITTED"
        with self._connection:
            self._connection.execute(
                """
                UPDATE leads
                SET status = ?, submitted = ?, last_attempt_at = ?,
                    attempt_count = attempt_count + 1, updated_at = ?
                WHERE id = ?
                """,
                (status, int(submitted), now, now, record_id),
            )
            self._event(record_id, "SUBMISSION_ATTEMPT", {"status": status, **(detail or {})}, now=now)
        return self._require(record_id)

    def suppress(self, record_id: str, *, reason: str = "User suppressed lead") -> LeadRecord:
        now = _utc_now()
        with self._connection:
            self._connection.execute(
                "UPDATE leads SET suppressed = 1, status = 'SUPPRESSED', updated_at = ? WHERE id = ?",
                (now, record_id),
            )
            self._event(record_id, "SUPPRESSED", {"reason": reason}, now=now)
        return self._require(record_id)

    def unsuppress(self, record_id: str) -> LeadRecord:
        now = _utc_now()
        with self._connection:
            self._connection.execute(
                "UPDATE leads SET suppressed = 0, status = 'QUALIFIED', updated_at = ? WHERE id = ?",
                (now, record_id),
            )
            self._event(record_id, "UNSUPPRESSED", {}, now=now)
        return self._require(record_id)

    def is_eligible_for_attempt(self, record_id: str, *, cooldown_days: int) -> tuple[bool, str]:
        record = self.get_by_id(record_id)
        if record is None:
            return False, "Lead was not found."
        if record.suppressed:
            return False, "Domain is suppressed."
        if not record.last_attempt_at:
            return True, "No previous submission attempt."
        try:
            attempted = datetime.fromisoformat(record.last_attempt_at)
        except ValueError:
            return False, "Previous submission timestamp is invalid."
        if datetime.now(UTC) - attempted < timedelta(days=max(0, cooldown_days)):
            return False, f"A submission attempt exists within the {cooldown_days}-day cooldown."
        return True, "Cooldown has elapsed."

    def count_attempts_today(self, campaign: str) -> int:
        today = datetime.now(UTC).date().isoformat()
        row = self._connection.execute(
            """
            SELECT COUNT(*) FROM audit_events e
            JOIN leads l ON l.id = e.lead_id
            WHERE l.campaign = ? AND e.event_type = 'SUBMISSION_ATTEMPT'
              AND substr(e.created_at, 1, 10) = ?
            """,
            (campaign, today),
        ).fetchone()
        return int(row[0])

    def list_leads(
        self,
        *,
        campaign: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[LeadRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if campaign:
            clauses.append("campaign = ?")
            params.append(campaign)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._connection.execute(
            f"SELECT * FROM leads {where} ORDER BY score DESC, updated_at DESC LIMIT ?",
            (*params, max(1, min(limit, 1000))),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def metrics(self, campaign: str | None = None) -> dict[str, int | float]:
        clauses = "WHERE campaign = ?" if campaign else ""
        params: tuple[Any, ...] = (campaign,) if campaign else ()
        totals = self._connection.execute(
            f"SELECT COUNT(*) AS total, COALESCE(AVG(score), 0) AS average_score FROM leads {clauses}",
            params,
        ).fetchone()
        status_rows = self._connection.execute(
            f"SELECT status, COUNT(*) AS count FROM leads {clauses} GROUP BY status",
            params,
        ).fetchall()
        output: dict[str, int | float] = {
            "total": int(totals["total"]),
            "average_score": round(float(totals["average_score"]), 1),
        }
        output.update({str(row["status"]).lower(): int(row["count"]) for row in status_rows})
        return output

    def export_csv(self, destination: str | Path, *, campaign: str | None = None) -> Path:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        records = self.list_leads(campaign=campaign, limit=1000)
        fields = [
            "id", "campaign", "domain", "url", "query", "status", "score", "reasons",
            "technologies", "emails", "form_found", "submitted", "draft_subject", "draft_message",
            "provider", "model", "error", "created_at", "updated_at", "last_attempt_at",
            "attempt_count", "suppressed",
        ]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for record in records:
                values = record.to_dict()
                for key in ("reasons", "technologies", "emails"):
                    values[key] = _json(values[key])
                writer.writerow({key: values[key] for key in fields})
        return path

    def audit(self, record_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT event_type, detail, created_at FROM audit_events WHERE lead_id = ? ORDER BY id DESC LIMIT ?",
            (record_id, max(1, min(limit, 1000))),
        ).fetchall()
        return [
            {
                "event_type": row["event_type"],
                "detail": self._decode(row["detail"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def _event(self, record_id: str, event_type: str, detail: dict[str, Any], *, now: str) -> None:
        self._connection.execute(
            "INSERT INTO audit_events (lead_id, event_type, detail, created_at) VALUES (?, ?, ?, ?)",
            (record_id, event_type, _json(detail), now),
        )
