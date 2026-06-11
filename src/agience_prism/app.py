"""Agience Prism — bge-m3 served as the ``embeddings.embed`` capability.

Built on agience-kernel. Speaks the contract the platform's ``kernel/embeddings.py``
(AgienceHTTPEmbeddings) expects::

    POST /embed  {"input": ["text", ...]}  ->  {"vectors": [[float, ...]], "model_id": "..."}

The model is **not** baked into the image — it downloads to ``$HF_HOME`` (mount a
volume there) on first start, then is cached. Vectors are L2-normalized so the
MANTLE vector arm can treat inner product as cosine.
"""
from __future__ import annotations

import os

from pydantic import BaseModel, Field

from agience_kernel import Host

MODEL_ID = os.getenv("EMBEDDINGS_MODEL", "BAAI/bge-m3")
DEVICE = os.getenv("EMBEDDINGS_DEVICE", "cpu")
EXPECTED_DIM = int(os.getenv("EMBEDDINGS_DIM", "1024"))
BATCH_SIZE = int(os.getenv("EMBEDDINGS_BATCH_SIZE", "32"))

_model = None


def _load_model():
    """Lazily construct the model and verify its output dimension."""
    global _model
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


# Shared bearer is optional but recommended — a RunPod proxy URL is public.
host = Host(
    "agience-prism",
    api_key=os.getenv("EMBEDDINGS_SERVER_API_KEY", ""),
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
    vectors = _load_model().encode(
        texts, batch_size=BATCH_SIZE, normalize_embeddings=True, convert_to_numpy=True
    )
    return EmbedResponse(vectors=[row.tolist() for row in vectors], model_id=_model_id())


app = host.app


def main() -> None:
    """Console entrypoint (``agience-prism`` / ``python -m agience_prism``)."""
    host.serve(port=int(os.getenv("PORT", "8083")))
