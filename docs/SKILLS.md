# Skills System

Skills are high-level, guided workflows that teach the agent to approach complex tasks systematically. Unlike tools (low-level functions), skills are reusable patterns and procedures.

## Overview

**Tools** = Low-level actions
- `read_file()`, `write_file()`, `code_execution()`
- Direct function calls
- Return results immediately

**Skills** = High-level workflows
- Multi-step procedures
- Guidance and structure
- Teaching patterns to the agent

## Creating Skills

### Structure

Skills live in a structured directory:

```
sandbox/engine/skills/
├── skill-name/
│   └── SKILL.md
├── another-skill/
│   └── SKILL.md
└── complex-skill/
    ├── SKILL.md
    ├── resources/
    │   └── example.py
    └── templates/
        └── template.txt
```

### SKILL.md Format

Each skill requires a `SKILL.md` file with YAML frontmatter and Markdown content:

```yaml
---
name: skill-name
description: Short description of what this skill does
---

# Skill Name

Full instructions for using this skill.

## Step 1: Preparation
- Explain what to prepare
- List any prerequisites

## Step 2: Execution
- Detailed steps
- Examples
- Code snippets

## Step 3: Validation
- How to verify success
- Common issues
```

**Frontmatter (required):**
- `name` — Unique identifier (used in `load_skill(name)`)
- `description` — Short description shown in skill catalog

### Example: Data Analysis Skill

```yaml
---
name: data-analysis
description: Perform exploratory data analysis on CSV files
---

# Data Analysis Skill

This skill guides you through analyzing a dataset using Python.

## Step 1: Load the Data

Load the CSV file and inspect its structure:

\`\`\`python
import pandas as pd

df = pd.read_csv("data.csv")
print(df.head())
print(df.info())
print(df.describe())
\`\`\`

## Step 2: Explore Patterns

Look for trends, outliers, and correlations:

\`\`\`python
import matplotlib.pyplot as plt

# Plot distributions
df.hist()
plt.show()

# Check for missing values
print(df.isnull().sum())
\`\`\`

## Step 3: Summarize Findings

Create a summary of key insights:

- What are the main distributions?
- Are there missing values?
- What correlations exist?
- Any outliers to investigate?

## Tools You'll Need

- `write_file()` — Save analysis results
- `code_execution()` — Run Python analysis
```

---

## Using Skills

### Via LLM Chat

The agent automatically discovers skills and shows them in the system prompt:

```
## Available Skills
Skills are high-level workflows...

- **data-analysis**: Perform exploratory data analysis on CSV files
- **web-scraping**: Extract and parse data from websites

**How to use skills:**
1. Call `load_skill(name)` to read the full skill instructions
2. Follow the step-by-step workflow...
```

When the user asks for help with a task, the agent can:

```
User: I need to analyze sales data
Agent: I can help with that! Let me load the data-analysis skill...

🔧 Calling load_skill(data-analysis)
[Loads full SKILL.md content]

Now I'll follow the steps in the skill to analyze your data...
```

### Via Python API

```python
from mva.agent import get_agent

agent = get_agent(skills_dir="./sandbox/engine/skills/")

# Skills automatically loaded and available
history = [{
    "role": "user",
    "content": "Analyze this data using the data-analysis skill"
}]

response = agent.run(history)
```

### Manual Skill Loading

```python
from mva.agent.skills import SkillCatalog

catalog = SkillCatalog("./sandbox/engine/skills/")
catalog.refresh()

# Load a skill manually
skill_content = catalog.load_skill("data-analysis")
print(skill_content)
```

---

## Skill Categories

### Data Processing
- **data-analysis**: Exploratory data analysis
- **data-cleaning**: Normalize and validate data
- **data-transformation**: Reshape and restructure data

### Code & Development
- **debugging**: Systematic debugging approach
- **refactoring**: Code improvement patterns
- **testing**: Test design and implementation

### Writing & Documentation
- **technical-writing**: Structure and clarity for docs
- **api-documentation**: OpenAPI/API doc generation
- **code-documentation**: Comment and docstring guidelines

### Research & Analysis
- **literature-review**: Structured research approach
- **competitive-analysis**: Market research methodology
- **architecture-design**: System design patterns

---

## Best Practices

### 1. Clear Step-by-Step Instructions

❌ **Bad:**
```markdown
# Web Scraping Skill

Use requests and BeautifulSoup to scrape websites.
```

✅ **Good:**
```markdown
# Web Scraping Skill

## Step 1: Set Up
1. Install required packages: `pip install requests beautifulsoup4`
2. Import the libraries

## Step 2: Fetch Page
1. Use `requests.get(url)` to fetch the page
2. Check the status code is 200

## Step 3: Parse HTML
1. Use BeautifulSoup to parse the HTML
2. Find target elements using CSS selectors

## Step 4: Extract Data
1. Extract text/attributes from elements
2. Store in a structured format

## Step 5: Save Results
Use the write_file tool to save results
```

### 2. Include Code Examples

Show working code that the agent can reference:

```markdown
## Example: Scraping Product Listings

\`\`\`python
import requests
from bs4 import BeautifulSoup

url = "https://example.com/products"
response = requests.get(url)

soup = BeautifulSoup(response.content, 'html.parser')
products = soup.find_all('div', class_='product')

for product in products:
    name = product.find('h2').text
    price = product.find('span', class_='price').text
    print(f"{name}: {price}")
\`\`\`
```

### 3. Explain Why, Not Just How

Help the agent understand the reasoning:

```markdown
## Step 3: Validate Data

Why: Bad data leads to wrong conclusions.

Check for:
1. **Missing values**: Rows with None/NaN
2. **Outliers**: Values far from the distribution
3. **Type mismatches**: Columns with wrong data types
4. **Duplicates**: Repeated rows
```

### 4. Mention Tool Usage

Direct the agent to use specific tools:

```markdown
## Step 2: Execute Script

Use the `code_execution` tool to run:

\`\`\`python
# Your analysis code
\`\`\`

If it fails, check:
- Syntax errors
- Missing imports
- File permissions
```

### 5. Handle Errors

Explain common failures and solutions:

```markdown
## Troubleshooting

### "Connection timed out"
- The website may be blocking requests
- Try adding a User-Agent header
- Use a proxy if needed

### "HTML structure doesn't match"
- Website may have changed
- Update your CSS selectors
- Check in a browser first
```

---

## Discovery & Configuration

### Auto-Discovery

Skills are auto-discovered from configured `skills_dir`:

```python
from mva.agent import get_agent

# Auto-discovers from:
# 1. ./sandbox/engine/skills/ (local)
# 2. ~/.config/private-notebook/skills/ (user)
agent = get_agent()

# Or specify explicitly
agent = get_agent(skills_dir="./my_skills")
```

### Configuration

In `config.yml`:

```yaml
# Skills directory (auto-discovered if not set)
skills_dir: ./sandbox/engine/skills/

# System prompt injection
system_prompt: |
  You are a helpful AI.
  Use skills for complex tasks.
```

### Runtime Check

```python
from mva.agent import get_agent

agent = get_agent()

# List all skills
if agent._skills.catalog:
    for name, info in agent._skills.catalog.items():
        print(f"{name}: {info['description']}")
else:
    print("No skills loaded")
```

---

## CLI Usage

### List Skills

```bash
$ uv run mva list
🎯 Available Skills:
  • data-analysis: Perform exploratory data analysis on CSV files
  • web-scraping: Extract and parse data from websites
```

### Chat with Skills

```bash
# Skills auto-loaded
$ uv run mva chat --skills ./sandbox/engine/skills/

# Or custom skills
$ uv run mva chat --skills ./my_custom_skills
```

---

## Advanced: Skill Catalog API

### SkillCatalog Class

```python
from mva.agent.skills import SkillCatalog

catalog = SkillCatalog("./sandbox/engine/skills/")

# Refresh (re-scan for changes)
catalog.refresh()

# Get catalog
for name, info in catalog.catalog.items():
    print(f"{name}: {info['description']}")
    print(f"  Path: {info['path']}")

# Load a skill
skill_content = catalog.load_skill("data-analysis")
print(skill_content)

# System prompt injection
prompt = catalog.system_prompt_injection(base_prompt="Your custom prompt")
```

### File Watching

Skills are re-scanned when:
- `catalog.refresh()` is called
- New `SKILL.md` files appear
- Files are modified

```python
catalog.refresh()  # Re-scan skills directory
skill_content = catalog.load_skill("updated-skill")  # Gets latest
```

---

## Examples

### Example 1: Simple Debugging Skill

```yaml
---
name: debugging
description: Systematic approach to finding and fixing bugs
---

# Debugging Skill

## Step 1: Reproduce the Bug

1. Write the simplest code that triggers the bug
2. Note the exact error message
3. Document the conditions needed to reproduce

## Step 2: Isolate the Problem

1. Comment out unrelated code
2. Add print statements to trace execution
3. Use the code_execution tool to test small pieces

## Step 3: Form a Hypothesis

Based on the error and trace:
- Where in the code is the problem?
- What's the root cause?
- What's the simplest fix?

## Step 4: Test the Fix

1. Implement a minimal fix
2. Verify it resolves the original issue
3. Check for side effects
```

### Example 2: Complex API Documentation Skill

```yaml
---
name: api-documentation
description: Create professional API documentation with examples
---

# API Documentation Skill

## Step 1: Analyze the API

Review the code to understand:
1. Endpoints (URL paths)
2. HTTP methods (GET, POST, etc.)
3. Request parameters
4. Response formats
5. Error codes

## Step 2: Create Endpoint Reference

For each endpoint, document:

\`\`\`
POST /api/users
Description: Create a new user
Parameters:
  - name (string, required)
  - email (string, required)
Response:
  - id (integer)
  - created_at (timestamp)
\`\`\`

## Step 3: Add Code Examples

Show practical usage:

\`\`\`python
import requests

response = requests.post(
    "https://api.example.com/users",
    json={"name": "John", "email": "john@example.com"}
)
user = response.json()
print(f"Created user {user['id']}")
\`\`\`

## Step 4: Document Errors

List error codes and meanings:
- 400: Invalid request
- 401: Unauthorized
- 404: Not found

## Step 5: Generate with write_file

Save the documentation using the write_file tool.
```

---

## Sharing Skills

Create a public repository:

```
my-mva-skills/
├── README.md
├── debugging/
│   └── SKILL.md
├── web-scraping/
│   └── SKILL.md
└── api-design/
    └── SKILL.md
```

Users can clone and use:

```bash
git clone https://github.com/user/my-mva-skills
uv run mva chat --skills ./my-mva-skills
```

---

## Troubleshooting

### Skill Not Loading

Check:
1. File is `SKILL.md` (exact case)
2. YAML frontmatter is valid (`---` markers)
3. Has `name` and `description` fields

```bash
# Debug: refresh and list
uv run mva list
# Should show your skill
```

### Skill Content Not Updating

Call `refresh()`:

```python
agent._skills.refresh()
updated = agent._skills.load_skill("my-skill")
```

### Skill Not Appearing in Chat

1. Verify `skills_dir` is set correctly
2. Check logs for parse errors (set `log_level: DEBUG`)
3. Restart chat session

---

## See Also

- [AGENT.md](AGENT.md) — Agent system and skill loading
- [TOOLS.md](TOOLS.md) — Tool system (lower-level functions)
- [CLI.md](CLI.md) — Command-line interface
