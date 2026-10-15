# Distributed example

PostgreSQL, Redis, three Goatbeat schedulers and two RQ workers. Each run of a task inserts a
row into `demo_runs`, so you can check that every occurrence ran exactly once even though three
schedulers compete for it.

```bash
docker compose up --build -d
docker compose logs -f scheduler        # one lease.acquired, then occurrence.dispatched
docker compose stop scheduler-1         # or kill the leader: a standby takes over
docker compose exec postgres psql -U goatbeat -c \
  "SELECT name, count(*) FROM demo_runs GROUP BY name"
docker compose run --rm scheduler goatbeat status
docker compose down -v
```

Django Tasks needs a worker backend that Django 6.1 does not ship, so this example uses RQ; a
Django project uses `python manage.py goatbeat scheduler` the same way.
