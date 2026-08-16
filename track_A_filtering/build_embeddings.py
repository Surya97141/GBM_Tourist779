"""One-time script: builds the FAISS similarity index for destinations.json.

Run manually whenever destinations.json changes:
    python build_embeddings.py
"""

import json
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

BASE_DIR = Path(__file__).resolve().parent
DESTINATIONS_PATH = BASE_DIR / "destinations.json"
INDEX_PATH = BASE_DIR / "vector_index.faiss"
ID_MAP_PATH = BASE_DIR / "destination_ids.json"

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def load_destinations() -> list[dict]:
    with open(DESTINATIONS_PATH, encoding="utf-8") as f:
        return json.load(f)


def build_embedding_text(dest: dict) -> str:
    return f"{dest['name']}. {dest['category']}. {dest['description']}"


def main() -> None:
    destinations = load_destinations()
    texts = [build_embedding_text(d) for d in destinations]

    model = SentenceTransformer(MODEL_NAME)
    embeddings = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    embeddings = embeddings.astype(np.float32)

    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)
    faiss.write_index(index, str(INDEX_PATH))

    destination_ids = [d["destination_id"] for d in destinations]
    with open(ID_MAP_PATH, "w", encoding="utf-8") as f:
        json.dump(destination_ids, f, indent=2)

    print(f"Indexed {len(destinations)} destinations -> {INDEX_PATH.name}")


if __name__ == "__main__":
    main()
