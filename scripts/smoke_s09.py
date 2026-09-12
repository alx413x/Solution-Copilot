"""Fresh synthetic customer → uploaded notes → confirmed requirements → solution → exports.

Uses only public application endpoints; retains the demo and reproducible metrics.
"""

import json
import time
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import httpx
from docx import Document


def main():
    origin = "http://127.0.0.1:3000"
    credential = json.loads(Path(".local/demo-credentials.json").read_text())["a-owner"]
    expected = json.loads(Path("evals/s09/expected.json").read_text())
    started = time.monotonic()
    with httpx.Client(
        base_url=origin, trust_env=False, timeout=60, headers={"Origin": origin}
    ) as web:

        def request(method, path, data=None):
            r = web.request(method, path, json=data)
            assert r.is_success, (r.status_code, r.text[:1000])
            return r.json()

        def poll(path, done, seconds=300):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                value = request("GET", path)
                if done(value):
                    return value
                time.sleep(0.5)
            raise AssertionError("Timed out: " + path)

        def run(run_id):
            result = poll(
                f"/api/backend/runs/{run_id}", lambda r: r["status"] not in {"queued", "running"}
            )
            assert result["status"] in {"succeeded", "waiting_user"}, result
            return result

        request(
            "POST",
            "/api/session",
            {"token": credential["token"], "organizationId": credential["organization_id"]},
        )
        customer = request(
            "POST", "/api/backend/customers", {"name": "S09 合成客户 " + uuid4().hex[:8]}
        )
        project = request(
            "POST",
            f"/api/backend/customers/{customer['id']}/projects",
            {"name": "S09 全流程交付验收"},
        )
        base = f"/api/backend/projects/{project['id']}"
        source = Path("evals/s09/meeting-1.md").read_bytes()
        uploaded = web.post(
            "/api/backend/documents",
            data={"scope": "project", "customer_id": customer["id"], "project_id": project["id"]},
            files={"file": ("meeting-1.md", source, "text/markdown")},
        )
        assert uploaded.status_code == 202, uploaded.text
        document = uploaded.json()["document"]
        doc = poll(
            f"/api/backend/documents/{document['id']}", lambda d: d["status"] in {"ready", "failed"}
        )
        assert doc["status"] == "ready", doc
        request("POST", base + "/requirements/extractions", {"document_ids": [doc["id"]]})
        profile = poll(
            base + "/requirements",
            lambda p: p["extraction"] and p["extraction"]["status"] in {"succeeded", "failed"},
        )
        assert profile["extraction"]["status"] == "succeeded", profile["extraction"]
        extracted = profile["items"]
        categories = {i["category"] for i in extracted}
        gold = set(expected["meeting_1_required"])
        quotes = [s["quote"] for i in extracted for s in i["sources"]]
        assert quotes and all(q in source.decode() for q in quotes)
        conversation = request("POST", base + "/conversations", {"title": "S09 验收"})
        workflow = request(
            "POST",
            f"/api/backend/conversations/{conversation['id']}/workflows",
            {"goal": "生成可核实的工作台建设方案", "epoch": 0, "request_id": str(uuid4())},
        )
        gate = run(workflow["id"])
        # Missing extraction categories are filled explicitly, never silently invented by the model.
        if gate["workflow"]["gate"] == 1:
            for q in request("GET", base + "/clarifications"):
                if q["category"] in expected["meeting_1_required"] and q["status"] == "open":
                    profile = request("GET", base + "/requirements")
                    request(
                        "POST",
                        f"/api/backend/clarifications/{q['id']}/answer",
                        {
                            "conversation_id": conversation["id"],
                            "answer": expected["meeting_1_required"][q["category"]],
                            "version": q["version"],
                            "profile_version": profile["version"],
                            "epoch": 0,
                        },
                    )
        profile = request("GET", base + "/requirements")
        request("POST", base + "/requirements/confirm", {"version": profile["version"]})
        if gate["workflow"]["gate"] == 1:
            request(
                "POST",
                f"/api/backend/runs/{workflow['id']}/resume",
                {"gate": 1, "approve": True, "request_id": str(uuid4())},
            )
            gate = run(workflow["id"])
        assert gate["workflow"]["gate"] == 2
        request(
            "POST",
            f"/api/backend/runs/{workflow['id']}/resume",
            {"gate": 2, "approve": True, "request_id": str(uuid4())},
        )
        assert run(workflow["id"])["status"] == "succeeded"
        solution = request(
            "POST",
            base + "/solutions",
            {"workflow_run_id": workflow["id"], "title": "S09 工作台建设方案"},
        )
        root = f"/api/backend/solutions/{solution['id']}"
        outline = request(
            "POST",
            root + "/outline",
            {
                "version": solution["version"],
                "request_id": str(uuid4()),
                "instruction": "仅用三章覆盖全部已确认需求：背景与目标、功能与隔离、实施与验收。",
            },
        )
        assert run(outline["id"])["status"] == "succeeded"
        solution = request("GET", root)
        approved = request(
            "POST",
            root + "/outline/approve",
            {
                "version": solution["version"],
                "request_id": str(uuid4()),
                "instruction": (
                    "覆盖本章相关确认需求；不得承诺自动报价、自动签约或100%准确率。"
                    "明确验收方法和边界。"
                ),
                "sections": [
                    {k: s[k] for k in ("id", "title", "goal")}
                    for s in solution["current"]["sections"]
                ],
            },
        )
        assert run(approved["id"])["status"] == "succeeded"
        solution = request("GET", root)
        before = solution["current"]
        first = before["sections"][0]
        edited = request(
            "PATCH",
            root,
            {
                "version": solution["version"],
                "request_id": str(uuid4()),
                "section_id": first["id"],
                "content": {
                    "type": "doc",
                    "content": [
                        *first["content"]["content"],
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "人工验收补充：本方案是草稿，交付前逐项核实。",
                                }
                            ],
                        },
                    ],
                },
                "change_summary": "S09 人工审核留痕",
            },
        )
        assert (
            request("GET", root + f"/versions/{before['version']}")["sections"]
            == before["sections"]
        )
        version = edited["version"]
        review = request("POST", root + "/verify", {"version": version, "request_id": str(uuid4())})
        assert run(review["run"]["id"])["status"] == "succeeded"
        results = request("GET", root + f"/deliveries?version={version}")
        quality = next(r for r in results if r["run"]["id"] == review["run"]["id"])
        out = Path(".local/s09")
        out.mkdir(exist_ok=True)
        files = {}
        for format, suffix in (("markdown", "md"), ("docx", "docx")):
            delivery = request(
                "POST",
                root + "/exports",
                {"version": version, "request_id": str(uuid4()), "format": format},
            )
            assert run(delivery["run"]["id"])["status"] == "succeeded"
            response = web.get(f"/api/backend/exports/{delivery['run']['id']}/download")
            assert (
                response.status_code == 200
                and response.headers["cache-control"] == "private, no-store"
            )
            (out / f"solution.{suffix}").write_bytes(response.content)
            text = (
                response.content.decode()
                if format == "markdown"
                else "\n".join(p.text for p in Document(BytesIO(response.content)).paragraphs)
            )
            assert "参考资料" in text and "人工验收补充" in text
            for s in edited["current"]["sections"]:
                assert s["title"] in text
                for c in s["citations"]:
                    assert c["quote"] in text.replace("\\", "")
            files[format] = {"run_id": delivery["run"]["id"], "bytes": len(response.content)}
        with httpx.Client(base_url=origin, trust_env=False) as anonymous:
            assert (
                anonymous.get(
                    f"/api/backend/exports/{files['docx']['run_id']}/download"
                ).status_code
                == 401
            )
        result = dict(
            project_id=project["id"],
            customer_id=customer["id"],
            solution_id=solution["id"],
            version=version,
            elapsed_seconds=round(time.monotonic() - started, 2),
            document_ready=True,
            extraction_items=len(extracted),
            extraction_category_recall=round(len(categories & gold) / len(gold), 3),
            extraction_quote_match_rate=1.0,
            advisory_coverage_percent=quality["coverage_percent"],
            quality_issues=quality["issues"],
            semantic_citation_support_rate=None,
            semantic_citation_note="模型建议和摘录匹配不能代替逐条人工支持度标注。",
            unauthorized_download_denied=True,
            history_immutable=True,
            exports=files,
        )
        Path("evals/s09-results.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
