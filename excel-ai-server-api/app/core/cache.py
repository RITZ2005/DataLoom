"""
Redis Semantic Cache — extracted from hybrid_chat_system.py.

Uses Redis Stack / RediSearch for vector-similarity-based query caching.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from array import array
from typing import Any, Dict, List, Optional

import redis

logger = logging.getLogger("HybridSystem")


class RedisSemanticCache:
    def __init__(
        self,
        host: str,
        port: int,
        password: Optional[str],
        ttl_seconds: int,
        index_name: str = "semantic_cache_idx",
        key_prefix: str = "semantic_cache:",
        ssl: bool = False,
    ):
        self._available = False
        self.ttl_seconds = ttl_seconds
        self.index_name = index_name
        self.key_prefix = key_prefix
        self._index_ready = False

        try:
            self.client = redis.Redis(
                host=host,
                port=port,
                password=password,
                decode_responses=False,
                socket_connect_timeout=3,
                ssl=ssl,
            )
            self.client.ping()
            # Verify RediSearch module is loaded (required for FT.* commands)
            modules = self.client.execute_command("MODULE", "LIST")
            module_names = {
                (m[1].decode("utf-8") if isinstance(m[1], bytes) else m[1])
                for m in modules
                if len(m) >= 2
            }
            if "search" not in module_names and "ft" not in module_names:
                logger.warning(
                    "⚠️  Redis connected but RediSearch module not loaded — semantic cache disabled"
                )
            else:
                self._available = True
                logger.info("✅ RedisSemanticCache connected (host=%s, port=%d)", host, port)
        except Exception as e:
            self.client = None  # type: ignore[assignment]
            logger.warning("⚠️  RedisSemanticCache unavailable — cache disabled: %s", e)

    def _vector_bytes(self, embedding: List[float]) -> bytes:
        return array("f", embedding).tobytes()

    def _escape_tag(self, value: str) -> str:
        return re.sub(r"([\\,\.<>\{\}\[\]\"'\:;!@#$%^&*()\-\+=~])", r"\\\1", value)

    def ensure_index(self, embedding_dim: int) -> None:
        if self._index_ready:
            return

        try:
            existing = self.client.execute_command("FT._LIST")
            existing_names = {
                name.decode("utf-8") if isinstance(name, bytes) else name
                for name in existing
            }
            if self.index_name in existing_names:
                self._index_ready = True
                return
        except redis.ResponseError:
            pass

        self.client.execute_command(
            "FT.CREATE",
            self.index_name,
            "ON",
            "HASH",
            "PREFIX",
            1,
            self.key_prefix,
            "SCHEMA",
            "file_uuid",
            "TAG",
            "query_text",
            "TEXT",
            "query_type",
            "TEXT",
            "response_data",
            "TEXT",
            "created_at",
            "NUMERIC",
            "query_embedding",
            "VECTOR",
            "HNSW",
            6,
            "TYPE",
            "FLOAT32",
            "DIM",
            embedding_dim,
            "DISTANCE_METRIC",
            "COSINE"
        )
        self._index_ready = True

    def check_cache(
        self,
        file_uuid: str,
        embedding: List[float],
        similarity_threshold: float = 0.05
    ) -> Optional[Dict[str, Any]]:
        if not self._available:
            return None
        try:
            return self._check_cache_inner(file_uuid, embedding, similarity_threshold)
        except Exception as e:
            logger.warning("Semantic cache check_cache error (degrading gracefully): %s", e)
            return None

    def _check_cache_inner(
        self,
        file_uuid: str,
        embedding: List[float],
        similarity_threshold: float = 0.05
    ) -> Optional[Dict[str, Any]]:
        self.ensure_index(len(embedding))
        vector_blob = self._vector_bytes(embedding)
        tag_value = self._escape_tag(file_uuid)
        query = f"@file_uuid:{{{tag_value}}}=>[KNN 1 @query_embedding $vec AS distance]"

        result = self.client.execute_command(
            "FT.SEARCH",
            self.index_name,
            query,
            "PARAMS",
            2,
            "vec",
            vector_blob,
            "SORTBY",
            "distance",
            "RETURN",
            4,
            "query_type",
            "response_data",
            "distance",
            "query_text",
            "DIALECT",
            2
        )

        if not result or result[0] == 0:
            return None

        fields = result[2]
        field_map = {
            fields[i]: fields[i + 1]
            for i in range(0, len(fields), 2)
        }

        raw_distance = field_map.get(b"distance") or field_map.get("distance")
        distance = float(raw_distance.decode("utf-8") if isinstance(raw_distance, bytes) else raw_distance)

        logger.info(
            "Semantic cache distance=%.6f threshold=%.6f file_uuid=%s",
            distance,
            similarity_threshold,
            file_uuid
        )

        if distance >= similarity_threshold:
            return None

        raw_query_type = field_map.get(b"query_type") or field_map.get("query_type")
        query_type = raw_query_type.decode("utf-8") if isinstance(raw_query_type, bytes) else raw_query_type

        raw_response = field_map.get(b"response_data") or field_map.get("response_data")
        response_text = raw_response.decode("utf-8") if isinstance(raw_response, bytes) else raw_response

        raw_text = field_map.get(b"query_text") or field_map.get("query_text")
        cached_query_text = raw_text.decode("utf-8") if isinstance(raw_text, bytes) else raw_text

        try:
            response_data = json.loads(response_text) if response_text else None
        except json.JSONDecodeError:
            response_data = response_text

        return {
            "query_type": query_type,
            "response_data": response_data,
            "distance": distance,
            "query_text": cached_query_text
        }

    def save_to_cache(
        self,
        file_uuid: str,
        query_text: str,
        query_type: str,
        response_data: Any,
        embedding: List[float]
    ) -> None:
        if not self._available:
            return
        try:
            self._save_to_cache_inner(file_uuid, query_text, query_type, response_data, embedding)
        except Exception as e:
            logger.warning("Semantic cache save_to_cache error (degrading gracefully): %s", e)

    def _save_to_cache_inner(
        self,
        file_uuid: str,
        query_text: str,
        query_type: str,
        response_data: Any,
        embedding: List[float]
    ) -> None:
        self.ensure_index(len(embedding))
        key = f"{self.key_prefix}{file_uuid}:{uuid.uuid4()}"
        payload = json.dumps(response_data, default=str)
        mapping = {
            "file_uuid": file_uuid,
            "query_text": query_text,
            "query_type": query_type,
            "response_data": payload,
            "created_at": int(time.time()),
            "query_embedding": self._vector_bytes(embedding)
        }
        self.client.hset(key, mapping=mapping)
        if self.ttl_seconds > 0:
            self.client.expire(key, self.ttl_seconds)

    def delete_file_cache(self, file_uuid: str) -> int:
        if not self._available:
            return 0
        try:
            return self._delete_file_cache_inner(file_uuid)
        except Exception as e:
            logger.warning("Semantic cache delete_file_cache error: %s", e)
            return 0

    def _delete_file_cache_inner(self, file_uuid: str) -> int:
        pattern = f"{self.key_prefix}{file_uuid}:*"
        deleted = 0
        pipeline = self.client.pipeline()
        for key in self.client.scan_iter(match=pattern, count=1000):
            pipeline.delete(key)
            deleted += 1
            if deleted % 500 == 0:
                pipeline.execute()
        if pipeline.command_stack:
            pipeline.execute()
        return deleted
