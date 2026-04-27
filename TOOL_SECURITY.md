# Security — AWS DevOps Agent

The AWS DevOps Agent integrates with AI coding assistants (Kiro, Claude, Cursor) to provide AWS operational intelligence. This document covers the security model for connecting the agent to external MCP servers and handling untrusted data.

## Architecture Overview

```
┌──────────────────────┐         ┌─────────────────────────┐
│  AI Coding Assistant │ ──────> │  AWS DevOps Agent API   │
│  (Kiro, Claude, etc) │ <────── │  (via MCP or ACP)       │
└──────────────────────┘         └─────────────────────────┘
                                            │
                                            v
                                  ┌──────────────────┐
                                  │  AWS Services    │
                                  │  CloudWatch, IAM │
                                  │  X-Ray, etc.     │
                                  └──────────────────┘
```

**Data Flow:**
- **AI → Agent**: Prompts with local context (file contents, error messages, git diffs)
- **Agent → AI**: Streaming responses with findings, recommendations, remediation steps
- **No reverse tool execution**: The DevOps Agent **does not** call back into the AI's local tools (filesystem, terminal, etc.)

## Threat Model

### 1. Prompt Injection (External MCP Servers)

**Risk**: If you connect external MCP servers to the DevOps Agent (e.g., custom observability tools, monitoring systems), malicious or compromised servers could inject adversarial prompts that manipulate the agent's responses.

**Mitigations**:
- **Tool Allowlisting**: Only allowlist specific read-only tools from each MCP server — never grant blanket "all tools" access
- **Read-Only Credentials**: Ensure MCP server authentication uses read-only IAM roles/credentials
- **Tool Approval**: Enable tool approval in your AI client (see "Tool Approval Recommendations" below)
- **Audit Logs**: Enable AWS CloudTrail to monitor DevOps Agent API calls

See [AWS DevOps Agent Security Documentation](https://docs.aws.amazon.com/devopsagent/latest/userguide/aws-devops-agent-security.html) for detailed guidance.

### 1b. Tool Sharing via Chat Responses

**Risk**: The `send_message` tool returns text from the DevOps Agent. This text flows back into the AI assistant's context as a tool result. If the agent's response contains instructions that look like tool calls (e.g., "run `rm -rf /`" or "call execute_command with..."), the AI assistant might interpret and execute them.

**Mitigations**:
- **Text-only responses**: The `send_message` MCP tool strips raw event payloads and returns only extracted text — no function_call events, tool_use blocks, or structured tool invocations are passed through
- **Boundary marker**: Every response includes a note instructing the AI assistant not to execute commands found in the text without user approval
- **No auto-approve for write tools**: `create_investigation`, `create_agent_space`, `start_evaluation`, `update_recommendation`, and `send_message` require user confirmation. `send_message` is the tool through which the prompt injection risk materializes, so the user approval gate is the strongest mitigation
- **Human-in-the-loop**: The AI assistant should always present the agent's response to the user and require explicit approval before acting on any suggestions

### 2. Sensitive Data Exposure

**Risk**: The AI sends local context (file contents, logs, environment variables) to the DevOps Agent, which processes it in AWS.

**Mitigations**:
- **Review before sending**: Use AI clients with approval gates to review prompts before submission
- **Redact secrets**: Never include AWS credentials, API keys, or passwords in prompts
- **Use IAM policies**: Scope DevOps Agent permissions to least-privilege (read-only where possible)

### 3. Unintended AWS Actions

**Risk**: The DevOps Agent provides recommendations that include AWS CLI commands, IaC changes, or scripts. If executed without review, these could impact production.

**Mitigations**:
- **Human-in-the-loop**: Always review generated code/scripts before execution
- **Test in non-prod first**: Apply recommendations to dev/staging environments before production
- **Use investigations over chat**: The investigation workflow provides structured, auditable analysis

## Security Best Practices

### 1. Tool Approval Recommendations

Configure your AI coding assistant to **require approval** for all DevOps Agent tool calls:

| AI Client | Configuration |
|-----------|---------------|
| **Kiro** | Add `"requireApproval": true` to `~/.kiro/settings/mcp.json` under the DevOps Agent server entry |
| **Claude Desktop** | Use "Ask before running tools" setting in preferences |
| **Cursor** | Enable "Manual tool approval" in settings |

**Why this matters**: Without approval, the AI can autonomously trigger investigations, which consume AWS API quota and may incur costs. Approval gates give you visibility and control.

### 2. Connecting External MCP Servers

If you register custom MCP servers with the DevOps Agent (e.g., for Datadog, PagerDuty, custom metrics):

**Checklist**:
- [ ] Use HTTPS endpoints only
- [ ] Authenticate with OAuth 2.0 or API keys (not basic auth)
- [ ] Only allowlist specific read-only tools — never "all tools"
- [ ] Grant read-only IAM permissions to MCP server credentials
- [ ] Regularly rotate API keys/tokens
- [ ] Monitor CloudTrail logs for suspicious API patterns

### 3. Local Context Handling

When the AI sends local context to the agent:

**Safe practices**:
- ✅ File excerpts (code snippets, config files)
- ✅ Error messages and stack traces (after redacting secrets)
- ✅ Git diffs and commit messages
- ✅ Resource ARNs

**Unsafe practices**:
- ❌ AWS credentials, API keys, private keys
- ❌ PII or customer data
- ❌ Unredacted environment variables

## Shared Responsibility Model

| You (the user) | AWS DevOps Agent Service |
|----------------|--------------------------|
| Configure tool approval in AI client | Validate API requests and enforce IAM policies |
| Review generated code before execution | Provide sandboxed investigation environment |
| Manage IAM permissions for agent access | Encrypt data in transit and at rest |
| Vet and allowlist external MCP servers | Log API calls to CloudTrail |
| Redact secrets from prompts | Monitor for service-side anomalies |

## Additional Resources

- [AWS DevOps Agent Security](https://docs.aws.amazon.com/devopsagent/latest/userguide/aws-devops-agent-security.html)
- [Configuring MCP Servers](https://docs.aws.amazon.com/devopsagent/latest/userguide/configuring-capabilities-for-aws-devops-agent-connecting-mcp-servers.html)
- [Prompt Injection Protection](https://docs.aws.amazon.com/devopsagent/latest/userguide/security-prompt-injection.html)

---

## Reporting Security Issues

If you discover a security vulnerability, please report it through the
[AWS vulnerability reporting page](https://aws.amazon.com/security/vulnerability-reporting/).
Do **not** create a public GitHub issue for security vulnerabilities.

---

**License**: MIT-0
**Repository**: https://github.com/aws-samples/sample-aws-devops-agent-acp-mcp
