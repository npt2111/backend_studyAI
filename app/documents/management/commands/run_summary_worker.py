import logging
import time

from django.core.management.base import BaseCommand

from app.documents.services import process_summary_job
from config.services import supabase_client

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the background summary worker loop."

    def add_arguments(self, parser):
        parser.add_argument("--poll-interval", type=float, default=3.0)
        parser.add_argument("--batch-size", type=int, default=5)
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        poll_interval = max(1.0, float(options["poll_interval"]))
        batch_size = max(1, min(int(options["batch_size"]), 50))
        run_once = bool(options["once"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Summary worker started (poll_interval={poll_interval}s, batch_size={batch_size}, once={run_once})"
            )
        )

        try:
            self._run_loop(poll_interval=poll_interval, batch_size=batch_size, run_once=run_once)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Summary worker stopped."))

    def _run_loop(self, *, poll_interval: float, batch_size: int, run_once: bool) -> None:
        while True:
            rows, status_code = supabase_client.list_queued_summary_jobs(limit=batch_size)
            if status_code >= 400:
                logger.warning("Could not list queued summary jobs: status=%s", status_code)
                if run_once:
                    return
                time.sleep(poll_interval)
                continue

            if not rows:
                if run_once:
                    return
                time.sleep(poll_interval)
                continue

            for row in rows:
                job_id = str(row.get("id_job") or "").strip()
                if not job_id:
                    continue
                try:
                    self.stdout.write(f"Processing summary job {job_id}...")
                    process_summary_job(job_id)
                    self.stdout.write(self.style.SUCCESS(f"Finished summary job {job_id}."))
                except Exception as exc:
                    logger.exception("Summary worker failed for job %s: %s", job_id, exc)
                    self.stdout.write(self.style.ERROR(f"Failed summary job {job_id}: {exc}"))

            if run_once:
                return
