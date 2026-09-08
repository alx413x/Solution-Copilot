"""Live Chinese retrieval evaluation: ten synthetic documents, thirty fixed questions."""

import json
import statistics
import time
from pathlib import Path

import httpx


def main():
    corpus = json.loads(Path("evals/s03-corpus.json").read_text())
    credential = json.loads(Path(".local/demo-credentials.json").read_text())["a-owner"]
    ids, records = {}, []
    with httpx.Client(
        base_url="http://127.0.0.1:8000/api/v1",
        trust_env=False,
        timeout=60,
        headers={
            "Authorization": f"Bearer {credential['token']}",
            "X-Organization-ID": credential["organization_id"],
        },
    ) as client:
        try:
            for item in corpus:
                response = client.post(
                    "/documents",
                    data={"scope": "organization"},
                    files={
                        "file": (item["title"] + ".txt", item["content"].encode(), "text/plain")
                    },
                )
                response.raise_for_status()
                document = response.json()["document"]
                ids[item["title"]] = document["id"]
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    state = client.get(f"/documents/{document['id']}").json()
                    if state["status"] in {"ready", "failed"}:
                        break
                    time.sleep(0.5)
                assert state["status"] == "ready", state.get("error_message")
            client.post("/retrieval/search", json={"query": "单点登录"}).raise_for_status()
            for item in corpus:
                for query in item["queries"]:
                    start = time.perf_counter()
                    response = client.post("/retrieval/search", json={"query": query})
                    response.raise_for_status()
                    results = response.json()["items"]
                    rank = next(
                        (
                            i
                            for i, result in enumerate(results, 1)
                            if result["document_id"] == ids[item["title"]]
                        ),
                        None,
                    )
                    records.append(
                        {
                            "query": query,
                            "expected": item["title"],
                            "rank": rank,
                            "latency_ms": round((time.perf_counter() - start) * 1000, 2),
                            "returned": [r["title"] for r in results],
                        }
                    )
            metrics = {
                "questions": len(records),
                "hit_at_8": sum(r["rank"] is not None for r in records) / len(records),
                "mrr_at_8": statistics.mean(1 / r["rank"] if r["rank"] else 0 for r in records),
                "p95_ms": sorted(r["latency_ms"] for r in records)[28],
            }
            output = {"profile": response.json()["profile"], "metrics": metrics, "results": records}
            Path("evals/s03-results.json").write_text(
                json.dumps(output, ensure_ascii=False, indent=2) + "\n"
            )
            print(json.dumps(metrics, ensure_ascii=False))
            assert metrics["hit_at_8"] >= 0.8 and metrics["p95_ms"] < 2000
        finally:
            for document_id in ids.values():
                client.delete(f"/documents/{document_id}").raise_for_status()


if __name__ == "__main__":
    main()
