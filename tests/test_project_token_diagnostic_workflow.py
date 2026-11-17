# SPDX-License-Identifier: Apache-2.0

"""Exercise the temporary workflow's inline code without network access or real secrets."""

import http.client
import json
import os
import ssl
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple
from unittest.mock import MagicMock

import pytest
import yaml

WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1] / ".github/workflows/diagnose_project_token.yml"
)
WORKFLOW = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
SCRIPT = WORKFLOW["jobs"]["diagnose-project-token"]["steps"][0]["run"]
FAKE_TOKEN = "ghp_FAKE_ONLY_NOT_A_REAL_TOKEN"
PRIVATE_MARKER = "PRIVATE_RESPONSE_DETAILS"
IDENTITY = json.dumps({"login": "example-user", "id": 123, "email": PRIVATE_MARKER}).encode()


def _run_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    *,
    token: str = FAKE_TOKEN,
    revoke: bool = False,
    responses: Optional[List[Tuple[int, bytes]]] = None,
    fault: Optional[Tuple[str, Exception]] = None,
) -> Tuple[str, Optional[SystemExit], MagicMock, MagicMock]:
    """Run with fake transport and assert secret-free, bounded output and requests."""
    monkeypatch.setenv("PROJECT_SYNC_TOKEN", token)
    monkeypatch.setenv("REVOKE", str(revoke).lower())
    monkeypatch.setattr(
        "socket.create_connection", MagicMock(side_effect=AssertionError("Network forbidden"))
    )
    connection = MagicMock()
    factory = MagicMock(return_value=connection)
    monkeypatch.setattr(http.client, "HTTPSConnection", factory)
    response_objects = []
    for status, body in responses if responses is not None else [(200, IDENTITY)]:
        response = MagicMock(status=status)
        response.read.return_value = body
        response_objects.append(response)
    connection.getresponse.side_effect = response_objects
    if fault:
        stage, error = fault
        if stage == "construct":
            factory.side_effect = error
        elif stage == "read":
            response_objects[0].read.side_effect = error
        else:
            getattr(connection, stage).side_effect = error
    failure = None
    try:
        exec(compile(SCRIPT, str(WORKFLOW_PATH), "exec"), {})
    except SystemExit as error:
        failure = error
    captured = capsys.readouterr()
    output = captured.out + captured.err + (str(failure) if failure else "")
    if token:
        assert token not in output
        assert repr(token) not in output
    assert PRIVATE_MARKER not in output
    assert "Traceback" not in output
    for call in factory.call_args_list:
        assert call.args == ("api.github.com",)
        assert call.kwargs["timeout"] == 30
        context = call.kwargs["context"]
        assert context.check_hostname
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.keylog_filename is None
    for call in connection.request.call_args_list:
        method, path, body, headers = call.args
        assert headers["User-Agent"] == "org-infra-project-token-diagnostic"
        if path == "/credentials/revoke":
            assert method == "POST"
            assert "Authorization" not in headers
            assert json.loads(body) == {"credentials": [token]}
        else:
            assert (method, path, body) == ("GET", "/user", None)
            assert headers["Authorization"] == f"Bearer {token}"
    if connection.request.called:
        assert connection.method_calls[0][0] == "set_debuglevel"
        assert connection.set_debuglevel.call_args.args == (0,)
    for response in response_objects:
        if response.status == 200:
            if response.read.called:
                response.read.assert_called_once_with(16385)
        else:
            response.read.assert_not_called()
    return output, failure, factory, connection


@pytest.mark.parametrize(
    ("prefix", "label"),
    [
        ("ghp_", "Classic personal access token"),
        ("github_pat_", "Fine-grained personal access token"),
        ("gho_", "OAuth access token"),
        ("ghu_", "GitHub App user access token"),
        ("ghs_", "GitHub App installation access token"),
        ("ghr_", "GitHub App refresh token"),
        ("legacy_", "Unknown credential format"),
    ],
)
def test_read_only_diagnostic_discloses_only_intended_identity(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, prefix: str, label: str
) -> None:
    output, failure, factory, _ = _run_diagnostic(monkeypatch, capsys, token=prefix + "FAKE_ONLY")
    assert failure is None
    assert output.splitlines() == [
        f"Credential type: {label}",
        "Authenticated account: example-user; account ID: 123",
        "Read-only diagnostic complete; no revocation requested.",
    ]
    assert factory.call_count == 1


@pytest.mark.parametrize("suffix", ["", "\nextra", "\rextra", "\x01", "\t", " ", "é"])
def test_missing_or_unsafe_credentials_never_reach_transport(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, suffix: str
) -> None:
    token = FAKE_TOKEN + suffix if suffix else ""
    output, failure, factory, _ = _run_diagnostic(monkeypatch, capsys, token=token)
    assert failure is not None
    assert "missing or malformed" in output
    factory.assert_not_called()


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308, 401, 403, 429, 500])
def test_redirects_and_http_errors_never_follow_or_revoke(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, status: int
) -> None:
    output, failure, factory, connection = _run_diagnostic(
        monkeypatch, capsys, revoke=True, responses=[(status, FAKE_TOKEN.encode())]
    )
    assert failure is not None
    assert f"HTTP {status}" in output
    assert factory.call_count == connection.request.call_count == 1
    connection.close.assert_called_once()


@pytest.mark.parametrize("stage", ["construct", "request", "getresponse", "read", "close"])
@pytest.mark.parametrize("error_type", [ValueError, RuntimeError, http.client.HTTPException])
def test_all_transport_failures_suppress_sensitive_exception_details(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    stage: str,
    error_type: type,
) -> None:
    output, failure, _, _ = _run_diagnostic(
        monkeypatch, capsys, fault=(stage, error_type(FAKE_TOKEN + PRIVATE_MARKER))
    )
    assert failure is not None
    assert output.endswith("::error::Diagnostic failed; details suppressed")


@pytest.mark.parametrize(
    "body",
    [
        b"not JSON",
        b"null",
        b"[]",
        b"{}",
        json.dumps({"login": FAKE_TOKEN, "id": 123}).encode(),
        json.dumps({"login": "::warning::" + PRIVATE_MARKER, "id": 123}).encode(),
        json.dumps({"login": "example-user", "id": PRIVATE_MARKER}).encode(),
        json.dumps({"login": "example-user", "id": True}).encode(),
        json.dumps({"login": "example-user", "id": -1}).encode(),
        json.dumps({"login": "example-user", "id": 2**63}).encode(),
        b"x" * 16385,
    ],
)
def test_invalid_identity_fails_closed_without_printing_or_revoking(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, body: bytes
) -> None:
    output, failure, _, connection = _run_diagnostic(
        monkeypatch, capsys, revoke=True, responses=[(200, body)]
    )
    assert failure is not None
    assert "details suppressed" in output
    assert connection.request.call_count == 1


def test_revocation_is_unauthenticated_and_requires_a_subsequent_401(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    output, failure, factory, connection = _run_diagnostic(
        monkeypatch, capsys, revoke=True, responses=[(200, IDENTITY), (202, b""), (401, b"")]
    )
    assert failure is None
    assert "Revocation confirmed: credential now returns HTTP 401." in output
    assert factory.call_count == connection.request.call_count == 3


@pytest.mark.parametrize("status", [200, 302, 403, 429, 500])
def test_revocation_acceptance_does_not_claim_success_without_401(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, status: int
) -> None:
    output, failure, _, _ = _run_diagnostic(
        monkeypatch,
        capsys,
        revoke=True,
        responses=[(200, IDENTITY), (202, b""), (status, IDENTITY)],
    )
    assert failure is not None
    assert "NOT confirmed" in output
    assert "Revocation confirmed:" not in output


@pytest.mark.parametrize("status", [302, 403, 422, 500])
def test_revocation_errors_do_not_read_or_follow_the_response(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, status: int
) -> None:
    output, failure, _, connection = _run_diagnostic(
        monkeypatch,
        capsys,
        revoke=True,
        responses=[(200, IDENTITY), (status, FAKE_TOKEN.encode())],
    )
    assert failure is not None
    assert f"Revocation request returned HTTP {status}" in output
    assert connection.request.call_count == 2


@pytest.mark.parametrize("prefix", ["legacy_", "ghs_"])
def test_unsupported_revocation_formats_never_submit_the_credential(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, prefix: str
) -> None:
    output, failure, _, connection = _run_diagnostic(
        monkeypatch, capsys, token=prefix + "FAKE_ONLY", revoke=True
    )
    assert failure is not None
    assert "not supported for revocation" in output
    assert connection.request.call_count == 1


def test_real_interpreter_does_not_print_sensitive_exception_traceback() -> None:
    prelude = """
import http.client
import os
secret_detail = os.environ["PROJECT_SYNC_TOKEN"]
def fail_connection(*args, **kwargs):
    raise ValueError(secret_detail)
http.client.HTTPSConnection = fail_connection
"""
    result = subprocess.run(
        [sys.executable, "-c", prelude + SCRIPT],
        env={**os.environ, "PROJECT_SYNC_TOKEN": FAKE_TOKEN, "REVOKE": "false"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    assert result.stdout == "Credential type: Classic personal access token\n"
    assert result.stderr == "::error::Diagnostic failed; details suppressed\n"
    assert FAKE_TOKEN not in result.stdout + result.stderr


def test_diagnostic_is_manual_default_branch_only_and_has_no_dependencies() -> None:
    trigger = WORKFLOW.get("on", WORKFLOW.get(True))
    assert set(trigger) == {"workflow_dispatch"}
    assert trigger["workflow_dispatch"]["inputs"]["revoke"]["default"] is False
    assert WORKFLOW["permissions"] == {}
    job = WORKFLOW["jobs"]["diagnose-project-token"]
    assert job["permissions"] == {}
    assert job["if"] == (
        "${{ github.ref == format('refs/heads/{0}', github.event.repository.default_branch) }}"
    )
    assert len(job["steps"]) == 1
    assert "uses" not in job["steps"][0]
    assert job["steps"][0]["shell"] == "python3 -I {0}"
    assert job["steps"][0]["env"] == {
        "PROJECT_SYNC_TOKEN": "${{ secrets.PROJECT_SYNC_TOKEN }}",
        "REVOKE": "${{ inputs.revoke }}",
    }
    for name in ("sync_project_board.yml", "report_sprint_velocity.yml"):
        assert not WORKFLOW_PATH.with_name(name).exists()
