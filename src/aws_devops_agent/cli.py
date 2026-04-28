# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""CLI entry point — run as MCP server, ACP server, auto-detect, or show help."""
import argparse
import json
import os
import sys


class _ReplayBuffer:
    """Binary buffer that replays consumed bytes, then reads from the original fd.

    FastMCP reads from sys.stdin.buffer (binary mode).  The auto-detect
    path must peek at the first line without draining the text-mode
    wrapper's internal buffer, so we read raw bytes with os.read() and
    replay them here.
    """

    def __init__(self, first_bytes: bytes, original_fd: int):
        self._buffer = first_bytes
        self._fd = original_fd

    def read(self, size: int = -1) -> bytes:
        if self._buffer:
            if size < 0:
                buf, self._buffer = self._buffer, b""
                return buf + self._read_all()
            chunk = self._buffer[:size]
            self._buffer = self._buffer[size:]
            return chunk
        return os.read(self._fd, size) if size > 0 else b""

    def read1(self, size: int = -1) -> bytes:
        return self.read(size)

    def readline(self) -> bytes:
        if self._buffer:
            idx = self._buffer.find(b"\n")
            if idx >= 0:
                line = self._buffer[:idx + 1]
                self._buffer = self._buffer[idx + 1:]
                return line
            buf, self._buffer = self._buffer, b""
            rest = b""
            while True:
                ch = os.read(self._fd, 1)
                if not ch or ch == b"\n":
                    return buf + rest + ch
                rest += ch
        line = b""
        while True:
            ch = os.read(self._fd, 1)
            if not ch or ch == b"\n":
                return line + ch
            line += ch

    def readinto(self, b):
        data = self.read(len(b))
        n = len(data)
        b[:n] = data
        return n

    def _read_all(self) -> bytes:
        chunks = []
        while True:
            try:
                chunk = os.read(self._fd, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
            except OSError:
                break
        return b"".join(chunks)

    @property
    def closed(self) -> bool:
        return False

    def readable(self) -> bool:
        return True

    def fileno(self) -> int:
        return self._fd


def _detect_protocol(first_line: str) -> str:
    """Detect ACP vs MCP from the first JSON-RPC message.
    ACP initialize has 'clientCapabilities' in params.
    MCP initialize has 'protocolVersion' in params.
    """
    try:
        msg = json.loads(first_line)
        params = msg.get("params", {})
        if "clientCapabilities" in params:
            return "acp"
        if "protocolVersion" in params or "capabilities" in params:
            return "mcp"
    except (json.JSONDecodeError, AttributeError):
        pass
    return "mcp"  # default to MCP if unrecognizable


def main():
    parser = argparse.ArgumentParser(
        prog="aws-devops-agent",
        description="AWS DevOps Agent — AI-powered operational intelligence for AWS.",
    )
    sub = parser.add_subparsers(dest="mode", help="Protocol mode")
    sub.add_parser("mcp", help="Run MCP server (for Claude Code, Cursor, Windsurf)")
    sub.add_parser("acp", help="Run ACP server (for Zed, JetBrains, Kiro)")
    sub.add_parser("auto", help="Auto-detect protocol from first message (default when piped)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {_get_version()}")
    args = parser.parse_args()
    if args.mode == "mcp":
        _run_mcp()
    elif args.mode == "acp":
        _run_acp()
    elif args.mode == "auto":
        _run_auto()
    else:
        # No subcommand: if stdin is a pipe, try auto-detect; otherwise show help
        if not sys.stdin.isatty():
            _run_auto()
        else:
            parser.print_help()
            print(
                "\nExamples:\n"
                "  aws-devops-agent mcp     # MCP server for Claude Code, Cursor\n"
                "  aws-devops-agent acp     # ACP server for Zed, JetBrains, Kiro\n"
                "  aws-devops-agent auto    # Auto-detect protocol\n",
                file=sys.stderr,
            )
            sys.exit(1)


def _run_mcp():
    try:
        from aws_devops_agent.mcp_server import main as run_mcp
    except ImportError:
        print(
            "MCP dependencies not installed. Run:\n"
            "  pip install 'aws-devops-agent-acp[mcp]'",
            file=sys.stderr,
        )
        sys.exit(1)
    run_mcp()


def _run_acp():
    from aws_devops_agent.acp_server import main as run_acp
    run_acp()


def _run_auto():
    """Read first message from stdin, detect protocol, dispatch.

    Uses os.read() on the raw file descriptor so we never drain Python's
    text-mode stdin buffer.  For the MCP path the consumed bytes are
    replayed via a binary buffer attached to sys.stdin.buffer, which is
    where FastMCP's stdio_server reads from.
    """
    raw_bytes = b""
    while True:
        chunk = os.read(0, 1)
        if not chunk:
            break
        raw_bytes += chunk
        if chunk == b"\n":
            break
    if not raw_bytes:
        print("No input received on stdin.", file=sys.stderr)
        sys.exit(1)
    first_line = raw_bytes.decode("utf-8", errors="replace")
    protocol = _detect_protocol(first_line)
    if protocol == "acp":
        from aws_devops_agent.acp_server import ACPServer
        server = ACPServer()
        msg = json.loads(first_line.strip())
        server.handle_message(msg)
        server.run()
    else:
        try:
            from aws_devops_agent.mcp_server import main as run_mcp
        except ImportError:
            print(
                "MCP dependencies not installed. Run:\n"
                "  pip install 'aws-devops-agent-acp[mcp]'",
                file=sys.stderr,
            )
            sys.exit(1)
        # Replay consumed bytes via binary buffer so FastMCP's
        # stdio_server (which reads sys.stdin.buffer) sees the full
        # initialize handshake.
        sys.stdin.buffer = _ReplayBuffer(raw_bytes, 0)
        run_mcp()


def _get_version() -> str:
    try:
        from aws_devops_agent import __version__
        return __version__
    except ImportError:
        return "unknown"


if __name__ == "__main__":
    main()
