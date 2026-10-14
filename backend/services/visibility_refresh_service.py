"""Signal-initiated visibility refresh queueing (SIGV2-1182).

Adding a prompt used to enqueue nothing. The only producer for the
``visibility_index_jobs`` queue was the visibility worker's own hourly loop
(``VISIBILITY_SCHEDULE_SECONDS``, 3600s by default), so a customer who had just
configured the one thing the feature needs saw "No prompt data yet" for up to an
hour, with nothing on screen to say a measurement was coming.

This module owns the queue mechanics for a refresh Signal starts on the
customer's behalf:

* the queue name and payload the existing visibility worker already consumes,
  so there is one queueing scheme rather than a second one;
* a Redis lease that coalesces a burst of prompt additions into a single
  project refresh and makes the enqueue idempotent while one is queued or in
  flight;
* that same lease, read back, as the "a measurement is running" signal the
  customer-facing surfaces need in place of "no data".

**Cost and allowance.** A refresh queued here is Signal-initiated, so it is
enqueued with ``charge_credits=False`` and no ``charge_user_id``. It creates no
``AuditJob``, so it cannot consume the 30-day scan allowance
(``services.scan_allowance_service`` counts ``AuditJob`` rows that declared
``scan_origin == 'customer'``), and it deliberately does not take the internal
scheduled-visibility credit the hourly sweep charges via
``VisibilityIndexJobService._charge_scheduled_visibility_credits``. Typing a
prompt is not a scan and must not be billed as one. Repeat measurements are also
cheap by construction: the 23h semantic cache in ``visibility_index_jobs``
serves an identical prompt+provider+engine identity without a provider call.

**Redis is best effort.** Queueing must never lose the prompt the customer just
saved, so every call here is defensive: a Redis failure is logged and reported,
never raised at the caller.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Iterator

from core.redis_client import get_sync_redis

logger = logging.getLogger(__name__)

# Batch states that mean work is genuinely still behind a lease. "queued" is
# the model default for a batch not yet picked up; "running" covers the
# window ``VisibilityIndexJobService`` holds between creating the row and
# marking it succeeded/degraded/failed (see services/visibility_index_jobs.py).
# Anything else (succeeded, degraded, failed) means the work is done, and a
# lease still present for that project at that point is on its way to the
# happy-path release in ``_run_project_refresh``'s ``finally``, not orphaned.
_IN_FLIGHT_BATCH_STATUSES = ("queued", "running")

# The queue the visibility worker blpops. Same env var the worker reads, so a
# deployment that renames the queue renames it for both ends at once.
VISIBILITY_QUEUE_NAME = os.getenv("VISIBILITY_QUEUE_NAME", "visibility_index_jobs")

# Payload discriminator. A refresh job names a project and nothing else: the
# worker enumerates that project's active prompts when the job starts, so a
# prompt added while the job was still waiting is measured by it too. A
# per-prompt payload would have frozen the prompt list at enqueue time.
REFRESH_JOB_KIND = "project_refresh"

# ``schedule_key`` for the batches a refresh produces. "queued" is the existing
# vocabulary ``_batch_measurement_origin`` maps to MEASUREMENT_ORIGIN_QUEUED;
# inventing a new key here would have classified these batches as "scheduled",
# which is a different provenance.
REFRESH_SCHEDULE_KEY = "queued"

# How long one project may hold the refresh lease. It is both the coalescing
# window and the backstop for a worker that dies mid-refresh: the worker
# releases the lease when the refresh finishes, and this TTL releases it when
# the worker never gets to.
REFRESH_LEASE_SECONDS = int(os.getenv("VISIBILITY_REFRESH_LEASE_SECONDS", "900"))

_LEASE_KEY_PREFIX = "visibility:refresh:lease"


def refresh_lease_key(project_id: int) -> str:
    """The one lease key for a project's Signal-initiated refresh."""
    return f"{_LEASE_KEY_PREFIX}:{int(project_id)}"


@dataclass(frozen=True)
class VisibilityRefreshResult:
    """What the enqueue did, in terms a caller can report or assert on."""

    # True when this call put a refresh on the queue.
    enqueued: bool = False
    # True when a refresh for this project was already queued or in flight, so
    # this call deliberately added nothing.
    coalesced: bool = False
    # Machine-readable detail: no_active_prompts | already_in_flight |
    # queue_unavailable. None when a refresh was enqueued.
    reason: str | None = None
    # SIGV2-1234: how long, in seconds, the lease blocking this call still
    # has to run per Redis TTL, when known. Only ever set alongside
    # reason == "already_in_flight"; lets a caller say when to try again
    # instead of refusing with no explanation.
    retry_after_seconds: int | None = None

    @property
    def pending(self) -> bool:
        """True when a measurement is on its way, whoever queued it."""
        return self.enqueued or self.coalesced

    @property
    def message(self) -> str | None:
        """A human-readable reason for a coalesced refusal, or None.

        SIGV2-1234: an orphaned lease looked identical to a real one from the
        caller's side, a refusal with no explanation. This is that
        explanation, with an ETA when Redis can still report one.
        """
        if self.reason != "already_in_flight":
            return None
        if self.retry_after_seconds and self.retry_after_seconds > 0:
            return (
                "A visibility refresh is already in progress for this project; "
                f"it should free in about {self.retry_after_seconds} seconds."
            )
        return "A visibility refresh is already in progress for this project."


@contextlib.contextmanager
def _redis(client: Any | None) -> Iterator[Any]:
    """Yield the caller's client, or a short-lived one of our own."""
    if client is not None:
        yield client
        return
    with get_sync_redis() as owned:
        yield owned


def enqueue_project_visibility_refresh(
    *,
    project_id: int,
    redis_client: Any | None = None,
    audit_job_id: str | None = None,
) -> VisibilityRefreshResult:
    """Queue one visibility refresh for ``project_id``, or coalesce into the
    refresh already pending for it.

    The lease is taken first (``SET NX EX``): losing that race is the whole
    point, it means another refresh is already queued or running and this call
    must not stack a second one on top of it. If the queue push then fails the
    lease is released, so the next prompt the customer adds can try again
    rather than being coalesced into a refresh that never got queued.

    ``audit_job_id`` attributes the batches this refresh produces to the scan
    that asked for them. ``visibility_run_batches.audit_job_id`` and every
    consumer of it (the ``?audit_job_id=`` summary filter, the scan-scoped PDF
    engine rows) already existed, but nothing ever set the column, so those
    surfaces could only ever return nothing. This is the missing producer
    side. It stays ``None`` for ordinary prompt-driven refreshes, which are
    project-scoped and belong to no scan.
    """
    lease_key = refresh_lease_key(project_id)
    payload_body: dict[str, Any] = {
        "kind": REFRESH_JOB_KIND,
        "project_id": int(project_id),
        "schedule_key": REFRESH_SCHEDULE_KEY,
        # Signal-initiated: never billed to the customer. See the module
        # docstring for why.
        "charge_credits": False,
        "lease_key": lease_key,
    }
    if audit_job_id:
        payload_body["audit_job_id"] = str(audit_job_id)
    payload = json.dumps(payload_body)

    try:
        with _redis(redis_client) as client:
            acquired = client.set(lease_key, "1", nx=True, ex=REFRESH_LEASE_SECONDS)
            if not acquired:
                retry_after_seconds = None
                with contextlib.suppress(Exception):
                    ttl_value = client.ttl(lease_key)
                    if isinstance(ttl_value, int) and ttl_value > 0:
                        retry_after_seconds = ttl_value
                logger.info(
                    "Visibility refresh already pending for project_id=%s, coalescing "
                    "(retry_after_seconds=%s)",
                    project_id,
                    retry_after_seconds,
                )
                return VisibilityRefreshResult(
                    coalesced=True,
                    reason="already_in_flight",
                    retry_after_seconds=retry_after_seconds,
                )
            try:
                client.rpush(VISIBILITY_QUEUE_NAME, payload)
            except Exception:
                with contextlib.suppress(Exception):
                    client.delete(lease_key)
                raise
    except Exception:
        logger.exception("Visibility refresh enqueue failed for project_id=%s", project_id)
        return VisibilityRefreshResult(reason="queue_unavailable")

    logger.info("Visibility refresh enqueued for project_id=%s", project_id)
    return VisibilityRefreshResult(enqueued=True)


def visibility_refresh_in_flight(
    project_id: int | None,
    *,
    redis_client: Any | None = None,
) -> bool:
    """True while a Signal-initiated refresh for this project is queued or running.

    This is what lets a surface say "a measurement is running" instead of "no
    data": the difference between nothing will happen and wait a moment is the
    whole of SIGV2-1182. Unreachable Redis reports False, which keeps the
    pre-existing unmeasured wording rather than claiming a run nobody can see.
    """
    if project_id is None:
        return False
    try:
        with _redis(redis_client) as client:
            return bool(client.exists(refresh_lease_key(project_id)))
    except Exception:
        logger.warning(
            "Visibility refresh lease unreadable for project_id=%s", project_id, exc_info=True
        )
        return False


def release_refresh_lease(project_id: int, *, redis_client: Any | None = None) -> None:
    """Release the lease once the refresh has actually finished.

    Sync counterpart of the worker's own release, for callers that abandon a
    refresh before it reaches the queue. Best effort: the TTL is the backstop.
    """
    try:
        with _redis(redis_client) as client:
            client.delete(refresh_lease_key(project_id))
    except Exception:
        logger.warning(
            "Visibility refresh lease release failed for project_id=%s", project_id, exc_info=True
        )


def _project_id_from_lease_key(lease_key: Any) -> int | None:
    """Parse the project id back out of one of our own lease keys, or None."""
    prefix = f"{_LEASE_KEY_PREFIX}:"
    text = str(lease_key)
    if not text.startswith(prefix):
        return None
    try:
        return int(text[len(prefix) :])
    except ValueError:
        return None


def _has_in_flight_batch(db: Any, project_id: int) -> bool:
    """True when a ``VisibilityRunBatch`` row still backs this project's lease."""
    import models
    from sqlalchemy import select

    stmt = (
        select(models.VisibilityRunBatch.id)
        .where(
            models.VisibilityRunBatch.project_id == project_id,
            models.VisibilityRunBatch.status.in_(_IN_FLIGHT_BATCH_STATUSES),
        )
        .limit(1)
    )
    return db.execute(stmt).first() is not None


def reconcile_orphaned_refresh_leases(
    db: Any,
    *,
    redis_client: Any | None = None,
) -> list[int]:
    """Release a refresh lease nothing is behind any more (SIGV2-1234).

    The TTL on a lease (``REFRESH_LEASE_SECONDS``, 15 minutes by default) is a
    backstop for a worker that dies mid-refresh, but it is a fifteen-minute
    backstop: a restart between "lease acquired" and "job popped off the
    queue", or mid-job, leaves the lease with no ``visibility_run_batches``
    row behind it at all, and every scan attempt for that project is refused
    until the TTL runs out with nothing to explain why.

    That state is cheap to detect and provably safe to clear: a lease key
    whose project has no ``VisibilityRunBatch`` row in ``queued`` or
    ``running`` status has no work it could still be protecting, so deleting
    it cannot race a real refresh. Meant to run once at worker startup (the
    restart is exactly what creates the orphan), and is cheap enough to call
    again on a timer if a future caller wants that too.

    Best effort like the rest of this module: any Redis or DB failure is
    logged and swallowed rather than raised, so a reconciliation pass can
    never block the worker from starting.
    """
    released: list[int] = []
    try:
        with _redis(redis_client) as client:
            lease_keys = list(client.scan_iter(match=f"{_LEASE_KEY_PREFIX}:*"))
            for lease_key in lease_keys:
                project_id = _project_id_from_lease_key(lease_key)
                if project_id is None:
                    continue
                if _has_in_flight_batch(db, project_id):
                    continue
                with contextlib.suppress(Exception):
                    client.delete(lease_key)
                released.append(project_id)
                logger.warning(
                    "Released orphaned visibility refresh lease for project_id=%s "
                    "(no matching in-flight visibility_run_batches row)",
                    project_id,
                )
    except Exception:
        logger.warning("Visibility refresh lease reconciliation failed", exc_info=True)
    return released
