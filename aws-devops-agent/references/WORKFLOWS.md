# Workflows — AWS DevOps Agent

Quick reference for choosing the right workflow.

## Investigation Workflow (Primary)

**When to use**: Root cause analysis, incidents, troubleshooting, cost optimization, architecture review

**Duration**: 5-8 minutes (async)

**Steps**:
1. `create_investigation(title, priority, description)` → `taskId`
2. Poll `get_task(taskId)` every 30-45s until `IN_PROGRESS` → `executionId`
3. Stream `list_journal_records(executionId)` every 30-45s
4. Once `COMPLETED`: `list_recommendations()` → `get_recommendation()`

**Best practices**:
- Pack local context into `description`: file contents, git diffs, error messages, IaC state
- Use descriptive titles: "ECS 503 after deploy" > "debug ECS"
- Stream journal findings to the user — don't silently poll

## Knowledge Discovery (Instant)

**When to use**: Exploring capabilities, finding configured services, listing goals

**Tools**:
- `list_services()` → Registered AWS accounts, repos, MCP servers
- `list_goals()` → Evaluation goals (cost, security, etc.)
- `list_agent_spaces()` → Available agent spaces

## Decision Matrix

| User Intent | Workflow | Duration |
|-------------|----------|----------|
| "My service is down" | Investigation | 5-8 min |
| "Optimize my AWS costs" | Investigation | 5-8 min |
| "Review terraform security" | Investigation | 5-8 min |
| "What services are configured?" | Knowledge Discovery | Instant |
| "What goals exist?" | Knowledge Discovery | Instant |

## Tips

1. **Always include local context** — the agent is more effective with IaC state, recent changes, and error messages
2. **Use investigations for everything operational** — structured, auditable, actionable
3. **Stream progress** — poll journal records, show findings in real-time
4. **Review before applying** — test recommendations in non-prod first

---

**License**: MIT-0 | **Repository**: https://github.com/awslabs/mcp
