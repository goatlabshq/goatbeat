"""Typed identifiers, so ids of different kinds cannot be mixed up."""

import os
import secrets
import socket
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScheduleId:
    value: str


@dataclass(frozen=True, slots=True)
class SchedulerId:
    value: str


@dataclass(frozen=True, slots=True, order=True)
class FencingToken:
    value: int


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    value: str


def new_scheduler_id() -> SchedulerId:
    return SchedulerId(f"{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(4)}")
