# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""AWS DevOps Agent — ACP Server.

Agent Client Protocol wrapper over the DevOps Agent APIs.

Architecture:
  ┌─────────────────────────────────────────────────────────┐
  │              IDE (ACP Client, e.g. Kiro)                 │
  │  Local tools: filesystem, terminal, search, browser      │
  └──────────┬──────────────────────────────┬───────────────┘
             ▼                              │
  ┌──────────────────────────────────────────────────────────┐
  │              ACP Server (this file)                       │
  │                                                          │
  │  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
  │  │ Chat (fast)  │  │Investigation │  │ Journal Poller │  │
  │  │ send_msg     │  │ (deep async) │  │ (background)   │  │
  │  └──────┬───────┘  └──────┬───────┘  └──────┬─────────┘  │
  │         │                 │                  │            │
  │         └────────┬────────┘──────────────────┘            │
  └──────────────────┼────────────────────────────────────────┘
                     ▼
  ┌──────────────────────────────────────────────────────────┐
  │              AWS DevOps Agent APIs                        │
  │  CP: control plane  |  DP: data plane (streaming)        │
  └──────────────────────────────────────────────────────────┘

Features:
  - Parallel investigation + chat: deep research runs alongside fast chat
  - Journal polling: streams investigation progress to user in real-time
  - Intent detection: auto-routes to investigation vs chat mode.
  - Native cancellation and permission-gated operations

Transport: JSON-RPC 2.0 over stdio (stdin/stdout), newline-delimited.
"""

import getpass
import json
import os
import re
import logging
import sys
import threading
import time
import uuid
from typing import Any, Optional

import aws_devops_agent.core.client as config
from aws_devops_agent.core import (
    call_raw,
    get_cp,
    get_dp,
    iter_stream_events,
    serialize,
)

# ---------------------------------------------------------------------------
# ACP-specific configuration
# ---------------------------------------------------------------------------
VERSION = "1.0.0"
JOURNAL_POLL_INTERVAL = int(os.environ.get("DEVOPS_AGENT_JOURNAL_POLL_SECS", "20"))
MAX_SESSIONS = int(os.environ.get("DEVOPS_AGENT_MAX_SESSIONS", "50"))
SESSION_TTL_SECS = int(os.environ.get("DEVOPS_AGENT_SESSION_TTL_SECS", "3600"))

# Fall back to OS user when DEVOPS_AGENT_USER_ID is not set
if not config.DEFAULT_USER_ID:
    config.DEFAULT_USER_ID = getpass.getuser()



# ---------------------------------------------------------------------------
# Session — tracks chat execution, investigation, and journal state
# ---------------------------------------------------------------------------
class Session:
    """Maps an ACP session to a DevOps Agent chat + optional investigation."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.created_at = time.monotonic()
        # Per-session AgentSpace (allows multi-space steering)
        self.agent_space_id: str = ""
        # Chat (fast responses)
        self.execution_id: Optional[str] = None
        # Investigation (deep async research)
        self.task_id: Optional[str] = None
        self.investigation_execution_id: Optional[str] = None
        self.investigation_status: Optional[str] = None
        # Journal polling
        self.last_journal_token: Optional[str] = None
        self.journal_records_seen: set[str] = set()
        # General
        self.cancelled = False
        self.seen_text_hashes: set = set()  # Dedup chat vs investigation


# ---------------------------------------------------------------------------
# ACP Server
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)


class ACPServer:
    """Agent Client Protocol server for AWS DevOps Agent.

    Lifecycle:
        initialize -> session/new -> session/prompt (loop) -> session/cancel

    Streaming:
        The server streams investigation progress and recommendations back
        to the client via JSON-RPC notifications.
    """

    def __init__(self):
        self.sessions: dict[str, Session] = {}
        self._write_lock = threading.Lock()
        self._journal_threads: dict[str, threading.Thread] = {}

    # ── I/O ───────────────────────────────────────────────────────────────

    def write(self, msg: dict):
        with self._write_lock:
            sys.stdout.write(json.dumps(msg, default=serialize) + "\n")
            sys.stdout.flush()

    def respond(self, msg_id: Any, result: dict):
        self.write({"jsonrpc": "2.0", "id": msg_id, "result": result})

    def error(self, msg_id: Any, code: int, message: str):
        self.write({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}})

    def notify(self, method: str, params: dict):
        self.write({"jsonrpc": "2.0", "method": method, "params": params})

    # ── Session updates (streaming to client) ─────────────────────────────

    def _send_text(self, session_id: str, text: str, dedup: bool = False):
        if dedup:
            h = hash(text.strip())
            session = self.sessions.get(session_id)
            if session and h in session.seen_text_hashes:
                return  # Skip duplicate
            if session:
                session.seen_text_hashes.add(h)
        self.notify("session/update", {
            "sessionId": session_id,
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": text},
            },
        })

    def _send_tool_start(self, session_id: str, tool_call_id: str,
                         name: str, title: str, params: Optional[dict] = None,
                         kind: str = "read"):
        self.notify("session/update", {
            "sessionId": session_id,
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": tool_call_id,
                "name": name,
                "title": title,
                "kind": kind,
                "status": "in_progress",
                **({"rawInput": params} if params else {}),
            },
        })

    def _send_tool_done(self, session_id: str, tool_call_id: str,
                        status: str = "completed", result: str = ""):
        self.notify("session/update", {
            "sessionId": session_id,
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": tool_call_id,
                "status": status,
                "result": result,
            },
        })

    def _send_turn_end(self, session_id: str):
        self.notify("session/update", {
            "sessionId": session_id,
            "update": {"sessionUpdate": "turn_end"},
        })

    def _cleanup_sessions(self):
        """Evict expired sessions and enforce max session count."""
        now = time.monotonic()
        expired = [
            sid for sid, s in self.sessions.items()
            if (now - s.created_at) > SESSION_TTL_SECS
        ]
        for sid in expired:
            self.sessions.pop(sid, None)
            self._journal_threads.pop(sid, None)
        while len(self.sessions) > MAX_SESSIONS:
            oldest = min(self.sessions, key=lambda s: self.sessions[s].created_at)
            self.sessions.pop(oldest, None)
            self._journal_threads.pop(oldest, None)

    # ── AgentSpace auto-provisioning ──────────────────────────────────────

    def _find_or_create_agent_space(self, msg_id: Any, allow_create: bool = False) -> str:
        """Find an existing AgentSpace, optionally creating one if none exist.

        When allow_create is False (default), only discovers existing spaces.
        When allow_create is True, creates a new space if none are found.
        Returns the agentSpaceId, or empty string on failure.
        """
        tc_id = str(uuid.uuid4())
        tmp_sid = str(uuid.uuid4())

        self._send_tool_start(tmp_sid, tc_id, "setup_agent_space",
                              "Setting up DevOps Agent — looking for AgentSpace…")
        try:
            resp = call_raw(get_cp().list_agent_spaces, maxResults=5)
            spaces = resp.get("agentSpaces", [])
            if spaces:
                space_id = spaces[0].get("agentSpaceId", "")
                name = spaces[0].get("name", "")
                self._send_tool_done(tmp_sid, tc_id, "completed",
                                     f"Found existing AgentSpace: {name} ({space_id})")
                print(f"   Auto-selected AgentSpace: {space_id} ({name})", file=sys.stderr)
                return space_id

            if not allow_create:
                self._send_tool_done(tmp_sid, tc_id, "completed",
                                     "No AgentSpace found.")
                self.error(msg_id, -32602,
                           "No AgentSpace found. To create one, either: "
                           "(1) retry session/new with {\"autoCreateSpace\": true}, "
                           "(2) set DEVOPS_AGENT_AUTO_CREATE_SPACE=true, or "
                           "(3) set DEVOPS_AGENT_SPACE_ID to an existing space ID.")
                return ""

            self._send_tool_done(tmp_sid, tc_id, "completed",
                                 "No AgentSpace found — creating one…")

            tc_id2 = str(uuid.uuid4())
            self._send_tool_start(tmp_sid, tc_id2, "create_agent_space",
                                  "Creating new AgentSpace…", kind="write")

            user = config.DEFAULT_USER_ID
            region = config.REGION
            create_resp = call_raw(
                get_cp().create_agent_space,
                name=f"acp-{user}-{region}",
            )
            space_id = create_resp.get("agentSpaceId", "")
            self._send_tool_done(tmp_sid, tc_id2, "completed",
                                 f"Created AgentSpace: {space_id}")
            print(f"   Auto-created AgentSpace: {space_id}", file=sys.stderr)
            return space_id

        except Exception as e:
            logger.exception("Failed to find or create AgentSpace")
            self._send_tool_done(tmp_sid, tc_id, "failed", "Failed to find or create AgentSpace")
            self.error(msg_id, -32603,
                       "Failed to find or create AgentSpace. "
                       "Set DEVOPS_AGENT_SPACE_ID manually or check IAM permissions.")
            return ""

    # ── Protocol handlers ─────────────────────────────────────────────────

    def handle_initialize(self, msg_id: Any, params: dict):

        self.respond(msg_id, {
            "protocolVersion": 1,
            "agentInfo": {
                "name": "AWS DevOps Agent",
                "version": VERSION,
                "description": (
                    "AI agent for AWS operational intelligence. "
                    "Supports parallel investigation (deep async research) and "
                    "chat (fast real-time responses). Use for incident investigation, cost optimization, "
                    "architecture review, topology mapping, and mitigation."
                ),
            },
            "agentCapabilities": {
                "supportsStreaming": True,
                "supportsCancellation": True,
            },
        })

    def handle_session_new(self, msg_id: Any, params: dict):
        self._cleanup_sessions()

        # Per-session AgentSpace: prefer explicit param, fall back to global
        space_id = params.get("agentSpaceId", "") or config.DEFAULT_AGENT_SPACE_ID
        # Per-request opt-in to create a space (never auto-creates by default)
        allow_create = params.get("autoCreateSpace", False) or config.AUTO_CREATE_AGENT_SPACE

        if not space_id:
            result = self._find_or_create_agent_space(msg_id, allow_create=allow_create)
            if not result:
                return
            space_id = result
            config.DEFAULT_AGENT_SPACE_ID = space_id

        if not config.DEFAULT_USER_ID:
            self.error(msg_id, -32602, "DEVOPS_AGENT_USER_ID env var is required")
            return

        session_id = str(uuid.uuid4())
        session = Session(session_id)
        session.agent_space_id = space_id

        tc_id = str(uuid.uuid4())
        self._send_tool_start(session_id, tc_id, "create_chat",
                              "Creating chat session with DevOps Agent…",
                              params={"agentSpaceId": session.agent_space_id})
        try:
            resp = call_raw(
                get_dp().create_chat,
                agentSpaceId=session.agent_space_id,
                userId=config.DEFAULT_USER_ID,
            )
            session.execution_id = resp.get("executionId")
            self._send_tool_done(session_id, tc_id, "completed",
                                 f"Chat session ready (execution: {session.execution_id})")
        except Exception as e:
            logger.exception("Failed to create chat")
            self._send_tool_done(session_id, tc_id, "failed", "Failed to create chat")
            self.error(msg_id, -32603, "Failed to create chat")
            return

        self.sessions[session_id] = session

        self.respond(msg_id, {
            "agentSpaceId": space_id,
            "sessionId": session_id,
            "modes": {
                "availableModes": [
                    {"id": "chat", "name": "Chat",
                     "description": "Fast analysis, optimization, topology, planning — "
                                    "multi-turn conversations with full context"},
                    {"id": "investigate", "name": "Investigate",
                     "description": "Deep incident research — alarms, outages, errors, "
                                    "root cause analysis. Runs async (5-8 min) with "
                                    "real-time journal updates. Chat remains available "
                                    "during investigation."},
                ],
            },
        })

    def handle_session_prompt(self, msg_id: Any, params: dict):
        session_id = params.get("sessionId", "")
        session = self.sessions.get(session_id)
        if not session:
            self.error(msg_id, -32602, "Unknown session")
            return

        prompt_blocks = params.get("content", params.get("prompt", []))
        text = " ".join(
            b.get("text", "") for b in prompt_blocks if b.get("type") == "text"
        ).strip()
        if not text:
            self.error(msg_id, -32602, "Empty prompt")
            return

        session.cancelled = False

        if not session.task_id and self._looks_like_investigation(text):
            self._start_parallel_investigation(session, text)

        self._stream_chat(session, text, msg_id)

    def handle_session_cancel(self, _msg_id: Any, params: dict) -> None:
        session_id = params.get("sessionId", "")
        session = self.sessions.get(session_id)
        if session:
            session.cancelled = True


    # ── Intent detection ──────────────────────────────────────────────────

    # NOTE: Intent detection determines whether to auto-launch a background
    # investigation alongside the chat response.  Be conservative — false
    # positives waste 5-8 min of async compute AND confuse the user.
    # A single keyword like "investigate" in a question that chat can
    # answer in <60 s should NOT trigger create_investigation.  Require
    # either multiple strong signals OR strong keywords WITHOUT any chat
    # keywords pulling the score down.

    INVESTIGATION_KEYWORDS = [
        "investigate", "what's wrong", "root cause", "debug",
        "failing", "outage", "down", "degraded",
        "high latency", "timeout", "5xx", "incident",
        "not working", "anomaly", "crash",
        "hung", "stuck", "unresponsive",
        "severity", "p1", "p2", "urgent",
        "underprovisioned", "under-provisioned",
    ]

    CHAT_KEYWORDS = [
        "check", "health", "status", "issues", "error", "alarm",
        "spike", "unhealthy", "alert", "page", "broken",
        "performance", "cpu", "memory", "disk", "throttle", "throttling", "throttled",
        "optimize", "cost", "analyze", "review", "recommend",
        "topology", "dependency", "architecture", "plan",
        "what if", "should i", "how to", "compare", "best practice",
        "list", "show", "describe", "tell me", "how many",
    ]

    STRONG_INVESTIGATION = [
        "investigate", "root cause", "what's wrong", "debug", "outage",
        "incident", "severity", "p1", "p2", "urgent",
    ]

    @classmethod
    def _looks_like_investigation(cls, text: str) -> bool:
        lower = text.lower()
        def _wb_match(kw: str) -> bool:
            return bool(re.search(rf'\b{re.escape(kw)}\b', lower))
        strong_matches = [kw for kw in cls.STRONG_INVESTIGATION if _wb_match(kw)]
        weak_matches = [kw for kw in cls.INVESTIGATION_KEYWORDS if _wb_match(kw)
                        and kw not in cls.STRONG_INVESTIGATION]
        chat_matches = [kw for kw in cls.CHAT_KEYWORDS if _wb_match(kw)]
        # Strong keywords score 3x, but a single strong keyword is not
        # enough when chat keywords are also present — require at least 2
        # strong matches OR a strong + weak combo to overcome chat gravity.
        inv_score = len(strong_matches) * 3 + len(weak_matches)
        chat_score = sum(1 for _ in chat_matches)
        has_strong = len(strong_matches) > 0
        # Require meaningful investigation signal to overcome chat gravity:
        # - With strong keyword(s): need at least 2 strong OR score > chat
        # - Without strong: investigation score must strictly exceed chat
        if has_strong and chat_score > 0:
            return len(strong_matches) >= 2 or (len(strong_matches) + len(weak_matches)) >= 3
        if has_strong:
            return True
        return inv_score > 0 and inv_score > chat_score

    # ── Parallel investigation + journal polling ──────────────────────────

    def _start_parallel_investigation(self, session: Session, text: str):
        """Start investigation (deep async) AND journal poller in background."""
        title = text[:400]
        tc_id = str(uuid.uuid4())
        self._send_text(session.session_id, "\n")
        self._send_tool_start(
            session.session_id, tc_id, "create_investigation",
            "Starting deep investigation (will run in background)…",
            {"title": title}, kind="write")

        try:
            resp = call_raw(
                get_dp().create_backlog_task,
                agentSpaceId=session.agent_space_id,
                taskType="INVESTIGATION",
                title=title,
                priority="HIGH",
            )
            task = resp.get("task", resp)
            session.task_id = task.get("taskId")
            session.investigation_execution_id = task.get("executionId")
            self._send_tool_done(session.session_id, tc_id, "completed",
                                 f"Investigation started (task: {session.task_id})")
            self._send_text(session.session_id,
                            f"🔍 **Investigation started** — task `{session.task_id}`\n"
                            f"_Deep analysis running in background (5-8 min). "
                            f"I'll stream progress updates. Chat is available now for fast answers._\n\n")
            self._start_journal_poller(session)

        except Exception as e:
            logger.exception("Could not start investigation")
            self._send_tool_done(session.session_id, tc_id, "failed", "Could not start investigation")
            self._send_text(session.session_id,
                            "⚠️ Could not start investigation. Check logs for details.\n\n")

    def _start_journal_poller(self, session: Session):
        """Start a background thread that polls journal records and streams updates."""
        if session.session_id in self._journal_threads:
            return

        def poll_loop():
            execution_id = None
            for _ in range(30):
                if session.cancelled:
                    return
                try:
                    task_resp = call_raw(
                        get_dp().get_backlog_task,
                        agentSpaceId=session.agent_space_id,
                        taskId=session.task_id,
                    )
                    task_data = task_resp.get("task", task_resp)
                    status = task_data.get("status", "")
                    session.investigation_status = status
                    execution_id = task_data.get("executionId")
                    if execution_id:
                        session.investigation_execution_id = execution_id
                        break
                    if status in ("COMPLETED", "FAILED"):
                        break
                except Exception as e:
                    print(f"Journal poll: get_task failed: {e}", file=sys.stderr)
                time.sleep(10)

            if not execution_id:
                self._send_text(session.session_id,
                                "\n📋 _Investigation is queued but hasn't started yet. "
                                "Use chat to ask about progress._\n")
                return

            terminal_states = {"COMPLETED", "FAILED"}
            deadline = time.monotonic() + MAX_POLL_TIME_SECONDS
            while not session.cancelled and time.monotonic() < deadline:
                try:
                    task_resp = call_raw(
                        get_dp().get_backlog_task,
                        agentSpaceId=session.agent_space_id,
                        taskId=session.task_id,
                    )
                    task_data = task_resp.get("task", task_resp)
                    session.investigation_status = task_data.get("status", "")

                    journal_kwargs = {
                        "agentSpaceId": session.agent_space_id,
                        "executionId": execution_id,
                    }
                    if session.last_journal_token:
                        journal_kwargs["nextToken"] = session.last_journal_token

                    journal_resp = call_raw(
                        get_dp().list_journal_records,
                        **journal_kwargs,
                    )

                    records = journal_resp.get("journalRecords", [])
                    session.last_journal_token = journal_resp.get("nextToken")

                    for record in records:
                        record_id = record.get("recordId", "")
                        if record_id in session.journal_records_seen:
                            continue
                        session.journal_records_seen.add(record_id)

                        content = record.get("content", "")
                        record_type = record.get("recordType", "")
                        if content:
                            emoji = {
                                "PLANNING": "📋",
                                "ANALYSIS": "🔬",
                                "FINDING": "🎯",
                                "ACTION": "🔧",
                                "SUMMARY": "📊",
                            }.get(record_type, "📝")
                            self._send_text(session.session_id,
                                            f"\n{emoji} **Investigation update** "
                                            f"({record_type}):\n{content[:1000]}\n")

                    if session.investigation_status in terminal_states:
                        status_emoji = "✅" if session.investigation_status == "COMPLETED" else "❌"
                        self._send_text(session.session_id,
                                        f"\n{status_emoji} **Investigation "
                                        f"{session.investigation_status.lower()}** "
                                        f"— task `{session.task_id}`\n"
                                        f"_Ask me to summarize findings or show recommendations._\n")
                        break

                except Exception as e:
                    logger.exception("Journal poll error")

                time.sleep(JOURNAL_POLL_INTERVAL)

            if not session.cancelled and time.monotonic() >= deadline:
                logger.warning("Journal polling timed out after %d seconds for task %s",
                               MAX_POLL_TIME_SECONDS, session.task_id)
                self._send_text(session.session_id,
                                "\n⏰ **Investigation polling timed out** "                                "— the investigation may still be running. "                                "Use chat to check status.\n")
            self._journal_threads.pop(session.session_id, None)

        thread = threading.Thread(target=poll_loop, daemon=True,
                                  name=f"journal-{session.session_id[:8]}")
        thread.start()
        self._journal_threads[session.session_id] = thread

    # ── Chat streaming ────────────────────────────────────────────────────

    def _stream_chat(self, session: Session, text: str, msg_id: Any):
        """Stream a chat message to the DevOps Agent and relay events to the client.

        Uses iter_stream_events from core for text deduplication, and handles
        function_call and summary events for progress display.
        """
        collected: list[str] = []
        tc_id = str(uuid.uuid4())
        self._send_tool_start(
            session.session_id, tc_id, "send_message",
            "Talking to DevOps Agent…",
            params={"message": text[:200]}, kind="read")

        try:
            resp = get_dp().send_message(
                agentSpaceId=session.agent_space_id,
                executionId=session.execution_id,
                content=text,
                userId=config.DEFAULT_USER_ID,
            )
            resp.pop("ResponseMetadata", None)

            self._send_tool_done(session.session_id, tc_id, "completed")

            for event_type, deduped_text, payload in iter_stream_events(
                resp.get("events", [])
            ):
                if session.cancelled:
                    self._send_text(session.session_id, "\n\n_Cancelled._\n")
                    break

                # Text (already deduplicated by iter_stream_events)
                if deduped_text:
                    collected.append(deduped_text)
                    self._send_text(session.session_id, deduped_text)

                elif event_type == "summary":
                    summary = payload.get("content", "")
                    if summary:
                        fc_id = str(uuid.uuid4())
                        self._send_tool_start(
                            session.session_id, fc_id, "aws_action",
                            f"🔧 {summary}", kind="read")
                        self._send_tool_done(session.session_id, fc_id, "completed")

            full_text = "".join(collected)
            if not full_text and not session.cancelled:
                if session.task_id and session.investigation_status:
                    self._send_text(session.session_id,
                                    f"_Investigation is {session.investigation_status.lower()}. "
                                    f"Journal updates will appear as findings emerge._\n")
                else:
                    self._send_text(session.session_id,
                                    "_Agent is processing — results will appear shortly._\n")

        except Exception as e:
            logger.exception("Stream error during chat")
            self._send_tool_done(session.session_id, tc_id, "failed", "Stream error")
            self._send_text(session.session_id,
                            "\n⚠️ Stream error. Check logs for details.\n")

        if msg_id is not None:
            self._send_turn_end(session.session_id)
            stop = "cancelled" if session.cancelled else "end_turn"
            self.respond(msg_id, {"stopReason": stop})

    # ── Main loop ─────────────────────────────────────────────────────────

    @property
    def _handlers(self) -> dict[str, Any]:
        return {
            "initialize": self.handle_initialize,
            "session/new": self.handle_session_new,
            "session/prompt": self.handle_session_prompt,
            "session/cancel": self.handle_session_cancel,
            "session/set_model": lambda mid, p: self.respond(mid, {}),
        }

    def _validate_config(self):
        """Print startup config to stderr for diagnostics."""
        space = config.DEFAULT_AGENT_SPACE_ID
        if not space:
            action = ("will auto-discover/create"
                      if config.AUTO_CREATE_AGENT_SPACE
                      else "will auto-discover, or pass autoCreateSpace in session/new")
            print(f"⚠️  DEVOPS_AGENT_SPACE_ID not set — {action}", file=sys.stderr)
        print(f"   Auto-create: {config.AUTO_CREATE_AGENT_SPACE}", file=sys.stderr)
        print(f"✅ AWS DevOps Agent ACP Server v{VERSION}", file=sys.stderr)
        print(f"   Region:      {config.REGION}", file=sys.stderr)
        print(f"   Agent Space: {space[:12] + '…' if space else '(not set)'}", file=sys.stderr)
        print(f"   User ID:     {config.DEFAULT_USER_ID}", file=sys.stderr)
        print(f"   Journal poll: {JOURNAL_POLL_INTERVAL}s", file=sys.stderr)
        print("", file=sys.stderr)

    def handle_message(self, msg: dict):
        """Handle a single pre-parsed JSON-RPC message (for auto-detect mode)."""
        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params", {})
        handler = self._handlers.get(method)
        if handler:
            handler(msg_id, params)
        elif msg_id:
            self.error(msg_id, -32601, f"Unknown method: {method}")

    def run(self):
        self._validate_config()

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            method = msg.get("method")
            msg_id = msg.get("id")
            params = msg.get("params", {})

            # Ignore unsolicited JSON-RPC responses (server sends no requests).
            if "result" in msg or "error" in msg:
                continue

            handler = self._handlers.get(method)
            if handler:
                handler(msg_id, params)
            elif msg_id:
                self.error(msg_id, -32601, f"Unknown method: {method}")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
def main():
    ACPServer().run()


if __name__ == "__main__":
    main()
