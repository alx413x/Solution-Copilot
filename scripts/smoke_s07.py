"""Live S07 acceptance through Web, API, dispatcher, worker, DeepSeek and PostgreSQL."""

import json
import time
from pathlib import Path
from uuid import uuid4

import httpx


def main():
    credential = json.loads(Path(".local/demo-credentials.json").read_text())["a-owner"]
    s06 = json.loads(Path("evals/s06-results.json").read_text())
    origin = "http://127.0.0.1:3000"
    with httpx.Client(
        base_url=origin, trust_env=False, timeout=60, headers={"Origin": origin}
    ) as web:

        def request(method, path, data=None):
            response = web.request(method, path, json=data)
            assert response.is_success, (response.status_code, response.text)
            return response.json()

        def settled(run_id):
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                row = request("GET", f"/api/backend/runs/{run_id}")
                if row["status"] not in {"queued", "running"}:
                    return row
                time.sleep(0.5)
            raise AssertionError("Worker did not settle")

        request(
            "POST",
            "/api/session",
            {"token": credential["token"], "organizationId": credential["organization_id"]},
        )
        project_id, workflow_id = s06["project_id"], s06["run_id"]
        solution = request(
            "POST",
            f"/api/backend/projects/{project_id}/solutions",
            {"workflow_run_id": workflow_id, "title": "S07 方案生成验收"},
        )
        solution_id = solution["id"]
        base = f"/api/backend/solutions/{solution_id}"
        started = time.monotonic()

        outline_run = request(
            "POST",
            base + "/outline",
            {
                "version": solution["version"],
                "request_id": str(uuid4()),
                "instruction": "生成简明且可追溯的售前方案大纲。",
            },
        )
        outline_run = settled(outline_run["id"])
        assert outline_run["status"] == "succeeded", outline_run
        solution = request("GET", base)
        outline_version = solution["version"]
        assert 1 <= len(solution["current"]["sections"]) <= 20

        sections = solution["current"]["sections"][:2]
        generation_run = request(
            "POST",
            base + "/outline/approve",
            {
                "version": solution["version"],
                "request_id": str(uuid4()),
                "instruction": "每章只写有已确认需求或授权来源支持的内容。",
                "sections": [
                    {"id": row["id"], "title": row["title"], "goal": row["goal"]}
                    for row in sections
                ],
            },
        )
        generation_run = settled(generation_run["id"])
        assert generation_run["status"] == "succeeded", generation_run
        generated = request("GET", base)
        assert generated["version"] == outline_version + 3
        assert all(row["status"] == "draft" for row in generated["current"]["sections"])
        citations = [
            citation
            for section in generated["current"]["sections"]
            for citation in section["citations"]
        ]
        assert citations and all(c["verification_status"] == "partial" for c in citations)

        first, second = generated["current"]["sections"]
        edited = request(
            "PATCH",
            base,
            {
                "version": generated["version"],
                "request_id": str(uuid4()),
                "section_id": first["id"],
                "content": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "人工复核后的验收正文。"}],
                        }
                    ],
                },
                "change_summary": "S07 smoke 人工复核",
            },
        )
        assert edited["version"] == generated["version"] + 1
        edited_first = edited["current"]["sections"][0]
        assert all(c["verification_status"] == "unverified" for c in edited_first["citations"])

        section_run = request(
            "POST",
            base + f"/sections/{second['id']}/generate",
            {
                "version": edited["version"],
                "request_id": str(uuid4()),
                "instruction": "重新生成并保留逐字来源引用。",
            },
        )
        section_run = settled(section_run["id"])
        assert section_run["status"] == "succeeded", section_run
        final = request("GET", base)
        assert final["version"] == edited["version"] + 1
        assert final["current"]["sections"][0] == edited_first
        assert final["current"]["sections"][1] != second

        history = request("GET", base + "/versions")
        assert len(history) == final["version"]
        prior = request("GET", base + f"/versions/{generated['version']}")
        assert prior["sections"] == generated["current"]["sections"]
        events = web.get(
            f"/api/backend/runs/{generation_run['id']}/events",
            headers={"Last-Event-ID": "0"},
        )
        events.raise_for_status()
        assert "section.completed" in events.text and "run.completed" in events.text

        result = {
            "project_id": project_id,
            "solution_id": solution_id,
            "outline_run_id": outline_run["id"],
            "generation_run_id": generation_run["id"],
            "section_run_id": section_run["id"],
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "version": final["version"],
            "sections": len(final["current"]["sections"]),
            "citations": len(citations),
            "model_info": generation_run["model_info"],
            "manual_edit_preserved": True,
            "history_immutable": True,
            "sse_completed": True,
        }
        Path("evals/s07-results.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
