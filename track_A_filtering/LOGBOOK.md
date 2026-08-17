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

## `should_ask_preference` tie rule

**Decision:** Ask the user for a preference only when more than
`EQUAL_RANK_CANDIDATE_THRESHOLD` (2) candidates fall within
`EQUAL_RANK_SCORE_MARGIN` (0.05) of the top `final_score`.

**Why:** If there's a clear top recommendation, asking the user adds a
step for no benefit. Asking only becomes useful when the ranking genuinely
can't distinguish between several good options.

**Tradeoffs:** Both constants are arbitrary starting points, not derived
from user testing. An LLM-based intent-parsing integration point is left
marked in `orchestrator.py` for a future version that could resolve ties
using free-text user input instead of a follow-up question — not wired up
in this session, per scope.

---

## Track B / Track C treated as interface contracts, not mocks

**Decision:** `orchestrator.py` defines `TrackBClient` and `TrackCClient`
as classes whose methods raise `NotImplementedError`, documenting the
exact input/output shape each track must satisfy, rather than writing
fake implementations that return plausible-looking data.

**Why:** A mock that "works" invites the rest of the system to be built
and tested against fake behavior that Track B/C's real implementation
might not actually match. A contract that fails loudly if called forces
integration to happen deliberately, once the real client exists.

**Tradeoffs:** `check_staleness()` can't be exercised end-to-end without a
caller supplying a real or fake `TrackBClient` — by design; see its
docstring and the fake client used in manual testing.

---

## Deferred: face blurring and footfall count (Track B, not this session)

**Decision:** Neither feature is implemented here. Logged so the reasoning
behind the `recent_readings` placeholder field (above) stays visible to
whoever picks up Track B next.

**Why:** Both are Track B / CV-pipeline concerns, out of scope for this
session. Face blurring is a display-layer change on the live bounding-box
overlay (detection still runs on the raw frame; only the rendered frame
gets faces blurred) and doesn't touch counting accuracy. Footfall count
(distinct people over time, via multi-object tracking across video frames)
is a materially different problem from the current single-photo headcount,
and depends on a persistent camera feed that the current photo-upload
design doesn't have — a legitimate future/government-partnership feature,
not an MVP item.

**Tradeoffs:** None yet — nothing was built against either feature, so
there's nothing to unwind later.

---

## Local dev environment rebuilt on a standard CPython install

**Decision:** The repo's `venv/` was rebuilt from
`C:\Users\hp\AppData\Local\Programs\Python\Python313\python.exe` instead of
the MSYS2 UCRT64 Python it previously pointed to.

**Why:** The existing venv had no working `pip` and, being an MSYS2 build,
would not reliably resolve prebuilt Windows wheels for `torch`/`faiss-cpu`
from PyPI. A standard python.org CPython build installs the full
`requirements.txt` (including `sentence-transformers` and `faiss-cpu`)
without issue.

**Tradeoffs:** None — `venv/` isn't tracked in git, so this doesn't affect
anyone else's checkout; each teammate builds their own venv locally.

---

## requirements.txt pinned to exact installed versions

**Decision:** All ten root `requirements.txt` entries pinned to the exact
versions verified working in this session (e.g. `torch`/`ultralytics`
resolve against `numpy==2.5.2`, `faiss-cpu==1.15.0`, etc.), rather than
left unpinned.

**Why:** Verified that everything Track A, Track B, and the shared/agent
layers actually import (`cv2`, `numpy`, `PIL`, `ultralytics`, `fastapi`,
`faiss`, `sentence_transformers`, `pandas`) was already covered by the
existing package list — nothing new needed adding. Track C has no source
files yet, so there's nothing to derive its dependencies from. Pinning
exact versions means every teammate's `pip install -r requirements.txt`
resolves to the same dependency tree instead of picking up whatever's
newest on the day they install, which matters here since `torch` and
`faiss-cpu` are large, fast-moving packages.

**Tradeoffs:** Versions need a manual bump if a track later needs a newer
release of something. Acceptable — an unpinned file that silently drifts
between teammates' machines is the worse failure mode for a team demo.

---

## track_B_CV/live_demo.py added as a standalone demo script

**Decision:** New file, `track_B_CV/live_demo.py`, that opens a live video
window (phone IP-camera stream or laptop webcam) with detection boxes, the
3x3 zone grid, and a running count/level readout drawn on each frame. It
imports `determine_crowd_level` and `drawgrid` from `main.py` rather than
reimplementing either, but is otherwise a fully separate entry point.

**Why:** Kept out of `main.py` on purpose — `main.py` is the production
API surface (`/detect-crowd`, `/detect-image`) that Track A's barrier
pipeline depends on. A live-camera loop with `cv2.imshow()` and a blocking
`while True` has no place inside a FastAPI request handler, and mixing a
GUI demo loop into the production file would risk breaking the endpoints
other tracks are integrating against. This script never imports or calls
`shared/barrier_store.py` and never takes a `destination_id` — it's a
visual sanity check for a demo table, not a data path.

While building this, found that `main.py` had just been edited (by
whoever owns Track B) to add `drawgrid()`, switch the loaded weights from
`yolov8n_best.pt` to `yolov8n.pt`, and drop the inference confidence from
0.20 to 0.15. Turned out `yolov8n_best.pt` in this checkout is a 0-byte
placeholder — the actual CrowdHuman-fine-tuned checkpoint was never
committed — which is presumably why production switched to the
auto-downloadable plain `yolov8n.pt` instead. `live_demo.py` follows
whatever `main.py` currently does (weights file, confidence threshold),
not a hardcoded snapshot, so the two don't silently drift apart.

**WiFi dependency introduced:** the phone-stream path
(`STREAM_URL = "http://<phone-ip>:8080/video"`) requires the demo laptop
and the phone running the IP camera app to be on the same local network
and able to reach each other directly. Conference/venue WiFi that
isolates client devices from each other (AP/client isolation) will break
this silently — the capture just never connects. The laptop's own webcam
(`STREAM_URL = 0`) has no such dependency and is the documented fallback
in the script if venue WiFi turns out to be a problem on the day.

**Tradeoffs:** Loading `yolov8n.pt` independently in this script means the
model is loaded twice in memory if `main.py` and `live_demo.py` ever run
in the same process (they don't — separate entry points, separate
processes) so this doesn't matter in practice. Importing `determine_crowd_level`
and `drawgrid` from `main.py` does trigger `main.py`'s own top-level model
load as a side effect of the import; unavoidable without modifying
`main.py`, which is out of scope here.

---

## Weights-file size guard added to live_demo.py

**Decision:** Before calling `YOLO(MODEL_WEIGHTS)`, `live_demo.py` now
checks the file size and prints a warning if it's under 1MB.

**Why:** `ultralytics.YOLO()` doesn't fail loudly when a checkpoint named
`yolov8n*` is corrupt or empty — it silently falls back to downloading the
plain COCO-pretrained model under that name instead of raising. That
fallback is exactly what masked the `yolov8n_best.pt` placeholder issue
above; production was quietly running weaker detection with no error
anywhere. Once the real fine-tuned weights land, this check gives an
immediate, visible signal if the swap didn't actually take (partial copy,
wrong file, etc.) instead of the same silent substitution happening again.

**Tradeoffs:** 1MB is a heuristic, not a guarantee — it only catches
obviously-broken files (0 bytes, truncated downloads), not a wrong-but-
plausibly-sized checkpoint. Can't fix the underlying `ultralytics` fallback
behavior itself, and can't add the same guard to `main.py` since that file
is out of scope for this change — worth someone doing there too.

---

## 2026-08-16 — check_staleness() no longer triggers detection itself

**Decision:** `check_staleness(destination_id, track_b_client)` reads the
barrier store and reports `{"fresh", "needs_remeasure", "current_reading"}`
only. It accepts `track_b_client` but never calls it. Actually invoking
Track B (and deciding what to do with the result) moved up into
`orchestrate()`, which takes an optional `fresh_reading` param for the
caller to hand back in after calling `track_b_client.detect()` themselves.

**Why:** `check_staleness()` has no photo to detect against — only the
caller (holding the actual image bytes) can produce one. Earlier this
function tried to do both the staleness check and the detection call in
one step, which meant it needed an `image` param it usually didn't have
and silently no-opped when it was missing. Splitting "is this stale" from
"go get a fresh one" makes each function's job unambiguous, and matches
how the real request flow works: the API layer has the image, the
orchestrator doesn't.

**Tradeoffs:** `track_b_client` being an accepted-but-unused parameter on
`check_staleness()` looks odd at first read — documented in the
function's docstring so it doesn't get "cleaned up" by someone assuming
it's dead code.

---

## 2026-08-16 — should_ask_preference() returns a plain bool

**Decision:** `should_ask_preference(recommendations: list) -> bool`,
not a dict with a reason field.

**Why:** Every caller of this function only ever needed a yes/no to branch
on (`orchestrate()` uses it as a straight `if`). A reason string was
information nobody was reading. Top score is computed with `max()` over
the list rather than assuming `recommendations[0]` is already
sorted-descending — `get_recommendations()` happens to return it sorted,
but this function shouldn't silently depend on a caller's ordering
convention to get the right answer.

**Tradeoffs:** None — this is a stricter, smaller contract than before.

---

## 2026-08-16 — TrackCClient.explain() takes one recommendation, not the whole list

**Decision:** `TrackCClient.explain(recommendation: dict) -> str` — one
call per candidate, not one call for the whole recommendations list plus
origin context.

**Why:** Keeps Track C's contract symmetric with how `orchestrate()`
actually uses it — looping over `recommendations` and calling `explain()`
per entry. A per-item contract is also easier for Track C to stub and test
independently, one example dict in, one string out, no origin-destination
plumbing required on their side.

**Tradeoffs:** If a future explanation needs to compare candidates against
each other (not just describe one in isolation), this contract doesn't
support that — would need a signature change then.

---

## 2026-08-16 — orchestrate() treats a non-barriered reading as a stop condition

**Decision:** In `orchestrate()`, if the reading in hand has sufficient
confidence but `crowd_level` isn't `HIGH`/`VERY_HIGH`, the function returns
`{"status": "not_barriered", ...}` immediately rather than continuing on
to `check_and_widen_radius()`.

**Why:** Not explicitly called out in the original function spec, but
required for `orchestrate()` to return something sensible in every branch.
Running the recommendation search for a destination that isn't crowded
would be wasted work and a confusing response — there's nothing to
recommend an alternative to.

**Tradeoffs:** None.

---

## 2026-08-16 — check_confidence() is only meaningful against a fresh_reading

**Decision:** No code change here, just a documented consequence of the
existing `shared/barrier_store.py` schema: stored entries don't carry a
`confidence_scores` field (only `crowd_level`, `estimated_count`,
`timestamp`, `ttl_minutes`, `recent_readings`). `check_confidence()` on a
`current_reading` pulled from the barrier store will always see a missing
key and fall through the empty-list branch ("sufficient" by default) — the
confidence check only does real work when `orchestrate()` is passed a
`fresh_reading` straight from `track_b_client.detect()`, which does carry
the field.

**Why:** This is expected, not a bug: a stale reading's per-box confidence
scores wouldn't mean anything useful anyway (they describe a detection run
that's already minutes old), so there was never a reason for the barrier
store to persist them. Recording this here so nobody "fixes" the missing
key on the store side without realizing why it's absent.

**Tradeoffs:** Confidence gating effectively only applies right after a
fresh detection, never in the needs_remeasure → cached-reading path. Fine,
since a cached reading has already implicitly passed a confidence check
whenever it was first written.

---

## 2026-08-17 — main.py wired into the Barrier Store

**Decision:** `track_B_CV/main.py`'s `/detect-crowd` endpoint now imports
the shared `barrier_store` singleton and calls `barrier_store.set(destination_id,
crowd_level, estimated_count)` right after computing `crowd_level`, only
on the success path (not in the `except` fallback branch). Also added the
same `sys.path` repo-root insertion pattern already used in `recommend.py`
and `orchestrator.py`, since `shared` isn't importable from `main.py`
without it.

**Why:** Without this, nothing ever populated the barrier store in a real
run — `check_staleness()` would report every destination as needing a
remeasurement forever, no matter how many photos got submitted, because
the reading never made it past the HTTP response. This was the single
biggest reason the pieces built so far never combined into a working
prototype. Only writing on success (not on `except`) is deliberate: an
`"unknown"` reading from a transient failure shouldn't overwrite a good
recent reading, and `check_confidence()` already treats an empty
`confidence_scores` list as sufficient, so a fallback write could
otherwise mask a real crowd behind a falsely-fresh "unknown" entry.

**Tradeoffs:** This is the one change to `main.py` made outside the normal
import-only rule for this file, done with explicit go-ahead. Kept to the
smallest possible diff - two import lines and one function call - so it
doesn't collide with whatever else Track B's owner is actively changing
in that file.

---

## 2026-08-17 — Real TrackBClient: in-process, not a live HTTP call

**Decision:** `agent_orchestrator/track_b_client.py` implements
`HttpTrackBClient` using FastAPI's `TestClient` against `track_B_CV.main.app`
directly, rather than making a real network call to a separately running
uvicorn process.

**Why:** `TestClient` exercises the actual ASGI app - real request
validation, real model inference, real response shape - without requiring
two servers to be started in the right order for a demo to work. A
prototype that needs a second terminal window running `uvicorn main:app`
before it does anything is a worse demo experience than one that just
works when you run it. If Track B ever gets deployed as a genuinely
separate service, swapping this for a real `httpx`/`requests` call against
a base URL is a small, contained change - the `TrackBClient` interface
doesn't change either way.

**Tradeoffs:** Only works when both `main.py` and the orchestrator are
importable in the same Python process (they are, in this repo layout).
Doesn't test actual network failure modes (timeouts, connection refused) -
fine for a prototype, would need revisiting for a real multi-service
deployment.

---

## 2026-08-17 — Real TrackCClient: template text, not an LLM call

**Decision:** `agent_orchestrator/track_c_client.py` implements
`TemplateTrackCClient`, which builds an explanation string from a
recommendation dict's `name`, `category`, and `distance_km` using plain
string formatting - no model call of any kind.

**Why:** `track_C_NLP/` is still empty and out of scope for this session,
and wiring up an external LLM (Groq or otherwise) was explicitly ruled out
per the standing guardrails on `should_ask_preference()`, which extends in
spirit to this client too. A rule-based stand-in gets the rest of the
pipeline (`orchestrate()`, the `/recommend` endpoint) fully working end to
end now, and Track C's real implementation can drop in later against the
exact same `TrackCClient.explain(recommendation)` contract without any
other file changing.

**Tradeoffs:** Explanation quality is genuinely template-flat compared to
what real NLP would produce - "X is a similar heritage site 6 km away" -
not written for a demo audience to be impressed by, just to prove the
contract works.

---

## 2026-08-17 — agent_orchestrator/app.py as the single entrypoint

**Decision:** New file, `agent_orchestrator/app.py`, exposing one FastAPI
endpoint (`POST /recommend`) that ties everything together: reads the
uploaded photo, calls `check_staleness()`, calls `track_b_client.detect()`
only if a remeasurement is actually needed, then calls `orchestrate()`
with whatever reading is in hand.

**Why:** Before this, Track A, the orchestrator, and Track B all worked
correctly in isolation but nothing actually called them in sequence from
one incoming request - there was no answer to "what happens when a user
submits a photo." This is that answer. Kept deliberately thin: no
business logic lives in this file, it only wires existing, already-tested
functions together in the order `orchestrate()`'s docstring already
specifies.

**Tradeoffs:** Single global `track_b_client` / `track_c_client` instances
at module scope rather than per-request dependency injection - fine for
one demo process, would want FastAPI's `Depends()` if this ever needs to
swap clients per-request or per-environment (e.g. a real Track B client in
production vs. this one in dev).

**Verified:** ran two scenarios through the actual FastAPI app via
`TestClient` - a blank-image request that runs real detection through
`main.py`, confirms `barrier_store` actually gets written, and correctly
returns `not_barriered`; and a pre-seeded `VERY_HIGH` reading that runs
the full path through to three real, explained recommendations.

---

## 2026-08-17 — Track C's real explain() written, template-based by design

**Decision:** `track_C_NLP/explain.py` now has a real `explain(recommendation) -> str`
implementation - three signals (`distance_km`, `similarity_score`,
`category`) each map to a phrase, phrases drop into one of three sentence
templates, template choice is picked deterministically from
`destination_id` (character-sum, not Python's built-in `hash()`, which is
per-process salted for strings and would make the same destination word
itself differently between runs). `agent_orchestrator/track_c_client.py`'s
`TemplateTrackCClient` stand-in is gone - replaced with `NlpTrackCClient`,
which just calls into `track_C_NLP.explain.explain()` directly. No
duplicate template logic living in two places anymore.

**Why:** No LLM call, by design - matches the standing rule against wiring
up external LLM APIs this session, and a rule-based generator has no API
key, no network dependency, no per-call cost or latency, and is
trivially testable (same input, same output, always). `track_C_NLP/`
doesn't import anything from `agent_orchestrator` - the dependency runs
one direction only, orchestrator depends on Track C's contract, not the
other way around, so Track C stays a module other things can import
without dragging the whole orchestrator in with it.

**Tradeoffs:** Explanation quality is genuinely template-flat compared to
what a real language model would produce - three sentence shapes, seven
category phrases, four distance bands. Good enough to prove the contract
and demo cleanly; if template repetition becomes noticeable with enough
destinations, the fix is more templates and phrases, not a different
architecture.

---

## 2026-08-17 — Two things changed underneath this session, worth flagging

**Decision:** No code change here - noting two things discovered while
wiring up Track C that came from elsewhere, not from this session's own
edits.

**Why:** `track_B_CV/yolov8n_best.pt` is no longer a 0-byte placeholder -
it's now a real ~6.2MB checkpoint, and `main.py` points at it again
(`model = YOLO("yolov8n_best.pt")`). That resolves the model-quality gap
flagged earlier. But `main.py`'s edits also came back without the
`barrier_store` wiring added earlier this session (the `sys.path` setup,
the `shared.barrier_store` import, and the `barrier_store.set()` call in
`/detect-crowd` are all gone) - a side effect of two people editing the
same uncommitted file in parallel, not a deliberate reversal. Also,
`classes=[0]` was dropped from both `model.predict()` calls in `main.py`,
so detection is no longer person-only - it'll now count any COCO class in
frame toward `estimated_count`.

**Tradeoffs:** Until the barrier-store wiring is re-added, `/detect-crowd`
computes a real reading but doesn't persist it, so `check_staleness()` in
the orchestrator will never see a cached hit from a real request - every
request re-detects. The `classes=[0]` removal is a correctness question
for whoever owns that line next: worth flagging rather than silently
re-adding it back in, since it's inside the file this session doesn't
edit without explicit sign-off.

---

## 2026-08-17 — Working the gap ledger from the last audit

**Decision:** Went through the gap list in order, fixing what's in scope
and flagging what isn't, rather than silently working around the two
that touch files this session doesn't own outright.

**Why / what changed, per gap:**

- **Barrier-store wiring, re-added to `main.py`.** The parallel edit that
  dropped it wasn't intentional (see the entry above) - restored the same
  two-line change: the `shared.barrier_store` import and the
  `barrier_store.set()` call in `/detect-crowd`'s success path.
- **`classes=[0]`, restored in `main.py`.** Confirmed with the user first
  rather than guessing - detection should only count people, not every
  COCO class. Restored in both `/detect-crowd` and `/detect-image`.
- **Unknown `destination_id` (`orchestrate()`).** `check_and_widen_radius()`
  raising `ValueError` is now caught in `orchestrate()` and turned into
  `{"status": "unknown_destination"}` instead of propagating as an
  unhandled 500.
- **Empty result after widening (`orchestrate()`).** A zero-length
  `recommendations` list now gets its own status,
  `"no_alternatives_found"`, instead of masquerading as `"success"`.
- **Track B's own failure vs. "not crowded" (`orchestrate()`).** Added an
  explicit branch: `crowd_level == "unknown"` now returns
  `{"status": "detection_failed", ...}` before the HIGH/VERY_HIGH check
  ever gets a chance to misread it as "not barriered."
- **Input validation on `/recommend`.** Added checks for a blank
  `destination_id`, a non-image content type, an empty upload, and a
  10MB upload cap - all return a clean `{"status": "invalid_request", ...}`
  rather than crashing further down the pipeline. Full auth and
  rate-limiting deliberately left alone - out of proportion for a
  hackathon demo, not an oversight.
- **In-memory-only barrier store.** Left as-is. `shared/barrier_store.py`
  is off-limits to edit this session, and a real fix (Redis or similar)
  is a bigger architectural change than a "gap fill" - documented as an
  accepted limitation, not silently worked around.
- **No automated tests.** Added a real `tests/` suite (`pytest`, pinned in
  `requirements.txt`) covering the barrier store, `recommend.py`,
  every `orchestrate()` outcome (six distinct statuses now, up from
  four), `explain()`, and the live `/recommend` endpoint through
  `TestClient` - 42 tests, all passing.

**Found while writing the tests, not fixed:** `shared/barrier_store.py`'s
`is_fresh()` only compares against the caller's `max_age_minutes`
argument - it never checks the entry's own `ttl_minutes`. An entry that
`get()` already treats as expired can still report `True` from
`is_fresh()` if `max_age_minutes` is more lenient than that entry's own
TTL. Not a live bug today: `check_staleness()` always calls `get()` first
and short-circuits on `None` before `is_fresh()` is ever consulted, so
the inconsistency is currently harmless in practice - but `is_fresh()`
isn't safe to call on its own. The test documents the real behavior
(`tests/test_barrier_store.py::test_is_fresh_ignores_the_entrys_own_ttl`)
rather than asserting something false. `shared/barrier_store.py` is
off-limits to edit this session, so this is reported, not patched.

**Tradeoffs:** `tests/conftest.py` changes the pytest process's working
directory to `track_B_CV/` at collection time, because `main.py` loads
its weights file by a relative path and anything importing it (directly
or via `agent_orchestrator.app`) needs to find that file. A more robust
fix would be for `main.py` to resolve its weights path relative to its
own file location rather than the process cwd - flagged here rather than
changed, since it's inside the file this session only touches with
explicit sign-off.

---

## 2026-08-17 — Groq wired into both marked integration points

**Decision:** `agent_orchestrator/groq_client.py` is a single thin
wrapper (`complete(prompt) -> str | None`) around the Groq chat API,
reading `GROQ_API_KEY` from the environment. Every other new piece calls
through this one function and treats `None` as "unavailable," never as
an error to raise:

- **Track C.** `GroqTrackCClient` (`track_c_client.py`) tries an LLM
  explanation first, falls back to Track C's existing rule-based
  `explain()` on a missing key, a network failure, or any exception.
  `NlpTrackCClient` (the pure rule-based one) stays as-is - nothing about
  it changed, it's just no longer what `app.py` uses by default.
- **`should_ask_preference()`'s tie-break.** `preference_resolver.py`
  adds `resolve_tie(tied_candidates, user_preference) -> dict | None`,
  which asks Groq to pick the best-matching candidate from free text
  like "somewhere quieter." `orchestrate()` gained an optional
  `user_preference` parameter - when a tie would otherwise trigger
  `needs_preference` and a preference string was given, a successful
  resolution promotes that candidate to the front of the results and
  the request finishes as `"success"` instead of stopping to ask. No
  preference given, no key configured, or Groq fails to return something
  parseable → falls straight back to `needs_preference`, unchanged from
  before this existed.
- **`app.py`.** `/recommend` gained an optional `preference` form field,
  threaded straight through. `load_dotenv()` runs at import time so a
  local `.env` file (never committed - added to a new root `.gitignore`
  alongside `__pycache__`/`venv`) is enough to configure the key without
  touching any code. `.env.example` documents the one variable needed.

**Why:** This reverses the earlier standing rule for this session ("no
external LLM calls"), on direct request - both integration points were
deliberately marked but left unwired specifically so this could be added
later without restructuring anything. Fail-soft was non-negotiable:
losing network access or an expired key should degrade explanation
quality, not take down `/recommend`. That's why every new function
returns `None` on failure instead of raising, and why the rule-based
implementations (`NlpTrackCClient`, the plain `needs_preference` path)
were kept intact rather than replaced.

**Verified:** all 52 tests pass, including 10 new ones - `complete()`
returning `None` with no key configured (true in this environment, so
this exercises the real fallback path, not a mock), the LLM-response
path via a mocked `complete()`, `resolve_tie()` picking the right
candidate from a mocked numeric reply and rejecting a garbage or
out-of-range one, and three `orchestrate()`-level scenarios (tie with no
preference, tie with a preference but no key, tie resolved by a mocked
Groq response). Also re-ran the full live `/recommend` endpoint with no
key configured end-to-end - identical output to before this change,
confirming the fallback is genuinely silent.

**Tradeoffs:** None of this has been tested against the real Groq API -
there's no key available in this environment. `GROQ_MODEL` in
`config.py` (`llama-3.1-8b-instant`) is a starting guess for a fast,
low-latency model reasonable for a live-inference demo; whoever adds the
real key should sanity-check that model name is still current and
swap it if not.
