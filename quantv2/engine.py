from __future__ import annotations
from quantv2.pipeline import decide

class Engine:
    def __init__(self) -> None:
        self.position = None

    def on_bar_close(self, ctx, **kw):
        if self.position is not None:
            return None
        return decide(ctx, position_open=False, **kw)
