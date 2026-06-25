# Agience Prism

The **embeddings** capability host for Agience — `bge-m3` served as `embeddings.embed`
over `POST /embed`, built on **agience-host**. AGPL-3.0.

    POST /embed  {"input": ["text", ...]}  ->  {"vectors": [[float, ...]], "model_id": "..."}

The **model is not baked into the image** — it caches to `$HF_HOME` (a mounted volume)
on first boot, so the image stays small and restarts are fast. Prism talks to the
platform only over the wire (Mantle calls `/embed`); it never imports core.

## Build & publish (public image — no pull token)

Prism depends on the `agience-host` SDK. Until the host is on PyPI, the build pulls
it from a sibling checkout via a BuildKit **named context** — no PyPI, no giant build
context:

```bash
# GPU image (RunPod). Run from the agience-prism repo root, with agience-host as a sibling dir:
docker build --build-context host=../agience-host \
  -f Dockerfile.gpu -t <your-namespace>/agience-prism:gpu .
docker push <your-namespace>/agience-prism:gpu        # push to a PUBLIC repo
```

`Dockerfile` is the CPU variant (same `--build-context`). **Once `agience-host` is
published to PyPI,** drop `--build-context` and the two `host` lines in the Dockerfile
— `pip install .` then resolves `agience-host` directly.

## Deploy on RunPod

1. **Deploy a Pod** → your `<ns>/agience-prism:gpu` image.
2. **Attach a Network Volume**, mounted at **`/data`** (model caches in `/data/hf`).
3. **Expose HTTP port `8083`.**
4. **Env:** `EMBEDDINGS_SERVER_API_KEY=<long random secret>` (the proxy URL is public — set it). `EMBEDDINGS_DEVICE=cuda` is baked into the GPU image.
5. Test:
   ```bash
   curl https://<podid>-8083.proxy.runpod.net/health
   curl -X POST https://<podid>-8083.proxy.runpod.net/embed \
     -H "Authorization: Bearer <secret>" -H "content-type: application/json" \
     -d '{"input":["hello"]}'
   ```

## Wire it to the platform

On **mantle**:

    EMBEDDINGS_URI=https://prism.agience.ai          # managed endpoint
    EMBEDDINGS_API_KEY=<the same secret as EMBEDDINGS_SERVER_API_KEY>

`EMBEDDINGS_URI` is a base URL; the client posts to `{EMBEDDINGS_URI}/embed`. For a
managed deployment, front the GPU node (a RunPod pod or a dedicated box) with a stable
subdomain of its own — `prism.agience.ai` — so embeddings stay an independent open-infra
endpoint, separate from any premium service. For a quick self-host, point straight at the
raw pod URL instead:

    EMBEDDINGS_URI=https://<podid>-8083.proxy.runpod.net

(`EMBEDDINGS_PROVIDER=agience` is the default.) Unset `EMBEDDINGS_URI` → BM25 fallback.

## Authentication

Prism authorizes inbound `/embed` calls with three modes, tried in order
(`/health` stays open). Configure any combination; **nothing set = open**.

**1. Authority JWT — RS256 (primary).** A JWT signed by a member of the install's
Origin *authority*. The platform's first-party services self-sign (Mantle:
`iss=mantle, aud=prism`); an Origin-issued OAuth2 token (`kid=origin-1,
aud=agience`) verifies the same way. Trust = the signing key (by `kid`) is in the
authority's published JWKS, which Prism reads from one of:

- `AUTHORITY_MANIFEST` — path to the install's `authority.manifest.json` (mount
  it when Prism is **co-located** with a core install; it carries every anchor's
  public JWKS, so Mantle-signed tokens verify with no Origin round-trip).
- `AUTHORITY_JWKS_URL` — e.g. `https://origin.<install>/.well-known/jwks.json`
  (for a **remote** Prism; gives Origin's key).

`EMBEDDINGS_AUDIENCES` (default `prism,agience`) gates the accepted `aud`.

**2. Local HS256 JWT (fallback).** Verified against `PRISM_LOCAL_JWT_SECRET` — the
standalone/dev path when no authority is reachable.

**3. Static API keys (fallback) — the managed allowlist.** This is how a shared
Prism serves many callers without handing each the same secret. The allowlist is
a **directory of key files** on the persistent volume (`EMBEDDINGS_KEYS_DIR`,
default `/data/keys.d`) — **one file per consumer**, the filename is the label.
Add or remove a file to grant or revoke a caller **live** (hot-reloaded, no
redeploy); the dir is on the volume so it survives pod recreations. Each install
sets its own `EMBEDDINGS_API_KEY` to the raw key.

```bash
# on Prism's volume — mint and grant a consumer:
key=$(openssl rand -hex 32)
printf '%s' "$key" > /data/keys.d/prod.key     # give $key to that Mantle's EMBEDDINGS_API_KEY
printf '%s' "$(openssl rand -hex 32)" > /data/keys.d/dev.key
rm /data/keys.d/dev.key                          # revoke (takes effect within seconds)
```

A file may hold one key per line (`#` comments allowed); dotfiles are ignored;
keys are matched in constant time. `EMBEDDINGS_SERVER_API_KEY` (comma-separated)
remains as an optional **inline bootstrap** for a brand-new, still-empty volume.
Why a dir and not one comma-blob secret: you can see every entry, add/remove one
without blind-overwriting the rest, and never silently drop a working key.

> **Cross-install note.** A token a *dev* install's Mantle self-signs won't verify
> against a *prod* Prism (different authority keys) — that's by design. A dev
> install reaches a shared prod Prism via the API-key (or HS256) fallback, or runs
> its **own** Prism that reads the dev install's manifest. Same-install pairs
> (prod↔prod, devbox↔its own Prism) use the JWT primary path.

## Run locally

```bash
pip install -e ../agience-host        # the SDK (until it's on PyPI)
pip install -e .                        # prism + model deps (pulls torch CPU)
python -m agience_prism                 # serves on :8083
```

## Env

| Var | Default | Meaning |
|---|---|---|
| `EMBEDDINGS_MODEL` | `BAAI/bge-m3` | HF model id |
| `EMBEDDINGS_DEVICE` | `cpu` | `cuda` on a GPU host (baked into the GPU image) |
| `EMBEDDINGS_DIM` | `1024` | asserted against the model at load |
| `EMBEDDINGS_BATCH_SIZE` | `32` | encode batch size |
| `EMBEDDINGS_KEYS_DIR` | `/data/keys.d` | directory of key files (one per consumer) — the managed allowlist; add/remove a file to grant/revoke, hot-reloaded |
| `EMBEDDINGS_SERVER_API_KEY` | _(unset)_ | optional inline bootstrap bearer(s); **comma-separated** for several |
| `AUTHORITY_MANIFEST` | _(unset)_ | path to the install's `authority.manifest.json` — enables RS256 authority-JWT auth (co-located Prism) |
| `AUTHORITY_JWKS_URL` | _(unset)_ | JWKS URL (e.g. Origin's `/.well-known/jwks.json`) — enables RS256 authority-JWT auth (remote Prism) |
| `EMBEDDINGS_AUDIENCES` | `prism,agience` | accepted JWT `aud` values (comma-separated) |
| `EMBEDDINGS_ALLOWED_ISSUERS` | _(unset)_ | optional `iss` allowlist; unset = trust any key in the authority JWKS |
| `PRISM_LOCAL_JWT_SECRET` | _(unset)_ | HS256 shared secret — enables the local-JWT fallback |
| `HF_HOME` | `/data/hf` | model cache (mount a volume) |
