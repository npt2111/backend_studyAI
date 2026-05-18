import os
import sys


def main() -> int:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    from django.core.management import execute_from_command_line

    argv = sys.argv[:]
    if len(argv) == 1:
        argv = [argv[0], "run_summary_worker"]
    else:
        argv = [argv[0], "run_summary_worker", *argv[1:]]
    execute_from_command_line(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
