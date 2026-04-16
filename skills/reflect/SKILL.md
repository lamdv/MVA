---
name: reflect
description: Reflect on agent performance and identify improvement opportunities
---

# Reflect on Performance

Use this skill to manually review how well the agent performed on a task and identify gaps.

## What is Reflection?

Reflection is analyzing what happened in a session:
- Which tools worked well?
- Which tools failed?
- Were there missing capabilities?
- What patterns emerged?
- How can future sessions improve?

Telemetry data lives in `sandbox/telemetry/sessions/` with per-tool statistics.

## Step 1: Review Session Telemetry

Check the most recent session:

```bash
cat sandbox/telemetry/sessions/*.json | python -m json.tool
```

Look for:
- **total_tool_calls**: How many tools were used?
- **success_rate**: What percentage succeeded?
- **failed_tool_calls**: Which tools failed?
- **tools_used**: What was the tool mix?

## Step 2: Analyze Tool Performance

For each tool that failed, check:
- What was the error?
- Was it a missing feature? (e.g., no HTTP library)
- Was it incorrect usage?
- Was it a data problem?

Example from telemetry:
```json
{
  "tool_name": "code_execution",
  "success": false,
  "error": "ModuleNotFoundError: No module named 'requests'",
  "latency_ms": 150
}
```

**Question**: Should we generate an `http_fetch` tool using stdlib?

## Step 3: Check Cross-Session Memory

```bash
cat sandbox/telemetry/memory.json | python -m json.tool
```

This shows:
- Tool statistics across all sessions
- Known patterns and issues
- Previously generated tools/skills

## Step 4: Identify Gaps

Ask these questions:

1. **Missing Tools**: Were there operations the agent couldn't do?
   - "Can't fetch from HTTP" → Generate http_fetch tool
   - "Can't parse XML" → Consider XML parser tool

2. **Slow Tools**: Were there bottlenecks?
   - "code_execution took 30 seconds" → Worth optimizing?
   - "read_file is slow on large files" → Add a summary tool?

3. **Repeated Failures**: Did the agent retry the same thing?
   - Failing pattern = opportunity for new tool or skill

4. **Workarounds**: Did the agent use clunky workarounds?
   - Verbose solution = opportunity for simpler tool

## Step 5: Document Insights

Create insight table for each category:

### Tool Insights
| Tool | Issue | Detail |
|------|-------|--------|
| code_execution | missing | No HTTP GET without requests |
| read_file | slow | Large files take time |

### Skill Insights
| Pattern | Action | Name |
|---------|--------|------|
| Fetch data from HTTP APIs | create | http-fetch |
| Process CSV data | create | csv-analysis |

## Step 6: Prioritize Improvements

Ask: What gives the most value?

**High Value**:
- Tools for common patterns (HTTP, CSV, JSON)
- Skills for complex workflows
- Performance fixes for slow operations

**Low Value**:
- One-off special cases
- Duplication of existing tools
- Niche operations

## Step 7: Document the Reflection

Write findings to markdown:

```markdown
---
session_id: uuid
created_at: ISO8601
trigger: user_manual_review
---

## What Happened

Agent tried to fetch Bitcoin prices. Failed first with requests library (not in sandbox).
Worked around using urllib. Session success rate: 85%.

## Tool Insights
| Tool | Issue | Detail |
|------|-------|--------|
| code_execution | missing | No HTTP library; urllib works but verbose |

## Skill Insights
| Pattern | Action | Name |
|---------|--------|------|
| Fetch data from HTTP APIs | create | http-fetch |

## Recommendations

1. Generate http_fetch tool using stdlib urllib
2. Consider generic http_post tool for API writes
3. Document API patterns as http-integration skill
```

## Manual Review Process

If you want to manually review without running code:

1. Check `sandbox/telemetry/memory.json` for stats
2. Read one or more session files
3. Write observations as markdown in `sandbox/telemetry/reflections/`
4. Use insights table format
5. Recommend actions (create tool, create skill, etc)

## When NOT to Reflect

Skip reflection if:
- Agent succeeded 100% of tool calls
- All used tools are already documented
- No clear pattern to address
- One-off failures that won't repeat

## Common Reflection Patterns

### Pattern 1: Missing Library
```
Tool: code_execution
Error: ModuleNotFoundError: requests
Solution: Create stdlib-based http_fetch tool
```

### Pattern 2: Repeated Manual Steps
```
Tool: read_file (8x), code_execution (5x)
Error: Agent kept reading file, parsing it manually
Solution: Create csv_analysis tool that does this automatically
```

### Pattern 3: Slow Operation
```
Tool: code_execution
Latency: 5000+ ms
Error: Large file processing
Solution: Create specialized json_extract or csv_filter tool
```

---

**Use this skill for manual review of telemetry. Phase 2 (Reflect) will automate this with LLM analysis.**
