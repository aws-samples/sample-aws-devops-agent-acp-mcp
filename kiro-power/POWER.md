---
name: "aws-devops-agent-acp"
displayName: "Investigate and Optimize AWS with DevOps Agent"
description: "AI agent for AWS operational intelligence. Investigate incidents, optimize costs, review architecture, map topology, and generate remediation — all enhanced with your local workspace context."
keywords:
  - devops
  - investigation
  - incident
  - troubleshoot
  - root-cause
  - operational
  - alarm
  - cloudwatch
  - cost
  - optimize
  - topology
  - architecture
  - review
  - dependency
  - mitigation
  - outage
  - latency
  - error-rate
  - chat
  - knowledge
  - runbooks
author: "Amazon Web Services"
version: "1.0.0"
homepage: "https://docs.aws.amazon.com/devopsagent/latest/userguide/"
repository: "https://github.com/aws-samples/sample-aws-devops-agent-acp-mcp"
---

# AWS DevOps Agent — Kiro Power

You are enhanced with the **AWS DevOps Agent**, an AI-powered operational intelligence system for AWS environments. You have 19 MCP tools that connect you to a cloud-native agent capable of deep incident investigation, cost optimization, architecture review, topology mapping, and automated remediation. The tools span Discovery (2), AgentSpace (4), Investigation (4), Journal (1), Chat (3), Recommendations (3), and Evaluation (2).

**Your superpower**: You can combine your local workspace knowledge (files, git, skills, terminal) with the DevOps Agent's cloud knowledge (CloudWatch, X-Ray, IAM, topology) by injecting local context into investigation descriptions and ACP prompts. This makes you far more effective than either system alone.

---

## Tools (20 MCP tools)

| Category | Tools | Purpose |
|----------|-------|---------|
| **Discovery** | `list_services`, `get_service` | List and inspect registered services (global — no AgentSpace needed) |
| **AgentSpace** | `list_agent_spaces`, `get_agent_space`, `create_agent_space`, `list_associations` | Manage workspaces (required before any operation) |
| **Investigation** | `create_investigation`, `get_task`, `list_tasks`, `list_executions` | Deep async incident analysis (5-8 min). `create_investigation` requires `title` and `priority` |
| **Journal** | `list_journal_records` | Stream the agent's step-by-step findings and root cause |
| **Chat** | `create_chat`, `list_chats`, `send_message` | Real-time conversational analysis (instant) |
| **Recommendations** | `list_recommendations`, `get_recommendation`, `update_recommendation`, `create_mitigation_plan` | Mitigation plans with actionable code. Use `create_mitigation_plan` to generate plans for completed investigations |
| **Evaluation** | `list_goals`, `start_evaluation` | Assess investigation quality against goals |

---

## 🧠 Intent Detection — Auto-Route Without Asking

When the user describes a problem, **automatically choose the right workflow** based on keywords. Never ask "should I investigate or chat?" — just do it.

### → Investigation (deep, async 5-8 min)
**Trigger words**: alarm, alert, outage, down, 5xx, 4xx, 503, 500, error spike, latency spike, timeout, degraded, unhealthy, failing, crash, OOM, sev1, sev2, incident, page, oncall, throttling, circuit breaker, deployment failure, rollback

**Action**: Start the **Investigation Pattern** (see below).

### → Chat (fast, real-time)
**Trigger words**: cost, optimize, architecture, review, topology, dependency, security, audit, what if, compare, plan, knowledge, skills, runbooks, what do you know, capabilities

**Action**: `create_chat` → `send_message` with local context. Instant responses for analysis, discovery, and optimization queries.

### → Unclear Intent
If the user's intent is unclear, default to chat — it's instant and the agent can always suggest starting an investigation if the problem warrants one.

---

## ⚡ The Chat-First Pattern — Instant Answers + Escalation

Start with chat for instant answers. Escalate to investigation only when the problem requires deep async analysis.

```
1. create_chat()                                     ← get executionId (instant)
2. send_message(executionId, "<question + local context>")  ← instant response (2-10s)
3. send_message(executionId, "follow-up question")   ← full context retained
4. If complex root cause needed:
   create_investigation(title="<incident>")          ← escalate to deep research (5-8 min)
   Poll get_task + list_journal_records → stream progress
   create_mitigation_plan(task_id) → generate mitigation plans (2-5 min)
   list_executions(task_id) → list_journal_records(execution_id, record_type="mitigation_summary_md")
```

---

## 🔍 Discovering Knowledge & Skills

The agent's knowledge base is built from runbooks, associated services, and learned investigation patterns. Use **chat** to discover what the agent knows.

### Discovery prompts

```
# Discover available knowledge and runbooks
create_chat() → executionId
send_message(executionId, "List all runbooks. For each, provide the title, description, and AWS services it covers.")

# Discover configured services and integrations
list_services()   → see all registered services (global)
list_associations(agent_space_id=SPACE_ID)   → see AWS account associations

# Discover investigation capabilities
send_message(executionId, "What types of incidents can you analyze?")
```

### When to discover

- **First time using an AgentSpace** — understand what the agent can do before asking it to investigate
- **After adding new runbooks or services** — verify the agent picked them up
- **Multi-account setups** — discover each space's capabilities to build a routing guide (see Multi-AgentSpace Skill Generation in SKILL.md)
- **Before complex investigations** — check if the agent has relevant domain knowledge

---

## 🔧 Local Context Injection — Your Killer Feature

The DevOps Agent knows your AWS cloud. You know the user's local workspace. **Bridge the gap** by injecting local context into the investigation `description` parameter or ACP prompts.

### What to Inject

Before starting an investigation, gather and inject:

**Always** (automatic):
- **Service identity**: Read `package.json`, `pom.xml`, `Cargo.toml`, `requirements.txt`, or `Makefile` to identify the service name, dependencies, and runtime
- **Recent changes**: `git log --oneline -10` — the agent can correlate deployments with incidents
- **Git status**: `git diff --stat` — uncommitted changes that might be relevant

**When investigating errors**:
- **Error logs**: Read the relevant log file or terminal output the user is looking at
- **Stack traces**: Extract and include the full trace
- **Config files**: CloudFormation templates, CDK stacks, Terraform files, ECS task defs

**When optimizing**:
- **Current architecture**: Read IaC files (CDK, CloudFormation, Terraform)
- **Service dependencies**: Read dependency manifests
- **Cost-relevant config**: Instance types, scaling policies, reserved capacity

### How to Inject

Pack local context into the `description` parameter of `create_investigation`:
```python
create_investigation(
    title="Why are we seeing 503 errors on the ECS service?",
    description="""
[Local Context]
Service: MyService (from package.json)
Last commits: abc1234 fix: increase timeout · def5678 feat: add /api/v2
Recent deploy: 2 hours ago (commit abc1234)
CDK Stack: lib/my-service-stack.ts — ECS Fargate with ALB
Error: "ConnectionError: upstream connect error"

[Question]
Why are we seeing 503 errors on the ECS service?
"""
)
```

### Skill Forwarding

If the user has Kiro skills (`.kiro/skills/`), read relevant skill files and include their content in the `description` parameter:
```python
skills = read_file(".kiro/skills/my-service/SKILL.md")
create_investigation(
    title="Why are we seeing 503 errors on the ECS service?",
    description=f"[Skill Context]\n{skills}\n\n[Question]\nInvestigate the alarm on my-service"
)
```

---

## 📋 Journal Streaming — Show Progress Live

Don't wait silently for investigations to complete. **Summarize updates to the user after every poll.**

```
1. get_task(taskId) → check status
2. If IN_PROGRESS or COMPLETED:
   list_journal_records(executionId, order="ASC")
3. Display each record with emoji prefix based on type:

   📋 PLANNING    — Agent is planning its approach
   🔍 SEARCHING   — Agent is querying CloudWatch, X-Ray, etc.
   🔬 ANALYSIS    — Agent is analyzing data
   🎯 FINDING     — Key discovery (highlight this!)
   🔧 ACTION      — Agent is taking an action
   📊 SUMMARY     — Investigation summary with root cause
   💡 SUGGESTION  — Recommended fix

4. Poll every 30-45 seconds until status = COMPLETED
5. After EVERY poll, give the user a brief progress summary (see format below)
6. On COMPLETED: list_recommendations() for actionable fixes
```

**Pagination**: Use `nextToken` from the previous response to only fetch NEW records each poll cycle. Don't re-fetch the entire journal.

### Progress Summary Format (REQUIRED after every poll)

After each poll, tell the user:
- **What phase** the investigation is in (use emoji cues above)
- **What's new** since the last poll — new findings, resources checked, root causes identified
- **What's next** — what the agent is working on now

**Example:** "🔬 **Update (2 min in):** The agent found CloudWatch metrics showing error rate spiked to 23% at 14:32 UTC on `my-ecs-service`. It's now checking X-Ray traces for downstream dependency failures."

**Example:** "🎯 **Update (5 min in):** Root cause identified — the ECS task definition memory was reduced from 512MB to 256MB in the last deploy, causing OOM kills. The agent is now generating remediation recommendations."

**Why this matters:** Users waiting 5–8 minutes with no feedback will assume something is broken. Regular summaries build trust and let users start thinking about next steps before the investigation completes.

---

## 🏗️ Common Workflows

### Incident Response
```
User: "Our ECS service is returning 503s"

You:
1. create_chat() → executionId
2. Gather local context: git log, package.json, CDK stack, error logs
3. send_message(executionId, "Our ECS service <name> is returning 503s. <local context>")
4. Show instant triage response to user
5. If deeper root cause needed:
   create_investigation(title="ECS 503 errors on <service>")
   Poll get_task + list_journal_records → stream progress with emojis
   On complete: create_mitigation_plan(task_id) → poll → list_journal_records(record_type="mitigation_summary_md")
6. If mitigation has IaC: generate the fix code locally
```

### Cost Optimization
```
User: "Help me reduce AWS costs"

You:
1. list_agent_spaces() → agentSpaceId
2. Read local IaC files (CDK, CloudFormation, Terraform)
3. create_chat() → executionId
4. send_message(executionId, "Analyze cost optimization opportunities. <local IaC context>")
5. If deeper analysis needed: create_investigation(title="<question>")
   Poll get_task → list_journal_records → list_recommendations
```

### Architecture Review
```
User: "Review my service architecture"

You:
1. list_agent_spaces() → agentSpaceId
2. Read CDK/CloudFormation/Terraform files + package dependencies
3. create_chat() → executionId
4. send_message(executionId, "Review architecture for <service>. <local IaC context>")
5. Iterate with follow-up send_message calls on specific areas
6. If deep analysis needed: create_investigation(title="<question>")
```

### Topology Mapping
```
User: "Show me dependencies for my ECS service"

You:
1. list_agent_spaces() → agentSpaceId
2. create_chat() → executionId
3. send_message(executionId, "Map dependencies for <ECS service>")
4. If deeper topology analysis needed: create_investigation(title="<question>")
```

### Knowledge & Skills Discovery
```
User: "What runbooks do you have?" / "Show available knowledge items"

You:
1. list_agent_spaces() → agentSpaceId
2. create_chat() → executionId
3. send_message(executionId, "List all runbooks and knowledge items you have access to. For each, provide the title and AWS services it covers.")
4. For deeper exploration on a specific topic:
   send_message(executionId, "Detail runbook for <specific-service>")
```

---

## 🔄 Session Management

- **Reuse chat sessions**: Keep the `executionId` from `create_chat` and reuse it for follow-up `send_message` calls — the agent retains full conversation context within a session.
- **List previous chats**: Use `list_chats()` to find and resume previous chat sessions.
- **Track investigation IDs**: Keep the `taskId` and `executionId` from each investigation to poll progress and retrieve results.
- **Resume analysis**: Use `list_tasks()` to find previous investigations. Check their status and recommendations.
- **One investigation per incident**: Don't create duplicate investigations. Use `list_tasks(status="IN_PROGRESS")` to check for existing ones.

---

## ⚠️ Error Handling

- **Partial results**: If an investigation fails, check journal records for partial findings.
- **AgentSpace not found**: Call `list_agent_spaces()` → if empty, `create_agent_space()` → inform user they need to associate their AWS account via console.
- **Investigation stuck at CREATED**: This usually means the agent hasn't picked it up yet. Wait 30-60 seconds and re-poll `get_task`.
- **Empty journal records**: Investigation is still early. Keep polling — records appear as the agent makes progress.

---

## ACP Client SDK (Alternative to MCP)

Kiro can also use the ACP Client SDK for a streaming Python API instead of MCP tools:

```python
from aws_devops_agent import ACPClient

with ACPClient() as client:
    for event in client.prompt("Investigate my ECS 503 errors"):
        if event.type == "text":
            print(event.text, end="", flush=True)
```

The SDK auto-discovers the server and handles the full ACP protocol lifecycle.


## 💡 Prompt Phrasing Guide

**Fast chat responses (2-10s):**
- Use: "Analyze...", "Optimize...", "Review...", "Compare...", "What if...", "Show topology...", "Audit..."

**Fast discovery responses (instant):**
- Use: "List...", "Show me...", "What is the status of...", "How many..."

**Deep investigation (5-8 min):**
- Use: "Investigate...", "What's wrong with...", "Root cause of..."

**Knowledge discovery (2-10s):**
- Use: "What runbooks...", "List knowledge items...", "What do you know about...", "What capabilities..."

**Tip:** The server's intent detection is keyword-based. Word choice directly controls response time.

## Setup

For the full step-by-step guide, see [KIRO_QUICKSTART.md](KIRO_QUICKSTART.md).

> **ACP vs MCP:** This Power uses MCP (19 discrete tools in the Powers panel).
> For deeper integration, consider the **ACP path** instead — it enables
> streaming prompt/response interaction via subprocess. The ACP path uses the
> `ACPClient` Python SDK and doesn't need any mcp.json config.
> See [KIRO_QUICKSTART.md](KIRO_QUICKSTART.md) for both paths.

### Quick Setup

1. **Install the package** (if not already installed):

   ```bash
   pip install 'aws-devops-agent-acp[mcp]'
   # OR from source: cd /path/to/AWSDevOpsAgentACPMCP && pip install -e '.[mcp]'
   ```

2. **Find the binary path** (Kiro needs the full absolute path):

   ```bash
   which aws-devops-agent
   # Example: /home/user/.venv/bin/aws-devops-agent
   ```

3. **Get your username**:

   ```bash
   whoami
   # OR: aws sts get-caller-identity --query Arn --output text | cut -d'/' -f2
   ```

4. **Edit `mcp.json`** — replace the two placeholders with values from steps 2 and 3:

```json
{
  "mcpServers": {
    "aws-devops-agent": {
      "command": "<REPLACE_WITH_BINARY_PATH>",
      "args": ["mcp"],
      "env": {
        "DEVOPS_AGENT_USER_ID": "<REPLACE_WITH_YOUR_USERNAME>",
        "DEVOPS_AGENT_REGION": "us-east-1",
        "DEVOPS_AGENT_AUTO_CREATE_SPACE": "true"
      }
    }
  }
}
```

5. **Copy config to Kiro settings**:

   ```bash
   mkdir -p .kiro/settings && cp kiro-power/mcp.json .kiro/settings/mcp.json
   ```

6. **Reload Kiro** (Command Palette → "Developer: Reload Window")
7. **Verify** — the power should appear in the Powers panel with all **19 tools** listed

---

## Support & Legal

- **Documentation**: [AWS DevOps Agent User Guide](https://docs.aws.amazon.com/devopsagent/latest/userguide/)
- **Support**: [AWS re:Post — DevOps Agent](https://repost.aws/tags/devops-agent)
- **License**: [MIT-0](https://opensource.org/license/mit-0)
- **Privacy**: [AWS Privacy Notice](https://aws.amazon.com/privacy/)
- **Source**: [GitHub](https://github.com/aws-samples/sample-aws-devops-agent-acp-mcp)
