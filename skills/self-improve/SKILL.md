---
name: self-improve
description: 'Read telemetry and reflections, generate new tools and skills into sandbox/telemetry/generated_*/. Use when asked to improve, learn from past sessions, or act on reflection insights.'
---

# Self-Improve

Generates new tools and skills from telemetry and reflection data. Output lands in
`sandbox/telemetry/generated_*/` — nothing is auto-loaded. User promotes files they trust.

---

## Step 1: Find the Latest Reflection

```python
import os, glob
files = sorted(glob.glob("sandbox/telemetry/reflections/*.md"), key=os.path.getmtime)
print(files[-1] if files else "NO_REFLECTIONS")
```

If no reflections exist, run the `reflect` skill first, then come back.

Read the latest reflection file with `read_file`.

---

## Step 2: Read Cross-Session Memory

```python
import json
data = json.load(open("sandbox/telemetry/memory.json"))
print(json.dumps(data["tool_stats"], indent=2))
print("Already generated:", data.get("generated_tools", []), data.get("generated_skills", []))
```

---

## Step 3: Identify What to Generate

From the reflection, extract two tables:

**Tool candidates** — rows from `### Tool Insights` where Issue = `missing`:
- Skip if already in `generated_tools` list from memory.json
- Skip if it duplicates a built-in (`read_file`, `write_file`, `list_files`, `code_execution`)
- Skip if it needs an external package (requests, pandas, etc) — use stdlib only

**Skill candidates** — rows from `### Skill Insights` where Action = `create`:
- Skip if already in `generated_skills` list from memory.json
- Skip if it's a one-off (not reusable across sessions)

If nothing qualifies, report "Nothing to generate" and stop.

---

## Step 4: Generate Tools

For each tool candidate, write a Python function to `sandbox/telemetry/generated_tools/<name>.py`.

Rules:
- `@sandbox` decorator if the function touches files
- stdlib only: `json`, `re`, `pathlib`, `os.path`, `urllib`, `csv`, `ast`, `statistics`
- All parameters type-hinted
- Return a dict (JSON-serializable)
- Clear docstring explaining purpose and when to use it
- Prefix name with `safe_` or `robust_` if replacing a failing built-in

Example — agent kept failing on HTTP fetches:

```python
# sandbox/telemetry/generated_tools/http_fetch.py
def http_fetch(url: str, timeout: int = 10) -> dict:
    """Fetch content from an HTTP URL using stdlib urllib.
    
    Use when: you need to GET data from a web API or URL.
    
    Returns dict with: success (bool), status_code (int), content (str), error (str)
    """
    import urllib.request, urllib.error
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return {"success": True, "status_code": r.status, "content": r.read().decode()[:10000]}
    except urllib.error.URLError as e:
        return {"success": False, "error": str(e.reason)}
    except Exception as e:
        return {"success": False, "error": str(e)}
```

**After writing each file, validate it:**

```python
import ast
code = open("sandbox/telemetry/generated_tools/http_fetch.py").read()
try:
    ast.parse(code)
    print("OK")
except SyntaxError as e:
    print(f"SYNTAX ERROR: {e}")
```

If validation fails, delete the file and log the failure. Do not leave broken files.

---

## Step 5: Generate Skills

For each skill candidate, write a SKILL.md to `sandbox/telemetry/generated_skills/<name>/SKILL.md`.

Structure:

```markdown
---
name: <slug>
description: '<one sentence>. Use when <trigger>.'
---

# <Title>

<One paragraph: what this skill teaches and when to use it.>

## Step 1: <First action>
<What to do. Include a code block if the step involves code_execution.>

## Step 2: <Next action>
...

## Common Mistakes
- <What goes wrong>

## Example
<Concrete walkthrough from start to finish.>
```

Keep it to 4-6 steps. Concise beats comprehensive.

---

## Step 6: Update Memory

```python
import json
from datetime import datetime

mem = json.load(open("sandbox/telemetry/memory.json"))
mem.setdefault("generated_tools", [])
mem.setdefault("generated_skills", [])

# Append what was generated (avoid duplicates)
for name in ["http_fetch"]:  # replace with actual names
    if name not in mem["generated_tools"]:
        mem["generated_tools"].append(name)

mem["last_updated"] = datetime.utcnow().isoformat() + "Z"
open("sandbox/telemetry/memory.json", "w").write(json.dumps(mem, indent=2))
```

---

## Step 7: Report

Summarize what was generated:

```
Generated tools:
  ✓ sandbox/telemetry/generated_tools/http_fetch.py
  ✗ json_query.py — syntax error, skipped

Generated skills:
  ✓ sandbox/telemetry/generated_skills/http-integration/SKILL.md

Nothing generated:
  - csv_analysis: already in generated_tools list
  - file-search: one-off, not reusable

To promote:
  cp sandbox/telemetry/generated_tools/http_fetch.py tools/
  cp -r sandbox/telemetry/generated_skills/http-integration/ sandbox/engine/skills/
  uv run mva list   # verify discovery
```

---

## When NOT to Generate

- Built-in already handles it (`read_file`, `write_file`, `list_files`, `code_execution`)
- Needs an external package
- Solves a one-off problem from a single session
- Already in `memory.json["generated_tools"]` or `["generated_skills"]`
- Requires system access, subprocess, or socket
