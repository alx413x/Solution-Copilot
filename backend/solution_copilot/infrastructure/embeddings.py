"""Pinned local Chinese encoder. Download explicitly; requests never fetch model artifacts."""

from functools import lru_cache
from pathlib import Path

import numpy as np
from tokenizers import Tokenizer

from solution_copilot.application.errors import AppError

MODEL = "BAAI/bge-small-zh-v1.5"
REPOSITORY = "Qdrant/bge-small-zh-v1.5"
REVISION = "46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59"
PROFILE = f"{MODEL}:{REVISION}:jieba-0.42.1:440-80-v1"
DIMENSIONS = 512
MODEL_DIR = Path(__file__).resolve().parents[3] / ".local" / "embedding" / REVISION


@lru_cache
def encoder():
    from fastembed import TextEmbedding

    if not (MODEL_DIR / "model_optimized.onnx").is_file():
        raise AppError(503, "EMBEDDING_UNAVAILABLE", "本地向量模型未准备，请运行模型准备脚本。")
    return TextEmbedding(
        MODEL, specific_model_path=str(MODEL_DIR), local_files_only=True, threads=2
    )


@lru_cache
def tokenizer():
    if not (MODEL_DIR / "tokenizer.json").is_file():
        raise AppError(503, "EMBEDDING_UNAVAILABLE", "本地分词模型未准备，请运行模型准备脚本。")
    result = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
    result.no_truncation()
    result.no_padding()
    return result


def checked(vectors, expected):
    values = np.asarray(list(vectors), dtype=np.float32)
    if values.shape != (expected, DIMENSIONS) or not np.isfinite(values).all():
        raise AppError(503, "EMBEDDING_INVALID", "向量输出或维度无效，请检查模型版本。")
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    if (norms == 0).any():
        raise AppError(503, "EMBEDDING_INVALID", "向量输出无效。")
    return (values / norms).tolist()


def embed_query(query):
    try:
        if len(tokenizer().encode(query).ids) > 512:
            raise AppError(422, "QUERY_TOO_LONG", "问题超过模型长度，请缩短后重试。")
        return checked(encoder().query_embed(query), 1)[0]
    except AppError:
        raise
    except Exception:
        raise AppError(503, "EMBEDDING_UNAVAILABLE", "本地向量模型暂时不可用，请重试。") from None


def index_chunks(chunks, checkpoint):
    from sqlalchemy import func

    from solution_copilot.application.retrieval import words

    result = []
    for chunk in chunks:
        encoding = tokenizer().encode(chunk["content"], add_special_tokens=False)
        start = 0
        while start < len(encoding.ids):
            end = min(start + 440, len(encoding.ids))
            left, right = encoding.offsets[start][0], encoding.offsets[end - 1][1]
            content = chunk["content"][left:right]
            result.append(
                {
                    **chunk,
                    "ordinal": len(result),
                    "content": content,
                    "token_count": len(tokenizer().encode(content).ids),
                    "embedding_profile": PROFILE,
                    "search_vector": func.to_tsvector("simple", " ".join(words(content))),
                    "data": {
                        **chunk["data"],
                        "source_char_start": left,
                        "source_char_end": right,
                        "character_count": len(content),
                        "embedding_profile": PROFILE,
                    },
                }
            )
            if end == len(encoding.ids):
                break
            start = end - 80
    for offset in range(0, len(result), 16):
        checkpoint(60)
        batch = result[offset : offset + 16]
        try:
            vectors = checked(encoder().passage_embed([c["content"] for c in batch]), len(batch))
        except AppError:
            raise
        except Exception:
            raise AppError(
                503, "EMBEDDING_UNAVAILABLE", "向量化失败，请检查本地模型后重试。"
            ) from None
        for chunk, vector in zip(batch, vectors, strict=True):
            chunk["embedding"] = vector
    return result
