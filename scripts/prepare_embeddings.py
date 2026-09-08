"""Explicitly download the pinned encoder; no credentials or business documents are sent."""

from huggingface_hub import snapshot_download
from solution_copilot.infrastructure.embeddings import MODEL_DIR, REPOSITORY, REVISION, embed_query

if __name__ == "__main__":
    snapshot_download(
        REPOSITORY,
        revision=REVISION,
        local_dir=MODEL_DIR,
        allow_patterns=["*.json", "*.txt", "model_optimized.onnx"],
    )
    print(
        f"Local encoder ready: {len(embed_query('中文检索验收'))} dimensions; revision {REVISION}"
    )
