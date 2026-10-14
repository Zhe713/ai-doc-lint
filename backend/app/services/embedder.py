"""Embedding 服务（W6 Day27）：bge-small-zh-v1.5 本地推理。

- 模型经 ModelScope 下载（境内可达；HF 直连被墙已实测），落到 modelcache 卷持久化；
- 进程级懒加载单例：首次调用下载+加载，之后复用，不重复占内存；
- 下载加跨进程文件锁：多 worker 并发首载时只允许一个进程下载，避免目录损坏；
- 纯本地推理，0 token；维度 512。
"""

from __future__ import annotations

import fcntl
import logging
import os

log = logging.getLogger("embedder")

MODEL_REPO = "AI-ModelScope/bge-small-zh-v1.5"
EMBEDDING_DIM = 512
_MODEL = None
_MODEL_LOCK = False


def _download_model(repo_dir: str) -> str:
    """ModelScope 下载模型到 repo_dir（返回真实模型快照路径）。

    快照路径写入 repo_dir/.snapshot_path：snapshot_download 的落盘结构是
    <cache_dir>/models/<repo>/snapshots/<rev>，根目录没有 config.json，
    若不记录真实路径，每次进程重启都会重新下载。
    """
    from modelscope import snapshot_download

    os.makedirs(repo_dir, exist_ok=True)
    lock_path = os.path.join(repo_dir, ".download.lock")
    marker = os.path.join(repo_dir, ".snapshot_path")
    with open(lock_path, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            if os.path.exists(marker):
                p = open(marker, encoding="utf-8").read().strip()
                if os.path.exists(os.path.join(p, "config.json")):
                    return p
            if os.path.exists(os.path.join(repo_dir, "config.json")):
                return repo_dir
            path = snapshot_download(MODEL_REPO, cache_dir=repo_dir)
            try:
                with open(marker, "w", encoding="utf-8") as f:
                    f.write(path)
            except OSError:
                pass
            return path
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def get_model():
    """进程级单例；返回 SentenceTransformer 实例。"""
    global _MODEL, _MODEL_LOCK
    if _MODEL is not None:
        return _MODEL
    if _MODEL_LOCK:
        # 另一线程/进程正在加载：简单等待（worker 单进程内基本不会触发）
        raise RuntimeError("embedding model still loading")
    _MODEL_LOCK = True
    try:
        cache_root = os.environ.get("MODEL_CACHE_DIR", "/root/.cache")
        repo_dir = os.path.join(cache_root, "bge-small-zh-v1.5")
        marker = os.path.join(repo_dir, ".snapshot_path")
        model_dir: str | None = None
        if os.path.exists(marker):
            p = open(marker, encoding="utf-8").read().strip()
            if os.path.exists(os.path.join(p, "config.json")):
                model_dir = p
        if model_dir is None and os.path.exists(
                os.path.join(repo_dir, "config.json")):
            model_dir = repo_dir
        if model_dir is None:
            log.info("downloading embedding model from ModelScope: %s",
                     MODEL_REPO)
            model_dir = _download_model(repo_dir)
        from sentence_transformers import SentenceTransformer

        _MODEL = SentenceTransformer(model_dir)
        log.info("embedding model ready: dim=%s", EMBEDDING_DIM)
        return _MODEL
    finally:
        _MODEL_LOCK = False


def encode(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """批量编码；空输入返回空列表。"""
    if not texts:
        return []
    model = get_model()
    vecs = model.encode(texts, batch_size=batch_size, normalize_embeddings=True,
                        show_progress_bar=False, convert_to_numpy=True)
    return [v.tolist() for v in vecs]


def encode_one(text: str) -> list[float]:
    return encode([text])[0]
