#!/usr/bin/env python3
"""Simple CLI for testing the Agent."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Enable arrow key navigation and history
try:
    import readline
    _HISTORY_FILE = Path.home() / ".mva_history"
    if _HISTORY_FILE.exists():
        readline.read_history_file(_HISTORY_FILE)
except ImportError:
    # readline not available on Windows
    pass

from .agent import get_agent, tools


def _save_history():
    """Save readline history to file."""
    try:
        readline.write_history_file(_HISTORY_FILE)
    except (NameError, OSError):
        # readline not available or write failed
        pass


def list_tools_and_skills():
    """List available tools and skills."""
    agent = get_agent()

    if _tools := tools.get_available_tools():
        print("📋 Available Tools:")
        for tool in _tools:
            print(f"  • {tool['name']}: {tool['description']}")
    else:
        print("No tools loaded.")

    print()

    if agent._skills.catalog:
        print("🎯 Available Skills:")
        for name, info in sorted(agent._skills.catalog.items()):
            print(f"  • {name}: {info['description']}")
    else:
        print("No skills loaded.")


def test(query: str, model: str = ""):
    """Run a single query and print the response."""
    kwargs = {}
    if model:
        kwargs["model"] = model

    agent = get_agent(**kwargs)
    history = [{"role": "user", "content": query}]

    print("🤖 Testing Agent:")
    print("-" * 50)

    try:
        response = agent.run(history)
        print(response)
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


def slash_function(agent, cmd: str, args=None):
    """Handle slash commands."""
    match cmd.lower():
        case "help":
            print("Available commands:")
            print("/help - Show this help message")
            print("/list - List available tools and skills")
            print("/exit or /quit - Exit the program")
        case "models":
            print("Available models:")
            for model in agent.client.ls_models():
                print(f"  • {model['id']}")
        case "list":
            if _tools := tools.get_available_tools():
                print("\n📋 Available Tools:")
                for tool in _tools:
                    tool = tool['function']
                    print(f"  • {tool['name']}: {tool['description'].splitlines()[0]}")
                    # print(f"===")
            else:
                print("No tools loaded.")

            if agent._skills.catalog:
                print("\n🎯 Available Skills:")
                for name, info in sorted(agent._skills.catalog.items()):
                    print(f"  • {name}: {info['description']}")
            else:
                print("No skills loaded.")
            print()
        case "exit" | "quit":
            _save_history()
            print("👋 Goodbye!")
            sys.exit(0)
        case _:
            print(f"Unknown command: /{cmd}")


def _chat(agent, verbose: bool = False):
    """Main chat loop."""
    history = []

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            _save_history()
            print("\n👋 Goodbye!")
            sys.exit(0)

        if not user_input:
            continue

        if user_input.startswith("/"):
            cmd = user_input[1:]
            slash_function(agent, cmd)
            continue

        # Add user message
        history.append({"role": "user", "content": user_input})

        if verbose:
            print(f"\n[Request has {len(history)} message(s)]\n")

        try:
            # Stream response
            response_parts = []
            for chunk in agent.stream(history):
                if chunk["type"] == "content":
                    part = chunk["content"]
                    response_parts.append(part)
                    print(part, end="", flush=True)
                elif chunk["type"] == "tool_start":
                    print(f"\n🔧 Calling {chunk['name']}...", file=sys.stderr)
                elif chunk["type"] == "tool_use":
                    if verbose:
                        result_preview = chunk["result"][:100]
                        if len(chunk["result"]) > 100:
                            result_preview += "..."
                        print(f"✓ {chunk['name']}: {result_preview}", file=sys.stderr)
                elif chunk["type"] == "error":
                    print(f"\n❌ Error: {chunk['content']}", file=sys.stderr)

            full_response = "".join(response_parts)
            print()  # newline
            history.append({"role": "assistant", "content": full_response})

        except Exception as e:
            print(f"\n❌ Error: {e}", file=sys.stderr)


def chat(
    system_prompt: str = "",
    model: str = "",
    tools_dir: str = "",
    skills_dir: str = "",
    verbose: bool = False,
):
    """Start an interactive chat session with the agent."""
    # Build kwargs
    kwargs = {}
    if system_prompt:
        kwargs["system_prompt"] = system_prompt
    if model:
        kwargs["model"] = model
    if tools_dir:
        kwargs["tools_dir"] = tools_dir
    if skills_dir:
        kwargs["skills_dir"] = skills_dir

    # Create agent
    agent = get_agent(
        **kwargs
    )
    if tools_dir:
        agent.tools_dir = Path(tools_dir).resolve()

    print("🤖 MVA Agent CLI")
    print("=" * 50)
    _tools = tools.get_available_tools()
    if _tools:
        print(f"📋 Loaded {len(_tools)} tool(s)")
    if agent._skills.catalog:
        print(f"🎯 Loaded {len(agent._skills.catalog)} skill(s)")
    print("\nCommands: /exit, /quit, /list")
    print("=" * 50 + "\n")

    _chat(agent, verbose=verbose)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="MVA Agent CLI for testing and interaction")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Chat command
    chat_parser = subparsers.add_parser("chat", help="Start interactive chat")
    chat_parser.add_argument("-s", "--system", help="Custom system prompt")
    chat_parser.add_argument("-m", "--model", help="LLM model to use")
    chat_parser.add_argument("--tools", help="Custom tools directory")
    chat_parser.add_argument("--skills", help="Custom skills directory")
    chat_parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    # Test command
    test_parser = subparsers.add_parser("test", help="Run a single query")
    test_parser.add_argument("query", help="Query to test")
    test_parser.add_argument("-m", "--model", help="LLM model to use")

    # List command
    list_parser = subparsers.add_parser("list", help="List tools and skills")

    args = parser.parse_args()

    if args.command == "chat":
        chat(
            system_prompt=args.system,
            model=args.model,
            tools_dir=args.tools,
            skills_dir=args.skills,
            verbose=args.verbose,
        )
    elif args.command == "test":
        test(args.query, model=args.model)
    elif args.command == "list":
        list_tools_and_skills()
    else:
        # Default to chat if no command specified
        chat()


if __name__ == "__main__":
    main()

