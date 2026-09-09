"""Synthetic live S05 acceptance through the Web proxy, API, worker and DeepSeek."""

import json
import time
from pathlib import Path
from uuid import uuid4

import httpx


def main():
    credential = json.loads(Path(".local/demo-credentials.json").read_text())["a-owner"]
    origin = "http://127.0.0.1:3000"
    with httpx.Client(
        base_url=origin, trust_env=False, timeout=40, headers={"Origin": origin}
    ) as web:
        login = web.post(
            "/api/session",
            json={"token": credential["token"], "organizationId": credential["organization_id"]},
        )
        login.raise_for_status()
        base = "/api/backend"
        customer = web.get(base + "/customers").json()["items"][0]
        r = web.post(
            base + f"/customers/{customer['id']}/projects", json={"name": "S05 澄清对话验收"}
        )
        r.raise_for_status()
        p = r.json()["id"]
        r = web.post(base + f"/projects/{p}/conversations", json={"title": "S05 合成会议"})
        r.raise_for_status()
        c = r.json()["id"]
        text = "项目预算上限100万元，必须部署在客户自有服务器。请记录这些要求。"
        started = time.monotonic()
        r = web.post(
            base + f"/conversations/{c}/messages",
            json={"text": text, "request_id": str(uuid4()), "epoch": 0},
        )
        r.raise_for_status()
        run = r.json()
        # Disconnect after the first durable event, then reconnect using its ID.
        first = None
        connect_deadline = time.monotonic() + 180
        while first is None and time.monotonic() < connect_deadline:
            with web.stream("GET", base + f"/runs/{run['id']}/events") as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line.startswith("id: "):
                        first = int(line[4:])
                        break
        assert first is not None
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            r = web.get(base + f"/runs/{run['id']}")
            r.raise_for_status()
            run = r.json()
            if run["status"] in {"succeeded", "waiting_user", "failed", "cancelled"}:
                break
            time.sleep(1)
        assert run["status"] in {"succeeded", "waiting_user"}, run
        elapsed = round(time.monotonic() - started, 2)
        stream = web.get(base + f"/runs/{run['id']}/events", headers={"Last-Event-ID": str(first)})
        stream.raise_for_status()
        ids = [int(line[4:]) for line in stream.text.splitlines() if line.startswith("id: ")]
        assert ids and min(ids) > first and "message.delta" in stream.text
        hist = web.get(base + f"/conversations/{c}/messages").json()
        assert len(hist["messages"]) == 2
        profile = web.get(base + f"/projects/{p}/requirements").json()
        assert profile["items"] and all(
            s["quote"] in text for i in profile["items"] for s in i["sources"]
        )
        q = next(
            q
            for q in web.get(base + f"/projects/{p}/clarifications").json()
            if q["category"] == "goal"
        )
        r = web.post(
            base + f"/clarifications/{q['id']}/answer",
            json={
                "conversation_id": c,
                "answer": "方案初稿产出时间缩短到1小时。",
                "version": q["version"],
                "profile_version": profile["version"],
                "epoch": 0,
            },
        )
        r.raise_for_status()
        m = web.post(
            base + f"/projects/{p}/memories",
            json={
                "source_message_id": hist["messages"][0]["id"],
                "scope": "customer",
                "content": "客户要求自有服务器部署。",
            },
        ).json()
        r = web.patch(
            base + f"/memories/{m['id']}",
            json={"version": m["version"], "content": m["content"], "status": "confirmed"},
        )
        r.raise_for_status()
        preview = web.post(base + f"/conversations/{c}/reset", json={"confirm": False}).json()
        r = web.post(base + f"/conversations/{c}/reset", json={"confirm": True})
        r.raise_for_status()
        memories = web.get(base + f"/projects/{p}/memories").json()
        assert any(x["id"] == m["id"] and x["status"] == "confirmed" for x in memories)
        artifact = dict(
            project_id=p,
            conversation_id=c,
            input=text,
            elapsed_seconds=elapsed,
            run=run,
            profile=profile,
            messages=hist["messages"],
            first_event_id=first,
            replayed_event_ids=ids,
            reset_preview=preview,
            customer_memory_preserved=True,
        )
        Path("evals/s05-results.json").write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2) + "\n"
        )
        print(
            json.dumps(
                {
                    "project_id": p,
                    "conversation_id": c,
                    "seconds": elapsed,
                    "items": len(profile["items"]),
                    "replayed_events": len(ids),
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
