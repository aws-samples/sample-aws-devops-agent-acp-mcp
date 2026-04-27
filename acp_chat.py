#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Quick-test CLI for the AWS DevOps Agent ACP path.

Usage:
    python acp_chat.py "What EC2 instances are running?"
    python acp_chat.py   # Interactive REPL
"""
import sys

from aws_devops_agent import ACPClient


def main() -> None:
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        print(ACPClient.quick(query))
    else:
        print("AWS DevOps Agent — Interactive Chat")
        print("Type 'quit' or 'exit' to stop.\n")
        with ACPClient() as client:
            while True:
                try:
                    query = input("You: ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if not query or query.lower() in ("quit", "exit"):
                    break
                for event in client.prompt(query):
                    if event.type == "text":
                        print(event.text, end="", flush=True)
                print()


if __name__ == "__main__":
    main()
