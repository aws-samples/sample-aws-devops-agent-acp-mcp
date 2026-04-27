# AWS DevOps Agent — Sample ACP Client, ACP Server & MCP Server

A sample implementation of an **ACP client**, **ACP server**, and **MCP server** for the [AWS DevOps Agent](https://docs.aws.amazon.com/devopsagent/latest/userguide/). Use these reference implementations to integrate AI-powered operational intelligence into your IDE or agent — investigate incidents, analyze costs, review architecture, map topology, and generate remediation.

**Version:** 1.0.0 | **License:** MIT-0 | **Status:** Sample / Reference Implementation

> 💡 **What's included:** A sample ACP server (`acp_server.py`), a streaming ACP client SDK (`acp_client.py`), and an MCP server with 19 tools (`mcp_server.py`). Use these as starting points for building your own integrations with the AWS DevOps Agent APIs.

> ⚠️ **Disclaimer:** This software is provided as-is for development and evaluation purposes. Users should thoroughly test and validate it in their own environments before deploying to production. Review IAM permissions, network configuration, and security controls to ensure they meet your organization's requirements.

> 🔒 **Security:** Streaming prompt/response interaction is secured with allowlist enforcement, argument validation, and configurable approval gates. See [TOOL_SECURITY.md](TOOL_SECURITY.md) for the full security model.

## Prerequisites

- Python 3.10+
- AWS credentials configured (`aws configure` or env vars)
- IAM permissions: `AIDevOpsAgentFullAccess` (user) + `AIDevOpsAgentAccessPolicy` (agent role) — see [ONBOARDING.md](aws-devops-agent/references/ONBOARDING.md)

Get your AWS username (you'll need this for config):

```bash
aws sts get-caller-identity --query Arn --output text | cut -d'/' -f2
```

## Quick Start

### 1. Install

```bash
pip install aws-devops-agent-acp

# With MCP support (for Claude Code, Cursor, Windsurf):
pip install 'aws-devops-agent-acp[mcp]'
```

**Installing from source** (development):

```bash
git clone https://github.com/awslabs/mcp
cd mcp/AWSDevOpsAgentACPMCP
pip install -e '.[mcp]'
```

### 2. Configure AWS Credentials

```bash
aws configure
# Verify:
aws sts get-caller-identity
```

You need `AIDevOpsAgentFullAccess` on your IAM user/role, plus an agent service role with `AIDevOpsAgentAccessPolicy`. See [ONBOARDING.md](aws-devops-agent/references/ONBOARDING.md) for full setup.

### 3. Verify Installation

```bash
aws-devops-agent --version
which aws-devops-agent   # Note this path — you'll need it for IDE config
```

### 4. Quick Test

Verify end-to-end connectivity before wiring up an IDE:

```bash
# From the repo root (requires acp_chat.py + valid AWS credentials)
python acp_chat.py "What EC2 instances are running?"
```

If credentials are wrong, the AgentSpace is missing, or the binary isn't on PATH,
you'll get a clear error in seconds rather than after configuring an IDE integration.
The interactive REPL (`python acp_chat.py` with no args) is also useful for debugging.

### 5. Connect Your IDE

#### Kiro (Recommended — ACP)

See [KIRO_QUICKSTART.md](kiro-power/KIRO_QUICKSTART.md) for a full step-by-step guide. The ACP path is just 3 steps:

1. `pip install -e .` (from this directory — no MCP extra needed)
2. Set env vars (`DEVOPS_AGENT_USER_ID`, `DEVOPS_AGENT_REGION`)
3. Use the SDK — no config files, no reload:

```python
from aws_devops_agent import ACPClient

# One-shot
response = ACPClient.quick("What alarms are firing?")
print(response)

# Streaming
with ACPClient() as client:
    for event in client.prompt("Investigate ECS 503 errors"):
        if event.type == "text":
            print(event.text, end="", flush=True)
```

The SDK auto-discovers the server binary and finds your AgentSpace. Zero config.

For **MCP tools** instead (19 tools in Powers panel, requires Python 3.10+), see the MCP path in [KIRO_QUICKSTART.md](kiro-power/KIRO_QUICKSTART.md#path-b-mcp-setup-fallback--7-steps).

#### Zed / JetBrains (Native ACP)

These IDEs have built-in ACP clients — point at the ACP server directly:

```json
{
  "agent_servers": {
    "AWS DevOps Agent": {
      "command": "aws-devops-agent-acp",
      "env": {
        "DEVOPS_AGENT_USER_ID": "<YOUR_USERNAME>",
        "DEVOPS_AGENT_REGION": "us-east-1"
      }
    }
  }
}
```

#### Claude Code / Cursor / Windsurf (MCP)

```json
{
  "mcpServers": {
    "aws-devops-agent": {
      "command": "aws-devops-agent",
      "args": ["mcp"],
      "env": {
        "DEVOPS_AGENT_USER_ID": "<YOUR_USERNAME>",
        "DEVOPS_AGENT_REGION": "us-east-1",
        "DEVOPS_AGENT_AUTO_CREATE_SPACE": "true"
      }
    }
  }
}
```

## CLI Modes

```bash
aws-devops-agent mcp     # MCP server for Claude Code, Cursor, Windsurf
aws-devops-agent acp     # ACP server for Zed, JetBrains, Kiro
aws-devops-agent auto    # Auto-detect protocol from first message
aws-devops-agent --version
```

**Auto-detect:** When stdin is piped with no subcommand, the CLI reads the first JSON-RPC message and routes to ACP or MCP based on the protocol handshake.

**Direct entry points** (skip subcommand parsing):
- `aws-devops-agent-acp` — ACP server directly
- `aws-devops-agent-mcp` — MCP server directly

## ACP Client SDK

For programmatic access when your IDE or agent doesn't have native ACP support:

```python
from aws_devops_agent import ACPClient, ACPEvent

# Context manager (recommended)
with ACPClient() as client:
    for event in client.prompt("What alarms are firing?"):
        if event.type == "text":
            print(event.text, end="", flush=True)
        elif event.type == "tool_call":
            print(f"  [{event.name}]")

# One-shot convenience
response = ACPClient.quick("How many EC2 instances are running?")

# With options
with ACPClient(region="us-west-2", verbose=True) as client:
    full_response = client.prompt_sync("Analyze my cost trends")
```

**Features:**
- Auto-discovers the ACP server binary (PATH → package directory → common locations)
- Streaming and synchronous APIs
- Thread-safe, supports cancellation
- TOCTOU-safe subprocess shutdown

## MCP Tools (19 tools)

When running in MCP mode, the following tools are available:

| Category | Tools |
|----------|-------|
| **Discovery** | `list_services`, `get_service` |
| **AgentSpace** | `list_agent_spaces`, `get_agent_space`, `create_agent_space`, `list_associations` |
| **Investigation** | `create_investigation`, `get_task`, `list_tasks`, `list_executions` |
| **Journal** | `list_journal_records` |
| **Chat** | `create_chat`, `list_chats`, `send_message` |
| **Recommendations** | `list_recommendations`, `get_recommendation`, `update_recommendation` |
| **Evaluation** | `list_goals`, `start_evaluation` |

## Workflow Patterns

### Chat (fast, seconds)

For cost optimization, architecture review, topology, knowledge discovery, follow-ups:

```
create_chat()
↓ send_message("Analyze cost trends for my ECS services")
↓ instant response
↓ send_message("follow-up question") — full context retained
```

### Investigation (deep, 5-8 minutes)

For alarms, outages, error spikes, performance issues:

```
create_investigation(title, priority="CRITICAL")
↓ poll get_task() every 30-45s
↓ stream list_journal_records() for progress
↓ list_recommendations() when complete
↓ generate remediation code
```

### Discovery (fast, instant)

Discover what the agent knows and what services are configured:

```
list_services()           → registered services (AWS accounts, repos, MCP servers)
get_service(service_id)   → detailed service configuration
list_goals()              → evaluation goals (cost, security, reliability)
```

### Knowledge & Skills Discovery

Use chat to discover what the agent knows:
```
create_chat() → executionId
send_message(executionId, "List all runbooks and their AWS services")
```

### Parallel (recommended for incidents)

Run both simultaneously — chat for instant triage, investigation for deep root cause:

```
┌─ Investigation (background, 5-8 min) ──────────────────┐
│  create_investigation → agent explores autonomously     │
│  ↓ journal records stream progress in real-time         │
├─ Chat (foreground, instant) ─────────────────────────────┤
│  create_chat → send_message for instant triage           │
├─ Results ───────────────────────────────────────────────┤
│  Investigation completes → root cause + recommendations │
└─────────────────────────────────────────────────────────┘
```

```
┌─────────────────────────────────────────────────┐
│  AI Agent / IDE                                  │
│  (Kiro, Zed, JetBrains, Claude Code, Cursor)   │
├──────────┬──────────────────────────────────────┤
│ ACPClient│  MCP Client (built into IDE)         │
│ (SDK)    │                                       │
├──────────┴──────────────────────────────────────┤
│  aws-devops-agent CLI (auto-detect / mcp / acp) │
├─────────────────────────────────────────────────┤
│  acp_server.py          │  mcp_server.py        │
│  (JSON-RPC/stdio)       │  (FastMCP/stdio)      │
├─────────────────────────┴───────────────────────┤
│  core/  (shared boto3 clients, streaming, utils) │
├─────────────────────────────────────────────────┤
│  AWS DevOps Agent APIs                           │
│  (Control Plane + Data Plane)                    │
└─────────────────────────────────────────────────┘
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DEVOPS_AGENT_USER_ID` | Yes | Your username — alphanumeric, dots, hyphens, underscores only (NOT an ARN). Run `whoami` or extract from `aws sts get-caller-identity` |
| `DEVOPS_AGENT_REGION` | No | AWS region (default: `us-east-1`) |
| `DEVOPS_AGENT_SPACE_ID` | No | AgentSpace ID (auto-discovered if not set) |
| `DEVOPS_AGENT_AUTO_CREATE_SPACE` | No | Auto-create AgentSpace if none exist (default: `false`). **Note:** The ACP server defaults to `false`; pass `autoCreateSpace: true` in `session/new` params or `auto_create_space=True` in ACPClient constructor to opt in per-request. Existing spaces are silently reused — a new one is only created when none exist. |

## Supported Regions

- **us-east-1** (default, recommended)
- us-west-2
- eu-west-1
- eu-central-1
- ap-southeast-1
- ap-northeast-1

## Troubleshooting

**"Failed to find or create AgentSpace":**
Check IAM permissions — you need `AIDevOpsAgentFullAccess` on your user and `AIDevOpsAgentAccessPolicy` on the agent role. Or set `DEVOPS_AGENT_SPACE_ID` directly.

**"ExpiredTokenException":**
Your AWS session token has expired. Refresh credentials (e.g., `aws sso login`, or update access keys via `aws configure`).

**Agent not appearing in IDE:**
Check your IDE's ACP/MCP configuration points to the correct binary. Run `which aws-devops-agent` to find the path.

**Slow responses:**
Investigations take 5-8 minutes by design (deep analysis). Use chat (`create_chat` + `send_message`) for quick answers.

**"Cannot find aws-devops-agent-acp":**
Install with `pip install aws-devops-agent-acp` and ensure the binary is on your PATH.

## Development

```bash
# Clone and install in development mode
git clone https://github.com/awslabs/mcp
cd mcp/AWSDevOpsAgentACPMCP
pip install -e '.[dev,mcp]'

# Run tests
pytest tests/ -v

# 110 tests pass on Python 3.11 (MCP tests skip on 3.9 — MCP needs 3.10+)
```

## License

MIT-0 — see [LICENSE.txt](LICENSE.txt)
