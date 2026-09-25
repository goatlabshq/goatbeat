import goatbeat


def test_facade_exposes_the_public_api() -> None:
    expected = {
        "CallableSubmitter",
        "ConfigurationError",
        "ExecutionStatus",
        "GoatbeatConfig",
        "GoatbeatError",
        "MemoryStore",
        "MisfirePolicy",
        "Registry",
        "SQLiteStore",
        "Scheduler",
        "TaskCall",
        "call",
    }
    assert expected <= set(goatbeat.__all__)
    for name in goatbeat.__all__:
        assert getattr(goatbeat, name) is not None
