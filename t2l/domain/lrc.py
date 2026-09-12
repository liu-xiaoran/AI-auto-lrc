from __future__ import annotations

from collections import defaultdict

from t2l.contracts import LyricsPlan, Timebase, TokenAlignment


def _format_frame(frame: int, timebase: Timebase) -> str:
    samples = (frame + timebase.frame_offset) * (
        timebase.hop_length * timebase.time_pooling
    )
    total_ms = samples * 1000 // timebase.sample_rate
    minutes, remainder = divmod(total_ms, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


class LrcRenderer:
    def render(
        self,
        lyrics: LyricsPlan,
        spans: tuple[TokenAlignment, ...],
        *,
        timestamp_mode: str,
        timebase: Timebase,
    ) -> str:
        if timestamp_mode not in {"line", "word"}:
            raise ValueError(f"Unsupported timestamp mode: {timestamp_mode}")

        by_token = {span.token_index: span for span in spans}
        by_line = defaultdict(list)
        for token in lyrics.tokens:
            by_line[token.line_index].append(token)

        rendered: list[str] = []
        for line_index in sorted(by_line):
            tokens = by_line[line_index]
            first_alignment = next(
                (by_token[t.token_index] for t in tokens if t.token_index in by_token),
                None,
            )
            line_prefix = ""
            if first_alignment is not None:
                line_prefix = (
                    "["
                    + _format_frame(first_alignment.frame_span.start, timebase)
                    + "]"
                )
            body = ""
            for token in tokens:
                alignment = by_token.get(token.token_index)
                if timestamp_mode == "word" and alignment is not None:
                    body += (
                        "<"
                        + _format_frame(alignment.frame_span.start, timebase)
                        + ">"
                    )
                body += token.text
            rendered.append(line_prefix + body)

        prefix = getattr(lyrics.payload, "pre_lines_unprocessed", "")
        if prefix:
            rendered.insert(0, prefix)
        return "\n".join(rendered)

