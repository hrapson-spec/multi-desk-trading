"""Priority-ordered dispatcher for ResearchLoopEvents (spec §6.1).

The dispatcher is synchronous and single-threaded. It processes a
queue of events in ascending priority order (0 = highest). Handlers
are pure functions returning a HandlerResult describing what was
produced; the dispatcher writes `completed_at_utc` and
`produced_artefact` back to the DuckDB row so that the audit trail
records the full trigger → artefact causation.

No parallelism by design (§6.1 "event work is minutes to hours;
periodic is bounded to hours; no parallel processing"). The event-
driven path preempts the periodic path at queue insertion time;
preemption within this dispatcher is implicit in the priority sort.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import duckdb

from contracts.v1 import ResearchLoopEvent
from persistence.db import insert_research_loop_event


@dataclass
class HandlerResult:
    """What a handler produced. Written to the event's produced_artefact."""

    artefact: str
    """Either a path to a persisted artefact, a short JSON-ish summary,
    or an opaque identifier. The contract is ≤ 4k chars to fit in
    research_loop_events.produced_artefact without DB bloat."""

    notes: str = ""
    """Human-readable notes. Not persisted; surface in tests only."""


HandlerFn = Callable[[duckdb.DuckDBPyConnection, ResearchLoopEvent], HandlerResult]
"""Signature: (conn, event) → HandlerResult. Handlers must be
side-effect-free except for writes through the bus or direct DB
inserts; they MUST NOT mutate the event itself — the dispatcher
owns that."""


@dataclass
class Dispatcher:
    """Priority-ordered event processor.

    Typical use:
        d = Dispatcher(conn=db)
        d.register("periodic_weekly", periodic_weekly_handler)
        d.submit(event)  # persists with completed_at_utc=None
        d.run(now_utc=...)  # processes queue in priority order
    """

    conn: duckdb.DuckDBPyConnection
    handlers: dict[str, HandlerFn] = field(default_factory=dict)

    def register(self, event_type: str, handler: HandlerFn) -> None:
        """Bind a handler to an event type. Re-registering overwrites."""
        self.handlers[event_type] = handler

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    def submit(self, event: ResearchLoopEvent) -> None:
        """Persist a new event as 'pending' (completed_at_utc is None)."""
        insert_research_loop_event(self.conn, event)

    def pending_events(self) -> list[ResearchLoopEvent]:
        """Return pending events ordered by (priority ASC, triggered_at ASC)."""
        rows = self.conn.execute(
            """
            SELECT event_id, event_type, triggered_at_utc,
                   priority, payload, completed_at_utc, produced_artefact
            FROM research_loop_events
            WHERE completed_at_utc IS NULL
            ORDER BY priority ASC, triggered_at_utc ASC, event_id ASC
            """
        ).fetchall()
        out: list[ResearchLoopEvent] = []
        import json

        for r in rows:
            out.append(
                ResearchLoopEvent(
                    event_id=r[0],
                    event_type=r[1],
                    triggered_at_utc=r[2],
                    priority=r[3],
                    payload=json.loads(r[4]) if isinstance(r[4], str) else r[4],
                    completed_at_utc=r[5],
                    produced_artefact=r[6],
                )
            )
        return out

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def run(self, *, now_utc: datetime) -> list[tuple[ResearchLoopEvent, HandlerResult]]:
        """Process all pending events in priority order.

        Returns (event, result) pairs in processing order. An event with
        no registered handler is skipped and remains pending (caller can
        detect via .pending_events() on the next call).
        """
        if now_utc.tzinfo is None:
            raise ValueError("now_utc must be timezone-aware")
        processed: list[tuple[ResearchLoopEvent, HandlerResult]] = []
        for event in self.pending_events():
            handler = self.handlers.get(event.event_type)
            if handler is None:
                continue
            result = handler(self.conn, event)
            self._mark_completed(
                event_id=event.event_id,
                completed_at_utc=now_utc,
                produced_artefact=result.artefact,
            )
            processed.append((event, result))
        return processed

    # ------------------------------------------------------------------

    def _mark_completed(
        self, *, event_id: str, completed_at_utc: datetime, produced_artefact: str
    ) -> None:
        self.conn.execute(
            """
            UPDATE research_loop_events
            SET completed_at_utc = ?, produced_artefact = ?
            WHERE event_id = ?
            """,
            [completed_at_utc, produced_artefact, event_id],
        )
