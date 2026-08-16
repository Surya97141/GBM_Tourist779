# Track A + Agent Orchestrator — Decision Logbook

Append-only. One entry per non-trivial decision.

---
## Destination set: Jaipur, single-city catalogue

**Decision:** `destinations.json` holds 21 real Jaipur destinations across 7
categories (Heritage, Monument, Temple, Urban, Nature, Wildlife, Cultural),
sourced from public knowledge of each landmark plus web lookups for
coordinates.

**Why:** Similarity ranking needs categories that actually differ from each
other to be meaningful — a single city keeps distances small enough for the
20km radius filter to matter, while enough category spread means "similar
alternative" isn't just "the next fort down the road" every time.

**Tradeoffs:** Coordinates for smaller/less-documented spots (e.g. Sisodia
Rani Garden) are approximate rather than survey-grade. Good enough for
haversine filtering at km resolution; not good enough for turn-by-turn
navigation.

---

## Embedding model and index type

**Decision:** `sentence-transformers/all-MiniLM-L6-v2`, embeddings
L2-normalized, indexed with FAISS `IndexFlatIP`.

**Why:** MiniLM-L6-v2 is small, fast on CPU, and good enough for short
place descriptions — no GPU dependency for an MVP demo. Normalizing before
indexing turns inner product into cosine similarity, and a flat (exact)
index is fine at this scale (tens of destinations) — no need for an
approximate index (IVF/HNSW) that would only pay off at thousands of
entries.

**Tradeoffs:** Full re-embedding is required whenever `destinations.json`
changes; there's no incremental update path. Not a problem at this
catalogue size.

---

## Barrier Store lives in shared/, not track_A_filtering/

**Decision:** `barrier_store.py` moved to `shared/barrier_store.py` as a
process-wide singleton (`shared.barrier_store.barrier_store`), imported by
both Track A and the orchestrator.

**Why:** Track B writes readings, Track A and the orchestrator both read
them — putting it under `track_A_filtering/` would have made a Track-B
write path reach into Track A's folder, which is the wrong ownership
direction.

**Tradeoffs:** In-memory only — readings are lost on process restart and
don't survive across multiple worker processes. Fine for a single-process
MVP demo; a real deployment would need Redis or similar.

---

## Barrier Store TTL: 30 minutes

**Decision:** Default `ttl_minutes=30` on every barrier entry; `get()`
returns `None` once an entry is older than its own TTL.

**Why:** Crowd levels at a tourist site can shift meaningfully within
half an hour, but re-running detection more often than that isn't worth
the cost for an MVP. 30 minutes also matches
`BARRIER_STALENESS_MINUTES` in the orchestrator, so the two layers agree
on what "fresh" means without needing to look up each other's constants.

**Tradeoffs:** Fixed per-store default rather than per-destination (e.g. a
market that empties out faster than a fort doesn't get a shorter TTL).
Not needed for MVP.

---

## `recent_readings` left as an empty placeholder

**Decision:** The Barrier Store schema includes a `recent_readings: list`
field on every entry, always written as `[]` and never read anywhere in
this session's code.

**Why:** Track B has a planned footfall-count feature (multi-frame people
tracking over a live camera feed, distinct from the current single-photo
headcount) that would eventually aggregate its output here. Reserving the
field now means the schema's shape doesn't change out from under Track A
or the orchestrator later. See the deferred-work entry below — this
session does not implement footfall tracking or populate this field.

**Tradeoffs:** Dead weight in the schema until footfall tracking exists.
Acceptable — the alternative is a breaking schema change down the line.

---

## Ranking weights: 0.7 similarity + 0.3 distance

**Decision:** `final_score = 0.7 * similarity_score + 0.3 * (1 - normalized_distance)`,
hardcoded in `recommend.py`.

**Why:** The core promise is "a genuinely similar alternative" — distance
is a secondary practicality filter, not the primary match criterion.
Weights are fixed for MVP rather than configurable; tuning is a
post-demo concern.

**Tradeoffs:** Not user-adjustable yet. A live weighting slider is a
plausible future demo feature but isn't implemented in this session.

---

## Geo radius: 20km default, 40km widened fallback

**Decision:** `RADIUS_KM_DEFAULT = 20` in `recommend.py`; the orchestrator's
`check_and_widen_radius()` retries once at `RADIUS_KM_WIDENED = 40` if the
default radius returns zero candidates, and reports back which radius
was actually used.

**Why:** 20km keeps "alternative" meaning "still a reasonable trip from
where you are," while 40km is a one-shot fallback so a destination in a
sparser part of the map doesn't come back with nothing. A single retry
(not a widening loop) keeps the behavior predictable and bounded.

**Tradeoffs:** A destination with literally nothing within 40km still
returns empty — there's no further fallback, by design, so the system
doesn't start recommending places that are no longer a reasonable
"alternative."

---

## Barrier-filter cutoff: exclude HIGH/VERY_HIGH only

**Decision:** `recommend.py` excludes a candidate only if its current
`crowd_level` is `HIGH` or `VERY_HIGH`. `LOW`, `MEDIUM`, `unknown`, and
missing/expired readings are all treated as "not barriered."

**Why:** Matches Track B's own four-level scale
(`track_B_CV/main.py::determine_crowd_level`). Treating `unknown` or a
missing reading as barriered would silently hide destinations just
because they haven't been photographed recently, which is a worse
failure mode than occasionally recommending a MEDIUM-crowd spot.

**Tradeoffs:** A destination that's actually crowded but has no recent
reading can still get recommended. Mitigated by the orchestrator's
staleness check, not by the filter itself.

---

## Low-confidence threshold: 0.4

**Decision:** `LOW_CONFIDENCE_THRESHOLD = 0.4` in `agent_orchestrator/config.py`.
`check_confidence()` flags a reading for a second photo when the average
of Track B's per-box `confidence_scores` falls below this.

**Why:** Below roughly 0.4, YOLO-style detectors are typically picking up
partial/occluded/ambiguous boxes rather than confidently-identified
people, which makes the resulting count untrustworthy as a basis for
barriering a destination. 0.4 is a starting value for the MVP demo, not a
value backed by a confidence-vs-accuracy study on this specific model.

**Tradeoffs:** A single global threshold, not scene- or lighting-aware.
Reasonable starting point; expect this to move once real detection data
comes in.

---
