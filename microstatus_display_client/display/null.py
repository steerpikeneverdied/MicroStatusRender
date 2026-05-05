from __future__ import annotations


class NullDisplay:
    def render_frame(self, frame: dict) -> None:
        del frame
