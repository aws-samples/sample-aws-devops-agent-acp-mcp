# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unit tests for aws_devops_agent.acp_server."""
import json
import sys
from unittest.mock import MagicMock, patch

import pytest

from aws_devops_agent.acp_server import ACPServer, Session


class TestSession:
    def test_init(self):
        s = Session("test-123")
        assert s.session_id == "test-123"
        assert s.execution_id is None
        assert s.task_id is None
        assert s.cancelled is False

class TestACPServer:
    def _make_server(self):
        server = ACPServer()
        server._captured = []
        original_write = server.write
        def capture_write(msg):
            server._captured.append(msg)
        server.write = capture_write
        return server

    def test_respond(self):
        server = self._make_server()
        server.respond("msg-1", {"ok": True})
        assert server._captured[0] == {
            "jsonrpc": "2.0", "id": "msg-1", "result": {"ok": True}
        }

    def test_error(self):
        server = self._make_server()
        server.error("msg-2", -32602, "bad param")
        assert server._captured[0]["error"]["code"] == -32602
        assert server._captured[0]["error"]["message"] == "bad param"

    def test_notify(self):
        server = self._make_server()
        server.notify("session/update", {"sessionId": "s1"})
        assert server._captured[0]["method"] == "session/update"
        assert "id" not in server._captured[0]

    def test_handle_initialize(self):
        server = self._make_server()
        server.handle_initialize("init-1", {
            "clientCapabilities": {
                "tools": [{"name": "read_file"}, {"name": "run_terminal"}]
            }
        })
        resp = server._captured[0]
        assert resp["result"]["agentInfo"]["name"] == "AWS DevOps Agent"
        assert resp["result"]["agentCapabilities"]["supportsStreaming"] is True


class TestIntentDetection:
    def test_investigation_keywords(self):
        assert ACPServer._looks_like_investigation("my ECS service is failing with 5xx errors") is True

    def test_chat_keywords(self):
        assert ACPServer._looks_like_investigation("optimize cost for my S3 buckets") is False
        assert ACPServer._looks_like_investigation("review my architecture") is False

    def test_single_strong_with_chat_keywords_does_not_trigger(self):
        # Bug #4: single "investigate" with chat keywords should NOT trigger
        # investigation — chat can answer in <60s and investigation wastes
        # 5-8 min of async compute.
        assert ACPServer._looks_like_investigation(
            "investigate the alarm on my Lambda function"
        ) is False
        assert ACPServer._looks_like_investigation(
            "investigate the error and optimize performance"
        ) is False

    def test_multiple_strong_keywords_triggers(self):
        # Multiple strong signals should trigger even with chat keywords —
        # exercises the `has_strong and chat_score > 0` branch.
        assert ACPServer._looks_like_investigation(
            "investigate the root cause of the outage"
        ) is True
        assert ACPServer._looks_like_investigation(
            "debug the incident affecting ECS"
        ) is True
        # 2 strong keywords + chat keyword → `len(strong_matches) >= 2` branch
        assert ACPServer._looks_like_investigation(
            "investigate the root cause and optimize performance"
        ) is True

    def test_single_strong_without_chat_keywords_triggers(self):
        assert ACPServer._looks_like_investigation("investigate this now") is True
        assert ACPServer._looks_like_investigation("there was an outage at 3am") is True

    def test_mixed_prefers_chat(self):
        # More chat keywords
        assert ACPServer._looks_like_investigation(
            "review architecture and recommend best practice plan"
        ) is False

    def test_neutral_text(self):
        assert ACPServer._looks_like_investigation("hello how are you") is False

    def test_substring_overlap_does_not_inflate_matches(self):
        # "sev" is a substring of "severity" — word-boundary matching must
        # prevent double-counting.  "severity" alone is 1 strong match +
        # chat keywords → should NOT trigger investigation.
        assert ACPServer._looks_like_investigation(
            "what is the severity? optimize costs"
        ) is False


class TestSessionCleanup:
    def test_evicts_expired(self):
        import time
        server = self._make_server_with_sessions()
        # Manually age one session
        server.sessions["old"].created_at = time.monotonic() - 99999
        server._cleanup_sessions()
        assert "old" not in server.sessions
        assert "new" in server.sessions

    def _make_server_with_sessions(self):
        server = ACPServer()
        server._captured = []
        server.write = lambda msg: server._captured.append(msg)
        s1 = Session("old")
        s2 = Session("new")
        server.sessions = {"old": s1, "new": s2}
        return server


class TestUnsolicitedResponseGuard:
    """Verify that unsolicited JSON-RPC responses are silently dropped."""

    def _make_server(self):
        server = ACPServer()
        server._captured = []
        server.write = lambda msg: server._captured.append(msg)
        return server

    def _feed_and_run(self, server, msg_str):
        """Feed a single JSON-RPC message to run() via mocked stdin."""
        lines = [msg_str + chr(10)]
        with patch.object(sys, "stdin", lines):
            server.run()

    def test_result_response_silently_dropped(self):
        """Server should not reply to an unsolicited result message."""
        server = self._make_server()
        msg = json.dumps({"jsonrpc": "2.0", "id": "unsolicited-1", "result": {"ok": True}})
        self._feed_and_run(server, msg)
        assert len(server._captured) == 0, f"Expected no output, got {server._captured}"

    def test_error_response_silently_dropped(self):
        """Server should not reply to an unsolicited error message."""
        server = self._make_server()
        msg = json.dumps({"jsonrpc": "2.0", "id": "unsolicited-2", "error": {"code": -1, "message": "fail"}})
        self._feed_and_run(server, msg)
        assert len(server._captured) == 0, f"Expected no output, got {server._captured}"
