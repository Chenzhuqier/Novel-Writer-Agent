"""
可选语义检索索引（RAG）—— 基于本地 sentence-transformers 实现。

设计原则：
- 默认关闭：`.env` 的 `ENABLE_VECTOR` 未开启、或 `sentence-transformers` 未安装、
  或模型加载失败时，SemanticIndex 处于禁用态，所有方法立刻返回降级结果，
  上层（StoryBible / StoryStateTracker）自动回退到原有子串匹配 + 滑窗摘要，
  行为与未接入前完全一致（Demo 模式不受影响）。
- 模型默认使用中文小模型 BAAI/bge-small-zh-v1.5，首次使用需联网下载。
"""

from __future__ import annotations

import json
import math
import os
import threading
from typing import Optional

ENABLE_VECTOR = os.environ.get("ENABLE_VECTOR", "off").strip().lower() in (
    "1", "true", "on", "yes",
)


class SemanticIndex:
    """惰性初始化的语义索引；禁用/不可用时安全降级。"""

    MODEL_NAME = os.environ.get(
        "VECTOR_MODEL", "BAAI/bge-small-zh-v1.5",
    )
    DEFAULT_PERSIST = "data/vector_store"
    DEFAULT_SIMILARITY_THRESHOLD = 0.8

    def __init__(self, persist_dir: str = None):
        self.persist_dir = persist_dir or self.DEFAULT_PERSIST
        self._state_path = os.path.join(self.persist_dir, "index.json")
        self._model = None
        # doc_id -> 原始文档文本（同时作为内容哈希的去重依据）
        self._documents: dict[str, str] = {}
        # doc_id -> 向量（JSON 存储用 list[float]）
        self._embeddings: dict[str, list[float]] = {}
        self._load_error: Optional[str] = None
        self._lock = threading.RLock()

        if ENABLE_VECTOR:
            self._try_load()

    # ============================================================
    # 启用状态与惰性加载
    # ============================================================

    @property
    def enabled(self) -> bool:
        """索引是否可用。不可用时调用方应走原有降级路径。"""
        return ENABLE_VECTOR and self._model is not None and self._load_error is None

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    def _try_load(self):
        """尝试加载模型与已持久化的索引；失败记录原因并保持禁用。"""
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.MODEL_NAME)
        except Exception as e:
            self._load_error = f"加载模型失败: {e}（请安装 sentence-transformers 或检查网络）"
            self._model = None
            print(f"[SemanticIndex] {self._load_error}")
            return

        try:
            self._load_persisted()
        except Exception as e:
            self._load_error = f"加载向量数据失败: {e}"
            print(f"[SemanticIndex] {self._load_error}")

    def _load_persisted(self):
        with self._lock:
            if not os.path.exists(self._state_path):
                return
            with open(self._state_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self._documents = dict(raw.get("documents", {}))
            self._embeddings = dict(raw.get("embeddings", {}))

    def _persist(self):
        with self._lock:
            try:
                os.makedirs(self.persist_dir, exist_ok=True)
                with open(self._state_path, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "documents": self._documents,
                            "embeddings": self._embeddings,
                        },
                        f,
                        ensure_ascii=False,  # 长度可控，不缩进以压缩体积
                    )
            except Exception as e:
                print(f"[SemanticIndex] 持久化失败: {e}")

    # ============================================================
    # 文档维护
    # ============================================================

    def add(self, doc_id: str, text: str) -> bool:
        """加入/更新一条文档。内容未变化时跳过重嵌入。禁用态直接返回 False。"""
        if not self.enabled or not (doc_id and text):
            return False
        with self._lock:
            # 内容未变化时直接返回，避免重复嵌入
            if self._documents.get(doc_id) == text:
                return True
            try:
                vector = self._encode(text)
            except Exception as e:
                print(f"[SemanticIndex] 嵌入失败 ({doc_id}): {e}")
                return False
            self._documents[doc_id] = text
            self._embeddings[doc_id] = vector
        self._persist()
        return True

    def remove(self, doc_id: str):
        if not self.enabled:
            return
        with self._lock:
            self._documents.pop(doc_id, None)
            self._embeddings.pop(doc_id, None)
        self._persist()

    def clear(self):
        with self._lock:
            self._documents.clear()
            self._embeddings.clear()
        self._persist()

    def _encode(self, text: str) -> list[float]:
        vector = self._model.encode([text], normalize_embeddings=True)[0]
        return [float(x) for x in vector.tolist()]

    # ============================================================
    # 检索
    # ============================================================

    def search(self, query: str, top_k: int = 5,
               prefix: str = None) -> list[dict]:
        """
        语义检索，返回 [{"doc_id", "text", "score"}]（按相似度降序）。

        Args:
            query: 查询文本
            top_k: 返回条数
            prefix: 若指定（如 `fs:`），仅返回 doc_id 以该前缀开头的条目
        """
        if not self.enabled or not query or not self._embeddings:
            return []
        with self._lock:
            qv = self._encode(query)
            scored = []
            for doc_id, vec in self._embeddings.items():
                if prefix and not doc_id.startswith(prefix):
                    continue
                score = self._cosine(qv, vec)
                scored.append((score, doc_id))
            scored.sort(reverse=True)
        results = []
        for score, doc_id in scored[:top_k]:
            results.append({
                "doc_id": doc_id,
                "text": self.get_text(doc_id),
                "score": round(score, 4),
            })
        return results

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a)) or 1.0
        nb = math.sqrt(sum(x * x for x in b)) or 1.0
        return dot / (na * nb)

    # ============================================================
    # 文档文本回查（搜索只存 hash，需回查原始文本）
    # ============================================================

    def get_text(self, doc_id: str) -> str:
        return self._documents.get(doc_id, "")

    # ============================================================
    # 伏笔两两相似判断（供 StoryStateTracker 使用）
    # ============================================================

    def similarity(self, a: str, b: str) -> Optional[float]:
        """两条短文本的余弦相似度（0~1）。禁用或编码失败返回 None。"""
        if not self.enabled:
            return None
        try:
            va = self._encode(a)
            vb = self._encode(b)
            return round(self._cosine(va, vb), 4)
        except Exception:
            return None


# 兼容性别名（模块级助手，方便 app 直接 import）
VECTOR_INDEX = SemanticIndex