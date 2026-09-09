"""Run independently of Redis: durable job reconciliation must survive broker outages."""

import logging
import time

from solution_copilot.application.conversation_jobs import dispatch_once as dispatch_conversations
from solution_copilot.application.document_jobs import dispatch_once
from solution_copilot.application.requirement_jobs import dispatch_once as dispatch_requirements

from apps.worker.main import app


def main():
    while True:
        try:
            dispatch_once(
                lambda job_id: app.send_task("documents.parse", args=[job_id], retry=False)
            )
        except Exception:
            logging.warning("Document dispatcher unavailable; will retry (details suppressed).")
        try:
            dispatch_requirements(
                lambda job_id: app.send_task("requirements.extract", args=[job_id], retry=False)
            )
        except Exception:
            logging.warning("Requirement dispatcher unavailable; will retry (details suppressed).")
        try:
            dispatch_conversations(
                lambda run_id: app.send_task("conversations.respond", args=[run_id], retry=False)
            )
        except Exception:
            logging.warning("Conversation dispatcher unavailable; will retry (details suppressed).")
        time.sleep(2)


if __name__ == "__main__":
    main()
