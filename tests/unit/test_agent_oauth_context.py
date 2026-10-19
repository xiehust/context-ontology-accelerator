# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""scripts/agent-oauth-context.sh: the agent OAuth (3LO) context guard shared by
deploy.sh and deploy-serve.sh."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[2]
_HELPER = _ROOT / "scripts" / "agent-oauth-context.sh"
_CB = "https://bedrock-agentcore.us-west-2.amazonaws.com/identities/oauth2/callback/abc"


@pytest.fixture
def aws_stub(tmp_path: Path) -> tuple[Path, Path]:
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    call_log = tmp_path / "aws-calls.log"
    stub = stub_dir / "aws"
    stub.write_text(
        """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$AWS_STUB_LOG"
if [ "$1 $2" = "ssm get-parameter" ]; then
  [ "$AWS_STUB_CLIENT" = "present" ] && exit 0
  echo "An error occurred (ParameterNotFound) when calling the GetParameter operation" >&2
  exit 254
fi
echo "unexpected aws invocation: $*" >&2
exit 2
"""
    )
    stub.chmod(0o755)
    return stub_dir, call_log


def _run(aws_stub: tuple[Path, Path], client: str, **extra_env: str) -> subprocess.CompletedProcess[str]:
    stub_dir, call_log = aws_stub
    env = {
        **os.environ,
        "PATH": f"{stub_dir}:{os.environ['PATH']}",
        "AWS_STUB_LOG": str(call_log),
        "AWS_STUB_CLIENT": client,
    }
    for name in ("SCL_AGENT_OAUTH_CALLBACK_URLS", "SCL_REMOVE_AGENT_OAUTH", "SCL_PREFIX"):
        env.pop(name, None)
    env.update(extra_env)
    script = f'set -euo pipefail; CONTEXT="--context env=dev"; . "{_HELPER}"; printf "%s" "$CONTEXT"'
    return subprocess.run(["bash", "-c", script], cwd=_ROOT, env=env, capture_output=True, text=True, check=False)


def test_callback_list_becomes_context_without_aws_lookup(aws_stub: tuple[Path, Path]) -> None:
    result = _run(aws_stub, "present", SCL_AGENT_OAUTH_CALLBACK_URLS=f"{_CB},{_CB}-prod")
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"--context env=dev --context agentOauthCallbackUrls={_CB},{_CB}-prod"
    assert not aws_stub[1].exists()


@pytest.mark.parametrize("value", [f'["{_CB}"]', f"{_CB}, {_CB}-prod"])
def test_json_or_spaced_list_is_refused(aws_stub: tuple[Path, Path], value: str) -> None:
    result = _run(aws_stub, "absent", SCL_AGENT_OAUTH_CALLBACK_URLS=value)
    assert result.returncode == 1
    assert "comma-separated" in result.stderr


def test_unset_list_refused_while_client_exists(aws_stub: tuple[Path, Path]) -> None:
    result = _run(aws_stub, "present", SCL_PREFIX="coa-w2")
    assert result.returncode == 1
    assert "/coa-w2/agent-oauth-client-id" in result.stderr
    assert "SCL_REMOVE_AGENT_OAUTH=1" in result.stderr


def test_explicit_removal_allowed(aws_stub: tuple[Path, Path]) -> None:
    result = _run(aws_stub, "present", SCL_REMOVE_AGENT_OAUTH="1")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "--context env=dev"


def test_no_client_no_context(aws_stub: tuple[Path, Path]) -> None:
    result = _run(aws_stub, "absent")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "--context env=dev"
    assert "ssm get-parameter --name /coa/agent-oauth-client-id" in aws_stub[1].read_text()
