# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Shared core — boto3 client, config, streaming, utilities."""
from aws_devops_agent.core.client import (
    get_client,
    get_cp,
    get_dp,
    resolve_agent_space,
    resolve_user_id,
)
from aws_devops_agent.core.streaming import iter_stream_events
from aws_devops_agent.core.util import call_api, call_raw, epoch_millis_to_iso, serialize

__all__ = [
    "get_client",
    "get_cp",
    "get_dp",
    "resolve_agent_space",
    "resolve_user_id",
    "iter_stream_events",
    "call_api",
    "call_raw",
    "epoch_millis_to_iso",
    "serialize",
]
