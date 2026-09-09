"""Synthetic Web/API/dispatcher/worker acceptance, without a generation model call."""

import json
import time
from pathlib import Path
from uuid import uuid4

import httpx


def main():
    credential = json.loads(Path(".local/demo-credentials.json").read_text())["a-owner"]
    origin = "http://127.0.0.1:3000"
    with httpx.Client(
        base_url=origin, trust_env=False, timeout=60, headers={"Origin": origin}
    ) as web:

        def request(method, path, data=None):
            response = web.request(method, path, json=data)
            response.raise_for_status()
            return response.json()

        def settled(run_id):
            deadline = time.monotonic() + 120
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
        customer = request("GET", "/api/backend/customers")["items"][0]
        p = request(
            "POST", f"/api/backend/customers/{customer['id']}/projects", {"name": "S06 编排验收"}
        )["id"]
        base = f"/api/backend/projects/{p}"
        c = request("POST", base + "/conversations", {"title": "S06 合成需求"})["id"]
        started = time.monotonic()
        run_id = request(
            "POST",
            f"/api/backend/conversations/{c}/workflows",
            {"goal": "权限隔离和部署方案", "epoch": 0, "request_id": str(uuid4())},
        )["id"]
        first = settled(run_id)
        assert first["status"] == "waiting_user" and first["workflow"]["gate"] == 1, first
        answers = {
            "background": "售前团队目前用文档整理客户需求。",
            "pain_point": "多人整理时需求遗漏，难以追溯来源。",
            "goal": "让确认后的需求可以生成方案草稿。",
            "functional": "支持需求记录、来源引用和人工确认。",
            "integration": "演示阶段不对接外部业务系统。",
            "security_compliance": "不同客户数据必须隔离，成员只能访问授权项目。",
            "constraint": "仅本地部署，本阶段不提供报价。",
            "acceptance_metric": "运行重启后能恢复，同一确认不会重复写入。",
        }
        for q in request("GET", base + "/clarifications"):
            if q["category"] not in answers:
                continue
            profile = request("GET", base + "/requirements")
            request(
                "POST",
                f"/api/backend/clarifications/{q['id']}/answer",
                {
                    "conversation_id": c,
                    "answer": answers[q["category"]],
                    "version": q["version"],
                    "profile_version": profile["version"],
                    "epoch": 0,
                },
            )
        profile = request("GET", base + "/requirements")
        assert profile["completeness_score"] == 100
        request("POST", base + "/requirements/confirm", {"version": profile["version"]})
        url = f"/api/backend/runs/{run_id}/resume"
        request("POST", url, {"gate": 1, "approve": True, "request_id": str(uuid4())})
        outline = settled(run_id)
        assert outline["status"] == "waiting_user" and outline["workflow"]["gate"] == 2, outline
        assert len(outline["workflow"]["outline"]) == 14
        decision = {"gate": 2, "approve": True, "request_id": str(uuid4())}
        request("POST", url, decision)
        final = settled(run_id)
        assert final["status"] == "succeeded", final
        assert request("POST", url, decision)["id"] == run_id
        messages = request("GET", f"/api/backend/conversations/{c}/messages")["messages"]
        assert len([m for m in messages if m["run_id"] == run_id]) == 1
        events = web.get(f"/api/backend/runs/{run_id}/events", headers={"Last-Event-ID": "1"})
        events.raise_for_status()
        assert "run.completed" in events.text and "id: 1\n" not in events.text
        result = dict(
            project_id=p,
            conversation_id=c,
            run_id=run_id,
            elapsed_seconds=round(time.monotonic() - started, 2),
            first_gate=first["workflow"]["gate"],
            outline_gate=outline["workflow"]["gate"],
            final=final,
            replay_safe=True,
            sse_replay=True,
        )
        Path("evals/s06-results.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
