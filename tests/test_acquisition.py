"""Offline transport integration tests using a local server with synthetic bodies."""
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.error import URLError

import pytest

from traffic_recovery.data.http import AcquisitionError, EvidenceClient, sha256_file
from traffic_recovery.data.sources import archive_url, list_versions


@pytest.fixture
def local_api():
    calls: dict[str, int] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls[self.path] = calls.get(self.path, 0) + 1
            status = 200
            body = b'{"fixture":"SYNTHETIC TEST DATA"}'
            if self.path == "/rate" and calls[self.path] == 1:
                status, body = 429, b"synthetic rate limit"
            elif self.path == "/missing":
                status, body = 404, b"synthetic not found"
            elif self.path == "/empty":
                body = b""
            elif self.path == "/html":
                body = b"<html>synthetic unexpected response</html>"
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Retry-After", "0")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_download_checksum_provenance_reuse_and_no_overwrite(tmp_path: Path, local_api) -> None:
    url, calls = local_api
    client = EvidenceClient(tmp_path)
    path = client.fetch(url + "/ok", "sample.json")
    metadata = json.loads((tmp_path / "sample.json.meta.json").read_text())
    assert metadata["sha256"] == sha256_file(path)
    assert metadata["requested_url"] == url + "/ok"
    assert metadata["status"] == 200
    assert metadata["retrieved_at"].endswith("+00:00")
    with pytest.raises(AcquisitionError, match="overwrite"):
        client.fetch(url + "/ok", "sample.json")
    assert EvidenceClient(tmp_path, reuse=True).fetch(url + "/ok", "sample.json") == path
    assert calls["/ok"] == 1
    path.write_text("tampered test bytes")
    with pytest.raises(AcquisitionError):
        EvidenceClient(tmp_path, reuse=True).fetch(url + "/ok", "sample.json")


def test_rate_limit_retries_and_preserves_both_attempts(tmp_path: Path, local_api) -> None:
    url, calls = local_api
    EvidenceClient(tmp_path).fetch(url + "/rate", "rate.json")
    assert calls["/rate"] == 2
    attempts = [json.loads(line) for line in (tmp_path / "requests.jsonl").read_text().splitlines()]
    assert [a["status"] for a in attempts] == [429, 200]
    assert (tmp_path / "rate.json.attempt-1.body").read_bytes() == b"synthetic rate limit"


def test_http_error_body_and_request_are_preserved_without_retry(tmp_path: Path, local_api) -> None:
    url, calls = local_api
    with pytest.raises(AcquisitionError, match="404"):
        EvidenceClient(tmp_path).fetch(url + "/missing", "missing.json")
    assert calls["/missing"] == 1
    record = json.loads((tmp_path / "missing.json.attempt-1.json").read_text())
    assert record["status"] == 404
    assert record["requested_url"] == url + "/missing"
    assert (tmp_path / record["body"]).read_bytes() == b"synthetic not found"
    with pytest.raises(AcquisitionError, match="failed-attempt evidence"):
        EvidenceClient(tmp_path).fetch(url + "/missing", "missing.json")
    assert calls["/missing"] == 1


@pytest.mark.parametrize("route", ["/empty", "/html"])
def test_empty_or_unexpected_response_fails(tmp_path: Path, local_api, route: str) -> None:
    url, _ = local_api
    with pytest.raises(AcquisitionError):
        EvidenceClient(tmp_path).json(url + route, "bad.json")


@pytest.mark.parametrize("name", ["../escape.xml", "sub/file.xml", "sub\\file.xml", ".."])
def test_evidence_paths_cannot_escape_output(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError):
        EvidenceClient(tmp_path).fetch("https://not-requested.invalid", name)


@pytest.mark.parametrize("failure", [TimeoutError("synthetic timeout"), URLError("synthetic DNS failure")])
def test_timeout_and_network_errors_are_recorded(tmp_path: Path, monkeypatch, failure: Exception) -> None:
    def fail_request(*args, **kwargs):
        raise failure
    monkeypatch.setattr("traffic_recovery.data.http.urlopen", fail_request)
    with pytest.raises(AcquisitionError, match="Request failed"):
        EvidenceClient(tmp_path, attempts=1).fetch("https://not-requested.invalid", "timeout.xml")
    record = json.loads((tmp_path / "timeout.xml.attempt-1.json").read_text())
    assert record["status"] is None
    assert "synthetic" in record["error"]


def test_archive_query_is_encoded_and_truncation_is_explicit(tmp_path: Path) -> None:
    source = "https://example.invalid/test.xml?x=1&y=2"
    url = archive_url("list-file-versions", url=source, start="20260101", end="20260101")
    assert "url=https%3A%2F%2Fexample.invalid%2Ftest.xml%3Fx%3D1%26y%3D2" in url

    class FixtureClient:
        def json(self, url, name):
            return {"timestamps": ["20260101-0000"], "version-count": 10001}

    with pytest.raises(AcquisitionError, match="truncated"):
        list_versions(FixtureClient(), source, date(2026, 1, 1), date(2026, 1, 1), "fixture.json")
    result = list_versions(FixtureClient(), source, date(2026, 1, 1), date(2026, 1, 1), "fixture.json", require_complete=False)
    assert result["version-count"] == 10001
