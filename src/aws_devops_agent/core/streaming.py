# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Event stream processing with text deduplication.

The DevOps Agent GA API streams responses as ``contentBlockDelta`` events
with nested ``delta.textDelta.text`` payloads.  Multiple content blocks
may arrive in a single response:

  - ``"text"`` blocks — incremental streaming response text.
  - ``"final_response"`` blocks — duplicate of the full text.
  - ``"chat_title"`` blocks — auto-generated chat title (metadata).

This module yields de-duplicated ``(event_type, text, payload)`` tuples,
extracting text only from ``"text"`` blocks and applying cross-block
repeat detection as a safety net.

Dedup strategy:
  1. **Block-type filtering**: only ``"text"`` blocks (or blocks with no
     declared type for backwards compat) yield text.  ``"final_response"``
     and ``"chat_title"`` blocks are suppressed.
  2. ``output_text_done`` is suppressed when streaming deltas were seen.
  3. **Cross-block repeat detection**: incoming text is buffered in a
     sliding window.  Once the window reaches 80+ chars, it is checked
     against all previously-yielded text.  If the window is a substring
     of already-sent text, the buffer is discarded and subsequent deltas
     are suppressed until a non-text event arrives or the stream ends.
"""
from typing import Any, Generator, List, Optional, Tuple

# Chars to buffer before checking for cross-block repeats.
_DEDUP_WINDOW = 80

# Minimum amount of already-sent text before repeat checking kicks in.
_MIN_SENT_BEFORE_CHECK = 100

_TEXT_DELTA_TYPES = frozenset({
    "output_text_delta", "reasoning_text_delta",
    "outputTextDelta", "reasoningTextDelta",
})
_BLOCK_BOUNDARY_TYPES = frozenset({
    "content_block_start", "contentBlockStart",
    "content_block_stop", "contentBlockStop",
})

# Content block types that carry response text.  "final_response" and
# "chat_title" are duplicates / metadata and must be suppressed.
_EXTRACTABLE_BLOCK_TYPES = frozenset({"text"})

_Queued = Tuple[str, str, dict]  # (event_type, delta_text, payload)


def iter_stream_events(
    events: list,
) -> Generator[tuple[str, Optional[str], dict[str, Any]], None, None]:
    """Iterate through a DevOps Agent event stream with text deduplication."""
    seen_streaming = False
    seen_text_deltas = False
    seen_output_text_done = False

    # Current content block type from the most recent contentBlockStart.
    # None means we are between blocks (after a stop) or haven't seen a
    # block start yet (backwards compat for pre-GA streams).
    current_block_type: Optional[str] = None
    # True once we see the first contentBlockStart.  Used to distinguish
    # pre-GA streams (no block starts) from GA orphaned deltas.
    seen_block_start = False

    sent_parts: List[str] = []        # All text yielded so far (joined for checks)
    pending: List[_Queued] = []       # Buffered deltas awaiting repeat check
    pending_parts: List[str] = []     # Text parts in pending (joined for checks)
    skipping = False                  # True once a repeat is confirmed

    def _flush_pending():
        """Flush pending buffer as real text, add to sent_text."""
        nonlocal pending_parts
        out = []
        for et, txt, pl in pending:
            sent_parts.append(txt)
            out.append((et, txt, pl))
        pending.clear()
        pending_parts = []
        return out

    def _discard_pending():
        """Discard pending buffer (suppress duplicate text)."""
        nonlocal pending_parts
        out = []
        for et, _, pl in pending:
            out.append((et, None, pl))
        pending.clear()
        pending_parts = []
        return out

    def _is_extractable_block() -> bool:
        """Check if the current content block should yield text."""
        if current_block_type is None:
            # Pre-GA streams have no contentBlockStart events at all;
            # allow text extraction for backwards compatibility.  GA
            # streams always have block starts, so None here means we
            # are between blocks (orphaned delta) — suppress.
            return not seen_block_start
        return current_block_type in _EXTRACTABLE_BLOCK_TYPES

    for event in events:
        for event_type, payload in event.items():
            if not isinstance(payload, dict):
                continue

            text: Optional[str] = None

            # -- Block boundaries: track type, reset skip state ----------
            if event_type in _BLOCK_BOUNDARY_TYPES:
                for item in _flush_pending():
                    yield item
                skipping = False
                if "Start" in event_type or "start" in event_type:
                    current_block_type = payload.get("type")
                    seen_block_start = True
                else:
                    current_block_type = None
                yield event_type, None, payload
                continue

            # -- Text deltas (output_text_delta / outputTextDelta) -------
            if event_type in _TEXT_DELTA_TYPES:
                delta = payload.get("delta", "")
                if delta:
                    seen_streaming = True
                    seen_text_deltas = True

                    if skipping:
                        yield event_type, None, payload
                        continue

                    sent_len = sum(len(s) for s in sent_parts)
                    if sent_len < _MIN_SENT_BEFORE_CHECK:
                        text = delta
                        sent_parts.append(delta)
                        yield event_type, text, payload
                        continue

                    pending.append((event_type, delta, payload))
                    pending_parts.append(delta)

                    pending_text = "".join(pending_parts)
                    if len(pending_text) < _DEDUP_WINDOW:
                        continue

                    sent_text = "".join(sent_parts)
                    if pending_text.strip() in sent_text:
                        skipping = True
                        for item in _discard_pending():
                            yield item
                        continue

                    for item in _flush_pending():
                        yield item
                    continue

            elif event_type == "output_text_done":
                for item in _flush_pending():
                    yield item
                if not seen_streaming and not seen_output_text_done:
                    t = payload.get("text", "")
                    if t:
                        seen_output_text_done = True
                        text = t
                        sent_parts.append(t)

            elif event_type in ("content_block_delta", "contentBlockDelta"):
                for item in _flush_pending():
                    yield item
                if not seen_text_deltas and _is_extractable_block():
                    delta = payload.get("delta", {})
                    if isinstance(delta, dict):
                        td = delta.get("text_delta") or delta.get("textDelta") or {}
                        if isinstance(td, dict) and td.get("text"):
                            txt = td["text"]
                            seen_streaming = True

                            if skipping:
                                yield event_type, None, payload
                                continue

                            sent_len = sum(len(s) for s in sent_parts)
                            if sent_len < _MIN_SENT_BEFORE_CHECK:
                                text = txt
                                sent_parts.append(txt)
                            else:
                                pending.append((event_type, txt, payload))
                                pending_parts.append(txt)

                                pending_text = "".join(pending_parts)
                                if len(pending_text) < _DEDUP_WINDOW:
                                    continue

                                sent_text = "".join(sent_parts)
                                if pending_text.strip() in sent_text:
                                    skipping = True
                                    for item in _discard_pending():
                                        yield item
                                    continue

                                for item in _flush_pending():
                                    yield item
                                continue

            else:
                for item in _flush_pending():
                    yield item
                if skipping:
                    skipping = False

            yield event_type, text, payload

    for item in _flush_pending():
        yield item
