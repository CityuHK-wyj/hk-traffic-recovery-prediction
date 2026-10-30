"""Command-line entry point for leakage-safe logistic regression."""
from .supervised import cli


if __name__ == "__main__":
    raise SystemExit(cli("logistic"))
