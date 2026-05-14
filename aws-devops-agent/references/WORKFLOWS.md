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

## Mitigation Workflow (Post-Investigation)

**When to use**: After an investigation completes, to generate actionable fix plans

**Duration**: 2-5 minutes (async)

**Steps**:
1. Ensure investigation is `COMPLETED` (via `get_task`)
2. `create_mitigation_plan(task_id)` → sets status to `PENDING_START`
3. Poll `get_task(task_id)` every 30-45s until `COMPLETED` again
4. `list_executions(task_id)` → find the newest execution (mitigation run)
5. `list_journal_records(execution_id, record_type="mitigation_summary_md")`
6. Generate remediation code from the mitigation summary

**What happens**: The Mitigation Agent analyzes the investigation's root cause findings
and generates a mitigation plan stored as `mitigation_summary_md` in journal records.
Retrieve it via `list_executions(task_id)` → `list_journal_records(execution_id)`.

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

**License**: MIT-0 | **Repository**: https://github.com/aws-samples/sample-aws-devops-agent-acp-mcp
