"""本地 Reranker（P2 混合检索组件之一）：bge-reranker-base 跨编码器精排。

- 模型经 ModelScope 下载，复用 embedder 的 modelcache 卷；进程级懒加载单例；
- 对 RRF 融合后的 top-N 逐条 (query, passage) 打分排序，0 token；
- 加载/推理失败自动降级：返回 None 由上层回退 RRF 顺序，不影响检索可用性。
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("reranker")

MODEL_REPO = "BAAI/bge-reranker-base"
_RERANKER = None
_LOAD_TRIED = False


def _download_model(cache_root: str) -> str:
    from modelscope import snapshot_download

    repo_dir = os.path.join(cache_root, "bge-reranker-base")
    os.makedirs(repo_dir, exist_ok=True)
    marker = os.path.join(repo_dir, ".snapshot_path")
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


def get_reranker():
    """进程级单例；失败返回 None（上层降级 RRF）。"""
    global _RERANKER, _LOAD_TRIED
    if _RERANKER is not None or _LOAD_TRIED:
        return _RERANKER
    _LOAD_TRIED = True
    try:
        cache_root = os.environ.get("MODEL_CACHE_DIR", "/root/.cache")
        repo_dir = os.path.join(cache_root, "bge-reranker-base")
        marker = os.path.join(repo_dir, ".snapshot_path")
        model_dir: str | None = None
        if os.path.exists(marker):
            p = open(marker, encoding="utf-8").read().strip()
            if os.path.exists(os.path.join(p, "config.json")):
                model_dir = p
        if model_dir is None and os.path.exists(os.path.join(repo_dir, "config.json")):
            model_dir = repo_dir
        if model_dir is None:
            log.info("downloading reranker model from ModelScope: %s", MODEL_REPO)
            model_dir = _download_model(cache_root)
        from sentence_transformers import CrossEncoder

        _RERANKER = CrossEncoder(model_dir, max_length=512)
        log.info("reranker ready")
        return _RERANKER
    except Exception as e:  # noqa: BLE001
        log.warning("reranker unavailable, fallback to RRF order: %s", e)
        return None


def rerank(query: str, candidates: list[dict], top_n: int) -> list[dict]:
    """对候选 [{content,...}] 打分精排；reranker 不可用时原样返回。"""
    model = get_reranker()
    if model is None or not candidates:
        return candidates
    pairs = [(query, c["content"][:512]) for c in candidates]
    scores = model.predict(pairs)
    ranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
    out = []
    for c, s in ranked[:top_n]:
        out.append({**c, "rerank_score": round(float(s), 4)})
    return out
