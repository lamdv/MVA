# Skills Directory

Curated, hand-written skills for the MVA agent.

These skills are checked into git and represent the canonical workflows your agents should follow.

## Structure

Each skill is a subdirectory with a SKILL.md file:

```
skills/
├── http-integration/
│   └── SKILL.md
├── csv-analysis/
│   └── SKILL.md
└── code-refactoring/
    └── SKILL.md
```

## Discovery

Skills are auto-discovered by the agent in priority order:
1. skills/ (this folder - curated)
2. sandbox/engine/skills/ (generated at runtime)

If a skill exists in both folders, the curated version takes precedence.

## Creating a New Skill

See `sandbox/engine/skills/create-skill/SKILL.md` for detailed instructions.

