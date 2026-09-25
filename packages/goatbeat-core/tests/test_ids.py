from goatbeat.core.ids import new_scheduler_id


def test_scheduler_ids_are_unique_and_readable() -> None:
    first, second = new_scheduler_id(), new_scheduler_id()
    assert first != second
    assert first.value.count(":") == 2
