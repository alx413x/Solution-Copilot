"""Run independently of Redis: durable job reconciliation must survive broker outages."""

import logging
import time

from solution_copilot.application.document_jobs import dispatch_once

from apps.worker.main import app


def main():
    while True:
        try:
            dispatch_once(
                lambda job_id: app.send_task("documents.parse", args=[job_id], retry=False)
            )
        except Exception:
            logging.warning("Document dispatcher unavailable; will retry (details suppressed).")
        time.sleep(2)


if __name__ == "__main__":
    main()
