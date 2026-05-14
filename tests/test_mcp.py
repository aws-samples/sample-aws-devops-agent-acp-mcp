# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unit tests for aws_devops_agent.mcp_server."""
import importlib

import pytest

pytestmark = pytest.mark.skipif(
    not importlib.util.find_spec("mcp"),
    reason="mcp package not installed (optional dependency)",
)


class TestMCPToolCount:
    def test_has_20_tools(self):
        from aws_devops_agent.mcp_server import mcp
        tools = mcp._tool_manager._tools
        assert len(tools) == 20, f"Expected 20 tools, got {len(tools)}: {list(tools.keys())}"

    def test_expected_tool_names(self):
        from aws_devops_agent.mcp_server import mcp
        tools = set(mcp._tool_manager._tools.keys())
        expected = {
            "list_services", "get_service",
            "list_agent_spaces", "get_agent_space", "create_agent_space",
            "list_associations",
            "create_investigation", "get_task", "list_tasks",
            "list_journal_records", "list_executions",
            "list_recommendations", "get_recommendation", "update_recommendation",
            "create_mitigation_plan",
            "list_goals", "start_evaluation",
            "create_chat", "list_chats", "send_message",
        }
        assert tools == expected
