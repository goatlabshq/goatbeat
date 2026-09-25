"""Importable tasks used by the tests."""

CALLS: list[tuple[object, ...]] = []


def generate_report() -> None:
    CALLS.append(("generate_report",))


def send_email(user_id: int, *, subject: str = "hello") -> None:
    CALLS.append(("send_email", user_id, subject))


class Namespace:
    @staticmethod
    def nested() -> None:
        CALLS.append(("nested",))


NOT_CALLABLE = 42
