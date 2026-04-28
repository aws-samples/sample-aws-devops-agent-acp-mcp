# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""ACP client SDK for the AWS DevOps Agent.

Wraps the ACP server in a subprocess and provides a streaming Python API.
Use this when your IDE or agent does not have a native ACP client (e.g. Kiro CLI).
IDEs with native ACP support (Zed, JetBrains) connect to the ACP server directly.

Quick start::

    from aws_devops_agent.acp_client import ACPClient

    # One-shot
    response = ACPClient.quick("What alarms are firing?")
    print(response)

    # Streaming
    with ACPClient() as client:
        for event in client.prompt("Investigate ECS 503 errors"):
            if event.type == "text":
                print(event.text, end="", flush=True)
"""


import collections
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


# Cross-block dedup constants (shared with core.streaming)
_DEDUP_WINDOW = 80
_MIN_SENT_BEFORE_CHECK = 100

# Thinking-event analysis: keyword sets → contextual status message
_THINKING_PATTERNS: List[tuple] = [
    ({"alarm", "alarms", "firing", "cloudwatch"}, "Querying CloudWatch alarms across your accounts"),
    ({"ec2", "instance", "instances", "server", "servers"}, "Scanning EC2 instances"),
    ({"s3", "bucket", "buckets", "storage"}, "Listing S3 buckets"),
    ({"cost", "costs", "spending", "bill", "billing"}, "Analyzing cost and usage data"),
    ({"lambda", "function", "functions", "invoke"}, "Querying Lambda functions"),
    ({"ecs", "container", "containers", "fargate", "task", "tasks"}, "Checking ECS services"),
    ({"rds", "database", "databases", "aurora", "mysql", "postgres"}, "Querying RDS databases"),
    ({"iam", "role", "roles", "policy", "policies", "permission"}, "Scanning IAM configuration"),
    ({"log", "logs", "cloudtrail", "trail"}, "Searching logs"),
    ({"vpc", "network", "subnet", "security", "sg"}, "Analyzing network configuration"),
    ({"deploy", "deployment", "pipeline", "codepipeline"}, "Checking deployment status"),
    ({"investigate", "debug", "troubleshoot", "diagnose"}, "Investigating the issue"),
    ({"503", "500", "error", "errors", "failure", "failures"}, "Analyzing error patterns"),
]
_THINKING_FOLLOWUP_DELAY = 20.0  # Seconds after first thinking → second message


class ACPEvent:
    """A single event from a streaming ACP prompt response."""

    __slots__ = ("type", "text", "name", "data", "arguments", "call_id")

    def __init__(self, type: str, text: str = "", name: str = "", data: Any = None,
                 arguments: Any = None, call_id: str = ""):
        self.type = type
        self.text = text
        self.name = name
        self.data = data
        self.arguments = arguments
        self.call_id = call_id

    def __repr__(self) -> str:
        parts = [f"type={self.type!r}"]
        if self.text:
            parts.append(f"text={self.text!r}")
        if self.name:
            parts.append(f"name={self.name!r}")
        if self.call_id:
            parts.append(f"call_id={self.call_id!r}")
        return f"ACPEvent({', '.join(parts)})"


class ACPError(Exception):
    """Error from the ACP protocol layer."""

    def __init__(self, message: str, code: int = -1):
        super().__init__(message)
        self.code = code


class ACPClient:
    """ACP client that manages a server subprocess and provides a streaming API.

    The client auto-discovers the ACP server binary, installs service models
    if needed, and handles the full ACP protocol lifecycle.
    """

    # Where to look for the ACP server binary


    _SERVER_BINARY = "aws-devops-agent-acp"
    _SERVER_SEARCH_PATHS = [
        # Common virtual-environment layouts
        lambda: str(Path.home() / "aws-devops-agent" / ".venv" / "bin" / "aws-devops-agent-acp"),
        lambda: str(Path.home() / ".local" / "bin" / "aws-devops-agent-acp"),
    ]

    def __init__(
        self,
        server_path: Optional[str] = None,
        region: Optional[str] = None,
        space_id: Optional[str] = None,
        user_id: Optional[str] = None,
        auto_create_space: bool = False,
        env: Optional[Dict[str, str]] = None,
        verbose: bool = False,
    ):
        self._server_path = server_path
        self._region = region
        self._space_id = space_id
        self._user_id = user_id
        self._auto_create_space = auto_create_space
        self._extra_env = env or {}
        self._verbose = verbose
        self._stderr_lines: collections.deque = collections.deque(maxlen=5000)

        self._proc: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._session_id: Optional[str] = None

        self._lock = threading.Lock()
        self._msg_id = 0
        self._responses: Dict[int, Any] = {}
        self._errors: Dict[int, Dict] = {}
        self._response_events: Dict[int, threading.Event] = {}
        self._notifications: List[Dict] = []
        self._notification_lock = threading.Lock()
        self._notification_event = threading.Event()

        self._initialized = False
        self._cancel_requested = False

    # -- Context manager ------------------------------------------------------

    def __enter__(self) -> "ACPClient":
        self.connect()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.shutdown()

    # -- Server discovery -----------------------------------------------------

    @staticmethod
    def find_server() -> str:
        """Find the ACP server binary."""
        import shutil
        found = shutil.which(ACPClient._SERVER_BINARY)
        if found:
            return found

        for path_fn in ACPClient._SERVER_SEARCH_PATHS:
            try:
                p = path_fn()
                if p and os.path.isfile(p) and os.access(p, os.X_OK):
                    return p
            except Exception:
                continue

        # Also check for server.py in the package directory
        pkg_dir = Path(__file__).parent
        server_py = pkg_dir / "acp_server.py"
        if server_py.is_file():
            return f"{sys.executable} {server_py}"

        raise FileNotFoundError(
            f"Cannot find '{ACPClient._SERVER_BINARY}'. "
            "Install with: pip install aws-devops-agent-acp"
        )

    # -- Connection lifecycle -------------------------------------------------

    def connect(self) -> None:
        """Spawn the ACP server and complete the protocol handshake."""
        if self._initialized:
            return

        server = self._server_path or self.find_server()
        if self._verbose:
            print(f"Starting ACP server: {server}", file=sys.stderr)

        # Build environment
        env = os.environ.copy()
        if self._region:
            env["DEVOPS_AGENT_REGION"] = self._region
        if self._space_id:
            env["DEVOPS_AGENT_SPACE_ID"] = self._space_id
        if self._user_id:
            env["DEVOPS_AGENT_USER_ID"] = self._user_id
        env.update(self._extra_env)

        cmd = shlex.split(server)

        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            bufsize=1,
        )

        # Start background readers
        self._reader_thread = threading.Thread(
            target=self._read_loop, daemon=True, name="acp-reader")
        self._reader_thread.start()

        self._stderr_thread = threading.Thread(
            target=self._stderr_reader, daemon=True, name="acp-stderr")
        self._stderr_thread.start()

        
        # ACP initialize handshake
        init_result = self._request("initialize", {
            "clientInfo": {"name": "aws-devops-agent-client", "version": "1.0.0"},
            "clientCapabilities": {},
        })

        if self._verbose:
            agent = init_result.get("agentInfo", {}).get("name", "unknown")
            print(f"Connected to: {agent}", file=sys.stderr)

        # Create session
        session_params: Dict[str, Any] = {}
        if self._auto_create_space:
            session_params["autoCreateSpace"] = True
        session_result = self._request("session/new", session_params)
        self._session_id = session_result.get("sessionId")
        if not self._space_id:
            self._space_id = session_result.get("agentSpaceId")
        self._initialized = True

        if self._verbose:
            print(f"Session: {self._session_id}", file=sys.stderr)

    def shutdown(self) -> None:
        """Stop the ACP server subprocess."""
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    self._proc.kill()
                except OSError:
                    pass
        self._proc = None
        self._initialized = False


    # -- Streaming prompt API -------------------------------------------------

    def prompt(self, text: str, timeout: float = 600,
               thinking_threshold: float = 5.0) -> Iterator[ACPEvent]:
        """Send a prompt and yield streaming events with text batching.

        Consecutive text deltas that have already arrived are coalesced into a
        single ``ACPEvent`` so consumers see readable chunks instead of
        word-at-a-time fragments.  This adds **zero latency** — it only
        combines events that are already sitting in the notification queue
        when the consumer reads.

        Args:
            text: The prompt to send.
            timeout: Maximum wait time in seconds.
            thinking_threshold: Seconds of silence before emitting a
                synthetic ``thinking`` event.  Set to ``0`` to disable.

        Yields ACPEvent objects with types: text, thinking, tool_call,
        tool_call_update, approval, turn_end.
        """
        if not self._initialized:
            self.connect()

        self._cancel_requested = False

        self._send({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "session/prompt",
            "params": {
                "sessionId": self._session_id,
                "content": [{"type": "text", "text": text}],
            },
        })

        deadline = time.monotonic() + timeout
        turn_ended = False

        turn_ended = yield from self._stream_prompt(deadline, text, thinking_threshold)

        if not turn_ended and not self._cancel_requested and time.monotonic() >= deadline:
            raise ACPError(f"Prompt timed out after {timeout}s")

    @staticmethod
    def _collapse_repeats(chunk: str) -> str:
        """Collapse identical consecutive tokens in a chunk.

        E.g. 'DoneDoneDoneDone' → 'Done', 'Hello Hello Hello ' → 'Hello '.
        Only collapses when the entire chunk is one token repeated.
        """
        if len(chunk) < 2:
            return chunk
        for token_len in range(1, len(chunk) // 2 + 1):
            token = chunk[:token_len]
            if token * (len(chunk) // token_len) == chunk:
                return token
        return chunk

    def _flush_text_buf(self, text_buf: List[str], seen_text: str) -> Iterator[ACPEvent]:
        """Flush coalesced text buffer, applying client-side dedup."""
        if not text_buf:
            return
        chunk = "".join(text_buf)
        text_buf.clear()
        chunk = self._collapse_repeats(chunk)
        if (len(chunk) > _DEDUP_WINDOW
                and len(seen_text) > _MIN_SENT_BEFORE_CHECK
                and chunk.strip()[:_DEDUP_WINDOW] in seen_text):
            return  # Skip large-block duplicate
        stripped = chunk.strip()
        if (stripped and len(stripped) < 20
                and seen_text.rstrip().endswith(stripped)):
            return  # Skip short consecutive duplicate (e.g. Done Done)
        yield ACPEvent("text", chunk)

    def _stream_prompt(
        self, deadline: float,
        prompt_text: str = "", thinking_threshold: float = 5.0,
    ) -> Iterator[ACPEvent]:
        """Inner generator that processes notifications from the server.

        Emits synthetic ``thinking`` events after *thinking_threshold*
        seconds of silence so consumers can show progress indicators
        while the backend is processing (e.g. cross-account API calls).
        """
        turn_ended = False
        seen_text = ""
        last_event_time = time.monotonic()
        thinking_stage = 0  # 0=not emitted, 1=first, 2=followup

        while not turn_ended and not self._cancel_requested:
            self._notification_event.wait(timeout=2)
            self._notification_event.clear()

            # Brief pause so more deltas queue up — 50ms is imperceptible
            # to users but lets dozens of word-fragments coalesce.
            time.sleep(0.05)
            if self._proc and self._proc.poll() is not None:
                break

            # --- Thinking events: fill silence with contextual analysis ---
            if thinking_threshold > 0:
                silence = time.monotonic() - last_event_time
                if thinking_stage == 0 and silence >= thinking_threshold:
                    msg = self._generate_thinking_text(prompt_text)
                    yield ACPEvent("thinking", msg)
                    thinking_stage = 1
                elif (thinking_stage == 1
                      and silence >= thinking_threshold + _THINKING_FOLLOWUP_DELAY):
                    yield ACPEvent(
                        "thinking", "⏳ Still working — this may involve multiple API calls")
                    thinking_stage = 2

            with self._notification_lock:
                batch = list(self._notifications)
                self._notifications.clear()

            # Coalesce consecutive text events across the entire batch
            # of notifications, not just within a single session/update.
            text_buf: List[str] = []

            for note in batch:
                params = note.get("params", {})
                method = note.get("method", "")

                if method == "session/update":
                    events = self._parse_session_update(params)
                    for ev in events:
                        if ev.type == "text" and ev.text:
                            text_buf.append(ev.text)
                            last_event_time = time.monotonic()
                        else:
                            if text_buf:
                                chunk = "".join(text_buf)
                                text_buf = []
                                for flushed in self._flush_text_buf([chunk], seen_text):
                                    seen_text += chunk
                                    yield flushed
                            yield ev
                            last_event_time = time.monotonic()
                        if ev.type == "turn_end":
                            turn_ended = True


            # Flush any remaining text from this batch
            if text_buf:
                chunk = "".join(text_buf)
                text_buf = []
                for flushed in self._flush_text_buf([chunk], seen_text):
                    seen_text += flushed.text
                    yield flushed
                    last_event_time = time.monotonic()

            if time.monotonic() >= deadline:
                with self._notification_lock:
                    self._notifications.clear()
                break

        return turn_ended

    def prompt_sync(self, text: str, timeout: float = 600) -> str:
        """Send a prompt and return the full text response."""
        parts = []
        for event in self.prompt(text, timeout=timeout):
            if event.type == "text":
                parts.append(event.text)
        return "".join(parts)

    def cancel(self) -> None:
        """Cancel the active prompt."""
        self._cancel_requested = True
        self._notification_event.set()
        if self._initialized and self._session_id:
            try:
                self._send({
                    "jsonrpc": "2.0",
                    "id": self._next_id(),
                    "method": "session/cancel",
                    "params": {"sessionId": self._session_id},
                })
            except (ACPError, OSError):
                pass  # Best-effort cancel

    @staticmethod
    def quick(prompt_text: str, **kwargs: Any) -> str:
        """One-shot convenience: connect, prompt, shutdown, return text."""
        client = ACPClient(**kwargs)
        try:
            client.connect()
            return client.prompt_sync(prompt_text)
        finally:
            client.shutdown()

    # -- JSON-RPC transport ---------------------------------------------------

    def _next_id(self) -> int:
        with self._lock:
            self._msg_id += 1
            return self._msg_id

    def _send(self, msg: Dict) -> None:
        """Send a JSON-RPC message to the server."""
        if not self._proc or self._proc.poll() is not None:
            raise ACPError("Server process is not running")
        line = json.dumps(msg) + "\n"
        try:
            self._proc.stdin.write(line)
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise ACPError("Failed to write to server") from e

    def _request(self, method: str, params: Dict, timeout: float = 60) -> Dict:
        """Send a JSON-RPC request and wait for the response."""
        msg_id = self._next_id()
        event = threading.Event()
        self._response_events[msg_id] = event

        self._send({
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params,
        })

        if not event.wait(timeout=timeout):
            raise ACPError(f"Timeout waiting for response to '{method}' (id={msg_id})")

        if msg_id in self._errors:
            err = self._errors.pop(msg_id)
            raise ACPError(err.get("message", "Unknown error"), err.get("code", -1))

        return self._responses.pop(msg_id, {})

    def _read_loop(self) -> None:
        """Background thread: read JSON-RPC messages from server stdout."""
        try:
            for line in self._proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_id = msg.get("id")

                if "method" in msg and msg_id is None:
                    # Notification
                    with self._notification_lock:
                        self._notifications.append(msg)
                    self._notification_event.set()

                elif "method" in msg and msg_id is not None:
                    # Request from server — no handlers registered,
                    # reply with JSON-RPC method-not-found error.
                    error_resp = {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {"code": -32601, "message": "Method not found"},
                    }
                    self._send(error_resp)

                elif msg_id is not None:
                    if "error" in msg:
                        self._errors[msg_id] = msg["error"]
                    elif "result" in msg:
                        self._responses[msg_id] = msg["result"]
                    event = self._response_events.pop(msg_id, None)
                    if event:
                        event.set()
        except (OSError, ValueError, ACPError):
            pass  # Server process closed stdout or write failed


    # -- Event parsing --------------------------------------------------------

    @staticmethod
    def _generate_thinking_text(prompt_text: str) -> str:
        """Generate a contextual thinking message based on prompt keywords."""
        words = set(prompt_text.lower().split())
        for keywords, message in _THINKING_PATTERNS:
            if words & keywords:
                return f"⏳ {message}..."
        return "⏳ Agent is processing your request..."

    def _parse_session_update(self, params: Dict) -> List[ACPEvent]:
        """Convert a session/update notification into ACPEvent objects."""
        events: List[ACPEvent] = []
        update = params.get("update", {})
        update_type = update.get("sessionUpdate", "")
        content = update.get("content", {})

        if update_type == "agent_message_chunk":
            text = content.get("text", "") if isinstance(content, dict) else str(content)
            if text:
                events.append(ACPEvent(type="text", text=text))

        elif update_type == "tool_call":
            name = content.get("name", "") if isinstance(content, dict) else ""
            if not name:
                name = update.get("name", "")
            events.append(ACPEvent(type="tool_call", name=name, data=content))

        elif update_type == "tool_call_update":
            events.append(ACPEvent(type="tool_call_update", data=content))

        elif update_type == "tool_call_done":
            events.append(ACPEvent(type="tool_call_update", data=content))

        elif update_type == "turn_end":
            events.append(ACPEvent(type="turn_end"))

        elif update_type == "approval":
            events.append(ACPEvent(type="approval", data=content))

        elif update_type:
            # Surface unknown event types instead of silently dropping them
            events.append(ACPEvent(type=update_type, data=content))

        return events

    # -- Stderr capture -------------------------------------------------------

    def _stderr_reader(self) -> None:
        """Background thread: capture server stderr for diagnostics."""
        try:
            for line in self._proc.stderr:
                line = line.rstrip("\n")
                self._stderr_lines.append(line)
                if self._verbose:
                    print(f"[server] {line}", file=sys.stderr)
        except (OSError, ValueError):
            pass  # Server process closed stderr
