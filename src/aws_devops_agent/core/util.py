import logging
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Shared utilities — serialization, timestamp conversion, API call wrapper."""
import json
from datetime import datetime, timezone
from typing import Any, Callable

from botocore.exceptions import ClientError


def serialize(obj: Any) -> Any:
    """Make boto3 responses JSON-serializable."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    raise TypeError(f"Not serializable: {type(obj)}")


def epoch_millis_to_iso(obj: Any) -> Any:
    """Recursively convert epoch-millisecond timestamps (>1e12) to ISO strings."""
    if isinstance(obj, dict):
        return {k: epoch_millis_to_iso(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [epoch_millis_to_iso(v) for v in obj]
    if isinstance(obj, (int, float)) and obj > 1e12:
        return datetime.fromtimestamp(obj / 1000, tz=timezone.utc).isoformat()
    return obj


logger = logging.getLogger(__name__)

def call_api(fn: Callable, **kwargs: Any) -> str:
    """Call a boto3 method, return a JSON string. Strips ResponseMetadata."""
    try:
        resp = fn(**{k: v for k, v in kwargs.items() if v is not None})
        resp.pop("ResponseMetadata", None)
        return json.dumps(resp, default=serialize, indent=2)
    except ClientError as e:
        error_data = e.response.get("Error", {}) if isinstance(e.response, dict) else {}
        code = error_data.get("Code", "ClientError")
        msg = error_data.get("Message", str(e))
        return json.dumps({"error": code, "message": msg})
    except Exception as e:
        logger.exception("Unexpected error in API call")
        return json.dumps({"error": "InternalError", "message": "An unexpected error occurred. Check server logs."})


def call_raw(fn: Callable, **kwargs: Any) -> dict:
    """Call a boto3 method, return the response dict. Strips ResponseMetadata."""
    resp = fn(**{k: v for k, v in kwargs.items() if v is not None})
    resp.pop("ResponseMetadata", None)
    return resp
