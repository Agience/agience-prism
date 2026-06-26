"""Agience Prism — bge-m3 served as the ``embeddings.embed`` capability.

Built on agience-host. Speaks the contract the platform's ``kernel/embeddings.py``
(AgienceHTTPEmbeddings) expects::

    POST /embed  {"input": ["text", ...]}  ->  {"vectors": [[float, ...]], "model_id": "..."}

The model is **not** baked into the image — it downloads to ``$HF_HOME`` (mount a
volume there) on first start, then is cached. Vectors are L2-normalized so the
MANTLE vector arm can treat inner product as cosine.
"""
from __future__ import annotations

import os
import threading

from pydantic import BaseModel, Field

from agience_kit import Host

# HF `tokenizers` (Rust) spins up worker threads on first use and can deadlock if
# the tokenizer is then driven from several threads at once (or across a fork).
# We serialize inference below and don't need that parallelism, so disable it
# explicitly — this removes a real hang path and the noisy runtime warning.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

MODEL_ID = os.getenv("EMBEDDINGS_MODEL", "BAAI/bge-m3")
DEVICE = os.getenv("EMBEDDINGS_DEVICE", "cpu")
EXPECTED_DIM = int(os.getenv("EMBEDDINGS_DIM", "1024"))
BATCH_SIZE = int(os.getenv("EMBEDDINGS_BATCH_SIZE", "32"))


def _csv(value: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in (value or "").split(",") if p.strip())

_model = None
# `_model_lock` guards the one-time lazy construction; `_encode_lock` serializes
# inference so overlapping /embed calls queue instead of hitting the shared model
# object concurrently (see embed()).
_model_lock = threading.Lock()
_encode_lock = threading.Lock()


def _load_model():
    """Lazily construct the model and verify its output dimension (thread-safe)."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer

                m = SentenceTransformer(MODEL_ID, device=DEVICE)
                dim = m.get_sentence_embedding_dimension()
                if dim != EXPECTED_DIM:
                    raise RuntimeError(
                        f"{MODEL_ID} emits {dim}-dim vectors but EMBEDDINGS_DIM={EXPECTED_DIM}; "
                        "refusing to start — a dimension mismatch would corrupt the MANTLE index"
                    )
                _model = m
    return _model


def _model_id() -> str:
    """Provenance id: ``hf:<path>@<ver>`` (matches the FACET embedding registry)."""
    ver = (os.getenv("EMBEDDINGS_MODEL_VERSION", "1.0") or "1.0").strip()
    if any(MODEL_ID.startswith(p) for p in ("hf:", "openai:", "custom:", "facet:")):
        return MODEL_ID if "@" in MODEL_ID else f"{MODEL_ID}@{ver}"
    return f"hf:{MODEL_ID}@{ver}"


# Inbound auth — three modes, tried in order (see agience_kit.host.TokenVerifier):
#
#   1. Authority JWT (RS256, PRIMARY). A JWT signed by a member of the install's
#      Origin authority (e.g. Mantle self-signs iss=mantle, aud=prism; or an
#      Origin OAuth2 token, kid=origin-1, aud=agience). Prism verifies against
#      the authority's keys, from either:
#        AUTHORITY_MANIFEST   — path to the install's authority.manifest.json
#                               (mount it when Prism is co-located with a core
#                               install; carries every anchor's public JWKS)
#        AUTHORITY_JWKS_URL   — e.g. https://origin.<install>/.well-known/jwks.json
#                               (for a remote Prism; gives Origin's key)
#      EMBEDDINGS_AUDIENCES gates the accepted `aud` (default "prism,agience").
#
#   2. Local HS256 JWT (FALLBACK). Verified against PRISM_LOCAL_JWT_SECRET — the
#      standalone/dev path when no authority is reachable.
#
#   3. Static API key(s) (FALLBACK). A hot-reloaded directory of key files on the
#      persistent volume — EMBEDDINGS_KEYS_DIR (default /data/keys.d), one file
#      per consumer (e.g. prod.key, dev.key). Drop or remove a file to grant or
#      revoke a caller live, no redeploy — this is the managed allowlist. Inline
#      EMBEDDINGS_SERVER_API_KEY (comma-separated) is also accepted for bootstrap.
#
# Nothing configured = open (a public proxy URL — set at least one).
host = Host(
    "agience-prism",
    api_key=os.getenv("EMBEDDINGS_SERVER_API_KEY", ""),
    api_keys_dir=os.getenv("EMBEDDINGS_KEYS_DIR", "/data/keys.d"),
    authority_manifest_path=os.getenv("AUTHORITY_MANIFEST"),
    authority_jwks_url=os.getenv("AUTHORITY_JWKS_URL"),
    hs256_secret=os.getenv("PRISM_LOCAL_JWT_SECRET"),
    expected_audiences=_csv(os.getenv("EMBEDDINGS_AUDIENCES", "prism,agience")),
    allowed_issuers=_csv(os.getenv("EMBEDDINGS_ALLOWED_ISSUERS", "")),
    warmup=_load_model,
)


class EmbedRequest(BaseModel):
    input: list[str] = Field(default_factory=list)


class EmbedResponse(BaseModel):
    vectors: list[list[float]]
    model_id: str = ""


@host.operator("embeddings.embed", path="/embed")
def embed(req: EmbedRequest) -> EmbedResponse:
    texts = req.input or []
    if not texts:
        return EmbedResponse(vectors=[], model_id=_model_id())
    model = _load_model()
    # FastAPI runs this sync handler in its threadpool, so two overlapping /embed
    # calls would otherwise invoke .encode() on the SAME model object at once.
    # SentenceTransformer/PyTorch inference isn't concurrency-safe: on CPU it
    # oversubscribes torch's worker threads and the HF tokenizer can deadlock,
    # surfacing as the occasional full hang (made more likely by the constant
    # internet scan traffic that reaches the public proxy URL). Serialize encode
    # so calls queue instead of colliding — the event loop stays free to answer
    # /health and unmatched (404) probes.
    with _encode_lock:
        vectors = model.encode(
            texts, batch_size=BATCH_SIZE, normalize_embeddings=True, convert_to_numpy=True
        )
    return EmbedResponse(vectors=[row.tolist() for row in vectors], model_id=_model_id())


app = host.app


def main() -> None:
    """Console entrypoint (``agience-prism`` / ``python -m agience_prism``)."""
    host.serve(port=int(os.getenv("PORT", "8083")))
