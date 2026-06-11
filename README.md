# Agience Prism

The **embeddings** capability host for Agience — `bge-m3` served as `embeddings.embed`
over `POST /embed`, built on **agience-kernel**. AGPL-3.0.

    POST /embed  {"input": ["text", ...]}  ->  {"vectors": [[float, ...]], "model_id": "..."}

The **model is not baked into the image** — it caches to `$HF_HOME` (a mounted volume)
on first boot, so the image stays small and restarts are fast. Prism talks to the
platform only over the wire (Mantle calls `/embed`); it never imports core.

## Build & publish (public image — no pull token)

Prism depends on the `agience-kernel` SDK. Until the kernel is on PyPI, the build pulls
it from a sibling checkout via a BuildKit **named context** — no PyPI, no giant build
context:

```bash
# GPU image (RunPod). Run from the agience-prism repo root, with agience-kernel as a sibling dir:
docker build --build-context kernel=../agience-kernel \
  -f Dockerfile.gpu -t <your-namespace>/agience-prism:gpu .
docker push <your-namespace>/agience-prism:gpu        # push to a PUBLIC repo
```

`Dockerfile` is the CPU variant (same `--build-context`). **Once `agience-kernel` is
published to PyPI,** drop `--build-context` and the two `kernel` lines in the Dockerfile
— `pip install .` then resolves `agience-kernel` directly.

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

## Run locally

```bash
pip install -e ../agience-kernel        # the SDK (until it's on PyPI)
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
| `EMBEDDINGS_SERVER_API_KEY` | _(unset)_ | shared bearer; unset = open |
| `HF_HOME` | `/data/hf` | model cache (mount a volume) |
