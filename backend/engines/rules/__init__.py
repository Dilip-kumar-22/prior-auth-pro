"""
Rules Engine package initialization.

This package contains the deterministic rules engine for evaluating Prior Authorization
requests against payer policies. It handles loading synthetic payer policies from JSON
seed files and evaluating requests to determine if they meet criteria for auto-approval,
auto-denial, or if they require further AI-driven clinical reasoning and review.

Modules:
- engine: Contains the RulesEngine class for policy evaluation.
- seed_data: Directory containing synthetic payer policies (UnitedHealth, Aetna, Cigna, BCBS).
"""

__version__ = "1.0.0"
__author__ = "Prior Auth Pro Team"

__all__ = []