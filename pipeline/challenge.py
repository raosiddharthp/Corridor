"""Single-use challenges for the aud/nonce binding of a delegated mandate chain."""
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


class ChallengeLimitError(RuntimeError):
    pass


@dataclass(frozen=True)
class Challenge:
    aud: str
    nonce: str
    expires_at: float


class MemoryChallengeStore:
    def __init__(
        self,
        *,
        ttl: float = 300.0,
        max_outstanding: int = 1000,
        clock: Callable[[], float] = time.time,
    ):
        self._ttl = ttl
        self._max = max_outstanding
        self._clock = clock
        self._items: dict[str, Challenge] = {}
        self._lock = threading.Lock()

    def _purge(self, now: float) -> None:
        for nonce in [n for n, c in self._items.items() if c.expires_at <= now]:
            del self._items[nonce]

    def issue(self, aud: str) -> Challenge:
        now = self._clock()
        with self._lock:
            if len(self._items) >= self._max:
                self._purge(now)
                if len(self._items) >= self._max:
                    raise ChallengeLimitError("too many outstanding challenges")
            challenge = Challenge(
                aud=aud,
                nonce=secrets.token_urlsafe(24),
                expires_at=now + self._ttl,
            )
            self._items[challenge.nonce] = challenge
            return challenge

    def consume(self, aud: str, nonce: str) -> bool:
        """Single use. Any attempt burns the nonce, valid or not."""
        now = self._clock()
        with self._lock:
            challenge = self._items.pop(nonce, None)
        return (
            challenge is not None
            and challenge.expires_at > now
            and challenge.aud == aud
        )
