"""Alternative-destination recommendation: similarity + geo + barrier filtering."""

import json
import math
import sys
from pathlib import Path

import faiss

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.barrier_store import barrier_store  # noqa: E402

DESTINATIONS_PATH = BASE_DIR / "destinations.json"
INDEX_PATH = BASE_DIR / "vector_index.faiss"
ID_MAP_PATH = BASE_DIR / "destination_ids.json"

CANDIDATE_POOL_SIZE = 10
RADIUS_KM_DEFAULT = 20
BARRIERED_LEVELS = {"HIGH", "VERY_HIGH"}
SIMILARITY_WEIGHT = 0.7
DISTANCE_WEIGHT = 0.3
TOP_N_RESULTS = 3

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _load_destinations() -> dict[str, dict]:
    with open(DESTINATIONS_PATH, encoding="utf-8") as f:
        destinations = json.load(f)
    return {d["destination_id"]: d for d in destinations}


def _load_index() -> tuple[faiss.Index, list[str]]:
    if not INDEX_PATH.exists():
        raise FileNotFoundError(
            f"{INDEX_PATH.name} not found — run build_embeddings.py first."
        )
    index = faiss.read_index(str(INDEX_PATH))
    with open(ID_MAP_PATH, encoding="utf-8") as f:
        destination_ids = json.load(f)
    return index, destination_ids


def _is_barriered(destination_id: str) -> bool:
    reading = barrier_store.get(destination_id)
    if reading is None:
        return False
    return reading["crowd_level"] in BARRIERED_LEVELS


def get_recommendations(
    origin_destination_id: str,
    radius_km: float = RADIUS_KM_DEFAULT,
    top_n: int = TOP_N_RESULTS,
) -> dict:
    destinations = _load_destinations()
    if origin_destination_id not in destinations:
        raise ValueError(f"Unknown destination_id: {origin_destination_id}")

    index, destination_ids = _load_index()
    origin_row = destination_ids.index(origin_destination_id)
    origin = destinations[origin_destination_id]
    origin_vector = index.reconstruct(origin_row).reshape(1, -1)

    k = min(CANDIDATE_POOL_SIZE + 1, index.ntotal)
    similarities, rows = index.search(origin_vector, k)

    scored = []
    for similarity, row in zip(similarities[0], rows[0]):
        candidate_id = destination_ids[row]
        if candidate_id == origin_destination_id:
            continue

        candidate = destinations[candidate_id]
        distance_km = haversine_km(origin["lat"], origin["lng"], candidate["lat"], candidate["lng"])
        if distance_km > radius_km:
            continue
        if _is_barriered(candidate_id):
            continue

        similarity_score = max(0.0, min(1.0, float(similarity)))
        normalized_distance = min(1.0, distance_km / radius_km)
        final_score = (
            SIMILARITY_WEIGHT * similarity_score
            + DISTANCE_WEIGHT * (1 - normalized_distance)
        )

        scored.append(
            {
                "destination_id": candidate_id,
                "name": candidate["name"],
                "category": candidate["category"],
                "similarity_score": round(similarity_score, 4),
                "distance_km": round(distance_km, 2),
                "final_score": round(final_score, 4),
            }
        )

    scored.sort(key=lambda r: r["final_score"], reverse=True)

    return {
        "origin_destination_id": origin_destination_id,
        "recommendations": scored[:top_n],
    }


if __name__ == "__main__":
    import sys as _sys

    origin_id = _sys.argv[1] if len(_sys.argv) > 1 else "dest_001"
    print(json.dumps(get_recommendations(origin_id), indent=2))
