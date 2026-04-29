# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unit tests for aws_devops_agent.core."""
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from aws_devops_agent.core.util import call_api, call_raw, epoch_millis_to_iso, serialize
from aws_devops_agent.core.streaming import iter_stream_events


# ── serialize ─────────────────────────────────────────────────────────────

class TestSerialize:
    def test_datetime(self):
        dt = datetime(2024, 1, 15, 12, 30, 0)
        assert serialize(dt) == "2024-01-15T12:30:00"

    def test_bytes(self):
        assert serialize(b"hello") == "hello"

    def test_unsupported_type_raises(self):
        with pytest.raises(TypeError, match="Not serializable"):
            serialize(set())


# ── epoch_millis_to_iso ───────────────────────────────────────────────────

class TestEpochMillisToIso:
    def test_converts_large_int(self):
        result = epoch_millis_to_iso(1700000000000)
        assert result == "2023-11-14T22:13:20+00:00"

    def test_leaves_small_int(self):
        assert epoch_millis_to_iso(42) == 42

    def test_recursive_dict(self):
        data = {"ts": 1700000000000, "name": "test"}
        result = epoch_millis_to_iso(data)
        assert isinstance(result["ts"], str)
        assert result["name"] == "test"

    def test_recursive_list(self):
        data = [1700000000000, "hello", 5]
        result = epoch_millis_to_iso(data)
        assert isinstance(result[0], str)
        assert result[1] == "hello"
        assert result[2] == 5


# ── call_api ──────────────────────────────────────────────────────────────

class TestCallApi:
    def test_success(self):
        mock_fn = MagicMock(return_value={"data": "ok", "ResponseMetadata": {}})
        result = json.loads(call_api(mock_fn, foo="bar"))
        assert result == {"data": "ok"}
        mock_fn.assert_called_once_with(foo="bar")

    def test_strips_none_kwargs(self):
        mock_fn = MagicMock(return_value={"ResponseMetadata": {}})
        call_api(mock_fn, a=1, b=None, c="x")
        mock_fn.assert_called_once_with(a=1, c="x")

    def test_client_error(self):
        from botocore.exceptions import ClientError
        error_resp = {"Error": {"Code": "NotFound", "Message": "not found"}}
        mock_fn = MagicMock(side_effect=ClientError(error_resp, "GetItem"))
        result = json.loads(call_api(mock_fn))
        assert result["error"] == "NotFound"
        assert result["message"] == "not found"

    def test_client_error_with_missing_error_fields(self):
        from botocore.exceptions import ClientError
        error_resp = {}
        mock_fn = MagicMock(side_effect=ClientError(error_resp, "GetItem"))
        result = json.loads(call_api(mock_fn))
        assert result["error"] == "ClientError"
        assert "GetItem" in result["message"]

    def test_generic_exception(self):
        mock_fn = MagicMock(side_effect=ValueError("bad"))
        result = json.loads(call_api(mock_fn))
        assert result["error"] == "InternalError"
        assert result["message"] == "An unexpected error occurred. Check server logs."


class TestCallRaw:
    def test_returns_dict_without_metadata(self):
        mock_fn = MagicMock(return_value={"data": 1, "ResponseMetadata": {"x": 1}})
        result = call_raw(mock_fn, key="val")
        assert result == {"data": 1}


# ── iter_stream_events ────────────────────────────────────────────────────

class TestIterStreamEvents:
    def test_output_text_delta(self):
        events = [
            {"output_text_delta": {"delta": "hello"}},
            {"output_text_delta": {"delta": " world"}},
        ]
        results = list(iter_stream_events(events))
        assert results[0] == ("output_text_delta", "hello", {"delta": "hello"})
        assert results[1] == ("output_text_delta", " world", {"delta": " world"})

    def test_dedup_output_text_done_when_deltas_seen(self):
        events = [
            {"output_text_delta": {"delta": "hello"}},
            {"output_text_done": {"text": "hello"}},
        ]
        results = list(iter_stream_events(events))
        # delta yields text
        assert results[0][1] == "hello"
        # done yields None (deduped)
        assert results[1][1] is None

    def test_output_text_done_when_no_deltas(self):
        events = [
            {"output_text_done": {"text": "full response"}},
        ]
        results = list(iter_stream_events(events))
        assert results[0][1] == "full response"

    def test_content_block_delta_fallback(self):
        events = [
            {"content_block_delta": {
                "delta": {"text_delta": {"text": "fallback"}}
            }},
        ]
        results = list(iter_stream_events(events))
        assert results[0][1] == "fallback"

    def test_content_block_delta_skipped_when_streaming(self):
        events = [
            {"output_text_delta": {"delta": "streamed"}},
            {"content_block_delta": {
                "delta": {"text_delta": {"text": "duplicate"}}
            }},
        ]
        results = list(iter_stream_events(events))
        assert results[0][1] == "streamed"
        assert results[1][1] is None  # skipped

    def test_non_text_events_yield_none_text(self):
        events = [
            {"function_call_arguments_done": {"call_id": "1", "name": "tool"}},
            {"summary": {"content": "did something"}},
        ]
        results = list(iter_stream_events(events))
        assert all(r[1] is None for r in results)

    def test_skips_non_dict_payloads(self):
        events = [{"some_event": "string_payload"}]
        results = list(iter_stream_events(events))
        assert results == []

    def test_reasoning_text_delta(self):
        events = [
            {"reasoning_text_delta": {"delta": "thinking..."}},
        ]
        results = list(iter_stream_events(events))
        assert results[0][1] == "thinking..."

    def test_cross_block_dedup_suppresses_repeat(self):
        """Duplicate content block with explicit block boundaries is suppressed."""
        response_text = (
            "Here's what I found across your AWS accounts in us-east-1. "
            "There are 2 instances running and 1 stopped instance. "
            "No impaired status checks were detected across any account."
        )
        events = [
            {"outputTextDelta": {"delta": response_text}},
            {"contentBlockStop": {}},
            {"contentBlockStart": {}},
            {"outputTextDelta": {"delta": response_text}},
            {"contentBlockStop": {}},
        ]
        texts = [t for _, t, _ in iter_stream_events(events) if t]
        assert len(texts) == 1
        assert texts[0] == response_text

    def test_cross_block_dedup_allows_different_text(self):
        """Different text in a second block should NOT be suppressed."""
        text1 = (
            "Here is the full analysis of your EC2 instances across all "
            "three accounts in us-east-1 region with detailed status checks."
        )
        text2 = (
            "EC2 instances status check for us-east-1 region completed "
            "successfully with no impaired instances found in your fleet."
        )
        events = [
            {"outputTextDelta": {"delta": text1}},
            {"contentBlockStop": {}},
            {"contentBlockStart": {}},
            {"outputTextDelta": {"delta": text2}},
            {"contentBlockStop": {}},
        ]
        texts = [t for _, t, _ in iter_stream_events(events) if t]
        assert len(texts) == 2

    def test_cross_block_dedup_ignores_short_repeats(self):
        """Short repeated text like 'Done' should NOT be suppressed."""
        events = [
            {"outputTextDelta": {"delta": "Done"}},
            {"outputTextDelta": {"delta": "Done"}},
            {"outputTextDelta": {"delta": "Done"}},
        ]
        texts = [t for _, t, _ in iter_stream_events(events) if t]
        assert len(texts) == 3

    def test_cross_block_dedup_with_incremental_deltas(self):
        """Dedup works when the duplicate arrives as many small deltas."""
        block1 = (
            "Here's the detailed analysis of your running instances "
            "and their health status across all three linked accounts."
        )
        events = [{"outputTextDelta": {"delta": block1}}]
        events.append({"contentBlockStart": {}})
        for word in block1.split():
            events.append({"outputTextDelta": {"delta": word + " "}})
        events.append({"contentBlockStop": {}})
        texts = [t for _, t, _ in iter_stream_events(events) if t]
        combined = "".join(texts).strip()
        assert combined == block1

    def test_cross_block_dedup_no_boundary_markers(self):
        """Dedup works even WITHOUT contentBlockStart/Stop markers."""
        block1 = (
            "Good news! There are no alarms currently firing across "
            "any of your AWS accounts. I checked all three accounts "
            "in us-east-1, us-west-2, and us-east-2."
        )
        # No block boundaries — just two rounds of deltas back to back
        events = [{"outputTextDelta": {"delta": block1}}]
        for word in block1.split():
            events.append({"outputTextDelta": {"delta": word + " "}})
        texts = [t for _, t, _ in iter_stream_events(events) if t]
        combined = "".join(texts).strip()
        assert combined == block1


# ── resolve_agent_space ──────────────────────────────────────────────────

class TestResolveAgentSpace:
    def test_returns_explicit_id(self):
        import aws_devops_agent.core.client as client
        original = client.DEFAULT_AGENT_SPACE_ID
        try:
            result = client.resolve_agent_space("explicit-id")
            assert result == "explicit-id"
        finally:
            client.DEFAULT_AGENT_SPACE_ID = original

    def test_returns_env_default(self):
        import aws_devops_agent.core.client as client
        original = client.DEFAULT_AGENT_SPACE_ID
        try:
            client.DEFAULT_AGENT_SPACE_ID = "env-space"
            result = client.resolve_agent_space()
            assert result == "env-space"
        finally:
            client.DEFAULT_AGENT_SPACE_ID = original

    def test_raises_when_no_id_and_auto_create_disabled(self):
        import aws_devops_agent.core.client as client
        from unittest.mock import patch, MagicMock
        orig_id = client.DEFAULT_AGENT_SPACE_ID
        orig_auto = client.AUTO_CREATE_AGENT_SPACE
        try:
            client.DEFAULT_AGENT_SPACE_ID = ""
            client.AUTO_CREATE_AGENT_SPACE = False
            mock_client = MagicMock()
            mock_client.list_agent_spaces.return_value = {"agentSpaces": []}
            with patch.object(client, "get_client", return_value=mock_client):
                with pytest.raises(ValueError, match="agent_space_id is required"):
                    client.resolve_agent_space()
        finally:
            client.DEFAULT_AGENT_SPACE_ID = orig_id
            client.AUTO_CREATE_AGENT_SPACE = orig_auto


class TestResolveUserId:
    def test_returns_explicit(self):
        import aws_devops_agent.core.client as client
        assert client.resolve_user_id("bob") == "bob"

    def test_raises_when_empty(self):
        import aws_devops_agent.core.client as client
        original = client.DEFAULT_USER_ID
        try:
            client.DEFAULT_USER_ID = ""
            with pytest.raises(ValueError, match="user_id is required"):
                client.resolve_user_id()
        finally:
            client.DEFAULT_USER_ID = original


# ── GA event format tests ────────────────────────────────────────────────

class TestGAStreamEvents:
    """Tests for GA API event format: contentBlockDelta with textDelta."""

    def test_ga_basic_streaming(self):
        """GA format: contentBlockDelta with nested textDelta.text."""
        events = [
            {"responseCreated": {"responseId": "r1", "sequenceNumber": 1}},
            {"responseInProgress": {"responseId": "r1", "sequenceNumber": 2}},
            {"contentBlockStart": {"index": 0, "type": "text", "sequenceNumber": 3}},
            {"contentBlockDelta": {"index": 0, "delta": {"textDelta": {"text": "Hello"}}, "sequenceNumber": 4}},
            {"contentBlockDelta": {"index": 0, "delta": {"textDelta": {"text": " world"}}, "sequenceNumber": 5}},
            {"contentBlockStop": {"index": 0, "type": "text", "sequenceNumber": 6}},
            {"responseCompleted": {"responseId": "r1", "sequenceNumber": 7}},
        ]
        texts = [t for _, t, _ in iter_stream_events(events) if t]
        assert "".join(texts) == "Hello world"

    def test_ga_final_response_suppressed(self):
        """GA format: final_response block text should NOT be yielded."""
        events = [
            {"contentBlockStart": {"index": 0, "type": "text"}},
            {"contentBlockDelta": {"index": 0, "delta": {"textDelta": {"text": "Hello world"}}}},
            {"contentBlockStop": {"index": 0, "type": "text"}},
            {"contentBlockStart": {"index": 1, "type": "final_response"}},
            {"contentBlockDelta": {"index": 1, "delta": {"textDelta": {"text": "Hello world"}}}},
            {"contentBlockStop": {"index": 1, "type": "final_response"}},
        ]
        texts = [t for _, t, _ in iter_stream_events(events) if t]
        assert len(texts) == 1
        assert texts[0] == "Hello world"

    def test_ga_chat_title_suppressed(self):
        """GA format: chat_title block text should NOT be yielded."""
        events = [
            {"contentBlockStart": {"index": 0, "type": "text"}},
            {"contentBlockDelta": {"index": 0, "delta": {"textDelta": {"text": "The sky is blue."}}}},
            {"contentBlockStop": {"index": 0, "type": "text"}},
            {"contentBlockStart": {"index": 2, "type": "chat_title"}},
            {"contentBlockDelta": {"index": 2, "delta": {"textDelta": {"text": "User asks about sky color"}}}},
            {"contentBlockStop": {"index": 2, "type": "chat_title"}},
        ]
        texts = [t for _, t, _ in iter_stream_events(events) if t]
        assert len(texts) == 1
        assert texts[0] == "The sky is blue."

    def test_ga_full_response_with_all_blocks(self):
        """GA format: text + final_response + chat_title — only text extracted."""
        events = [
            {"responseCreated": {"responseId": "r1"}},
            {"responseInProgress": {"responseId": "r1"}},
            {"contentBlockStart": {"index": 0, "type": "text"}},
            {"contentBlockDelta": {"index": 0, "delta": {"textDelta": {"text": "I'm"}}}},
            {"contentBlockDelta": {"index": 0, "delta": {"textDelta": {"text": " here"}}}},
            {"contentBlockDelta": {"index": 0, "delta": {"textDelta": {"text": " to help!"}}}},
            {"contentBlockStop": {"index": 0, "type": "text"}},
            {"contentBlockStart": {"index": 1, "type": "final_response"}},
            {"contentBlockDelta": {"index": 1, "delta": {"textDelta": {"text": "I'm here to help!"}}}},
            {"contentBlockStop": {"index": 1, "type": "final_response", "last": True}},
            {"contentBlockStart": {"index": 2, "type": "chat_title"}},
            {"contentBlockDelta": {"index": 2, "delta": {"textDelta": {"text": "User requests greeting"}}}},
            {"contentBlockStop": {"index": 2, "type": "chat_title"}},
            {"responseCompleted": {"responseId": "r1", "usage": {"inputTokens": 3, "outputTokens": 10}}},
        ]
        texts = [t for _, t, _ in iter_stream_events(events) if t]
        assert "".join(texts) == "I'm here to help!"

    def test_ga_unknown_block_type_suppressed(self):
        """Unknown block types should be suppressed (safe default)."""
        events = [
            {"contentBlockStart": {"index": 0, "type": "text"}},
            {"contentBlockDelta": {"index": 0, "delta": {"textDelta": {"text": "Hello"}}}},
            {"contentBlockStop": {"index": 0, "type": "text"}},
            {"contentBlockStart": {"index": 1, "type": "some_new_type"}},
            {"contentBlockDelta": {"index": 1, "delta": {"textDelta": {"text": "metadata"}}}},
            {"contentBlockStop": {"index": 1, "type": "some_new_type"}},
        ]
        texts = [t for _, t, _ in iter_stream_events(events) if t]
        assert len(texts) == 1
        assert texts[0] == "Hello"

    def test_ga_no_block_start_backwards_compat(self):
        """When no contentBlockStart is sent, contentBlockDelta still works."""
        events = [
            {"contentBlockDelta": {"delta": {"textDelta": {"text": "old format"}}}},
        ]
        texts = [t for _, t, _ in iter_stream_events(events) if t]
        assert texts == ["old format"]

    def test_ga_cross_block_dedup_safety_net(self):
        """Even without block type, cross-block dedup catches long repeats."""
        long_text = (
            "The investigation found that your ECS service has been experiencing "
            "intermittent 503 errors due to target group health check failures. "
            "The root cause is insufficient container memory allocation."
        )
        events = [
            {"contentBlockStart": {"index": 0, "type": "text"}},
            {"contentBlockDelta": {"index": 0, "delta": {"textDelta": {"text": long_text}}}},
            {"contentBlockStop": {"index": 0, "type": "text"}},
            # Even if a second "text" block appears with same content
            {"contentBlockStart": {"index": 1, "type": "text"}},
            {"contentBlockDelta": {"index": 1, "delta": {"textDelta": {"text": long_text}}}},
            {"contentBlockStop": {"index": 1, "type": "text"}},
        ]
        texts = [t for _, t, _ in iter_stream_events(events) if t]
        combined = "".join(texts)
        assert combined == long_text

    def test_ga_orphaned_tool_summary_delta_suppressed(self):
        """Orphaned tool_summary deltas between STOP and next START are suppressed.

        When the agent makes concurrent tool calls, the service may send
        tool_summary completion deltas (e.g. "Done") after a contentBlockStop
        without a new contentBlockStart.  These must not leak into the output.
        """
        events = [
            {"contentBlockStart": {"index": 0, "type": "text"}},
            {"contentBlockDelta": {"index": 0, "delta": {"textDelta": {"text": "Checking."}}}},
            {"contentBlockStop": {"index": 0, "type": "text"}},
            # tool_summary block with proper start/stop
            {"contentBlockStart": {"index": 1, "type": "tool_summary"}},
            {"contentBlockDelta": {"index": 1, "delta": {"textDelta": {"text": "Calling ec2.describe_instances"}}}},
            {"contentBlockDelta": {"index": 1, "delta": {"textDelta": {"text": "Done"}}}},
            {"contentBlockStop": {"index": 1, "type": "tool_summary"}},
            # Orphaned delta — no contentBlockStart before this
            {"contentBlockDelta": {"index": 2, "delta": {"textDelta": {"text": "Done"}}}},
            {"contentBlockStop": {"index": 2, "type": "tool_summary"}},
            # Another orphaned delta
            {"contentBlockDelta": {"index": 3, "delta": {"textDelta": {"text": "Done"}}}},
            {"contentBlockStop": {"index": 3, "type": "tool_summary"}},
            # Real text block
            {"contentBlockStart": {"index": 4, "type": "text"}},
            {"contentBlockDelta": {"index": 4, "delta": {"textDelta": {"text": "Results here."}}}},
            {"contentBlockStop": {"index": 4, "type": "text"}},
        ]
        texts = [t for _, t, _ in iter_stream_events(events) if t]
        assert "".join(texts) == "Checking.Results here."
