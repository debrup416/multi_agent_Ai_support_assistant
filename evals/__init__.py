"""Evaluation cases and a simple runner for end-to-end behavior checks."""

from evals.cases import CASES, EvalCase
from evals.runner import run_case, run_evals

__all__ = ["CASES", "EvalCase", "run_case", "run_evals"]
