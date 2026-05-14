#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, Set


RESULT_KEYS = ("passed_tests", "failed_tests", "skipped_tests")


def parse_log(ut_log: str) -> Dict[str, Set[str]]:
    """
    Parse one project's unit-test log and return unified test results.

    Each project should implement its own parsing flow here. The returned
    dictionary must contain these keys, and each value must be a set of test
    names:
      - passed_tests
      - failed_tests
      - skipped_tests
    """
    raise NotImplementedError("Implement project-specific unit-test log parsing in parse_log().")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run a unit-test command or parse a test log, then print unified JSON results."
    )
    parser.add_argument("ut_log", nargs="?", help="Optional existing unit-test log file to parse.")
    parser.add_argument("--cwd", default=".", help="Working directory for the command after --.")
    parser.add_argument("--json", action="store_true", help="Accepted for compatibility; output is always JSON.")
    parser.add_argument("--verbose", action="store_true", help="Stream command output to stderr while running.")
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Optional unit-test command after --, for example: -- pytest tests -v.",
    )
    return parser.parse_args()


def log_progress(message: str):
    print(f"[demo.py] {message}", file=sys.stderr, flush=True)


def command_text(command: Iterable[str]) -> str:
    return " ".join(str(part) for part in command)


def normalize_results(results: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
    normalized = {}
    for key in RESULT_KEYS:
        value = results.get(key, set())
        normalized[key] = set(str(item) for item in value)
    return normalized


def jsonable_results(results: Dict[str, Set[str]]) -> Dict[str, list]:
    normalized = normalize_results(results)
    return {key: sorted(value) for key, value in normalized.items()}


def emit_results(results: Dict[str, Set[str]]):
    print(json.dumps(jsonable_results(results), ensure_ascii=False))


def run_command(command, cwd: Path, verbose: bool) -> str:
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise ValueError("No unit-test command provided after --.")

    log_progress(f"running unit-test command: {command_text(command)}")

    if verbose:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
        output = []
        assert process.stdout is not None
        for line in process.stdout:
            output.append(line)
            print(line, end="", file=sys.stderr)
        return_code = process.wait()
        combined_output = "".join(output)
    else:
        process = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
        return_code = process.returncode
        combined_output = f"{process.stdout}\n{process.stderr}"

    log_progress(f"unit-test command finished with exit code {return_code}")
    return combined_output


def main():
    args = parse_args()

    if args.ut_log:
        ut_log = Path(args.ut_log).read_text(encoding="utf-8", errors="replace")
    else:
        ut_log = run_command(args.command, Path(args.cwd).resolve(), args.verbose)

    results = normalize_results(parse_log(ut_log))
    emit_results(results)
    return 1 if results["failed_tests"] else 0


if __name__ == "__main__":
    sys.exit(main())
