"""Real TrackCClient implementations. NlpTrackCClient is backed by Track
C's own rule-based explain(). GroqTrackCClient tries an LLM first and
falls back to the same rule-based explain() on any failure or missing
API key, so losing Groq access never breaks a recommendation.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent_orchestrator.groq_client import complete
from agent_orchestrator.orchestrator import TrackCClient
from track_C_NLP.explain import explain


class NlpTrackCClient(TrackCClient):
    def explain(self, recommendation: dict) -> str:
        return explain(recommendation)


class GroqTrackCClient(TrackCClient):
    def explain(self, recommendation: dict) -> str:
        prompt = (
            "Write one short, natural sentence recommending this place to a "
            "tourist as an uncrowded alternative. No quotation marks, no preamble.\n\n"
            f"Name: {recommendation['name']}\n"
            f"Category: {recommendation['category']}\n"
            f"Distance: {recommendation['distance_km']:.1f} km away\n"
            f"Similarity to what they wanted (0-1 scale): {recommendation['similarity_score']:.2f}\n"
        )
        result = complete(prompt, max_tokens=80)
        return result if result else explain(recommendation)
