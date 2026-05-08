# MVA (Minimum Viable Agent)

MVA is an interactive, agentic Read-Eval-Print Loop (REPL) for Large Language Models (LLMs). It transforms a standard chat interface into a powerful agent capable of interacting with your local environment through a secure, extensible tool-calling framework.

## ✨ Features

- **Agentic Tool-Calling**: The LLM can autonomously decide to use tools (like reading files or running bash commands) and process the results in a multi-turn loop.
- **Streaming Intelligence**: Supports streaming responses, including specialized rendering for "thinking" or reasoning blocks.
- **Security-First Design**: 
    - **Path Sandboxing**: Built-in checks to prevent tools from accessing files outside the current working directory.
    - **User Confirmation**: Sensitive operations (like writing files or executing bash commands) trigger a manual "Proceed? [y/N]" prompt.
    - **Resource Limits**: Bash executions are constrained by CPU, memory, and process limits to prevent runaway commands.
- **Extensible Architecture**: Add new capabilities in seconds using a simple Python decorator-based registry.
- **Beautiful Terminal UI**: Powered by `rich` for high-quality, readable, and colorful terminal output.

## 🚀 Getting Started

### Prerequisites

- **Python 3.13+**
- [**uv**](https://github.com/astral-sh/uv) (A lightning-fast Python package installer and resolver)

### Installation

Clone the repository and sync the environment using `uv`:

```bash
# Clone the repo
git clone <your-repo-url>
cd mva

# Install dependencies and create virtual environment
uv sync
```

### Running the Agent

Launch the interactive REPL directly:

```bash
uv run --package mva python -m mva
```

## 🛠 Built-in Tools

The following tools are available out-of-the-box:

| Tool | Description |
| :--- | :--- |
| `read` | Reads text or image files (supports `offset` and `limit`). |
| `write` | Writes content to a file (creates directories automatically). |
| `list_files` | Recursively lists directory contents with a depth limit. |
| `bash` | Executes bash commands in a sandboxed environment. |
| `ls` | An alias for `list_files`. |

## ⌨️ Commands

Inside the REPL, you can use slash commands to manage your session:
- `/help` - Show available commands.
- `/exit` - Terminate the session.

## 🏗 Extending MVA

Adding new tools is the core strength of MVA. You can define a new tool by simply decorating a Python function with `@_register`.

For a detailed guide on how to implement secure, production-ready tools, please refer to:
👉 [**docs/adding_tools.md**](./docs/adding_tools.md)

## 🛡 Security Architecture

MVA implements a multi-layered security stack:
1. **Layer 0 (Blocklist)**: Unconditional blocking of dangerous patterns (e.g., `rm -rf /`, `sudo`).
2. **Layer 1 (Path Escape Check)**: Detection of attempts to access files outside the project root.
3. **Layer 2 (User Confirmation)**: Interactive prompts for any operation flagged by Layer 1.
4. **Layer 3 (Resource Sandboxing)**: Enforced `RLIMIT` for CPU, memory, and file size on subprocesses.

---
*Developed by [ldang](mailto:lam.dv@live.com)*
