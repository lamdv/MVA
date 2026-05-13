"""Shim package — delegates to mva-cli in the monorepo workspace."""

from mva_cli.app import _app


def main():
    _app()
