# Tool folder

Agent will automatically discover tool from this folder on the fly.

All tools will have to `import mva.tools.sandbox` in order to be allowed to use.

IMPORTANT: ALWAYS DEFINE `__all__` param to avoid false discovery