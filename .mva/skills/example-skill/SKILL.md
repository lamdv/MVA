# Example Skill

Use this skill when the user asks about MVA's architecture or wants to add new features.

## Steps

1. Read `src/mva/cli.py` to understand the REPL loop
2. Read `src/mva/tools/__init__.py` to understand tool registration
3. Follow the patterns in `docs/adding_tools.md` for new tools
4. Use `@_register` decorator for new tool functions
5. Test changes with `uv run --package mva python -m mva`
