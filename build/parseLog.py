#!/usr/bin/env python3
import argparse
import json
import os
import re
import selectors
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Iterable, Set, Tuple


RESULT_KEYS = ("passed_tests", "failed_tests", "skipped_tests")
PROGRESS_HEARTBEAT_SECONDS = 15
DEFAULT_CWD = Path("/workspace/android-upload")
DEFAULT_COMMAND = ["./gradlew", "testDebugUnitTest", "--continue", "--console=plain", "--no-daemon"]


def empty_results() -> Dict[str, Set[str]]:
    return {key: set() for key in RESULT_KEYS}


def parse_log(ut_log: str) -> Dict[str, Set[str]]:
    results = empty_results()
    status_to_key = {
        "PASSED": "passed_tests",
        "FAILED": "failed_tests",
        "SKIPPED": "skipped_tests",
    }
    pattern = re.compile(r"^\s*(?P<name>.+?)\s+(?P<status>PASSED|FAILED|SKIPPED)\s*$")

    for line in ut_log.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        name = re.sub(r"\s*>\s*", ".", match.group("name").strip())
        results[status_to_key[match.group("status")]].add(name)

    return results


def parse_junit_xml(root_dir: Path) -> Dict[str, Set[str]]:
    results = empty_results()
    seen = set()
    xml_files = sorted(root_dir.glob("**/build/test-results/testDebugUnitTest/**/*.xml"))
    xml_files.extend(sorted(root_dir.glob("**/build/test-results/test*/**/*.xml")))

    for xml_file in xml_files:
        if xml_file in seen or xml_file.name.startswith("binary"):
            continue
        seen.add(xml_file)
        try:
            root = ET.parse(xml_file).getroot()
        except ET.ParseError:
            continue

        for case in root.iter("testcase"):
            class_name = case.attrib.get("classname") or root.attrib.get("name") or ""
            method_name = case.attrib.get("name") or xml_file.stem
            test_name = f"{class_name}.{method_name}" if class_name else method_name

            if case.find("skipped") is not None:
                results["skipped_tests"].add(test_name)
            elif case.find("failure") is not None or case.find("error") is not None:
                results["failed_tests"].add(test_name)
            else:
                results["passed_tests"].add(test_name)

    return results


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run android-upload unit tests, then print unified JSON results."
    )
    parser.add_argument("--cwd", default=str(DEFAULT_CWD), help="Working directory for the command after --.")
    parser.add_argument("--json", action="store_true", help="Accepted for compatibility; output is always JSON.")
    parser.add_argument("--verbose", action="store_true", help="Stream command output to stderr while running.")
    parser.add_argument(
        "remainder",
        nargs=argparse.REMAINDER,
        help="Optional log file to parse, or a unit-test command after --. Defaults to ./gradlew testDebugUnitTest.",
    )
    args = parser.parse_args()
    args.ut_log = None
    args.command = []

    if args.remainder:
        if args.remainder[0] == "--":
            args.command = args.remainder
        else:
            args.ut_log = args.remainder[0]
            args.command = args.remainder[1:]

    del args.remainder
    return args


def log_progress(message: str):
    print(f"[demo.py] {message}", file=sys.stderr, flush=True)


def command_text(command: Iterable[str]) -> str:
    return " ".join(str(part) for part in command)


def should_echo_progress(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    progress_tokens = (
        "BUILD ",
        "Downloading ",
        "Installing ",
        "Preparing ",
        "FAILED",
        "FAILURE",
        "PASSED",
        "SKIPPED",
        "SUCCESS",
        "ERROR",
        "Exception",
    )
    return stripped.startswith((">", ":", "[")) or any(token in stripped for token in progress_tokens)


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


def run_command(command, cwd: Path, verbose: bool) -> Tuple[str, int]:
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        command = DEFAULT_COMMAND

    log_progress(f"running unit-test command: {command_text(command)}")

    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )
    assert process.stdout is not None

    output_chunks = []
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    start_time = time.monotonic()
    last_progress = start_time
    progress_buffer = ""

    try:
        while True:
            events = selector.select(timeout=1.0)
            for key, _ in events:
                chunk = os.read(key.fileobj.fileno(), 8192)
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue

                output_chunks.append(chunk)
                text = chunk.decode("utf-8", errors="replace")
                if verbose:
                    print(text, end="", file=sys.stderr)
                    last_progress = time.monotonic()
                else:
                    progress_buffer += text.replace("\r", "\n")
                    lines = progress_buffer.split("\n")
                    progress_buffer = lines.pop() if lines else ""
                    for line in lines:
                        if should_echo_progress(line):
                            print(line, file=sys.stderr, flush=True)
                            last_progress = time.monotonic()

            return_code = process.poll()
            if return_code is not None:
                break

            now = time.monotonic()
            if not verbose and now - last_progress >= PROGRESS_HEARTBEAT_SECONDS:
                elapsed = int(now - start_time)
                log_progress(f"unit-test command still running after {elapsed}s; use --verbose for full output")
                last_progress = now
    except KeyboardInterrupt:
        log_progress("received interrupt; stopping unit-test command")
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise
    finally:
        selector.close()

    combined_output = b"".join(output_chunks).decode("utf-8", errors="replace")

    log_progress(f"unit-test command finished with exit code {return_code}")
    return combined_output, return_code


def merge_results(primary: Dict[str, Set[str]], secondary: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
    merged = normalize_results(primary)
    for key in RESULT_KEYS:
        merged[key].update(secondary.get(key, set()))
    return merged


def main():
    args = parse_args()
    cwd = Path(args.cwd).resolve()
    return_code = 0

    try:
        if args.ut_log:
            ut_log = Path(args.ut_log).read_text(encoding="utf-8", errors="replace")
            results = parse_log(ut_log)
        else:
            ut_log, return_code = run_command(args.command, cwd, args.verbose)
            results = parse_junit_xml(cwd)
            if not any(results.values()):
                results = parse_log(ut_log)
            else:
                results = merge_results(results, parse_log(ut_log))
    except KeyboardInterrupt:
        log_progress("interrupted")
        return 130

    results = normalize_results(results)
    if return_code and not results["failed_tests"]:
        results["failed_tests"].add(f"gradle_command_exit_{return_code}")

    emit_results(results)
    return 1 if return_code or results["failed_tests"] else 0


if __name__ == "__main__":
    sys.exit(main())