from __future__ import annotations

from .sketch_surface import format_metric_number


class ConsoleDisplay:
    def __init__(self):
        self._last_output: str | None = None

    def render_frame(self, frame: dict) -> None:
        output = self._format_frame(frame)
        if output == self._last_output:
            return
        self._last_output = output
        print(output, flush=True)

    def _format_frame(self, frame: dict) -> str:
        mode = frame.get("mode")
        if mode == "blank":
            return "[blank]"
        if mode == "status":
            return "\n".join(str(line) for line in frame.get("lines") or [])

        lines = [f"[{frame.get('phase', 'metric')}]"]
        for item in frame.get("items") or []:
            if item.get("value_type") == "bar":
                minimum = float(item.get("min_value") or 0.0)
                maximum = float(item.get("max_value") or 100.0)
                current = float(item.get("current_value") or 0.0)
                span = maximum - minimum
                fraction = 0.0 if span <= 0 else max(0.0, min(1.0, (current - minimum) / span))
                fill = int(round(10 * fraction))
                bar = "#" * fill + "-" * (10 - fill)
                current_text = format_metric_number(current)
                unit = str(item.get("unit") or "").strip()
                suffix = f" {unit}" if unit else ""
                lines.append(f"{item.get('title', '')}: [{bar}] {current_text}{suffix}".rstrip())
                continue
            value = str(item.get("value") or "")
            unit = str(item.get("unit") or "").strip()
            suffix = f" {unit}" if unit else ""
            lines.append(f"{item.get('title', '')}: {value}{suffix}".rstrip())
        return "\n".join(lines) if lines else "Status\nIdle"
