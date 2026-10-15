import logging
from datetime import timedelta

from goatbeat.core.execution import Lease
from goatbeat.core.ids import SchedulerId
from goatbeat.core.observability import Event, MetricsSink, log_event
from goatbeat.core.protocols import LeaseManager
from goatbeat.core.time import Clock


class LeaseKeeper:
    """Stops trusting the lease ``renew_interval`` before the store could hand it to another node.

    The deadline is measured from when the acquire request was sent, so a slow round trip
    only shortens the local validity.
    """

    def __init__(
        self,
        leases: LeaseManager,
        holder: SchedulerId,
        *,
        ttl: timedelta,
        renew_interval: timedelta,
        clock: Clock,
        metrics: MetricsSink,
        logger: logging.Logger,
    ) -> None:
        self._leases = leases
        self._holder = holder
        self._ttl = ttl
        self._renew = renew_interval.total_seconds()
        self._validity = (ttl - renew_interval).total_seconds()
        self._clock = clock
        self._metrics = metrics
        self._logger = logger
        self._lease: Lease | None = None
        self._renew_due = float("-inf")
        self._deadline = float("-inf")

    @property
    def lease(self) -> Lease | None:
        return self._lease if self.valid() else None

    def valid(self) -> bool:
        return self._lease is not None and self._clock.monotonic() < self._deadline

    def seconds_until_renewal(self) -> float:
        return max(0.0, self._renew_due - self._clock.monotonic())

    def ensure(self) -> Lease | None:
        started = self._clock.monotonic()
        if self._lease is not None and started < self._renew_due:
            return self.lease
        self._renew_due = started + self._renew
        try:
            acquired = self._leases.acquire(self._holder, self._ttl)
        except Exception as error:
            log_event(self._logger, Event.STORE_UNAVAILABLE, logging.WARNING, error=str(error))
            if not self.valid():
                self._lose()
            return self.lease
        if acquired is None:
            self._lose()
            return None
        if self._lease is None or self._lease.token != acquired.token:
            self._gain(acquired)
        self._lease = acquired
        self._deadline = started + self._validity
        return acquired

    def lost(self) -> None:
        """Called when the store refused a fenced write: someone else leads now."""
        self._lose()

    def release(self) -> None:
        if self._lease is None:
            return
        lease, self._lease = self._lease, None
        try:
            self._leases.release(lease)
        except Exception as error:
            log_event(self._logger, Event.STORE_UNAVAILABLE, logging.WARNING, error=str(error))
        self._metrics.leadership(is_leader=False)

    def _gain(self, lease: Lease) -> None:
        log_event(
            self._logger,
            Event.LEASE_ACQUIRED,
            scheduler_id=self._holder.value,
            fencing_token=lease.token.value,
        )
        self._metrics.leadership(is_leader=True)
        self._metrics.failover()

    def _lose(self) -> None:
        if self._lease is None:
            return
        log_event(
            self._logger,
            Event.LEADER_LOST,
            logging.WARNING,
            scheduler_id=self._holder.value,
            fencing_token=self._lease.token.value,
        )
        self._lease = None
        self._deadline = float("-inf")
        self._metrics.leadership(is_leader=False)
