from __future__ import annotations
from datetime import datetime, timezone, timedelta

_IST = timezone(timedelta(hours=5, minutes=30))


class SessionClock:
    def __init__(self, exchange: str = "NSE", open_hm: tuple[int, int] = (9, 15), force_exit_hm: tuple[int, int] = (15, 20), close_hm: tuple[int, int] = (15, 30)) -> None:
        self.exchange = exchange
        self.open_min = open_hm[0] * 60 + open_hm[1]
        self.fe_min = force_exit_hm[0] * 60 + force_exit_hm[1]
        self.close_min = close_hm[0] * 60 + close_hm[1]

    @staticmethod
    def _mod(epoch: float) -> int:
        dt = datetime.fromtimestamp(epoch, tz=_IST)
        return dt.hour * 60 + dt.minute

    def is_open(self, epoch: float) -> bool:
        m = self._mod(epoch)
        return self.open_min <= m < self.close_min

    def force_exit(self, epoch: float) -> bool:
        return self._mod(epoch) >= self.fe_min