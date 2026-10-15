# Multiple workers

Workers belong to your task backend, not to Goatbeat. Scale them as you normally would: more
Django Tasks workers, more Celery or Dramatiq processes, more RQ workers.

Goatbeat affects workers in two ways:

- **Routing.** A schedule's `queue=` (and `priority=` where the backend supports it) decides which
  workers receive its tasks. Unsupported routing is rejected rather than ignored: RQ has no
  priority; Dramatiq honors priority on RabbitMQ only; no backend lets a schedule pick a
  different broker except Django Tasks' `backend=`.
- **Idempotency.** In the at-least-once window a task can be delivered twice, possibly to two
  different workers. Use the idempotency key (Celery task id, Dramatiq message id, RQ job id,
  Django `goatbeat_key` parameter) to make the second delivery a no-op.

Make sure a worker consumes every queue your schedules route to: a message sent to a queue no
worker reads waits forever.
