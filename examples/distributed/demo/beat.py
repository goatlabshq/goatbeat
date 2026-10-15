import os

from redis import Redis

from demo.tasks import record
from goatbeat import GoatbeatApp, Registry, call
from goatbeat.rq import RQSubmitter

beat = Registry()
beat.schedule(name="every-5-seconds", task=call(record, "every-5-seconds"), every="5s")
beat.schedule(name="every-minute", task=call(record, "every-minute"), cron="* * * * *")

app = GoatbeatApp(registry=beat, submitter=RQSubmitter(Redis.from_url(os.environ["REDIS_URL"])))
