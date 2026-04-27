# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""AWS DevOps Agent — unified MCP + ACP server with ACP client SDK."""

__version__ = "1.0.0"

from aws_devops_agent.acp_client import ACPClient, ACPError, ACPEvent

__all__ = ["ACPClient", "ACPError", "ACPEvent", "__version__"]
