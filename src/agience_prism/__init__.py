"""Agience Prism — the embeddings capability host (bge-m3), built on agience-kernel.

AGPL-3.0-or-later. Prism is a *host*: it depends on the permissive `agience-kernel`
SDK and exposes the `embeddings.embed` capability over `POST /embed`. It talks to the
platform only over the wire — it never imports core.
"""
from .app import app, host, main

__version__ = "0.1.0"
__all__ = ["app", "host", "main", "__version__"]
