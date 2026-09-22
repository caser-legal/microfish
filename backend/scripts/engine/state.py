"""
World state.

A generic, domain-neutral store for everything a simulation needs to be true
about its world. Replaces the old hardcoded social-media schema (post/like/
follow/comment/vote) with four general tables:

  world_entity    - things that exist (an instrument, a post, a proposal, a city)
  world_resource  - who holds how much of what (cash, position, reputation, doses)
  world_link      - typed relationships (follows, holds, allied_with)
  world_event     - the audit log of every action attempted, successful or not

The critical property is that resources have *constraints*. An action that
spends more cash than an agent holds is rejected, the transaction is rolled
back, and the failure reason is recorded. This is what allows outcomes to be
computed rather than asserted.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any, Dict, Iterable, List, Optional, Tuple


SCHEMA = """
CREATE TABLE IF NOT EXISTS world_entity (
    key         TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    attrs       TEXT NOT NULL DEFAULT '{}',
    created_round INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS world_resource (
    holder      TEXT NOT NULL,
    resource    TEXT NOT NULL,
    amount      REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (holder, resource)
);

CREATE TABLE IF NOT EXISTS world_link (
    src         TEXT NOT NULL,
    rel         TEXT NOT NULL,
    dst         TEXT NOT NULL,
    attrs       TEXT NOT NULL DEFAULT '{}',
    created_round INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (src, rel, dst)
);

CREATE TABLE IF NOT EXISTS world_event (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    round       INTEGER NOT NULL,
    track       TEXT NOT NULL DEFAULT 'main',
    actor       TEXT NOT NULL,
    verb        TEXT NOT NULL,
    args        TEXT NOT NULL DEFAULT '{}',
    outcome     TEXT NOT NULL DEFAULT '{}',
    success     INTEGER NOT NULL DEFAULT 1,
    failure_reason TEXT,
    timestamp   TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_event_round ON world_event(round);
CREATE INDEX IF NOT EXISTS idx_event_actor ON world_event(actor);
CREATE INDEX IF NOT EXISTS idx_entity_type ON world_entity(type);
CREATE INDEX IF NOT EXISTS idx_link_rel ON world_link(rel);
CREATE INDEX IF NOT EXISTS idx_resource_res ON world_resource(resource);
"""


class StateError(Exception):
    """Raised when a state operation violates a constraint."""


class WorldState:
    """
    Shared mutable world state backed by SQLite.

    Thread-safety: a single lock serializes writes. The engine runs agent
    decisions concurrently but applies their effects one action at a time, so
    each action is atomic with respect to every other action.
    """

    def __init__(self, db_path: str = ":memory:", allow_negative: Optional[Iterable[str]] = None):
        """
        Args:
            db_path: SQLite path, or ":memory:".
            allow_negative: resources permitted to go below zero (e.g. "position"
                for a market that allows short selling). Every other resource is
                constrained to be non-negative.
        """
        self.db_path = db_path
        self._allow_negative = set(allow_negative or ())
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self.current_round = 0

    # ------------------------------------------------------------------
    # Entities
    # ------------------------------------------------------------------

    def put_entity(self, key: str, type_: str, attrs: Optional[Dict[str, Any]] = None) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO world_entity (key, type, attrs, created_round) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET type=excluded.type, attrs=excluded.attrs",
                (key, type_, json.dumps(attrs or {}), self.current_round),
            )

    def get_entity(self, key: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            "SELECT key, type, attrs, created_round FROM world_entity WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        return {
            "key": row["key"],
            "type": row["type"],
            "created_round": row["created_round"],
            **json.loads(row["attrs"]),
        }

    def entities_of_type(self, type_: str, limit: int = 100) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT key FROM world_entity WHERE type = ? ORDER BY created_round DESC LIMIT ?",
            (type_, limit),
        ).fetchall()
        return [self.get_entity(r["key"]) for r in rows]

    def set_attr(self, key: str, attr: str, value: Any) -> None:
        with self._lock:
            row = self.conn.execute(
                "SELECT type, attrs FROM world_entity WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                # Auto-create untyped entities so packs can set attributes on
                # things they did not pre-declare.
                self.conn.execute(
                    "INSERT INTO world_entity (key, type, attrs, created_round) VALUES (?, ?, ?, ?)",
                    (key, "Thing", json.dumps({attr: value}), self.current_round),
                )
                return
            attrs = json.loads(row["attrs"])
            attrs[attr] = value
            self.conn.execute(
                "UPDATE world_entity SET attrs = ? WHERE key = ?", (json.dumps(attrs), key)
            )

    def get_attr(self, key: str, attr: str, default: Any = None) -> Any:
        entity = self.get_entity(key)
        if entity is None:
            return default
        return entity.get(attr, default)

    # ------------------------------------------------------------------
    # Resources (the ledger)
    # ------------------------------------------------------------------

    def balance(self, holder: str, resource: str) -> float:
        row = self.conn.execute(
            "SELECT amount FROM world_resource WHERE holder = ? AND resource = ?",
            (holder, resource),
        ).fetchone()
        return float(row["amount"]) if row else 0.0

    def add_resource(self, holder: str, resource: str, delta: float) -> float:
        """
        Change a balance by delta. Raises StateError if the result would be
        negative and the resource is not in allow_negative.
        """
        with self._lock:
            current = self.balance(holder, resource)
            new = current + float(delta)
            if new < 0 and resource not in self._allow_negative:
                raise StateError(
                    f"insufficient {resource}: {holder} holds {current:g}, "
                    f"needs {abs(float(delta)):g}"
                )
            self.conn.execute(
                "INSERT INTO world_resource (holder, resource, amount) VALUES (?, ?, ?) "
                "ON CONFLICT(holder, resource) DO UPDATE SET amount = excluded.amount",
                (holder, resource, new),
            )
            return new

    def set_resource(self, holder: str, resource: str, amount: float) -> None:
        with self._lock:
            amount = float(amount)
            if amount < 0 and resource not in self._allow_negative:
                raise StateError(f"cannot set {resource} negative for {holder}")
            self.conn.execute(
                "INSERT INTO world_resource (holder, resource, amount) VALUES (?, ?, ?) "
                "ON CONFLICT(holder, resource) DO UPDATE SET amount = excluded.amount",
                (holder, resource, amount),
            )

    def transfer(self, src: str, dst: str, resource: str, amount: float) -> None:
        """Move a resource between holders. Atomic: both legs or neither."""
        amount = float(amount)
        if amount < 0:
            raise StateError("transfer amount must be non-negative")
        with self._lock:
            self.add_resource(src, resource, -amount)
            self.add_resource(dst, resource, amount)

    def holdings(self, holder: str) -> Dict[str, float]:
        rows = self.conn.execute(
            "SELECT resource, amount FROM world_resource WHERE holder = ?", (holder,)
        ).fetchall()
        return {r["resource"]: float(r["amount"]) for r in rows}

    def all_holders(self, resource: str) -> Dict[str, float]:
        rows = self.conn.execute(
            "SELECT holder, amount FROM world_resource WHERE resource = ?", (resource,)
        ).fetchall()
        return {r["holder"]: float(r["amount"]) for r in rows}

    # ------------------------------------------------------------------
    # Links
    # ------------------------------------------------------------------

    def link(self, src: str, rel: str, dst: str, attrs: Optional[Dict[str, Any]] = None) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO world_link (src, rel, dst, attrs, created_round) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(src, rel, dst) DO UPDATE SET attrs = excluded.attrs",
                (src, rel, dst, json.dumps(attrs or {}), self.current_round),
            )

    def unlink(self, src: str, rel: str, dst: str) -> None:
        with self._lock:
            self.conn.execute(
                "DELETE FROM world_link WHERE src = ? AND rel = ? AND dst = ?", (src, rel, dst)
            )

    def links_from(self, src: str, rel: Optional[str] = None) -> List[Dict[str, Any]]:
        if rel:
            rows = self.conn.execute(
                "SELECT src, rel, dst, attrs FROM world_link WHERE src = ? AND rel = ?", (src, rel)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT src, rel, dst, attrs FROM world_link WHERE src = ?", (src,)
            ).fetchall()
        return [
            {"src": r["src"], "rel": r["rel"], "dst": r["dst"], "attrs": json.loads(r["attrs"])}
            for r in rows
        ]

    def links_to(self, dst: str, rel: Optional[str] = None) -> List[Dict[str, Any]]:
        if rel:
            rows = self.conn.execute(
                "SELECT src, rel, dst, attrs FROM world_link WHERE dst = ? AND rel = ?", (dst, rel)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT src, rel, dst, attrs FROM world_link WHERE dst = ?", (dst,)
            ).fetchall()
        return [
            {"src": r["src"], "rel": r["rel"], "dst": r["dst"], "attrs": json.loads(r["attrs"])}
            for r in rows
        ]

    def count_links_to(self, dst: str, rel: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM world_link WHERE dst = ? AND rel = ?", (dst, rel)
        ).fetchone()
        return int(row["n"])

    # ------------------------------------------------------------------
    # Events (audit log)
    # ------------------------------------------------------------------

    def record_event(
        self,
        round_num: int,
        actor: str,
        verb: str,
        args: Dict[str, Any],
        outcome: Dict[str, Any],
        success: bool,
        failure_reason: Optional[str] = None,
        track: str = "main",
        timestamp: str = "",
    ) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO world_event (round, track, actor, verb, args, outcome, success, "
                "failure_reason, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    round_num,
                    track,
                    actor,
                    verb,
                    json.dumps(args, ensure_ascii=False),
                    json.dumps(outcome, ensure_ascii=False, default=str),
                    1 if success else 0,
                    failure_reason,
                    timestamp,
                ),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def recent_events(
        self,
        limit: int = 20,
        actor: Optional[str] = None,
        verb: Optional[str] = None,
        success_only: bool = False,
    ) -> List[Dict[str, Any]]:
        clauses, params = [], []
        if actor:
            clauses.append("actor = ?")
            params.append(actor)
        if verb:
            clauses.append("verb = ?")
            params.append(verb)
        if success_only:
            clauses.append("success = 1")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        rows = self.conn.execute(
            f"SELECT * FROM world_event {where} ORDER BY id DESC LIMIT ?", params
        ).fetchall()
        return [self._event_row(r) for r in rows]

    def last_failure_for(self, actor: str) -> Optional[Dict[str, Any]]:
        """The agent's most recent failed action, so it can be told what went wrong."""
        row = self.conn.execute(
            "SELECT * FROM world_event WHERE actor = ? AND success = 0 ORDER BY id DESC LIMIT 1",
            (actor,),
        ).fetchone()
        return self._event_row(row) if row else None

    @staticmethod
    def _event_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "round": row["round"],
            "track": row["track"],
            "actor": row["actor"],
            "verb": row["verb"],
            "args": json.loads(row["args"]),
            "outcome": json.loads(row["outcome"]),
            "success": bool(row["success"]),
            "failure_reason": row["failure_reason"],
            "timestamp": row["timestamp"],
        }

    # ------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------

    def begin(self) -> None:
        self._lock.acquire()
        self.conn.execute("SAVEPOINT action")

    def commit(self) -> None:
        try:
            self.conn.execute("RELEASE SAVEPOINT action")
            self.conn.commit()
        finally:
            self._lock.release()

    def rollback(self) -> None:
        try:
            self.conn.execute("ROLLBACK TO SAVEPOINT action")
            self.conn.execute("RELEASE SAVEPOINT action")
        finally:
            self._lock.release()

    def close(self) -> None:
        with self._lock:
            self.conn.commit()
            self.conn.close()

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        """Compact summary used for reports and progress display."""
        def scalar(sql: str) -> int:
            return int(self.conn.execute(sql).fetchone()[0])

        return {
            "entities": scalar("SELECT COUNT(*) FROM world_entity"),
            "links": scalar("SELECT COUNT(*) FROM world_link"),
            "events": scalar("SELECT COUNT(*) FROM world_event"),
            "failed_events": scalar("SELECT COUNT(*) FROM world_event WHERE success = 0"),
            "rounds": scalar("SELECT COALESCE(MAX(round), 0) FROM world_event"),
        }
