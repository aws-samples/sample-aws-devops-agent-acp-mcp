# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unit tests for aws_devops_agent.acp_client."""
import os
import json
import threading
from unittest.mock import MagicMock, patch

import pytest

from aws_devops_agent.acp_client import ACPClient, ACPError, ACPEvent


class TestACPEvent:
    def test_init_defaults(self):
        ev = ACPEvent(type="text")
        assert ev.type == "text"
        assert ev.text == ""
        assert ev.name == ""
        assert ev.data is None

    def test_init_full(self):
        ev = ACPEvent(type="tool_call", text="", name="read_file", data={"path": "/tmp"})
        assert ev.type == "tool_call"
        assert ev.name == "read_file"
        assert ev.data == {"path": "/tmp"}

    def test_repr(self):
        ev = ACPEvent(type="text", text="hello")
        assert "text" in repr(ev)
        assert "hello" in repr(ev)


class TestACPError:
    def test_message_and_code(self):
        err = ACPError("bad", code=-32600)
        assert str(err) == "bad"
        assert err.code == -32600

    def test_default_code(self):
        err = ACPError("oops")
        assert err.code == -1


class TestACPClientInit:
    def test_defaults(self):
        client = ACPClient()
        assert client._server_path is None
        assert client._region is None
        assert client._initialized is False
        assert client._cancel_requested is False

    def test_custom_params(self):
        client = ACPClient(
            server_path="/bin/test",
            region="us-west-2",
            space_id="sp-123",
            user_id="alice",
            verbose=True,
        )
        assert client._server_path == "/bin/test"
        assert client._region == "us-west-2"
        assert client._space_id == "sp-123"
        assert client._user_id == "alice"
        assert client._verbose is True


class TestFindServer:
    def test_finds_via_which(self):
        with patch("shutil.which", return_value="/usr/bin/aws-devops-agent-acp"):
            assert ACPClient.find_server() == "/usr/bin/aws-devops-agent-acp"

    def test_falls_back_to_package_server_py(self):
        """When binary not on PATH, finds acp_server.py in package dir."""
        with patch("shutil.which", return_value=None), \
             patch("os.path.isfile", return_value=False), \
             patch("os.access", return_value=False):
            result = ACPClient.find_server()
            # Should find acp_server.py in the same package directory
            assert "acp_server.py" in result

    def test_raises_when_not_found(self):
        with patch("shutil.which", return_value=None), \
             patch("os.path.isfile", return_value=False), \
             patch("os.access", return_value=False), \
             patch("pathlib.Path.is_file", return_value=False):
            with pytest.raises(FileNotFoundError, match="Cannot find"):
                ACPClient.find_server()


class TestConnect:
    def test_connect_lifecycle(self):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stderr = MagicMock()

        with patch.object(ACPClient, "find_server", return_value="/fake/binary"):
                with patch("subprocess.Popen", return_value=mock_proc):
                    with patch("threading.Thread"):
                        with patch("time.sleep"):
                            client = ACPClient(server_path="/fake/binary")
                            with patch.object(client, "_request", side_effect=[
                                {"agentInfo": {"name": "Test"}, "agentCapabilities": {}},
                                {"sessionId": "s-123"},
                            ]):
                                client.connect()
                                assert client._initialized is True
                                assert client._session_id == "s-123"


class TestShutdown:
    def test_terminates_process(self):
        client = ACPClient()
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        client._proc = mock_proc
        client.shutdown()
        mock_proc.terminate.assert_called_once()
        assert client._initialized is False

    def test_handles_already_dead(self):
        client = ACPClient()
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        client._proc = mock_proc
        client.shutdown()
        mock_proc.terminate.assert_not_called()

    def test_handles_terminate_race(self):
        """Test TOCTOU: process exits between poll() and terminate()."""
        client = ACPClient()
        client._proc = MagicMock()
        client._proc.poll.return_value = None
        client._proc.terminate.side_effect = ProcessLookupError
        client.shutdown()  # should not raise
        assert client._proc is None


class TestPromptSync:
    def test_collects_text(self):
        client = ACPClient()
        client._initialized = True
        client._session_id = "s-1"

        events = [
            ACPEvent(type="text", text="Hello "),
            ACPEvent(type="text", text="World"),
            ACPEvent(type="turn_end"),
        ]

        with patch.object(client, "prompt", return_value=iter(events)):
            result = client.prompt_sync("test")
            assert result == "Hello World"


class TestCancel:
    def test_sets_flag(self):
        client = ACPClient()
        client._initialized = True
        client._session_id = "s-1"
        client._proc = MagicMock()
        client._proc.poll.return_value = None
        client._proc.stdin = MagicMock()

        client.cancel()
        assert client._cancel_requested is True

    def test_cancel_before_init(self):
        client = ACPClient()
        client.cancel()  # should not raise
        assert client._cancel_requested is True


class TestParseSessionUpdate:
    def test_text_event(self):
        client = ACPClient()
        events = client._parse_session_update({
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"text": "hello"},
            },
        })
        assert len(events) == 1
        assert events[0].type == "text"
        assert events[0].text == "hello"

    def test_turn_end(self):
        client = ACPClient()
        events = client._parse_session_update({
            "update": {"sessionUpdate": "turn_end"},
        })
        assert len(events) == 1
        assert events[0].type == "turn_end"

    def test_tool_call_start(self):
        client = ACPClient()
        events = client._parse_session_update({
            "update": {
                "sessionUpdate": "tool_call",
                "name": "aws_action",
            },
        })
        assert len(events) == 1
        assert events[0].type == "tool_call"
        assert events[0].name == "aws_action"

    def test_approval_event(self):
        client = ACPClient()
        events = client._parse_session_update({
            "update": {
                "sessionUpdate": "approval",
                "content": {"toolName": "run_command"},
            },
        })
        assert len(events) == 1
        assert events[0].type == "approval"

    def test_unknown_type(self):
        client = ACPClient()
        events = client._parse_session_update({
            "update": {"sessionUpdate": "unknown_type"},
        })
        assert len(events) == 1
        assert events[0].type == "unknown_type"


class TestQuick:
    def test_one_shot(self):
        with patch.object(ACPClient, "connect"):
            with patch.object(ACPClient, "prompt_sync", return_value="response"):
                with patch.object(ACPClient, "shutdown"):
                    result = ACPClient.quick("hello")
                    assert result == "response"


class TestTransport:
    def test_send_raises_when_proc_dead(self):
        client = ACPClient()
        client._proc = MagicMock()
        client._proc.poll.return_value = 1  # dead
        with pytest.raises(ACPError, match="not running"):
            client._send({"jsonrpc": "2.0"})

    def test_send_raises_on_broken_pipe(self):
        client = ACPClient()
        client._proc = MagicMock()
        client._proc.poll.return_value = None
        client._proc.stdin.write.side_effect = BrokenPipeError
        with pytest.raises(ACPError, match="Failed to write"):
            client._send({"jsonrpc": "2.0"})

    def test_request_timeout(self):
        client = ACPClient()
        client._proc = MagicMock()
        client._proc.poll.return_value = None
        client._proc.stdin = MagicMock()

        with pytest.raises(ACPError, match="Timeout"):
            client._request("test/method", {}, timeout=0.1)

    def test_next_id_increments(self):
        client = ACPClient()
        assert client._next_id() == 1
        assert client._next_id() == 2
        assert client._next_id() == 3


class TestGenerateThinkingText:
    """Tests for _generate_thinking_text keyword matching."""

    def test_alarm_keyword(self):
        msg = ACPClient._generate_thinking_text("What alarms are firing?")
        assert "⏳" in msg
        assert "CloudWatch" in msg

    def test_ec2_keyword(self):
        msg = ACPClient._generate_thinking_text("How many EC2 instances in us-east-1?")
        assert "EC2" in msg

    def test_s3_keyword(self):
        msg = ACPClient._generate_thinking_text("List S3 buckets")
        assert "S3" in msg

    def test_cost_keyword(self):
        msg = ACPClient._generate_thinking_text("Show me my costs this month")
        assert "cost" in msg.lower()

    def test_investigate_keyword(self):
        msg = ACPClient._generate_thinking_text("Investigate why my service is down")
        assert "Investigating" in msg

    def test_error_keyword(self):
        msg = ACPClient._generate_thinking_text("Why am I getting 503 errors?")
        assert "error" in msg.lower()

    def test_fallback_message(self):
        msg = ACPClient._generate_thinking_text("Tell me about yourself")
        assert "⏳" in msg
        assert "processing" in msg.lower()

    def test_case_insensitive(self):
        msg = ACPClient._generate_thinking_text("SHOW ME ALL ALARMS")
        assert "CloudWatch" in msg

    def test_multiple_keywords_picks_first_match(self):
        msg = ACPClient._generate_thinking_text("Check alarms and EC2 instances")
        assert "CloudWatch" in msg  # alarms pattern is first




class TestReadLoopMethodNotFound:
    """Tests that _read_loop sends method-not-found for server requests."""

    def test_server_request_gets_error_response(self):
        client = ACPClient()
        client._send = MagicMock()

        # Simulate a server-initiated request (has both method and id)
        server_request = json.dumps({
            "jsonrpc": "2.0",
            "id": 42,
            "method": "tools/call",
            "params": {"name": "read_file", "arguments": {"path": "/etc/hosts"}},
        })

        # Mock stdout to yield one server request then stop
        mock_proc = MagicMock()
        mock_proc.stdout.__iter__ = MagicMock(return_value=iter([server_request + "\n"]))
        client._proc = mock_proc

        client._read_loop()

        client._send.assert_called_once_with({
            "jsonrpc": "2.0",
            "id": 42,
            "error": {"code": -32601, "message": "Method not found"},
        })

    def test_notification_still_queued(self):
        client = ACPClient()
        client._send = MagicMock()

        # Notification (method but no id)
        notification = json.dumps({
            "jsonrpc": "2.0",
            "method": "$/progress",
            "params": {"token": "abc"},
        })

        mock_proc = MagicMock()
        mock_proc.stdout.__iter__ = MagicMock(return_value=iter([notification + "\n"]))
        client._proc = mock_proc

        client._read_loop()

        # Should NOT send error response for notifications
        client._send.assert_not_called()
        assert len(client._notifications) == 1

class TestParseSessionUpdateUnknown:
    """Tests for unknown event type passthrough in _parse_session_update."""

    def test_unknown_type_surfaced(self):
        client = ACPClient()
        events = client._parse_session_update({
            "update": {
                "sessionUpdate": "agent_thinking",
                "content": {"text": "I'm analyzing the data"},
            },
        })
        assert len(events) == 1
        assert events[0].type == "agent_thinking"
        assert events[0].data == {"text": "I'm analyzing the data"}

    def test_empty_type_not_surfaced(self):
        client = ACPClient()
        events = client._parse_session_update({
            "update": {"sessionUpdate": "", "content": {}},
        })
        assert len(events) == 0

    def test_known_types_not_duplicated(self):
        client = ACPClient()
        events = client._parse_session_update({
            "update": {
                "sessionUpdate": "turn_end",
                "content": {},
            },
        })
        assert len(events) == 1
        assert events[0].type == "turn_end"


class TestThinkingThreshold:
    """Tests for thinking_threshold parameter on prompt()."""

    def test_prompt_accepts_thinking_threshold(self):
        """Verify the parameter is accepted without error."""
        client = ACPClient()
        # Can't call prompt() without a server, but verify the signature
        import inspect
        sig = inspect.signature(client.prompt)
        assert "thinking_threshold" in sig.parameters
        assert sig.parameters["thinking_threshold"].default == 5.0


class TestCollapseRepeats:
    """Tests for _collapse_repeats static method."""

    def test_collapse_identical_tokens(self):
        assert ACPClient._collapse_repeats("DoneDoneDoneDone") == "Done"

    def test_collapse_two_repeats(self):
        assert ACPClient._collapse_repeats("DoneDone") == "Done"

    def test_no_collapse_unique_text(self):
        assert ACPClient._collapse_repeats("Hello world") == "Hello world"

    def test_single_char(self):
        assert ACPClient._collapse_repeats("a") == "a"

    def test_empty_string(self):
        assert ACPClient._collapse_repeats("") == ""

    def test_collapse_with_spaces(self):
        assert ACPClient._collapse_repeats("ok ok ok ") == "ok "

    def test_no_collapse_partial_repeat(self):
        assert ACPClient._collapse_repeats("DoneDoneDon") == "DoneDoneDon"

    def test_single_token_passthrough(self):
        assert ACPClient._collapse_repeats("Done") == "Done"

    def test_long_real_text_not_collapsed(self):
        text = "The investigation found 3 issues in your VPC configuration."
        assert ACPClient._collapse_repeats(text) == text


class TestShortTokenDedup:
    """Tests for short consecutive token dedup in _flush_text_buf."""

    def test_suppresses_short_consecutive_duplicate(self):
        client = ACPClient()
        seen = "Some long text that is over one hundred characters for sure, definitely more than that threshold value.Done"
        result = list(client._flush_text_buf(["Done"], seen))
        assert len(result) == 0

    def test_allows_different_short_token(self):
        client = ACPClient()
        seen = "Some text ending with Done"
        result = list(client._flush_text_buf(["Complete"], seen))
        assert len(result) == 1
        assert result[0].text == "Complete"

    def test_allows_long_repeated_text(self):
        client = ACPClient()
        long_text = "This is a normal sentence that happens to repeat."
        seen = "prefix text " + long_text
        result = list(client._flush_text_buf([long_text], seen))
        assert len(result) == 1
