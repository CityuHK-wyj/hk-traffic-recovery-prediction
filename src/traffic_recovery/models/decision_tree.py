"""Command-line entry point for pruned decision-tree training."""
from .supervised import cli


if __name__ == "__main__":
    raise SystemExit(cli("tree"))
