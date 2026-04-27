# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""CLI entry point — run as MCP server, ACP server, auto-detect, or show help."""
import argparse
import io
import json
import sys


class _ReplayStdin(io.TextIOBase):
    """Wraps stdin to replay a buffered first line, then delegate to real stdin."""

    def __init__(self, first_line: str, original: io.TextIOBase):
        self._buffer = first_line
        self._original = original

    def readline(self, limit: int = -1) -> str:
        if self._buffer:
            line = self._buffer
            self._buffer = ""
            return line
        return self._original.readline(limit)

    def read(self, size: int = -1) -> str:
        if self._buffer:
            if size < 0:
                data = self._buffer + self._original.read()
                self._buffer = ""
                return data
            chunk = self._buffer[:size]
            self._buffer = self._buffer[size:]
            return chunk
        return self._original.read(size)

    @property
    def closed(self) -> bool:
        return self._original.closed

    def readable(self) -> bool:
        return True

    def fileno(self) -> int:
        return self._original.fileno()


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
    """Read first message from stdin, detect protocol, dispatch."""
    first_line = sys.stdin.readline()
    if not first_line:
        print("No input received on stdin.", file=sys.stderr)
        sys.exit(1)

    protocol = _detect_protocol(first_line)

    if protocol == "acp":
        from aws_devops_agent.acp_server import ACPServer
        server = ACPServer()
        msg = json.loads(first_line.strip())
        server._handle_message(msg)
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
        # Replay the consumed first line so MCP server sees the full handshake
        sys.stdin = _ReplayStdin(first_line, sys.stdin)
        run_mcp()


def _get_version() -> str:
    try:
        from aws_devops_agent import __version__
        return __version__
    except ImportError:
        return "unknown"


if __name__ == "__main__":
    main()
