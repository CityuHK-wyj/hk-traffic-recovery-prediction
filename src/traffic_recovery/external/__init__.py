"""Verified external context and prediction-time-safe integration.

Adapters accept source-preserving tables with explicit availability timestamps;
they do not claim that an optional source has complete historical coverage.
"""

from .build import ContextRules, build_context_features

__all__ = ["ContextRules", "build_context_features"]
