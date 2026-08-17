"""Threshold constants for the orchestration layer, kept in one place so
tuning any of these doesn't require hunting through orchestrator.py."""

BARRIER_STALENESS_MINUTES = 30
LOW_CONFIDENCE_THRESHOLD = 0.4
RADIUS_KM_DEFAULT = 20
RADIUS_KM_WIDENED = 40
EQUAL_RANK_CANDIDATE_THRESHOLD = 2
EQUAL_RANK_SCORE_MARGIN = 0.05
GROQ_MODEL = "llama-3.1-8b-instant"
