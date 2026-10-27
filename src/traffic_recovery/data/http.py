"""Small evidence-preserving HTTP client using the standard library."""
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)
HEADERS = {"content-type", "content-length", "date", "last-modified", "etag",
           "retry-after", "location", "content-disposition", "content-encoding"}


class AcquisitionError(RuntimeError):
    """HTTP/network/response failure; inspect preserved request metadata."""


def sha256_file(path: Path) -> str:
    """Hash a file without loading large road/traffic resources into memory."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class EvidenceClient:
    """Preserve bodies, bounded retries, metadata and JSONL request logs.

    `reuse` reads only checksum-verified previous successful responses for the
    identical URL. Otherwise existing response files are never overwritten.
    """

    def __init__(self, root: Path, *, timeout: float = 90, attempts: int = 3,
                 reuse: bool = False) -> None:
        if timeout <= 0 or attempts < 1:
            raise ValueError("timeout and attempts must be positive")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.attempts = attempts
        self.reuse = reuse

    def fetch(self, url: str, name: str) -> Path:
        """GET to a safe relative filename; raise AcquisitionError after retries.

        HTTP error bodies and each attempt's metadata survive failures. Cookies
        and other nonessential headers are deliberately not recorded.
        """
        if Path(name).name != name or name in {"", ".", ".."} or "\\" in name:
            raise ValueError("Evidence name must be a single filename")
        path = self.root / name
        metadata = self.root / f"{name}.meta.json"
        if path.exists() or metadata.exists():
            if self.reuse and path.exists() and metadata.exists():
                previous = json.loads(metadata.read_text(encoding="utf-8"))
                if (previous.get("requested_url") == url and previous.get("status") == 200
                        and previous.get("sha256") == sha256_file(path)):
                    return path
            raise AcquisitionError(f"Refusing to overwrite existing evidence: {path}")
        if any(self.root.glob(f"{name}.attempt-*")):
            raise AcquisitionError(f"Existing failed-attempt evidence for {name}; use a fresh output directory")
        for attempt in range(1, self.attempts + 1):
            record = {"requested_url": url, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                      "attempt": attempt, "status": None}
            retry = False
            delay = min(2 ** (attempt - 1), 30)
            body_path = self.root / f"{name}.attempt-{attempt}.body"
            try:
                request = Request(url, headers={"User-Agent": "HKTrafficRecoveryResearch/0.1",
                                                "Accept-Encoding": "identity"})
                with urlopen(request, timeout=self.timeout) as response:
                    record.update(status=response.status, final_url=response.url,
                                  headers={k.lower(): v for k, v in response.headers.items()
                                           if k.lower() in HEADERS})
                    with body_path.open("xb") as stream:
                        while block := response.read(1024 * 1024):
                            stream.write(block)
                if body_path.stat().st_size == 0:
                    raise AcquisitionError("Empty HTTP response")
                declared = record["headers"].get("content-length")
                if declared and int(declared) != body_path.stat().st_size:
                    raise AcquisitionError("Incomplete HTTP response")
                body_path.rename(path)
                record.update(bytes=path.stat().st_size, sha256=sha256_file(path), body=name)
            except HTTPError as exc:
                body_path.write_bytes(exc.read())
                record.update(status=exc.code, error=str(exc), body=body_path.name,
                              headers={k.lower(): v for k, v in exc.headers.items()
                                       if k.lower() in HEADERS})
                retry = exc.code == 429 or 500 <= exc.code < 600
                retry_after = exc.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    delay = min(int(retry_after), 60)
            except (URLError, TimeoutError, OSError, AcquisitionError) as exc:
                record.update(error=f"{type(exc).__name__}: {exc}")
                retry = not isinstance(exc, AcquisitionError)
            record["completed_at"] = datetime.now(timezone.utc).isoformat()
            if body_path.exists():
                record.update(body=body_path.name, bytes=body_path.stat().st_size,
                              sha256=sha256_file(body_path))
            (self.root / f"{name}.attempt-{attempt}.json").write_text(
                json.dumps(record, indent=2), encoding="utf-8")
            with (self.root / "requests.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record) + "\n")
            LOGGER.info("http_request %s", json.dumps(record))
            if "error" not in record:
                metadata.write_text(json.dumps(record, indent=2), encoding="utf-8")
                return path
            if not retry or attempt == self.attempts:
                raise AcquisitionError(f"Request failed: {url}: {record['error']}")
            time.sleep(delay)
        raise AssertionError("unreachable")

    def json(self, url: str, name: str) -> dict:
        """Fetch and validate a JSON object; preserve unexpected response bytes."""
        path = self.fetch(url, name)
        try:
            result = json.loads(path.read_bytes())
        except (ValueError, UnicodeError) as exc:
            raise AcquisitionError(f"Unexpected JSON response: {path}") from exc
        if not isinstance(result, dict):
            raise AcquisitionError(f"Expected JSON object: {path}")
        return result
