import os
from contextlib import asynccontextmanager
from threading import Lock
from time import time

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
CACHE_DIR = os.getenv("EMBEDDING_CACHE_DIR", "/models")
_model = None
_load_error: str | None = None
_lock = Lock()


def load_model():
    global _model, _load_error
    if _model is not None:
        return _model
    with _lock:
        if _model is None:
            try:
                from fastembed import TextEmbedding

                _model = TextEmbedding(model_name=MODEL_NAME, cache_dir=CACHE_DIR, threads=2)
                _load_error = None
            except Exception as exc:
                _load_error = f"{exc.__class__.__name__}: {exc}"
                raise
    return _model


@asynccontextmanager
async def lifespan(_: FastAPI):
    await run_in_threadpool(load_model)
    yield


app = FastAPI(title="AI Test Platform Embedding Service", version="1.0.0", lifespan=lifespan)


class EmbeddingRequest(BaseModel):
    model: str | None = None
    input: str | list[str]


@app.get("/health")
async def health():
    if _model is None:
        return {"status": "initializing" if not _load_error else "failed", "error": _load_error}
    return {"status": "healthy", "model": MODEL_NAME}


@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [{"id": MODEL_NAME, "object": "model", "owned_by": "local"}]}


@app.post("/v1/embeddings")
async def embeddings(request: EmbeddingRequest):
    texts = [request.input] if isinstance(request.input, str) else request.input
    if not texts or any(not isinstance(text, str) or not text.strip() for text in texts):
        raise HTTPException(422, "input 必须是非空字符串或非空字符串数组")
    try:
        model = await run_in_threadpool(load_model)
        vectors = await run_in_threadpool(lambda: [vector.tolist() for vector in model.embed(texts)])
    except Exception as exc:
        raise HTTPException(503, f"嵌入模型不可用: {exc.__class__.__name__}") from exc
    return {
        "object": "list",
        "model": MODEL_NAME,
        "data": [
            {"object": "embedding", "index": index, "embedding": vector}
            for index, vector in enumerate(vectors)
        ],
        "usage": {"prompt_tokens": sum(len(text) for text in texts), "total_tokens": sum(len(text) for text in texts)},
        "created": int(time()),
    }
