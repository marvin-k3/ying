# RTSP Music Tagger — Implementation Plan (TDD-First)

## 0) Goals & Constraints

* Ingest **multiple RTSP streams** (≤5) → extract **12s** audio windows every **120s** → call **Shazam (unofficial)** and **AcoustID** in parallel.
* **Decision policy**: Shazam **two-hit confirm** (same track in consecutive windows) → insert a **play**; AcoustID stored for observability only.
* Persist to **SQLite** with forward-only **SQL migrations**.
* Web UI (FastAPI + Jinja + Bootstrap CDN) shows **day view**, **search** (FTS + embeddings), **diagnostics**, **clusters** (UMAP+HDBSCAN), with **Chart.js** for histograms/scatter.
* **Prometheus** metrics; **OpenTelemetry** traces to Jaeger.
* **No auth**; bind `0.0.0.0:44100` (you’ll map ports as needed).
* **Hot reload** via **SIGHUP** and **/internal/reload** (no auth).

---

## 1) Repo Layout (confirmed)

```
app/
  main.py                 # FastAPI app + startup (spawns workers)
  config.py               # env parsing & defaults
  logging_setup.py        # structured logs + trace correlation
  tracing.py              # OpenTelemetry init (OTLP → Jaeger)
  metrics.py              # Prometheus registry + ASGI middleware
  scheduler.py            # windowing, two-hit confirm, fakeable Clock
  ffmpeg.py               # async ffmpeg runner (fakeable)
  worker.py               # per-stream orchestration
  recognizers/
    base.py               # MusicRecognizer interface + models
    shazamio_recognizer.py
    acoustid_recognizer.py
  db/
    migrations/           # 0001_init.sql, 0002_*.sql…
    migrate.py            # simple forward-only migrator
    repo.py               # aiosqlite queries (dedup logic)
    fts.py                # FTS5 + triggers
  embeddings/
    embedder.py           # SentenceTransformers wrapper (CPU)
    index.py              # cosine kNN + FTS blending
  clustering/
    pipeline.py           # UMAP + HDBSCAN (seeded)
    models.py             # persisted artifacts
  web/
    routes.py             # /, /search, /diagnostics, /clusters, /internal/reload
    templates/            # Jinja2; Bootstrap + Chart.js via CDN
    static/
  devharness/
    wav_stream.py         # --from-wav mode
tests/
  unit/                   # fakes for FFmpeg, Recognizers, Clock, Embedder
  integration/            # app boot with temp DB; /metrics, /healthz
  data/                   # tiny WAVs, JSON fixtures
```

---

## 2) ENV Contract (final)

Core:

* `PORT=44100`, `TZ=America/Los_Angeles`, `DB_PATH=/data/plays.db`
* `ENABLE_PROMETHEUS=true`, `METRICS_PATH=/metrics`
  Streams:
* `STREAM_COUNT=5`, `STREAM_1_NAME=…`, `STREAM_1_URL=…`, `STREAM_1_ENABLED=true` … up to 5
  Windowing / Dedup:
* `WINDOW_SECONDS=12`, `HOP_SECONDS=120`, `DEDUP_SECONDS=300`
  Decision:
* `DECISION_POLICY=shazam_two_hit`, `TWO_HIT_HOP_TOLERANCE=1`
  Retention:
* `RETAIN_PLAYS_DAYS=-1`, `RETAIN_RECOGNITIONS_DAYS=30`, `RETENTION_CLEANUP_LOCALTIME=04:00`
  Providers:
* `ACOUSTID_ENABLED=true`, `ACOUSTID_API_KEY=…`, `CHROMAPRINT_PATH=/usr/bin/fpcalc`
  Logging/Tracing:
* `LOG_LEVEL=INFO`, `STRUCTURED_LOGS=true`
* `OTEL_SERVICE_NAME=rtsp-music-tagger`, `OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317`, `OTEL_TRACES_SAMPLER_ARG=1.0`
  Queues/Backpressure:
* `GLOBAL_MAX_INFLIGHT_RECOGNITIONS=3`, `PER_PROVIDER_MAX_INFLIGHT=3`, `QUEUE_MAX_SIZE=500`
  Clustering/Embeddings:
* `CLUSTERS_ENABLED=true`
* `EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2`, `EMBED_MODEL_REVISION=main`, `EMBED_DEVICE=cpu`
  Reload:
* `/internal/reload` **enabled by default**; SIGHUP also supported.

---

## 3) Database (SQLite) — Schema & Migrations

Tables: `streams`, `tracks`, `plays`, `recognitions` (+ `schema_migrations`), plus FTS and embeddings tables.

* `tracks`: `UNIQUE(provider, provider_track_id)`, store artwork + metadata JSON.
* `plays`: FK to `tracks` & `streams`, `dedup_bucket = recognized_at_utc / dedup_seconds`, `UNIQUE(track_id, stream_id, dedup_bucket)`.
* `recognitions`: store raw JSON per provider for diagnostics/metrics.
* `tracks_fts(title, artist)` (FTS5) + triggers.
* `track_embeddings(track_id PK, provider, dim, vector BLOB, updated_at_utc)`.

**Migrations**: forward-only `.sql` files; `migrate.py` applies pending files on startup.

**TDD (write first)**

* In-memory DB migration test (applies 0001), asserts tables/indexes/uniques.
* Property test: random timestamps respect dedup uniqueness.
* Repo tests: upsert track; insert play de-duped; day queries with PT boundary.

---

## 4) Audio Ingest & Scheduling

* `ffmpeg.py`: spawn with `-rtsp_transport tcp -stimeout 10000000 -rw_timeout 15000000 -vn -ac 1 -ar 44100 -f wav pipe:1`; robust restart/backoff.
* `scheduler.py`: assemble **12s** WAV windows every **120s**; **fakeable Clock**; no real sleeps in tests.
* `worker.py`: per stream: `FFmpegRunner` → `WindowScheduler` → `RecognizersParallel` → `DecisionAggregator` → DB.

**TDD**

* Fake `FFmpegRunner` yields scripted PCM; table-driven assert of ffmpeg args.
* Scheduler unit tests with fake clock: windows & hops correct; DST boundaries safe.
* Backpressure tests: caps respected; overflow drops oldest per stream.

---

## 5) Recognition Layer

* Interface `MusicRecognizer.recognize(wav_bytes, timeout)` → `RecognitionResult` (track\_id-like key, title, artist, album, isrc?, confidence/score, artwork, raw JSON).
* `shazamio_recognizer.py` (async; reverse-engineered API; 12s clips).
* `acoustid_recognizer.py` uses `fpcalc` + AcoustID + MusicBrainz.

**Policy A (final)**: **Shazam two-hit confirm** drives `plays`; AcoustID stored only in `recognitions`.

**TDD**

* Fake recognizer for unit tests (no network).
* Contract tests w/ recorded fixtures: low/med/high confidence, “no match”.
* Aggregator tests: two-hit confirm logic across consecutive windows; dedup never double-inserts.

---

## 6) Web App (FastAPI + Jinja + Bootstrap CDN)

Routes:

* `GET /` (Day View): date picker (PT), stream filter, table: time (PT), title, artist, stream, confidence, **album art**, provider link, **CSV download**.
* `GET /api/plays?date=YYYY-MM-DD&stream=name|all` (JSON for table & CSV).
* `GET /diagnostics` (recent recognitions with status, latency, raw JSON link).
* `GET /search?q=…` — blended **FTS+embeddings**; per result show **last-30-days histogram** (Chart.js).
* `GET /clusters` — 2D UMAP scatter (Chart.js scatter), cluster tables with top tracks.
* `GET /healthz`, `GET /metrics`, `POST /internal/reload`.

**TDD**

* FastAPI `TestClient` golden HTML for `/`, `/search`, `/diagnostics`, `/clusters` (when enabled).
* API tests: bad params, empty days, pagination.
* Histogram data tests across DST & month edges.

---

## 7) Search (FTS + Embeddings)

* FTS5 tokenizer: `unicode61 remove_diacritics=2 tokenchars ".'-&/"`; synonym expand for `feat.`/`ft` and `and/&`.
* Embed titles (and optionally artist) via SentenceTransformers (`all-MiniLM-L6-v2`, CPU).
* Blend: **`score = 0.6 * FTS_norm + 0.4 * cosine`**; candidates from both (top100 each) → top50.

**TDD**

* Fake embedder returns deterministic vectors (no HF calls).
* Golden queries: “Beyoncé/Beyonce”, “AC/DC”, “feat./ft.”; ensure exact FTS hits never get dropped by blending.

---

## 8) Clustering (Nightly, recent plays)

* Schedule **03:30 PT daily**; scope: tracks with ≥2 plays in last **90 days**.
* UMAP (cosine): `n_neighbors=15`, `min_dist=0.1`, seed=42 → 2D.
* HDBSCAN on UMAP-2D: `min_cluster_size=8`, `min_samples=5`.
* Persist coordinates + labels; render scatter via Chart.js (tooltip shows title/artist).

**TDD**

* Deterministic seeds; golden labels on tiny synthetic set.
* If `CLUSTERS_ENABLED=false`, routes return 404.

---

## 9) Observability

**Prometheus metrics** (agreed):

* Counters: `ffmpeg_restarts_total{stream}`, `recognitions_*`, `plays_inserted_total{stream,provider}`, `retention_deletes_total{table}`
* Histograms: `recognizer_latency_seconds{provider}`, `window_to_recognized_seconds{stream}`, `ffmpeg_read_gap_seconds{stream}`
* Gauges: `streams_active{stream}`, `queue_depth{name}`, `*_last_run_timestamp`, `embeddings_index_size`
* HTTP: request counters + duration

**Tracing**:

* OTLP to Jaeger; instrument FastAPI, aiohttp, DB spans; inject trace/span IDs into logs.

**TDD**

* In-memory span exporter asserts span names/attrs; `/metrics` golden scrape.

---

## 10) Retention Jobs

* Daily at **04:00 PT**: delete `recognitions` older than `RETAIN_RECOGNITIONS_DAYS`; `plays` per `RETAIN_PLAYS_DAYS` (-1 keep forever).
* Weekly `VACUUM` + `ANALYZE`; WAL mode at startup.

**TDD**

* Fake clock; boundary tests for inclusive/exclusive cutoffs; property test never deletes “too new”.

---

## 11) Dev Harness

* `devharness/wav_stream.py --from-wav file.wav` simulates a stream (skips ffmpeg).
* Scripted fixtures and JSON recognizer fakes make end-to-end tests hermetic.

---

## 12) Dockerfile (Plan A)

```dockerfile
# Dockerfile
FROM python:3.12-slim

# System deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Install uv + rye
RUN pip install --no-cache-dir uv && \
    pip install --no-cache-dir rye

WORKDIR /app
# Copy project files (adjust as needed)
COPY pyproject.toml ./
# Resolve & install deps (uv as backend via rye)
RUN rye sync --no-dev

# Now copy source
COPY app ./app
COPY tests ./tests

# Create data dir and user
RUN useradd -m appuser && mkdir -p /data && chown -R appuser:appuser /data /app
USER appuser

ENV DB_PATH=/data/plays.db \
    PORT=44100 \
    TZ=America/Los_Angeles

EXPOSE 44100
VOLUME ["/data"]

# Run via uvicorn (single-process; asyncio workers inside)
CMD ["rye", "run", "serve"]
```

**Build/Run**

```bash
docker build -t rtsp-music-tagger .
docker run --rm -it \
  -e STREAM_COUNT=2 \
  -e STREAM_1_NAME=living \
  -e STREAM_1_URL=rtsp://user:pass@cam1/stream \
  -e STREAM_1_ENABLED=true \
  -e STREAM_2_NAME=yard \
  -e STREAM_2_URL=rtsp://user:pass@cam2/stream \
  -e STREAM_2_ENABLED=true \
  -e ACOUSTID_ENABLED=true \
  -e ACOUSTID_API_KEY=YOUR_KEY \
  -p 127.0.0.1:44100:44100 \
  -v $(pwd)/data:/data \
  rtsp-music-tagger
```

---

## 13) Development Scripts (Rye)

* `dev`: `uvicorn app.main:app --host 0.0.0.0 --port 44100 --reload`
* `serve`: `uvicorn app.main:app --host 0.0.0.0 --port 44100`
* `test`: `pytest -q --cov=app --cov-report=term-missing --cov-fail-under=85`
* `lint`: `ruff check .` / `fmt`: `ruff format .` / `typecheck`: `mypy app`
* `migrate`: `python -m app.db.migrate`
* `embed-backfill`: `python -m app.embeddings.index backfill`
* `clusters-recompute`: `python -m app.clustering.pipeline run-once`
* `dev-wav`: `python -m app.devharness.wav_stream --from-wav ./tests/data/demo.wav`

---

## 14) Milestones & Test Checklist

**M0 – Scaffold & Config**

* Implement `config.py` w/ validation.
* Tests: table-driven for envs (STREAM\_\* bounds, defaults).

**M1 – DB Migrations + Repo**

* Write `0001_init.sql`; `migrate.py`; repo CRUD.
* Tests: migration idempotency; dedup uniqueness; FK/CK enforced.

**M2 – Metrics, Logging, Tracing**

* ASGI metrics, JSON logs, OTEL init.
* Tests: `/metrics` present; in-memory traces emitted.

**M3 – FFmpeg Runner**

* Async spawn, read stdout, restart on EOF/backoff.
* Tests: fake runner; arg builder; restart policy.

**M4 – Scheduler + Two-Hit**

* Windowing, hop, dedup seconds; aggregator logic.
* Tests: fake clock; two-hit confirm across windows; tolerance.

**M5 – Recognizers**

* Shazamio adapter + fixtures; AcoustID adapter + fpcalc shim.
* Tests: contract fixtures; timeout/error paths; parallel calls capped.

**M6 – Worker Orchestration**

* Glue pipeline; global caps; overflow policy.
* Tests: backpressure invariants; fairness across 5 streams.

**M7 – Web: Day View + CSV**

* Jinja templates; PT grouping; CSV endpoint.
* Tests: golden HTML/CSV; DST boundary grouping.

**M8 – Diagnostics**

* Table + raw JSON link.
* Tests: golden HTML; paging; filter by date/stream.

**M9 – Search (FTS + Embeddings)**

* FTS setup; embedder; blending; last-30-days histogram data; Chart.js.
* Tests: diacritics/AC-DC/feat synonyms; blend never drops exact FTS hits.

**M10 – Clusters**

* Nightly job; UMAP+HDBSCAN; scatter page.
* Tests: deterministic labels; route disabled when off.

**M11 – Retention + Maintenance**

* Daily cleanup; weekly VACUUM/ANALYZE; WAL enable.
* Tests: boundary deletions; never delete too-new.

**M12 – Hot Reload**

* SIGHUP + `/internal/reload` restart workers.
* Tests: fake config source; route 200; workers restarted deterministically.

**M13 – E2E Smoke**

* Boot app with temp DB; feed `--from-wav`; ensure `/healthz`, `/metrics`, `/` render.

---

If you want, I can also generate the **initial migration SQL** (`0001_init.sql`) and **starter test files** next.
