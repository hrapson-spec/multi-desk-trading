"""Keep public-data runbook commands parseable by the real CLI."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from v2.ingest.cli import build_parser

RUNBOOK = Path("docs/v2/operator_runbook_public_data.md")


def _cli_commands() -> list[list[str]]:
    text = RUNBOOK.read_text(encoding="utf-8")
    commands: list[list[str]] = []
    for block in re.findall(r"```bash\n(.*?)```", text, flags=re.DOTALL):
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line or not line.startswith("python -m v2.ingest.cli "):
                continue
            argv = shlex.split(line)[3:]
            commands.append(argv)
    return commands


def test_public_data_runbook_cli_commands_parse():
    parser = build_parser()
    commands = _cli_commands()
    assert commands, "runbook should contain public-data CLI commands"
    for argv in commands:
        parser.parse_args(argv)
