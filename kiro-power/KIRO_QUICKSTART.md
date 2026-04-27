# Kiro Quick Start — AWS DevOps Agent

Step-by-step guide for Kiro (or any AI agent) to set up the AWS DevOps Agent.

## ACP vs MCP

| | ACP | MCP |
|---|---|---|
| **How** | Python SDK (`ACPClient`) — streaming | 19 native tools in Powers panel |
| **Tool sharing** | ✅ Streaming prompt/response | ❌ One-directional (Kiro → Agent only) |
| **Config needed** | `pip install` only — no mcp.json, no reload | mcp.json + Kiro reload |
| **Python version** | 3.10+ | 3.10+ |
| **Best for** | Investigations, collaborative debugging | Quick tool access, simple queries |

**Recommendation:** Use **ACP** — simplest setup, streaming interaction. Use **MCP** for 19 discrete tools in the Powers panel. For the AWS MCP Server (all 40 DevOps Agent APIs + 15,000+ AWS APIs), see the published [Kiro Power](https://github.com/kirodotdev/powers).

---

## Step 0: Install & Verify (Both Paths)

```bash
cd /path/to/AWSDevOpsAgentACPMCP
pip install -e .
```

Verify (catches stale binaries from previous installs):

```bash
aws-devops-agent --version
# Expected: aws-devops-agent 1.0.0
# If this fails: pip install --force-reinstall -e .
```

Set environment variables:

```bash
export DEVOPS_AGENT_USER_ID=$(whoami)
export DEVOPS_AGENT_REGION=us-east-1
```

Quick test to verify everything works end-to-end:

```bash
python3 -c "from aws_devops_agent import ACPClient; print(ACPClient.quick('List my agent spaces'))"
```

If you see AgentSpace results, the install is good! `ACPClient.quick()` is one-shot only — no streaming. Use it for testing, then use the full streaming API below.

> **Note on AgentSpaces:** If you already have AgentSpaces, the SDK silently reuses the first one it finds — it doesn't create a new one. A new space is only created when none exist and `auto_create_space=True` is passed. To target a specific space, pass `space_id="your-space-id"`.

---


## MCP Setup (Native Tools)

Use this if you want 19 discrete tools in Kiro's Powers panel (`create_investigation`, `list_journal_records`, `create_chat`, `send_message`, etc.). The agent provides results via structured journal records, recommendations, and real-time chat.

### Step 1: Install MCP Support

```bash
pip install -e '.[mcp]'
```

> MCP requires Python 3.10+. If this fails, install 3.10 via `uv venv --python 3.10`, or use ACP instead.

### Step 2: Find the Binary Path

```bash
which aws-devops-agent
# Example: /home/user/.venv/bin/aws-devops-agent
```

### Step 3: Configure mcp.json

Edit `kiro-power/mcp.json` — replace the two placeholders:

```json
{
  "mcpServers": {
    "aws-devops-agent": {
      "command": "<REPLACE_WITH_BINARY_PATH>",
      "args": ["mcp"],
      "env": {
        "DEVOPS_AGENT_USER_ID": "<REPLACE_WITH_YOUR_USERNAME>",
        "DEVOPS_AGENT_REGION": "us-east-1"
      }
    }
  }
}
```

### Step 4: Place the Config & Reload

```bash
mkdir -p .kiro/settings
cp kiro-power/mcp.json .kiro/settings/mcp.json
```

Reload Kiro: Command Palette → **"Developer: Reload Window"**

### Step 5: Verify

Open the **Powers** panel — you should see **AWS DevOps Agent** with **19 tools**.

---

## Reference: SKILL.md

The `aws-devops-agent/SKILL.md` provides workflow guidance for investigations, chat, knowledge discovery, journal streaming, and multi-space steering — regardless of which integration path you choose.

---

## Troubleshooting

**"ExpiredTokenException"**
→ AWS credentials expired. Refresh credentials (e.g., `aws sso login` or update access keys via `aws configure`).

**"No AgentSpace found"**
→ Pass `auto_create_space=True` to `ACPClient()`, or set `DEVOPS_AGENT_AUTO_CREATE_SPACE=true` in env.

**"Failed to find or create AgentSpace"**
→ Check IAM permissions (`AIDevOpsAgentFullAccess` on your user, `AIDevOpsAgentAccessPolicy` on agent role). See [ONBOARDING.md](../aws-devops-agent/references/ONBOARDING.md).

**`aws-devops-agent --version` fails or shows import error**
→ Stale binary from a previous install. Fix: `pip install --force-reinstall -e .`

**`pip install -e '.[mcp]'` fails — "No matching distribution found for mcp"**
→ MCP requires Python 3.10+. Install 3.10 if needed: `uv venv --python 3.10`

**0 tools in Powers panel (MCP path)**
→ Check `mcp.json` has the correct absolute binary path. Test: `/full/path/to/aws-devops-agent mcp`

**"Connection error" in ACP mode**
→ Verify ACP server is running and the connection URL is correct. Check `ACPClient()` configuration and network connectivity.
