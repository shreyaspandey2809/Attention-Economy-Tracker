"""All SQL for the M8 tables lives here; callers never write SQL themselves.

Every method takes/uses the `Database` it was built with and wraps writes in
`Database.transaction()`. Timestamps are stored as fixed-format UTC text so
they sort lexicographically.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable

from attention_tracker.pipeline.features.feature_vector import FeatureVector
from attention_tracker.schema.app_metadata import AppCategory
from attention_tracker.schema.app_metadata_entry import AppMetadataEntry
from attention_tracker.schema.raw_event import EventType, RawEvent
from attention_tracker.schema.session import Session
from attention_tracker.storage.db import Database

_TS_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"

FEATURE_COLUMNS: tuple[str, ...] = (
    "total_time_sec",
    "session_count",
    "avg_session_duration_sec",
    "max_session_duration_sec",
    "sessions_under_30s_ratio",
    "interarrival_mean_sec",
    "interarrival_under_2min_ratio",
    "late_night_usage_pct",
    "late_night_usage_time_ratio",
    "hourly_usage_entropy",
    "weekend_usage_ratio",
    "productive_interruption_rate",
)


def to_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(_TS_FMT)


def from_ts(text: str) -> datetime:
    return datetime.strptime(text, _TS_FMT).replace(tzinfo=timezone.utc)


def now_ts() -> str:
    return to_ts(datetime.now(timezone.utc))


@dataclass(frozen=True)
class WindowRow:
    """One (user, app, day) window: its features, category and scores."""

    day: date
    features: FeatureVector
    category: AppCategory
    heuristic_score: float
    distraction_score: float
    addiction_model_score: float | None = None
    distraction_model_score: float | None = None
    addiction_model_version: str | None = None
    distraction_model_version: str | None = None


@dataclass(frozen=True)
class DailyRow:
    day: date
    total_time_sec: float
    heuristic_score: float
    distraction_score: float
    addiction_model_score: float | None
    distraction_model_score: float | None
    is_complete: bool
    max_gap_hours: float
    completeness_reason: str


class Repository:
    def __init__(self, db: Database):
        self.db = db

    # ---- users -----------------------------------------------------------

    def create_user(self, user_id: str) -> bool:
        """Create the user if absent. Returns True when newly created."""
        with self.db.transaction() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO users(user_id, created_at) VALUES (?, ?)",
                (user_id, now_ts()),
            )
            return cur.rowcount == 1

    def get_user(self, user_id: str) -> dict | None:
        with self.db.lock:
            row = self.db.conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def list_user_ids(self) -> list[str]:
        with self.db.lock:
            rows = self.db.conn.execute("SELECT user_id FROM users ORDER BY user_id").fetchall()
        return [r["user_id"] for r in rows]

    def stale_user_ids(self) -> list[str]:
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT user_id FROM users WHERE scores_stale = 1 ORDER BY user_id"
            ).fetchall()
        return [r["user_id"] for r in rows]

    def set_consent(self, user_id: str) -> str | None:
        """Record consent (first time wins). Returns the consent timestamp, None if no such user."""
        with self.db.transaction() as c:
            c.execute(
                "UPDATE users SET consent_at = COALESCE(consent_at, ?) WHERE user_id = ?",
                (now_ts(), user_id),
            )
            row = c.execute("SELECT consent_at FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return row["consent_at"] if row else None

    def delete_user(self, user_id: str) -> bool:
        """Hard delete: the user and every row that references them (FK cascade)."""
        with self.db.transaction() as c:
            cur = c.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            return cur.rowcount == 1

    # ---- devices ---------------------------------------------------------

    def create_device(self, device_id: str, user_id: str, token_hash: str) -> None:
        with self.db.transaction() as c:
            c.execute(
                "INSERT INTO devices(device_id, user_id, token_hash, created_at) VALUES (?, ?, ?, ?)",
                (device_id, user_id, token_hash, now_ts()),
            )

    def device_for_token_hash(self, token_hash: str) -> dict | None:
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT device_id, user_id FROM devices WHERE token_hash = ? AND revoked_at IS NULL",
                (token_hash,),
            ).fetchone()
        return dict(row) if row else None

    def revoke_device(self, device_id: str) -> bool:
        with self.db.transaction() as c:
            cur = c.execute(
                "UPDATE devices SET revoked_at = ? WHERE device_id = ? AND revoked_at IS NULL",
                (now_ts(), device_id),
            )
            return cur.rowcount == 1

    # ---- app metadata ----------------------------------------------------

    def seed_app_metadata(self, entries: Iterable[AppMetadataEntry]) -> None:
        """Insert taxonomy rows that are not present yet; never overwrites (so user overrides survive)."""
        with self.db.transaction() as c:
            c.executemany(
                "INSERT OR IGNORE INTO app_metadata(package_name, display_name, category, is_user_override) "
                "VALUES (?, ?, ?, ?)",
                [(e.package_name, e.display_name, e.category.value, int(e.is_user_override)) for e in entries],
            )

    def category_override(self, package_name: str) -> AppCategory | None:
        """Category stored for a package only when it is a user override."""
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT category FROM app_metadata WHERE package_name = ? AND is_user_override = 1",
                (package_name,),
            ).fetchone()
        return AppCategory(row["category"]) if row else None

    def count_app_metadata(self) -> int:
        with self.db.lock:
            return self.db.conn.execute("SELECT COUNT(*) AS n FROM app_metadata").fetchone()["n"]

    # ---- raw events ------------------------------------------------------

    def insert_events(self, user_id: str, events: list[RawEvent]) -> tuple[int, int]:
        """Idempotently store events. Returns (accepted, duplicates)."""
        if not events:
            return 0, 0
        with self.db.transaction() as c:
            before = c.total_changes
            c.executemany(
                "INSERT OR IGNORE INTO raw_events(user_id, package_name, event_type, timestamp, "
                "tz_offset_minutes, session_duration_sec, session_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        user_id,
                        e.package_name,
                        e.event_type.value,
                        to_ts(e.timestamp),
                        e.tz_offset_minutes,
                        e.session_duration_sec,
                        e.session_id,
                    )
                    for e in events
                ],
            )
            accepted = c.total_changes - before
            if accepted:
                c.execute("UPDATE users SET scores_stale = 1 WHERE user_id = ?", (user_id,))
        return accepted, len(events) - accepted

    def load_events(self, user_id: str) -> list[RawEvent]:
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT * FROM raw_events WHERE user_id = ? ORDER BY timestamp, id", (user_id,)
            ).fetchall()
        return [
            RawEvent(
                user_id=r["user_id"],
                package_name=r["package_name"],
                event_type=EventType(r["event_type"]),
                timestamp=from_ts(r["timestamp"]),
                tz_offset_minutes=r["tz_offset_minutes"],
                session_duration_sec=r["session_duration_sec"],
                session_id=r["session_id"],
            )
            for r in rows
        ]

    # ---- derived tables --------------------------------------------------

    def replace_derived(
        self,
        user_id: str,
        sessions: list[Session],
        windows: list[WindowRow],
        daily: list[DailyRow],
    ) -> None:
        """Rebuild sessions / feature_vectors / scores / daily_scores for one user, atomically."""
        scored_at = now_ts()
        with self.db.transaction() as c:
            c.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            c.execute("DELETE FROM feature_vectors WHERE user_id = ?", (user_id,))  # cascades to scores
            c.execute("DELETE FROM daily_scores WHERE user_id = ?", (user_id,))

            c.executemany(
                "INSERT OR REPLACE INTO sessions(user_id, session_id, package_name, start_time, end_time, "
                "duration_sec, tz_offset_minutes, transition_from, transition_to) VALUES (?,?,?,?,?,?,?,?,?)",
                [
                    (
                        s.user_id,
                        s.session_id,
                        s.package_name,
                        to_ts(s.start_time),
                        to_ts(s.end_time),
                        s.duration_sec,
                        s.tz_offset_minutes,
                        s.transition_from,
                        s.transition_to,
                    )
                    for s in sessions
                ],
            )

            fv_cols = ", ".join(FEATURE_COLUMNS)
            placeholders = ", ".join("?" for _ in FEATURE_COLUMNS)
            for w in windows:
                fv = w.features
                c.execute(
                    f"INSERT INTO feature_vectors(user_id, package_name, day, category, {fv_cols}) "
                    f"VALUES (?, ?, ?, ?, {placeholders})",
                    (user_id, fv.package_name, w.day.isoformat(), w.category.value)
                    + tuple(getattr(fv, col) for col in FEATURE_COLUMNS),
                )
                c.execute(
                    "INSERT INTO scores(user_id, package_name, day, heuristic_score, distraction_score, "
                    "addiction_model_score, distraction_model_score, addiction_model_version, "
                    "distraction_model_version, scored_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        user_id,
                        fv.package_name,
                        w.day.isoformat(),
                        w.heuristic_score,
                        w.distraction_score,
                        w.addiction_model_score,
                        w.distraction_model_score,
                        w.addiction_model_version,
                        w.distraction_model_version,
                        scored_at,
                    ),
                )

            c.executemany(
                "INSERT INTO daily_scores(user_id, day, total_time_sec, heuristic_score, distraction_score, "
                "addiction_model_score, distraction_model_score, is_complete, max_gap_hours, "
                "completeness_reason) VALUES (?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        user_id,
                        d.day.isoformat(),
                        d.total_time_sec,
                        d.heuristic_score,
                        d.distraction_score,
                        d.addiction_model_score,
                        d.distraction_model_score,
                        int(d.is_complete),
                        d.max_gap_hours,
                        d.completeness_reason,
                    )
                    for d in daily
                ],
            )
            c.execute(
                "UPDATE users SET scores_stale = 0, last_scored_at = ? WHERE user_id = ?",
                (scored_at, user_id),
            )

    def list_window_scores(
        self, user_id: str, start: date | None = None, end: date | None = None
    ) -> list[dict]:
        sql = (
            "SELECT s.*, f.category, f.total_time_sec, f.session_count FROM scores s "
            "JOIN feature_vectors f USING (user_id, package_name, day) WHERE s.user_id = ?"
        )
        args: list = [user_id]
        if start is not None:
            sql += " AND s.day >= ?"
            args.append(start.isoformat())
        if end is not None:
            sql += " AND s.day <= ?"
            args.append(end.isoformat())
        sql += " ORDER BY s.day, s.heuristic_score DESC, s.package_name"
        with self.db.lock:
            rows = self.db.conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def list_daily_scores(
        self, user_id: str, start: date | None = None, end: date | None = None
    ) -> list[dict]:
        sql = "SELECT * FROM daily_scores WHERE user_id = ?"
        args: list = [user_id]
        if start is not None:
            sql += " AND day >= ?"
            args.append(start.isoformat())
        if end is not None:
            sql += " AND day <= ?"
            args.append(end.isoformat())
        sql += " ORDER BY day"
        with self.db.lock:
            rows = self.db.conn.execute(sql, args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["is_complete"] = bool(d["is_complete"])
            out.append(d)
        return out

    # ---- SAS-SV labels ---------------------------------------------------

    def upsert_sas_sv_total(self, user_id: str, total: int) -> str:
        collected_at = now_ts()
        with self.db.transaction() as c:
            c.execute(
                "INSERT INTO sas_sv_labels(user_id, sas_sv_total, collected_at) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET sas_sv_total = excluded.sas_sv_total, "
                "collected_at = excluded.collected_at",
                (user_id, total, collected_at),
            )
        return collected_at

    def get_sas_sv(self, user_id: str) -> dict | None:
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT sas_sv_total, collected_at FROM sas_sv_labels WHERE user_id = ?", (user_id,)
            ).fetchone()
        return dict(row) if row else None

    # ---- export ----------------------------------------------------------

    def export_user(self, user_id: str) -> dict | None:
        """Every row held about one user (device token hashes excluded)."""
        user = self.get_user(user_id)
        if user is None:
            return None

        def rows(sql: str) -> list[dict]:
            with self.db.lock:
                return [dict(r) for r in self.db.conn.execute(sql, (user_id,)).fetchall()]

        return {
            "user": user,
            "devices": rows("SELECT device_id, created_at, revoked_at FROM devices WHERE user_id = ?"),
            "raw_events": rows(
                "SELECT package_name, event_type, timestamp, tz_offset_minutes, session_duration_sec, "
                "session_id FROM raw_events WHERE user_id = ? ORDER BY timestamp, id"
            ),
            "sessions": rows("SELECT * FROM sessions WHERE user_id = ? ORDER BY start_time"),
            "feature_vectors": rows("SELECT * FROM feature_vectors WHERE user_id = ? ORDER BY day, package_name"),
            "scores": rows("SELECT * FROM scores WHERE user_id = ? ORDER BY day, package_name"),
            "daily_scores": rows("SELECT * FROM daily_scores WHERE user_id = ? ORDER BY day"),
            "sas_sv_label": self.get_sas_sv(user_id),
        }
