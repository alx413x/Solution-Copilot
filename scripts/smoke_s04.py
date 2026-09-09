"""Real model acceptance with synthetic input only; retain the sample for browser review."""

import json
import time
from pathlib import Path

import httpx


def main():
    credential = json.loads(Path(".local/demo-credentials.json").read_text())["a-owner"]
    text = (
        "示例制造企业有三个工厂，现有资料分散在多个系统，查找困难。"
        "目标是建立统一项目资料工作台。必须支持单点登录和资料上传。"
        "需要对接现有 ERP 系统。客户资料必须按客户隔离。"
        "部署必须使用客户现有服务器。预算上限 100 万元。"
        "验收时需验证未授权用户无法读取其他客户资料。"
    )
    with httpx.Client(
        base_url="http://127.0.0.1:8000/api/v1",
        trust_env=False,
        timeout=30,
        headers={
            "Authorization": f"Bearer {credential['token']}",
            "X-Organization-ID": credential["organization_id"],
        },
    ) as client:
        customer = client.get("/customers").json()["items"][0]
        p = client.post(f"/customers/{customer['id']}/projects", json={"name": "S04 需求验收示例"})
        p.raise_for_status()
        project = p.json()
        path = f"/projects/{project['id']}/requirements"
        started = time.monotonic()
        r = client.post(path + "/extractions", json={"text": text})
        r.raise_for_status()
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            r = client.get(path)
            r.raise_for_status()
            profile = r.json()
            if profile["extraction"]["status"] in {"succeeded", "failed"}:
                break
            time.sleep(1)
        assert profile["extraction"]["status"] == "succeeded", profile["extraction"]
        assert profile["items"] and all(i["status"] == "proposed" for i in profile["items"])
        assert all(s["quote"] in text for i in profile["items"] for s in i["sources"])
        r = client.post(path + "/confirm", json={"version": profile["version"]})
        r.raise_for_status()
        assert r.json()["confirmed_at"]
        artifact = {
            "prompt_version": "s04-v1",
            "project_id": project["id"],
            "input": text,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "profile": r.json(),
        }
        Path("evals/s04-results.json").write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2) + "\n"
        )
        print(
            json.dumps(
                {
                    "project_id": project["id"],
                    "items": len(profile["items"]),
                    "completeness_score": profile["completeness_score"],
                    "seconds": artifact["elapsed_seconds"],
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
