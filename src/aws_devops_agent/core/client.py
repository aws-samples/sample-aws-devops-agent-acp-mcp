# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Boto3 client initialization and agent-space / user-id resolution."""
import os
import sys
from typing import Optional

import logging
import threading

import boto3

# ---------------------------------------------------------------------------
# Configuration (override via environment variables)
# ---------------------------------------------------------------------------
REGION = os.environ.get("AWS_REGION", os.environ.get("DEVOPS_AGENT_REGION", "us-east-1"))
AUTO_CREATE_AGENT_SPACE = (
    os.environ.get("DEVOPS_AGENT_AUTO_CREATE_SPACE", "false").lower() == "true"
)
DEFAULT_AGENT_SPACE_ID = os.environ.get("DEVOPS_AGENT_SPACE_ID", "")
DEFAULT_USER_ID = os.environ.get("DEVOPS_AGENT_USER_ID", "")

# ---------------------------------------------------------------------------
# Boto3 client (lazy-initialized singleton)
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

_client = None
_client_lock = threading.Lock()


def get_client():
    """Return the unified DevOps Agent boto3 client (singleton).

    The DevOps Agent service historically had a control-plane / data-plane
    split. The boto3 client is now unified, but API method names still
    carry the legacy distinction:

        Control-plane style:  list_agent_spaces, create_agent_space, ...
        Data-plane style:     create_backlog_task, get_backlog_task,
                              send_message, list_journal_records, ...

    In particular, task operations use ``get_backlog_task`` (NOT
    ``get_task``). The ``get_cp()`` and ``get_dp()`` aliases both return
    this same client — they exist only for readability so callers can
    signal intent (e.g. ``get_dp().get_backlog_task(...)``).
    """
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:  # double-checked locking
                _client = boto3.client("devops-agent", region_name=REGION)
    return _client


# Backwards-compatible aliases — both CP and DP are now unified.  Use
# get_dp() for data-plane calls (task, chat, journal, streaming) and
# get_cp() for control-plane calls (agent spaces, associations, goals).
get_cp = get_client
get_dp = get_client


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------
def resolve_agent_space(agent_space_id: Optional[str] = None) -> str:
    """Resolve agent_space_id: param -> env -> auto-discover -> auto-create.

    Always attempts to discover an existing AgentSpace (safe, read-only).
    Only creates a new AgentSpace when DEVOPS_AGENT_AUTO_CREATE_SPACE=true
    (opt-in, defaults to false) to avoid silently creating resources in
    unintended AWS accounts.
    """
    global DEFAULT_AGENT_SPACE_ID
    resolved = agent_space_id or DEFAULT_AGENT_SPACE_ID
    if resolved:
        return resolved

    # Always safe: discover existing AgentSpaces (read-only API call)
    try:
        resp = get_client().list_agent_spaces(maxResults=5)
        resp.pop("ResponseMetadata", None)
        spaces = resp.get("agentSpaces", [])
        if spaces:
            DEFAULT_AGENT_SPACE_ID = spaces[0]["agentSpaceId"]
            return DEFAULT_AGENT_SPACE_ID
    except Exception as e:
        logger.exception("Auto-discover AgentSpace failed")

    # Only create if explicitly opted in — avoids creating resources in wrong accounts
    if AUTO_CREATE_AGENT_SPACE:
        try:
            user = DEFAULT_USER_ID or "default"
            create_resp = get_client().create_agent_space(name=f"devops-{user}-{REGION}")
            create_resp.pop("ResponseMetadata", None)
            DEFAULT_AGENT_SPACE_ID = create_resp.get("agentSpaceId", "")
            return DEFAULT_AGENT_SPACE_ID
        except Exception as e:
            logger.exception("Auto-create AgentSpace failed")

    raise ValueError(
        "agent_space_id is required. Pass it explicitly, set the "
        "DEVOPS_AGENT_SPACE_ID environment variable, or set "
        "DEVOPS_AGENT_AUTO_CREATE_SPACE=true to auto-discover."
    )


def resolve_user_id(user_id: Optional[str] = None) -> str:
    """Resolve user_id: param -> env."""
    resolved = user_id or DEFAULT_USER_ID
    if not resolved:
        raise ValueError(
            "user_id is required. Pass it explicitly or set the "
            "DEVOPS_AGENT_USER_ID environment variable."
        )
    return resolved
