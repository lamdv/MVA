---
name: create-skill
description: Author new SKILL.md workflow files for MVA agents
---

# Create Skill

Use this skill when you need to author a new high-level workflow (SKILL.md) for agents.

## What is a Skill?

A **Skill** is a markdown-based workflow that guides an agent through a multi-step task. It:
- Teaches a specific domain pattern or best practice
- Breaks complex tasks into manageable steps
- Provides concrete examples and templates
- Uses agent tools (read_file, write_file, code_execution, etc)
- Is discoverable and reusable across sessions

## Step 1: Identify the Skill's Purpose

Ask:
1. **What pattern does this teach?** (e.g., "Data analysis", "Web scraping", "API integration")
2. **Who will use it?** (Agent or human reviewing the task)
3. **What tools will it require?** (read_file, write_file, code_execution, custom tools)
4. **How many steps?** (usually 3-7 concrete steps)

## Step 2: Skill Structure

Every SKILL.md has:

```markdown
---
name: skill-name
description: One-line description of what this skill teaches
---

# Skill Title

Clear intro paragraph explaining the pattern.

## Step 1: [First Action]
What to do and why.

## Step 2: [Second Action]
More details, code examples if needed.

...

## Step N: [Final Action]
How to verify success.

## Common Mistakes
- What to avoid
- What breaks the pattern

## Example Walkthrough
Show a concrete example from start to finish.
```

## Step 3: Write Each Step

### ✅ Good Step:
```markdown
## Step 1: Load the Data

Use `read_file` or `code_execution` to load the CSV into a pandas DataFrame.

If using code_execution:
\`\`\`python
import pandas as pd
df = pd.read_csv("data.csv")
print(df.head())
\`\`\`

Look for: Missing values, data types, shape (rows/columns).
```

### ❌ Avoid:
- Vague instructions ("use the tool")
- Unexplained abbreviations
- Skipping error cases
- Assuming knowledge of advanced tools

## Step 4: Best Practices

### ✅ DO:
- Use markdown formatting (headers, code blocks, lists)
- Include concrete code examples
- Explain WHY each step matters
- Provide alternative approaches when relevant
- Cover common errors and how to fix them
- Reference the tools available (read_file, write_file, code_execution, list_files)

### ❌ DON'T:
- Use only high-level abstractions without examples
- Assume the agent knows domain-specific shortcuts
- Skip error handling ("this never fails")
- Make steps too granular (30 steps) or too coarse (1 step)
- Assume external tools exist (requests, pandas, etc) without code_execution

## Step 5: Common Skill Patterns

### Pattern: Data Analysis
```markdown
# Data Analysis Workflow

## Step 1: Load and Explore
Load your data and examine its structure.

## Step 2: Clean
Remove duplicates, handle missing values.

## Step 3: Analyze
Calculate summaries, find patterns.

## Step 4: Visualize
Create charts to communicate findings.

## Step 5: Report
Save results to output file.
```

### Pattern: Code Refactoring
```markdown
# Code Refactoring Workflow

## Step 1: Read the Original Code
Understand current structure and behavior.

## Step 2: Identify Issues
Find code smells, performance problems, etc.

## Step 3: Plan Refactoring
Design the improved structure.

## Step 4: Implement
Write the refactored code.

## Step 5: Test
Verify behavior is preserved.

## Step 6: Compare
Show before/after to demonstrate improvement.
```

### Pattern: Multi-Tool Workflow
```markdown
# Generate a Report

## Step 1: Gather Data
Read files, compute metrics, fetch external data.

## Step 2: Process
Transform raw data into report format.

## Step 3: Render
Create formatted output (JSON, CSV, Markdown, HTML).

## Step 4: Save
Write report to file.

## Step 5: Verify
Check file exists and content is correct.
```

## Step 6: Frontmatter

Every SKILL.md starts with YAML frontmatter:

```yaml
---
name: skill-name
description: One-line description for the skill catalog
---
```

Rules:
- `name`: slug format (lowercase, hyphens, no spaces) — must be unique
- `description`: 1-2 sentences explaining the pattern
- These are extracted by `SkillCatalog` for the skill menu

## Step 7: File Location

New skill goes in: `sandbox/engine/skills/<skill-name>/SKILL.md`

Example:
```
sandbox/engine/skills/
├── data-analysis/
│   └── SKILL.md
├── api-integration/
│   └── SKILL.md
└── code-refactoring/
    └── SKILL.md
```

The agent discovers skills automatically from this directory.

## Step 8: Validation Checklist

Before submitting the skill, verify:
- [ ] YAML frontmatter present (name, description)
- [ ] Clear, numbered steps (Step 1, Step 2, etc)
- [ ] Code examples in each step (if applicable)
- [ ] Tools referenced exist (read_file, write_file, code_execution, list_files)
- [ ] Error cases mentioned
- [ ] Common mistakes section included
- [ ] Example walkthrough provided
- [ ] No assumed external packages

## Example: HTTP API Integration Skill

```markdown
---
name: http-api-fetch
description: Fetch and parse data from HTTP APIs using stdlib urllib
---

# HTTP API Integration

Learn to integrate with REST APIs using Python's built-in urllib.

## Step 1: Understand the API

Read the API documentation:
- Base URL
- Authentication (if any)
- Rate limits
- Response format (usually JSON)

Use code_execution to test a simple request:
\`\`\`python
import urllib.request
import json

url = "https://api.example.com/data"
try:
    with urllib.request.urlopen(url) as response:
        data = json.loads(response.read())
    print(f"Got {len(data)} records")
except Exception as e:
    print(f"Error: {e}")
\`\`\`

## Step 2: Parse the Response

Extract the fields you need:
\`\`\`python
for item in data:
    print(item.get('name'), item.get('value'))
\`\`\`

## Step 3: Handle Errors

Check status codes and error responses:
\`\`\`python
try:
    response = urllib.request.urlopen(url, timeout=10)
    if response.status == 200:
        data = json.loads(response.read())
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}: {e.reason}")
except Exception as e:
    print(f"Failed: {e}")
\`\`\`

## Step 4: Save Results

Write parsed data to file:
\`\`\`python
import json
with open('output.json', 'w') as f:
    json.dump(data, f, indent=2)
\`\`\`

## Common Mistakes

- **Missing timeout**: Always set timeout to avoid hanging
- **No error handling**: APIs fail; handle HTTP errors gracefully
- **Parsing errors**: Verify JSON structure before accessing fields
- **Rate limiting**: Respect API rate limits; add delays if needed

## Example Walkthrough

Fetch cryptocurrency prices:

1. Find an API: (hypothetical) https://api.prices.example/crypto
2. Fetch: GET /crypto?coin=btc
3. Parse: Extract "price" field
4. Save: Write to prices.json
```

---

**Use this skill when Phase 3 (Improve) needs to generate a new high-level workflow based on identified patterns.**
