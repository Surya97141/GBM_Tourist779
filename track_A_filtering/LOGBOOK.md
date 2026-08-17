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

---

## 2026-08-17 — shared/barrier_store.py: fixed a real crash, not just a warning

**Decision:** `datetime.datetime()` (three call sites: `set()`,
`is_fresh()`, `_is_expired()`) replaced with `datetime.now(timezone.utc)`.

**Why:** This wasn't the `datetime.utcnow()` deprecation warning noted
earlier - somewhere between then and now, someone's own attempt to quiet
that warning landed on `datetime.datetime()` instead, which doesn't
exist on the `datetime` class this file imports (`from datetime import
datetime` - so `datetime` here already *is* the class, not the module).
Every call to `barrier_store.set()` was raising `AttributeError: type
object 'datetime.datetime' has no attribute 'datetime'` - confirmed by
running it directly before touching anything. `/detect-crowd`'s success
path would have failed on every single request. `datetime.now(timezone.utc)`
is the actual non-deprecated replacement for `utcnow()` - a real
timezone-aware UTC timestamp instead of a naive one that only claimed to
be UTC by convention.

**Tradeoffs:** None - this is a straight correctness fix, done with
explicit go-ahead to edit this file for this one purpose. Timestamps
stored from here on are timezone-aware; anything reading `entry["timestamp"]`
elsewhere and assuming a naive datetime would need to be aware of that
distinction, though nothing in this codebase currently does arithmetic on
it outside this file. The `is_fresh()` gap noted earlier this session
(ignores the entry's own `ttl_minutes`) is untouched - out of scope for
this specific fix.

---

## 2026-08-17 — Real Groq key added; caught a test that only worked by accident

**Decision:** A real `GROQ_API_KEY` was provided and written to a local
`.env` (git-ignored, never committed). Both integration points now run
against the live API instead of the fallback path.

**Why:** Confirms the whole point of building `groq_client.py` /
`preference_resolver.py` / `GroqTrackCClient` fail-soft in the first
place - this was the first real test against the actual API, not a mock.
`resolve_tie()` picked the Nature candidate over Heritage and Temple
options for "somewhere quiet and green, not a historical monument" -
genuinely reasoned, not a lucky guess. `GroqTrackCClient` produces
noticeably richer explanations than the rule-based fallback, as expected.

Adding the real key immediately broke four tests
(`test_groq_integration.py`), and the reason was worth catching: those
tests asserted "no key configured" by relying on the *ambient*
environment happening not to have `GROQ_API_KEY` set, rather than forcing
that condition directly. The moment a real `.env` existed, `app.py`'s
`load_dotenv()` (triggered just by another test file importing it) put
the key into the process environment for the rest of the test run, and
the "no key" tests started seeing a real client. Fixed by patching
`agent_orchestrator.groq_client._get_client` directly to return `None`,
so those four tests now assert the fallback path unconditionally -
true whether a real `.env` exists or not, instead of true by accident.

**Tradeoffs:** None of this has been committed or will be - `.env` stays
local and git-ignored. The key itself arrived pasted directly into a chat
message, which is worth flagging plainly: anything shared that way is
worth treating as at least potentially exposed and rotating if this
matters. Not this session's call to make, just noting it here since it's
a real fact about how this key entered the project, not a hypothetical.

---

## 2026-08-17 — model_training/ added for judge-facing model justification

**Decision:** New top-level folder, `model_training/`, answering "why
YOLOv8n, and why this fine-tune" with evidence that's either extracted
directly from `track_B_CV/yolov8n_best.pt`'s own embedded training
history or measured live on this machine - nothing fabricated, no invented
benchmark numbers. Two reproducible scripts
(`extract_training_history.py`, `compare_variants.py`) plus a README
tying the real output together.

**Why:** The concern was specific: judges asking "why didn't you train
this yourselves" and the team not having a real answer ready. Turned out
the checkpoint already had the answer embedded in it - Ultralytics
checkpoints keep the full per-epoch `train_results` history inside the
`.pt` file, not just final weights, so `yolov8n_best.pt` already proves
100 real training epochs happened (precision 0.806, recall 0.638, mAP50
0.740, mAP50-95 0.463, clean convergence by ~epoch 70-80) without needing
to retrain anything or reconstruct history from nothing. For "why nano
specifically," downloaded the official yolov8s.pt/yolov8m.pt and measured
real CPU inference latency and parameter counts side by side with nano -
nano runs in roughly a third of medium's time on an eighth of the
compute, which is the actual, defensible reason for the choice given this
project's real deployment target (a laptop CPU, not a GPU server) and a
four-bucket LOW/MEDIUM/HIGH/VERY_HIGH output that doesn't need
maximum-precision localization to be useful.

**What's deliberately not claimed:** there's no original validation set
on hand to recompute a fair head-to-head mAP between the fine-tuned model
and the plain COCO checkpoint on identical held-out data, so the README
says that directly instead of presenting an invented or approximate
number as if it were measured. The CrowdHuman dataset attribution comes
from the team's own earlier code comments in `main.py`, not from
anything independently verifiable in the checkpoint's metadata (its
`train_args` only shows a generic `dataset.yaml` and a project name of
`yolov8n-person`) - the README is explicit about which claims are which.

**Tradeoffs:** The variant-comparison script downloads ~80MB of official
Ultralytics weights (yolov8s.pt, yolov8m.pt) to measure against - those
aren't committed, the script re-downloads them fresh each run, so
`model_training/` itself stays under 150KB despite the comparison being
against real, freshly-fetched models rather than cached assumptions.

---

## 2026-08-17 — model_training/: added a real training run, not just checkpoint inspection

**Decision:** A comparison table alone doesn't prove the team can run a
training loop, only that they can read one someone else already ran. So
`train_demo_run.py` and `plot_demo_run.py` were added, and actually
executed: 15 real epochs, real backprop, on this machine, right now -
starting from COCO-pretrained `yolov8n.pt` and fine-tuning on
Ultralytics' `coco128` sample set (the original CrowdHuman-derived data
`yolov8n_best.pt` was trained on isn't available in this environment).
Real outputs kept in `outputs/`: loss/accuracy curves plotted from the
run's own `results.csv`, the confusion matrix Ultralytics generated, the
raw `results.csv` itself, and - the most concrete evidence - an actual
prediction image showing the resulting checkpoint correctly detecting
`person` across several genuinely different held-out validation scenes
(a baseball game, a tennis match, a family group, someone by a lake).

**Why:** Hyperparameters were chosen to mirror `yolov8n_best.pt`'s own
recorded `train_args` where practical (`optimizer=auto`, same
transfer-learning starting point). Epochs (100 → 15) and image size
(640 → 320) were cut specifically and only for CPU runtime - no GPU is
available here, and the README says this directly rather than letting a
smaller-scope demo run pass as a reproduction of the production
training. Final person-class precision on this demo run came out at
0.960 (mAP50 0.622) - lower overall than the 100-epoch production run
across all 80 coco128 classes (expected: 15 epochs, a much smaller
per-class sample, and a harder multi-class task), but real, and openly
labeled as a smaller-scope demonstration rather than dressed up as
equivalent to production.

**Tradeoffs:** `model_training/` grew from under 150KB to ~900KB once the
real prediction image, confusion matrix, and results CSV were added -
still small, and every byte of the increase is real training output, not
padding. The training run's own large working files (checkpoint weights,
downloaded `yolov8n.pt`, full batch visualization images) were deleted
after the lightweight artifacts were extracted - `train_demo_run.py`
writes to a local `.train_run/` directory, now added to `.gitignore`
alongside the two scratch directories `compare_variants.py` and the
timing tests used, so rerunning any of these scripts won't accidentally
stage large binaries.

---

## G-01 / G-02 verified end-to-end via real running services, not fake clients

**Decision:** No code change to `orchestrator.py` - both fixes (catching
`ValueError` from `check_and_widen_radius()` into `{"status": "unknown_destination", ...}`,
and an empty `recommendations` list after widening returning
`{"status": "no_alternatives_found", ...}` instead of a hollow
`"success"`) were already in place from earlier work and matched this
task's spec exactly on inspection. This entry records the real
verification, not a code fix.

**Why this needed a throwaway script instead of pure curl:** Started
`track_B_CV/main.py` and `agent_orchestrator/app.py` as two separate real
`uvicorn` processes and confirmed the full pipeline end-to-end with a
real photo and a real destination_id - genuine response, no crash. But
`HttpTrackBClient` (`agent_orchestrator/track_b_client.py`) uses
`fastapi.testclient.TestClient` against an in-process import of
`track_B_CV.main.app`, not a network call - confirmed by grepping the
standalone Track B process's own log after the request: zero
`/detect-crowd` hits reached it. The orchestrator's request never left
its own process. That means `barrier_store` in the live orchestrator
process can't be seeded from outside it - there's no IPC, no endpoint
for it, and no real crowd photo available to force a HIGH/VERY_HIGH
reading through genuine detection. Both G-01 and G-02 need a
HIGH/VERY_HIGH reading to even reach the code path being tested, so a
fresh script importing the real `agent_orchestrator.app` (real
`HttpTrackBClient`, real `GroqTrackCClient`, real `orchestrate()` - no
`FakeTrackBClient`/`FakeTrackCClient` anywhere) and seeding
`barrier_store` directly in that same process was the only way to
actually trigger either path with real production code. Both asserted
and printed a passing result; see this session's response to the
verification task for the exact output.

**Tradeoffs:** `httpx==0.28.1` added to `requirements.txt`, pinned -
`TestClient` requires it and it was previously only present transitively
(via `groq`'s own dependency chain), not guaranteed. `requests` was not
added - nothing in this codebase uses it. The architectural fact that
`HttpTrackBClient` doesn't actually call over the network is not new
behavior introduced here, just newly confirmed by directly observing
Track B's standalone process log receive zero traffic during a real
end-to-end request - `track_b_client.py` itself is out of scope for this
task's edits, so it's reported rather than changed.

---

## live_demo.py: manual "submit this frame" bridge to the real pipeline

**Decision:** `live_demo.py` gained a manual, keypress-triggered bridge -
pressing S takes the current camera frame, encodes it as JPEG, and sends
it as a real `requests.post()` HTTP call to `RECOMMEND_ENDPOINT`
(`agent_orchestrator/app.py`'s `/recommend`, default
`http://127.0.0.1:8000/recommend`), using `DEMO_DESTINATION_ID` as the
destination. The response prints to the console formatted for live
reading and shows a short summary banner on the video window for a few
seconds. Nothing about the existing detection/display loop changed when
S isn't pressed - it's additive, not a rewrite.

**Why:** This is a genuine cross-process network call this time, not the
in-process `TestClient` `HttpTrackBClient` uses elsewhere - `live_demo.py`
and `agent_orchestrator/app.py` really are two separate running programs
here, confirmed by actually running both during testing. A judge watching
the live camera feed can now see the real pipeline's actual answer for a
real frame on demand, without the demo ever auto-submitting or silently
writing to `barrier_store` on every frame - only an explicit keypress
reaches the real pipeline, matching the existing "demo convenience, not
part of the API" framing this file already had. Errors (orchestrator not
running, timeout) are caught specifically (`requests.exceptions.ConnectionError`,
`.Timeout`, then a general `.RequestException` for anything else
request-related) and turned into a clean dict rather than an unhandled
exception - a failed submit shows an error banner and the camera feed
keeps running, exactly as specified.

**Timeout value, measured not guessed:** started the real orchestrator
fresh and timed the literal first request against it - 4.74s, a one-time
model warm-up cost paid once per process, not per request (a second
request to the same warm process came back in 0.01-0.25s). A 5-second
timeout would intermittently fail on exactly the first demo attempt after
starting the service, which is the worst possible moment for it to fail.
Set to 15 seconds instead, with the reasoning left as a comment at the
constant so nobody drops it back to "a few seconds" without knowing why.

**Tradeoffs:** The request is synchronous - the camera preview visibly
pauses for the duration of the request (fast after warm-up, up to 15s
worst case on the very first press). No threading/async was added to
avoid it, since this is a single deliberate keypress action in a demo
script, not a redesign, and the task explicitly ruled out retry logic;
adding background threading for one manual trigger would be more
complexity than the problem warrants here. `DEMO_DESTINATION_ID` is a
hardcoded constant that has to be set correctly per physical camera
setup before a demo - there's no way for the script to know what
location it's pointed at on its own, so this is a manual step, documented
at the constant itself. `requests` is used here (per the task's
instruction) but still isn't pinned in `requirements.txt` - that file was
out of scope for this task's edits, and a previous logbook entry's claim
that "nothing in this codebase uses `requests`" is now out of date

---

## live_demo.py: DEMO_DESTINATION_ID replaced with a switchable list

**Decision:** The single `DEMO_DESTINATION_ID` constant is gone, replaced
by `DEMO_DESTINATIONS`, a hardcoded list of five `(destination_id, name)`
pairs pulled from `track_A_filtering/destinations.json` - two forts
(Amber, Jaigarh), one monument (Hawa Mahal), one market (Johari Bazaar),
one temple (Birla Mandir) - switched live with number keys 1-5.
`SELECT_KEYS` maps key code to list index and is built from
`len(DEMO_DESTINATIONS)` rather than hardcoded to 5, so the key range in
the on-screen hint and the actual handling can't drift apart if the list
ever changes. The currently selected destination now shows persistently
on screen (`Target: <name> (<id>)`), not just briefly after switching, and
`submit_current_frame()` is called with whichever destination is active
at the moment S is pressed, not a fixed value.

**Why:** An operator standing at a venue needs to say "camera's on the
market now" between shots without editing the file and restarting the
whole script - that's the entire point of this change. Five is a hardcoded
demo subset by design, not the real 21-destination catalogue - a live
demo needs a short, memorable set reachable by a single keypress, not a
scrollable list. This isn't loaded from `destinations.json` at runtime;
the task was explicit that a short hardcoded subset is the right call
here, and pulling the full catalogue in would mean more than 9 keys are
needed to reach some of it, which defeats the purpose.

**Tradeoffs:** The on-screen label for `dest_009` reads "Birla Mandir,"
shortened from its full catalogue name "Birla Mandir (Laxmi Narayan
Temple)" - deliberate, for a banner that has to stay readable at a
glance, and harmless since only `destination_id` (not the display name)
is what actually reaches the real pipeline. If `destinations.json`'s
names or ids ever change, this list won't notice - it's a hardcoded
snapshot, not a live reference, which is exactly why it was verified by
hand against the real file rather than assumed correct. Superseded by
this change: the previous entry's note that `DEMO_DESTINATION_ID` "has to
be set correctly per physical camera setup before a demo" - that's now a
live number-key choice instead of a file edit.

---

## live_demo.py: threaded frame reader to stop the growing display lag

**Decision:** Added `LatestFrameReader`, a small class that runs
`cap.read()` on its own background thread in a tight loop and keeps only
the single most recent frame behind a lock - not a queue. `main()`'s loop
now calls `reader.read()` instead of `cap.read()` directly, and calls
`reader.stop()` (which flips a flag and joins the thread) before
`cap.release()` on the way out.

**Why:** The old loop called `cap.read()`, ran YOLO inference, then
displayed, all in series. `cv2.VideoCapture` keeps its own internal
buffer of arrived-but-unread frames, so any time inference took longer
than the camera's actual frame interval, the backlog grew - observed at
6-8+ seconds and climbing the longer the demo ran, because nothing was
ever draining that buffer except the same slow loop that was falling
behind in the first place. Reading on a separate thread that never blocks
on inference means the buffer never has a chance to accumulate - it's
drained continuously and only the latest frame is kept, so frames genuinely
get dropped when inference can't keep up, which is correct: a demo should
show the newest reality, not work through a queue of increasingly stale
ones. `cv2.CAP_PROP_BUFFERSIZE` was considered and specifically not used -
it's inconsistently honored on FFMPEG-backed network streams, which is
what `STREAM_URL` is, so it wouldn't reliably bound the lag here even if
set; noted directly in the class's own docstring so nobody tries it again
expecting a different result.

**Verified:** exercised `LatestFrameReader` against a fake capture source
standing in for the camera - confirmed the background thread reads far
faster than any single-threaded loop could (tens of thousands of reads in
under half a second against a trivial fake source), confirmed `read()`
returns a genuine copy (mutating a returned frame doesn't affect the next
read), confirmed `(False, None)` when nothing's been read yet without
raising, and confirmed `stop()` actually joins the thread -
`thread.is_alive()` is `False` immediately after, and no further reads
happen afterward. Couldn't verify the actual on-screen lag reduction
directly - that needs a real camera and a human watching the window, which
this session doesn't have - but the mechanism (drain continuously, keep
only the newest, block nothing on inference) is the standard fix for
exactly this class of problem and was exercised end to end short of the
literal video output.

**Tradeoffs:** `read()` copies the frame out under the lock on every call
- a deliberate cost for correctness (the background thread could otherwise
overwrite a frame the main thread is still using mid-inference), and
trivial next to YOLO inference time. The background thread reads in a
truly tight loop with no sleep, exactly as asked for - on a real network
stream this paces itself against frame arrival, but it does mean the
thread spins as fast as `cap.read()` returns, which is a fair trade for
never missing a frame that just arrived.

---

## demo_ui/: Streamlit front end, isolated venv, and two real response-shape corrections

**Decision:** New `demo_ui/` folder - `app.py` (Streamlit page), `README.md`,
`requirements.txt`. Pure HTTP client of `/recommend`: no import of any
backend code, same `(destination_id, name)` demo subset `live_demo.py`
hardcodes, duplicated rather than imported for the same reason. Renders
one branch per known status (`success`, `not_barriered`,
`unknown_destination`, `no_alternatives_found`), plus a dedicated `error`
branch for connection failures/timeouts, plus a fallback that shows raw
JSON for anything else rather than hiding it.

**Why the isolated venv:** installing Streamlit into the same environment
as the backend's dependencies downgraded `starlette` from 1.6.0 to 1.3.1 -
confirmed directly, not assumed, by running `pip install streamlit` in
the shared venv and diffing the result. All 52 backend tests still passed
against the downgraded version, but that's beside the point: the whole
reason this page exists as a pure HTTP client is so it can never be the
reason the backend behaves differently, and a shared Python environment
is exactly the kind of coupling that guarantee is supposed to rule out,
even though it isn't a Python import. Restored the shared venv to its
pinned state (`pip install starlette==1.6.0`, backend tests re-confirmed
passing) and built a completely separate `demo_ui/venv` instead -
documented as the first step in `demo_ui/README.md`, with the actual
downgrade that was observed named directly so the reasoning doesn't get
skipped as boilerplate caution.

**Two response-shape assumptions in the task turned out to be wrong, and
were corrected rather than worked around:** the task said to "show the
crowd level prominently" for `success` and `no_alternatives_found`.
Checked both against the real running backend rather than assuming the
task's description was accurate - neither actually carries a
`crowd_level` field; that field only exists on `not_barriered`. (Makes
sense once you look at `orchestrator.py`: by the time either of those two
statuses is reached, the crowd-level check has already passed and its
specific value wasn't threaded through to the final response.) Handled
with `.get("crowd_level")` and a generic "This destination is currently
crowded" fallback when it's absent, rather than crashing on a missing key
or inventing a value that was never actually returned.

**Verified:** ran the real backend and fed `demo_ui`'s own `submit_photo()`
a real photo through a fake Streamlit-`UploadedFile`-shaped object - real
`not_barriered` response came back. Generated real `success`,
`no_alternatives_found`, and `unknown_destination` payloads the same way
this session's earlier tasks did (pre-seeding `barrier_store` in a fresh
process, since it's per-process state) and ran all of them plus a
synthetic `error` and an unrecognized `needs_preference` status through
`render_response()` with `streamlit` mocked out - all six rendered without
exception. Booted the actual Streamlit process headlessly and confirmed
it serves a real page with no startup errors. Confirmed the
backend-not-running path returns a clean error dict, not a crash, with
the backend genuinely stopped at the time. While cleaning up, found and
killed an orphaned uvicorn process left over from a previous task's
testing that was still holding port 8000 - unrelated to this task's own
work, but worth fixing since it would have made this task's own "is the
backend actually reachable" tests misleading.

**Tradeoffs:** `demo_ui/requirements.txt` is separate from the root one
by design, matching the separate-venv decision above - anyone setting
this up installs into `demo_ui/venv`, not the project's main environment.
No caching or session state beyond Streamlit's own single-run request
cycle, as specified - a second click re-submits fresh rather than
remembering the previous result.

---

## demo_ui/weather.py: per-destination current weather, display-only

**Decision:** New `demo_ui/weather.py`, one public function -
`get_weather(lat, lng) -> dict` - that calls OpenWeatherMap's
current-weather endpoint and returns either
`{"available": True, "temperature", "description", "humidity"}` or
`{"available": False, "reason": "..."}`. `demo_ui/app.py` looks up the
selected destination's coordinates directly from
`track_A_filtering/destinations.json` (reading the file, not calling any
backend function) and shows a one-line weather caption next to the
destination selector when available - nothing shown when it isn't. A
process-local dict cache, keyed by `(lat, lng)` rounded to four decimal
places, holds each result for 5 minutes so re-selecting the same
destination during a demo doesn't re-hit the API or risk the free tier's
rate limit.

**Why:** The API key comes from `OPENWEATHER_API_KEY` via `python-dotenv`
loading `demo_ui/.env` - same pattern `agent_orchestrator/app.py` already
uses for `GROQ_API_KEY` - never hardcoded, and `.env.example` documents
the variable name without a real value. Cache is keyed by coordinates
rather than `destination_id` even though the task described it that way:
`get_weather()`'s specified signature only takes `lat`/`lng`, and since
every destination in this dataset has fixed, unique coordinates, keying
by the coordinate pair is exactly as unique as keying by `destination_id`
would have been - simpler than threading an extra parameter through a
function whose signature was given explicitly. Weather fetch happens
while rendering the destination selector, structurally separate from
`submit_photo()`'s code path, so a slow or dead weather API can't delay
the actual "check crowd" request - the two have nothing in common except
both using `requests`.

**Verified:** exercised every failure path for real rather than assuming
the `try`/`except` blocks were sufficient - no key set, a genuine
connection failure against a real unreachable address, a mocked timeout,
a mocked 401, and a mocked malformed JSON body all returned a clean
`{"available": False, ...}` with no exception escaping. Mocked a
successful response to confirm the parsing matches OpenWeatherMap's
actual field names (`main.temp`, `weather[0].description`,
`main.humidity`). Confirmed the cache genuinely prevents a second live
call for the same coordinates within the TTL, confirmed two different
coordinate pairs are never conflated into the same cache entry, and
confirmed the cache actually expires and re-fetches once the TTL passes
(shrunk it temporarily in the test to make this fast to check). Confirmed
`load_destination_coordinates()` resolves real, correct coordinates for
all five demo destinations against the actual `destinations.json`. Booted
the real Streamlit app with no `OPENWEATHER_API_KEY` set at all - the
realistic default for anyone who hasn't gone through the README's setup
section - confirmed it starts cleanly with no weather line shown and no
error surfaced.

**Tradeoffs:** No real OpenWeatherMap API key is available in this
environment, so the actual live "temperature and conditions came back
correctly for a real coordinate" path was verified by mocking the
response shape to match OpenWeatherMap's documented format, not by an
actual network round trip to their service - everything up to and after
that network call was verified for real. While testing, found two more
orphaned background processes left over from earlier tasks (one holding
port 8501, one holding port 8000) that a prior `TaskStop` call hadn't
actually killed - unrelated to this task's own changes, but cleaned up
since a stray process on the same port this task needed to test against
would have made the results meaningless.

---

## track_B_CV/main.py + live_demo.py: raised the detection confidence threshold from 0.15 to 0.35

**Decision:** `conf=0.15` -> `conf=0.35` in both of `main.py`'s
`model.predict()` calls (`/detect-crowd` and `/detect-image`), and the
same change in `live_demo.py`'s `CONF_THRESHOLD` to keep it matching, as
its own comment already claims it does.

**Why:** Live-tested and directly observed the failure this was causing -
a screenshot of `live_demo.py` running showed `person 0.18` and
`person 0.20` boxes drawn on a knee and a fold of clothing, not on an
actual second and third person. Both numbers sit right at the edge of the
old 0.15 cutoff - not confident wrong guesses, the model's own stated
uncertainty being let through anyway because the bar was set low enough
to accept it. Also confirmed the reported "count kept climbing" wasn't a
counter bug: `estimated_count`/`count` are recomputed from that frame's
own `results[0].boxes` on every single call, nothing persists between
frames in either file. What looked like an increasing count was low-
confidence false positives flickering in and out on different body parts
frame to frame as the subject moved - different marginal guesses crossing
the 15% bar at different moments, not a running total.

0.35 was picked with real margin above the two observed false positives
(0.18, 0.20), while staying below a strict cutoff - the original 0.15 was
lower than Ultralytics' own inference default of 0.25, and per the
existing "FIX 3" comment already in `main.py`, that low bar looks
deliberate: catching partially-occluded, lower-confidence people in
dense, overlapping crowds is the whole reason this checkpoint was
fine-tuned in the first place. Going straight to a strict threshold
(0.5+) would fix the false-positive problem shown here while likely
undermining that original intent on the actual dense-crowd photos this
project is for.

**Verified:** all 52 backend tests still pass unchanged. Ran a live
smoke test against the real `/detect-crowd` endpoint through `main.py`
directly with the new threshold - still returns the correct response
shape, no crash. Could not reproduce the exact reported scenario (the
specific photo isn't available in this environment) - the fix targets
the confirmed root cause (the confidence math, directly readable from the
screenshot's own numbers) rather than something guessed at.

**Tradeoffs:** 0.35 is a reasoned starting point, not a value tuned
against real crowd photos or a precision/recall study - same caveat as
`LOW_CONFIDENCE_THRESHOLD` elsewhere in this project. If dense, genuinely
crowded scenes turn out to have real people sitting in the 0.15-0.35
confidence band (plausible, given heavy occlusion is exactly what this
checkpoint was fine-tuned to handle), this trades away some real recall
to remove the false positives seen here - worth revisiting once real
crowd photos are available to check against, not just a single indoor
test frame.
