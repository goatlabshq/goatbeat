from goatbeat.core.stores.memory import MemoryStore
from goatbeat.core.testing import FakeClock, StoreConformance, StoreUnderTest


class TestMemoryStore(StoreConformance):
    def make_store(self, clock: FakeClock) -> StoreUnderTest:
        store = MemoryStore(clock)
        return StoreUnderTest(store=store, leases=store, clock=clock)
