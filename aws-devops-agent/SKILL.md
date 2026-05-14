---
name: aws-devops-agent-acp
description: >-
  AWS DevOps Agent for operational intelligence via ACP and MCP. Investigate incidents,
  optimize costs, review architecture, map topology, get mitigation recommendations,
  generate remediation code, and get actionable recommendations.
---

Orchestrate AWS DevOps Agent investigations and analysis.

**Kiro integration:** This skill is the primary integration point for Kiro. Use the
ACP path (ACPClient SDK) for streaming interaction, or the MCP path (19 tools
in Powers panel) as a fallback. See `../kiro-power/KIRO_QUICKSTART.md` for setup.
**ACP provides streaming prompt/response via subprocess**


See `references/WORKFLOWS.md` for guidance on investigation workflows.

## Which interface to use

| Situation | Use |
|-----------|-----|
| Quick one-off question | `python acp_chat.py "..."` (from repo root) |
| Programmatic / scripted | `ACPClient` SDK (`from aws_devops_agent import ACPClient`) |
| Claude Code / Cursor / Windsurf | MCP tools (19 tools via `.mcp.json`) |
| Kiro (native ACP) | ACP server directly (see `../kiro-power/KIRO_QUICKSTART.md`) |
| Zed / JetBrains | ACP server directly (`aws-devops-agent-acp`) |
| Debugging / credential validation | `python acp_chat.py` (instant end-to-end feedback) |

# AWS DevOps Agent skill

## Prerequisites

1. An AgentSpace created and configured (see `references/ONBOARDING.md`)
2. AWS credentials configured (`aws configure` or environment variables)
3. IAM permissions for the AWS DevOps Agent service

Auto-create is off by default. To have the server find or create an AgentSpace automatically,
pass `autoCreateSpace: true` in `session/new` params (ACP), or set `DEVOPS_AGENT_AUTO_CREATE_SPACE=true` in env.

## Choosing chat vs investigation

**Default to chat** (`create_chat` + `send_message`) — it's instant and conversational.
**Escalate to investigation** (`create_investigation`) when the task is complex enough
to warrant deep async analysis (5-8 minutes).

### → Chat first (fast, seconds)
**Use for**: cost questions, architecture review, topology, knowledge discovery,
quick diagnostics, follow-ups, "show me", "explain", "what if", "how many"

```
create_chat() → executionId
send_message(executionId, "your question") → instant response
send_message(executionId, "follow-up") → full context retained
```

### → Escalate to investigation (deep, 5-8 min)
**Use when**: root cause analysis needed, multi-service correlation, alarm triage,
incident postmortem, or when chat suggests deeper analysis is warranted

**Trigger words**: investigate, root cause, outage, debug, alarm, incident, 503, 5xx,
latency spike, error spike, OOM, deployment failure, rollback

```
create_investigation(title="ECS 503 errors", priority="HIGH") → taskId
poll get_task(taskId) → list_journal_records(executionId) → list_recommendations()
```

### → Discovery (instant, no chat needed)
**Use for**: listing configured services, goals, agent spaces

```
list_services() → registered services
list_goals() → evaluation goals
list_agent_spaces() → available spaces
```

## Chat workflow

### Step 1: Identify the AgentSpace

```
list_agent_spaces
```

Save the `agentSpaceId`. All subsequent calls require it.

### Step 2: Start a chat session

```
create_chat(agent_space_id, user_id) → executionId
```

Save the `executionId`. Reuse it for the entire conversation — the agent retains
full context server-side.

### Step 3: Send messages

```
send_message(execution_id, content="your question + local context")
```

The response is returned as collected text (the streaming EventStream is consumed
and assembled). Include local context in the `content` parameter for better results.

### Step 4: Follow up or escalate

Continue the conversation with more `send_message` calls using the same `executionId`.
If the agent suggests deeper analysis is needed, or the problem is complex, escalate
to an investigation:

```
create_investigation(
    title="Root cause of ECS 503 errors",
    description="Chat context: agent identified high error rate but needs deeper
    CloudWatch/X-Ray correlation across multiple services."
)
```

## Discovering knowledge & skills

Use chat to discover what the agent knows **before** starting investigations.

### Discovery via chat

```
create_chat() → executionId

# What runbooks and knowledge does the agent have?
send_message(executionId, "List all runbooks and knowledge items you have access to.
  For each, provide the title, description, and AWS services it covers.")

# What services are configured?
send_message(executionId, "What AWS services and accounts are configured in this agent space?")

# What can the agent investigate?
send_message(executionId, "What investigation capabilities and skills do you have?")

# Domain-specific knowledge
send_message(executionId, "What do you know about [ECS / Lambda / RDS / etc.]?")
```

### When to run discovery

- **First time using an AgentSpace** — understand what the agent can do
- **After adding new runbooks or services** — verify the agent picked them up
- **Multi-account setups** — discover each space's capabilities to build a routing guide
- **Before complex investigations** — check for relevant domain knowledge

## Investigation workflow (deep analysis)

Use when chat isn't sufficient — complex incidents, multi-service correlation,
or when the agent needs to autonomously explore CloudWatch, X-Ray, and logs.

### Step 1: Start an investigation

```
create_investigation(title="Describe the issue here", priority="HIGH")
```

Priority values: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `MINIMAL`. Save the `taskId`.

Include local context in the `description` parameter — recent git changes, error logs,
IaC state, anything that helps the agent narrow scope.

### Step 2: Stream progress to the user

**Investigations take 5–8 minutes.** Don't silently poll — **summarize updates to the user after every poll**.

1. Tell the user: "Investigation started — typically takes 5–8 minutes. I'll keep you updated."
2. Poll `get_task` every 30–45 seconds. When `IN_PROGRESS` with an `executionId`, call `list_journal_records`.
3. **After every poll, give the user a brief progress summary** covering:
   - **What phase** the investigation is in (use emoji cues below)
   - **What's new** since the last poll — new findings, resources checked, root causes identified
   - **What's next** — what the agent is doing now
4. Use record types as emoji cues:
   - `PLANNING` → "📋 Planning investigation approach..."
   - `ANALYSIS` → "🔬 Analyzing: [title]"
   - `FINDING` → "🎯 Root cause identified: [title]"
   - `ACTION` → "🔧 Recommended action: [title]"
   - `SUMMARY` → "📊 Investigation complete"
5. Track `recordId`s to avoid repeating information.

**Example summary after a poll:**
> 🔬 **Update (2 min in):** The agent found CloudWatch metrics showing error rate spiked to 23% at 14:32 UTC on `my-ecs-service`. It's now checking X-Ray traces for downstream dependency failures.

**Example summary after a later poll:**
> 🎯 **Update (5 min in):** Root cause identified — the ECS task definition memory was reduced from 512MB to 256MB in the last deploy, causing OOM kills. The agent is now generating remediation recommendations.

**Why this matters:** Users waiting 7–8 minutes with no feedback will assume something is broken. Regular summaries build trust and let users start thinking about next steps before the investigation completes.

### Step 4: Read full findings

When the investigation reaches `COMPLETED`, call `list_journal_records` with `order=DESC` and `limit=10`. Present a consolidated root cause summary.

### Step 5: Get recommendations

```
list_recommendations(task_id="<TASK_ID>")
get_recommendation(recommendation_id="<RECOMMENDATION_ID>")
```

If no recommendations exist, trigger mitigation plan generation:

```
create_mitigation_plan(task_id="<TASK_ID>")
```

This sets the task to `PENDING_START`, activating the Mitigation Agent. Poll `get_task`
until `COMPLETED` again, then retrieve the mitigation plan:

```
list_executions(task_id="<TASK_ID>")  → find newest execution_id
list_journal_records(execution_id="<EXECUTION_ID>", record_type="mitigation_summary_md")
```

### Step 6: Generate remediation code

Parse the recommendation spec. Generate IaC (CloudFormation, CDK, or Terraform) or a boto3 script. Always include a dry-run mode.

## ACP streaming interaction

The ACP Client SDK provides streaming prompt/response for programmatic access:

```python
from aws_devops_agent import ACPClient

with ACPClient() as client:
    for event in client.prompt("What alarms are firing?"):
        if event.type == "text":
            print(event.text, end="", flush=True)
```

## Parallel pattern (recommended for incidents)

Start chat for instant triage AND investigation for deep root cause simultaneously:

```
create_chat() → executionId
send_message(executionId, "What's causing the 503s?") → instant triage

create_investigation(title="ECS 503 errors", priority="HIGH") → taskId
poll get_task → list_journal_records → deep root cause (5-8 min)
```

### Stream event types

| Event | Meaning |
|-------|---------|
| `contentBlockStart` | Start of a content block (type: text, final_response, chat_title) |
| `contentBlockDelta` | Streaming text chunk — extract via `delta.textDelta.text` |
| `contentBlockStop` | End of a content block |
| `responseCreated` | Response initialized |
| `responseInProgress` | Agent is processing |
| `responseCompleted` | Response finished (includes `usage` with token counts) |
| `responseFailed` | Response failed |
| `summary` | Summary of agent actions |
| `heartbeat` | Keep-alive (ignore) |

## First-time setup on a new machine

When the user asks to "set up devops agent", "configure agent spaces", or you detect
that credentials or agent space configuration is missing, run this workflow.

### Step 1: Gather account info from the user

Ask the user for their agent space accounts. Each space needs:
- **AWS Account ID** (12-digit number)
- **Purpose** (e.g. "Chat Agent", "Knowledge Service", "Production", "Staging")
- **Region** (default: `us-east-1`)

Example prompt: "What AWS accounts are your agent spaces in? For each, tell me the
account ID, region, and what it's for (e.g. investigations, knowledge/runbooks)."

### Step 2: Create AWS named profiles

For each account, create a named profile in `~/.aws/config`. This is the standard
AWS credential mechanism that works across all platforms and tools.

```ini
# ~/.aws/config
[profile devops-agent]
region = us-east-1

[profile knowledge-service]
region = us-east-1
```

Then configure credentials via one of:

```bash
# Option A: Access keys
aws configure --profile devops-agent

# Option B: SSO (recommended for organizations)
aws configure sso --profile devops-agent

# Option C: IAM Identity Center
# Add to ~/.aws/config:
# [profile devops-agent]
# sso_session = my-sso
# sso_account_id = 123456789012
# sso_role_name = DevOpsAgentRole
# region = us-east-1
```

Naming convention: use the purpose as the profile name (e.g. `devops-agent`, `knowledge-service`).

### Step 3: Verify credentials

```bash
AWS_PROFILE=<profile-name> aws sts get-caller-identity
```

If using SSO, refresh with: `aws sso login --profile <profile-name>`

### Step 4: Discover agent space IDs

For each profile, query the agent space:

```bash
AWS_PROFILE=<profile-name> DEVOPS_AGENT_USER_ID=<username> DEVOPS_AGENT_REGION=us-east-1 \
  python3 -c "from aws_devops_agent import ACPClient; print(ACPClient.quick('List my agent spaces'))"
```

Parse the agent space name and ID from the response.

### Step 5: Choose primary MCP space

If the user has multiple spaces, pick one as the primary MCP server (typically the one
used for investigations/incidents). Other spaces are accessible via shell wrappers or
by passing `agent_space_id` explicitly.

If the user has only one space, it becomes the primary.

### Step 6: Configure the IDE

Each IDE has its own MCP configuration format. Generate the appropriate config
for the user's IDE.

#### Kiro (mcp.json)

Location: `~/.kiro/settings/mcp.json` (global) or `.kiro/settings/mcp.json` (workspace)

```json
{
  "mcpServers": {
    "devops-agent-<purpose>": {
      "command": "<output of which aws-devops-agent>",
      "args": ["mcp"],
      "env": {
        "DEVOPS_AGENT_USER_ID": "<username>",
        "DEVOPS_AGENT_REGION": "us-east-1",
        "DEVOPS_AGENT_AUTO_CREATE_SPACE": "true",
        "AWS_PROFILE": "<profile-name>"
      },
      "autoApprove": [
        "list_services", "get_service", "list_agent_spaces", "get_agent_space",
        "list_associations", "get_task", "list_tasks", "list_executions",
        "list_journal_records", "list_recommendations", "get_recommendation", "list_goals"
      ]
    }
  }
}
```

#### Claude Code / Cursor / Windsurf (mcp config)

Location varies by IDE. The server entry is the same:

```json
{
  "mcpServers": {
    "aws-devops-agent": {
      "command": "<output of which aws-devops-agent>",
      "args": ["mcp"],
      "env": {
        "DEVOPS_AGENT_USER_ID": "<username>",
        "DEVOPS_AGENT_REGION": "us-east-1",
        "DEVOPS_AGENT_AUTO_CREATE_SPACE": "true",
        "AWS_PROFILE": "<profile-name>"
      }
    }
  }
}
```

#### Zed / JetBrains (ACP — native)

These IDEs have built-in ACP clients. Point at the ACP server:

```json
{
  "agent_servers": {
    "AWS DevOps Agent": {
      "command": "aws-devops-agent-acp",
      "env": {
        "DEVOPS_AGENT_USER_ID": "<username>",
        "DEVOPS_AGENT_REGION": "us-east-1",
        "AWS_PROFILE": "<profile-name>"
      }
    }
  }
}
```

Preserve any existing entries in the config file.

### Step 7: Create shell wrappers for additional spaces

For each space that is NOT the primary MCP space, create a wrapper script so
the user (or the AI assistant) can query it via shell:

```bash
#!/usr/bin/env bash
# <Purpose> ACP wrapper — queries <Space Name> (<account-id>)
set -euo pipefail
[ $# -eq 0 ] && { echo "Usage: $(basename "$0") \"your question\""; exit 1; }
export AWS_PROFILE=<profile-name>
export DEVOPS_AGENT_USER_ID=<username>
export DEVOPS_AGENT_REGION=<region>
exec python3 -c "
import sys
from aws_devops_agent import ACPClient
print(ACPClient.quick(sys.argv[1]))
" "$*"
```

Install to `~/.local/bin/<script-name>` and `chmod +x`.

### Step 8: Generate a local context file

Create a context file the AI assistant can reference in future sessions.
The format depends on the IDE:

- **Kiro**: `~/.kiro/skills/devops-agent/SKILL.md` (skill) or `.kiro/steering/devops-agent.md` (workspace)
- **Claude Code**: `.claude/AGENTS.md` or project instructions
- **Cursor**: `.cursorrules`
- **Windsurf**: `.windsurfrules`

The content should include:

```markdown
# AWS DevOps Agent — Local Setup

## Agent Spaces

| Space | Account | AWS Profile | Agent Space ID | Region | Purpose |
|-------|---------|-------------|----------------|--------|---------|
| **<Name>** | `<account-id>` | `<profile>` | `<space-id>` | `<region>` | <purpose> |

## Credential Refresh

If you see `ExpiredTokenException`, refresh credentials:
- SSO: `aws sso login --profile <profile-name>`
- Access keys: `aws configure --profile <profile-name>`

## Routing

<describe which space handles what type of query>
```

### Step 9: Verify

Restart the IDE or reload the MCP config, then confirm:
- MCP tools work (e.g. `list_agent_spaces` returns results)
- Shell wrappers work for additional spaces
- Context file is loaded by the assistant

## Multi-AgentSpace knowledge discovery

After setup, use chat to discover what each space knows so you can route queries effectively.

### Workflow

1. Call `list_agent_spaces` to discover all spaces.
2. For each space, start a chat and ask the agent what it knows:
   ```
   create_chat(agent_space_id="<SPACE_ID>") → executionId
   send_message(executionId, "List all your runbooks.
     For each, provide the title, description, and AWS services it covers.")
   ```
3. Create a local context file with the routing guide (see Step 8 in setup).

### Discovery prompts

- **Runbooks**: "List all runbooks you have access to. For each, give the title, description, and AWS services it covers."
- **Services**: "What AWS services are configured in this agent space?"
- **Capabilities**: "Summarize your investigation capabilities."

### When to run discovery

- After first-time setup
- After adding new runbooks or services to an AgentSpace
- When the user asks "what can you investigate?"

## Evaluation workflow

1. `list_goals` → find a goal
2. `start_evaluation(goal_id="<GOAL_ID>")` → creates evaluation task
3. Poll `get_task` until `COMPLETED`
4. `list_journal_records` → read evaluation analysis
5. `list_recommendations` → get improvement suggestions

## Error handling

| Error | Action |
|-------|--------|
| `ResourceNotFoundException` | Verify `agent_space_id` with `list_agent_spaces` |
| `ThrottlingException` | Retry with exponential backoff |
| `ValidationException` | Check required parameters (see MCP tool docstrings) |
| `AccessDeniedException` | Verify IAM permissions |

## Next steps

- Set up your AgentSpace: `references/ONBOARDING.md`
- Choose the right workflow: `references/WORKFLOWS.md`
- Learn more: [AWS DevOps Agent documentation](https://docs.aws.amazon.com/devopsagent/latest/userguide/)
