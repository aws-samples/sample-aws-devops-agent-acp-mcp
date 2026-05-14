# Changelog — AWS DevOps Agent (Sample ACP Client, Server & MCP Server)

All notable changes are documented here. Format based on [Keep a Changelog](https://keepachangelog.com/).

## [1.1.0] - 2026-05-14

### Added

- **`create_mitigation_plan` MCP tool** — Generates mitigation plans for completed investigations by setting task status to `PENDING_START`, activating the Mitigation Agent to produce actionable recommendations.
- **Mitigation Workflow documentation** in WORKFLOWS.md, SKILL.md, POWER.md, CLAUDE.md, and README.md.

### Changed

- MCP tool count: 19 → 20

## [1.0.0] - 2026-03-31

### Added

- **19 MCP Tools** for operational intelligence:
  - Agent Space Management: `list_agent_spaces`, `get_agent_space`, `create_agent_space`, `list_associations`
  - Investigations: `create_investigation`, `get_task`, `list_tasks`
  - Findings: `list_journal_records`, `list_executions`
  - Chat: `create_chat`, `list_chats`, `send_message`
  - Recommendations: `list_recommendations`, `get_recommendation`, `update_recommendation`
  - Goals & Evaluation: `list_goals`, `start_evaluation`
  - Service Discovery: `list_services`, `get_service`
- **ACP Client SDK** — Streaming prompt/response Python client
- **Thinking Events** — Client-side contextual messages during processing (13 keyword patterns, 2-stage timing)
- **GA SDK Integration** — Unified `boto3.client('devops-agent')`
- **Investigation Workflow** — Deep async root cause analysis with structured journal records and recommendations
- **Streaming Deduplication** — Content block type filtering with cross-block repeat detection
- **Kiro Powers** — Two integration paths:
  - `kiro-power/` — Standalone MCP server with direct tool access
  - AWS MCP Server power — published separately at [kirodotdev/powers](https://github.com/kirodotdev/powers)
- **Security Documentation** — TOOL_SECURITY.md covering MCP server security, tool approval, threat model
- **110 Unit Tests** — Streaming, GA event formats, deduplication, core SDK

### Changed

- **Unified Client** — `get_client()` returns single `devops-agent` boto3 client
- **GA Event Format** — `contentBlockStart`/`contentBlockDelta` with type-based filtering

### Removed

- **Pre-GA Service Models** — Native boto3 service definitions used instead
- **Setup CLI** — Model installation no longer needed
- **Pre-GA Endpoints** — GA SDK auto-resolves endpoints

---

**Full Changelog**: https://github.com/aws-samples/sample-aws-devops-agent-acp-mcp/commits/main
