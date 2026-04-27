# AWS DevOps Agent Onboarding Guide

## Quick Setup

### 1. Install

```bash
# ACP only — recommended for Kiro, works with Python 3.10+
pip install -e .

# With MCP tools — for Claude Code, Cursor, Windsurf (requires Python 3.10+)
pip install -e '.[mcp]'
```

Verify (catches stale binaries from previous installs):

```bash
aws-devops-agent --version
# Expected: aws-devops-agent 1.0.0
# If this fails: pip install --force-reinstall -e .
```

### 2. Configure AWS Credentials

```bash
aws configure
# Verify:
aws sts get-caller-identity
```

### 3. Set Environment Variables

```bash
# Required:
export DEVOPS_AGENT_USER_ID=$(whoami)
export DEVOPS_AGENT_REGION=us-east-1

# Optional (only if you have an existing AgentSpace):
# export DEVOPS_AGENT_SPACE_ID="your-agent-space-id"
```

**Verify the SDK can reach the service:**

```bash
aws devops-agent list-agent-spaces --region us-east-1
# Success: returns {"agentSpaces": [...]} (may be empty)
```

### 4. Smoke Test — Verify Everything Works

Paste this and confirm you get a response:

```python
from aws_devops_agent import ACPClient
print(ACPClient.quick("What EC2 instances are running?"))
```

If this works, your install is complete! Skip to **Usage** below.

If it fails with "No AgentSpace found", continue to step 5 to create one.

### 5. IAM Setup (First-Time Only)

You need **two types of permissions**:

**A. Your IAM user/role** — to call `aidevops:*` APIs (create spaces, run investigations):

```bash
# Attach to your IAM user or role:
aws iam attach-user-policy --user-name <YOUR_USER> \
  --policy-arn arn:aws:iam::aws:policy/AIDevOpsAgentFullAccess

# Or for read-only access:
# --policy-arn arn:aws:iam::aws:policy/AIDevOpsAgentReadOnlyAccess
```

**B. Agent Space service role** — assumed by the DevOps Agent to investigate your resources:

```bash
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

cat > trust-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "aidevops.amazonaws.com" },
    "Action": "sts:AssumeRole",
    "Condition": {
      "StringEquals": { "aws:SourceAccount": "<ACCOUNT_ID>" },
      "ArnLike": { "aws:SourceArn": "arn:aws:aidevops:us-east-1:<ACCOUNT_ID>:agentspace/*" }
    }
  }]
}
EOF

aws iam create-role --role-name DevOpsAgentRole-AgentSpace \
  --assume-role-policy-document file://trust-policy.json

# Agent access policy — read-only access to 200+ AWS services for investigations
aws iam attach-role-policy --role-name DevOpsAgentRole-AgentSpace \
  --policy-arn arn:aws:iam::aws:policy/AIDevOpsAgentAccessPolicy

# Inline policy for Resource Explorer service-linked role creation
aws iam put-role-policy --role-name DevOpsAgentRole-AgentSpace \
  --policy-name ResourceExplorerSLR \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": "iam:CreateServiceLinkedRole",
      "Resource": "arn:aws:iam::*:role/aws-service-role/resource-explorer-2.amazonaws.com/AWSServiceRoleForResourceExplorer",
      "Condition": {
        "StringLike": { "iam:AWSServiceName": "resource-explorer-2.amazonaws.com" }
      }
    }]
  }'
```

> **Managed Policies Reference:**
> | Policy | Purpose |
> |--------|---------|
> | `AIDevOpsAgentFullAccess` | Full `aidevops:*` API access for users/admins |
> | `AIDevOpsAgentReadOnlyAccess` | Read-only `aidevops:Get*` + `List*` for users |
> | `AIDevOpsAgentAccessPolicy` | Agent service role — 200+ service read-only for investigations |
> | `AIDevOpsOperatorAppAccessPolicy` | Webapp operator access (optional) |
>
> See [AWS DevOps Agent IAM documentation](https://docs.aws.amazon.com/devopsagent/latest/userguide/security-iam.html) for details.

### 6. Create AgentSpace (First-Time Only)

Auto-create is **off by default**. Three ways to opt in:
1. SDK: `ACPClient(auto_create_space=True)`
2. ACP: `session/new` with `{"autoCreateSpace": true}`
3. Env: `export DEVOPS_AGENT_AUTO_CREATE_SPACE=true`

> **Note:** If AgentSpaces already exist, the SDK silently reuses the first one found — it does not create a new one. A new space is only created when none exist.

To create manually:

```bash
aws devops-agent create-agent-space \
  --name "MyAgentSpace" \
  --description "Monitoring my application" \
  --region us-east-1
```

### 7. Associate AWS Account

```bash
aws devops-agent associate-service \
  --agent-space-id <AGENT_SPACE_ID> \
  --service-id aws \
  --configuration '{
    "aws": {
      "assumableRoleArn": "arn:aws:iam::<ACCOUNT_ID>:role/DevOpsAgentRole-AgentSpace",
      "accountId": "<ACCOUNT_ID>",
      "accountType": "monitor",
      "resources": [
        {"resourceArn": "arn:aws:cloudformation:<REGION>:<ACCOUNT_ID>:stack/<STACK_NAME>/<STACK_ID>"}
      ]
    }
  }' \
  --region us-east-1
```

### 8. Optional Integrations

| Service | serviceId | Configuration Key | Key Fields |
|---------|-----------|-------------------|------------|
| GitHub | github | `github` | repoName, repoId, owner, ownerType |
| ServiceNow | (registered UUID) | `servicenow` | instanceUrl |
| Dynatrace | (registered UUID) | `dynatrace` | envId, resources[] |

For ServiceNow/Dynatrace, first `register-service` to get a serviceId, then `associate-service`.

## Usage

### Quick Queries (chat)

Simple questions like "check my alarms", "how many EC2 instances", "show Lambda errors" use chat — fast, single API call via `create_chat` + `send_message`.

### Knowledge & Skills Discovery

To discover what the agent knows, use investigations:

```
list_agent_spaces() → agentSpaceId
create_investigation(title="List all runbooks and knowledge items you have access to", agent_space_id=agentSpaceId, priority="LOW")
create_investigation(title="What AWS services are configured in this agent space?", agent_space_id=agentSpaceId, priority="LOW")
create_investigation(title="What investigation capabilities do you have?", agent_space_id=agentSpaceId, priority="LOW")
```

Run this when first setting up an AgentSpace, after adding runbooks, or before complex investigations.

### Investigation (deep analysis)

Questions with words like "investigate", "root cause", "outage", "debug" trigger a **parallel investigation** — the agent starts a background analysis task (5-8 min) while answering immediately via chat. Investigation progress streams via journal polling every 30-45 seconds.

## Regions

- **us-east-1** (recommended)

## Verification

```bash
# Verify SDK:
python3 -c "from aws_devops_agent import ACPClient; print(ACPClient.quick('List my agent spaces'))"
```
