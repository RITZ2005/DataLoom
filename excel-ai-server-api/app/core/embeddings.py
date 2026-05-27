"""
Custom embeddings class — extracted from hybrid_chat_system.py.

Compatible with both OpenWebUI and native Ollama servers.
The endpoint is configured through EMBEDDING_BASE_URL and auto-detected at runtime.
"""
from __future__ import annotations

import os
import logging
from typing import Any, Dict, List

import requests
from langchain_core.embeddings import Embeddings

from app.utils.logging import log_full_exception

logger = logging.getLogger("HybridSystem")


class OpenWebUIEmbeddings(Embeddings):
    """Custom embeddings class compatible with both OpenWebUI and native Ollama servers.

        The server shape is auto-detected from EMBEDDING_BASE_URL at runtime:
            ollama    → /api/embed batch, fallback /api/embeddings per-text (Ollama format)
            openwebui → /api/embeddings batch with {"input": [...]} (OpenWebUI format)
            auto      → tries Ollama batch first, then OpenWebUI batch, then Ollama per-text
    """

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.model = model
        self.endpoint_batch   = f"{self.base_url}/api/embed"        # Ollama 0.4+ batch
        self.endpoint_legacy  = f"{self.base_url}/api/embeddings"   # OpenWebUI / Ollama single
        # Resolve server type from env once at construction time.
        # SERVER_TYPE is still accepted as a legacy override, but is not required.
        _st = os.getenv('SERVER_TYPE', 'auto').lower()
        self._is_ollama    = (_st == 'ollama') or (_st == 'auto' and ':11434' in self.base_url)
        self._is_openwebui = (_st == 'openwebui')
        logger.info(f"Embeddings endpoint base: {self.base_url}  "
                    f"(SERVER_TYPE={_st}, is_ollama={self._is_ollama})")

    def _post(self, endpoint: str, payload: Dict[str, Any]):
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        return requests.post(endpoint, json=payload, headers=headers, timeout=30)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of documents.

                Strategy is determined by EMBEDDING_BASE_URL with optional legacy SERVER_TYPE:
          ollama    → tries /api/embed batch, then per-text /api/embeddings {"prompt": text}
          openwebui → tries /api/embeddings batch {"input": [...]}
          auto      → ollama path first, then openwebui batch, then ollama per-text fallback
        """
        # ── Ollama batch: POST /api/embed  {"input": [texts]}  ──
        if self._is_ollama or not self._is_openwebui:
            try:
                resp = self._post(self.endpoint_batch, {"model": self.model, "input": texts})
                if resp.status_code in (200, 201):
                    result = resp.json()
                    batch_embs = result.get("embeddings")  # {"embeddings": [[...], ...]}
                    if isinstance(batch_embs, list) and len(batch_embs) == len(texts) and batch_embs[0]:
                        return batch_embs
            except Exception:
                pass

        # ── OpenWebUI batch: POST /api/embeddings  {"input": [texts]}  ──
        if self._is_openwebui or not self._is_ollama:
            try:
                resp = self._post(self.endpoint_legacy, {"model": self.model, "input": texts})
                if resp.status_code in (200, 201):
                    result = resp.json()
                    data = result.get("data") or result.get("embeddings")
                    embeddings: List[List[float]] = []
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                emb = item.get("embedding") or item.get("vector")
                                embeddings.append(emb)
                            elif isinstance(item, list):
                                embeddings.append(item)
                    if embeddings and len(embeddings) == len(texts) and embeddings[0]:
                        return embeddings
            except Exception as e:
                err_str = str(e).lower()
                if not any(k in err_str for k in ("timed out", "refused", "unreachable")):
                    log_full_exception(e, "Batch embed attempt (OpenWebUI) failed")

        # ── Ollama per-text fallback: POST /api/embeddings  {"prompt": text}  ──
        embeddings = []
        for text in texts:
            try:
                resp = self._post(self.endpoint_legacy, {"model": self.model, "prompt": text})
                resp.raise_for_status()
                result = resp.json()
                # Ollama: {"embedding": [...]}
                emb = result.get("embedding")
                if not emb:
                    # OpenWebUI per-text: {"data": [{"embedding": [...]}]}
                    data = result.get("data")
                    if isinstance(data, list) and data:
                        first = data[0]
                        emb = first.get("embedding") or first.get("vector") if isinstance(first, dict) else first
                if not emb:
                    raise RuntimeError(f"No embedding returned: {result}")
                embeddings.append(emb)
            except Exception as e:
                # Distinguish transient network errors from other failures.
                err_str = str(e).lower()
                is_network = isinstance(e, requests.exceptions.RequestException) or any(k in err_str for k in ("timed out", "failed to establish", "unreachable", "max retries exceeded", "10051", "10060"))
                if is_network:
                    logger.warning(f"⚠️ Embedding failed for individual text due to network error: {err_str[:150]}")
                else:
                    log_full_exception(e, "Embedding failed for individual text")
                raise
        return embeddings

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]
