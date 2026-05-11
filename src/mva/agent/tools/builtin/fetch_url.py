"""``fetch_url`` tool — fetch content from HTTP(S) URLs."""

from __future__ import annotations

from typing import Any

import requests

from mva.agent.tools.base import SecurityCheck, Tool, ToolResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_RESPONSE_BYTES = 512 * 1024  # 512 KB
_DEFAULT_TIMEOUT = 30  # seconds

# Blocked schemes for SSRF prevention
_BLOCKED_SCHEMES = (
    "file",
    "dict",
    "gopher",
    "tftp",
    "ftp",
)


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class FetchUrlTool(Tool):
    name = "fetch_url"
    description = (
        "Fetch content from an HTTP or HTTPS URL and return the response "
        f"body. Responses are limited to {_MAX_RESPONSE_BYTES // 1024}KB. "
        "Useful for reading API responses, web pages, documentation, "
        "or any publicly accessible URL content."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "HTTP or HTTPS URL to fetch",
            },
            "timeout": {
                "type": "number",
                "description": "Request timeout in seconds (default: 30)",
            },
            "headers": {
                "type": "object",
                "description": (
                    "Optional HTTP headers as key-value pairs "
                    "(e.g. {\"Authorization\": \"Bearer token\"})"
                ),
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["url"],
    }
    prompt_snippet = "Fetch content from a URL"

    def check_security(self, url: str, **kwargs: Any) -> SecurityCheck | None:
        """Block non-HTTP schemes and private/internal IPs to prevent SSRF."""
        # -- Block dangerous schemes -------------------------------------------
        scheme = url.split("://")[0].lower() if "://" in url else "http"
        if scheme in _BLOCKED_SCHEMES:
            return SecurityCheck(
                safe=False,
                message=f"Blocked URL scheme '{scheme}://' — only http/https allowed",
                offending_path=url,
            )

        code = 200
        # -- Check for private/internal addresses ------------------------------
        # Extract hostname (rough but good enough for security gating)
        try:
            host = url.split("://", 1)[1].split("/")[0].split(":")[0]
        except IndexError:
            return SecurityCheck(
                safe=False,
                message=f"Could not parse hostname from URL: '{url}'",
                offending_path=url,
            )

        # Check for private / loopback IPs
        if _is_private_or_loopback(host):
            return SecurityCheck(
                safe=False,
                message=(
                    f"URL resolves to a private or loopback address '{host}'.\n"
                    "  Use a fetch_url tool to access internal services?"
                ),
                offending_path=url,
            )

        # Check for localhost-like hostnames
        if host.lower() in ("localhost", "localhost.localdomain", "127.0.0.1", "::1"):
            return SecurityCheck(
                safe=False,
                message=f"URL points to localhost ('{host}'). Use a fetch_url tool?",
                offending_path=url,
            )

        return None

    def execute(
        self,
        url: str,
        timeout: float | None = None,
        headers: dict[str, str] | None = None,
        _confirmed: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        _timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT
        _headers = headers or {}

        # Set a sensible User-Agent
        if "User-Agent" not in _headers:
            _headers["User-Agent"] = "MVA/1.0 (+https://github.com/ldang/mva)"

        try:
            # Stream so we can enforce the size limit
            with requests.get(
                url,
                headers=_headers,
                timeout=_timeout,
                stream=True,
                allow_redirects=True,
            ) as resp:
                content_chunks: list[bytes] = []
                total = 0
                truncated = False

                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if total + len(chunk) > _MAX_RESPONSE_BYTES:
                        allowed = _MAX_RESPONSE_BYTES - total
                        if allowed > 0:
                            content_chunks.append(chunk[:allowed])
                        truncated = True
                        break
                    content_chunks.append(chunk)
                    total += len(chunk)

                body_bytes = b"".join(content_chunks)

        except requests.exceptions.Timeout:
            return ToolResult(
                content=f"Request timed out after {_timeout}s: '{url}'",
                is_error=True,
            )
        except requests.exceptions.ConnectionError as exc:
            return ToolResult(
                content=f"Connection error for '{url}': {exc}",
                is_error=True,
            )
        except requests.exceptions.TooManyRedirects:
            return ToolResult(
                content=f"Too many redirects fetching '{url}'",
                is_error=True,
            )
        except requests.exceptions.RequestException as exc:
            return ToolResult(
                content=f"Request failed for '{url}': {exc}",
                is_error=True,
            )
        except Exception as exc:
            return ToolResult(
                content=f"Unexpected error fetching '{url}': {exc}",
                is_error=True,
            )

        # Try UTF-8 text first; fall back to latin-1
        try:
            body = body_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                body = body_bytes.decode("latin-1")
            except Exception:
                body = body_bytes.decode("utf-8", errors="replace")

        # Build the response summary
        lines: list[str] = []

        # Status line
        lines.append(f"[Status {resp.status_code} {resp.reason}]")

        # Content type
        ct = resp.headers.get("Content-Type", "unknown")
        lines.append(f"[Content-Type: {ct}]")
        lines.append(f"[Content-Length: {resp.headers.get('Content-Length', 'unknown')}]")

        # Final URL after redirects
        if resp.url != url:
            lines.append(f"[Redirected to: {resp.url}]")

        if truncated:
            lines.append(
                f"[Response truncated — showing {_MAX_RESPONSE_BYTES // 1024}KB "
                f"of {resp.headers.get('Content-Length', 'unknown')} bytes]"
            )

        lines.append("")
        lines.append(body)

        is_error = resp.status_code >= 400

        return ToolResult(content="\n".join(lines), is_error=is_error)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_PRIVATE_PREFIXES = (
    "10.",
    "172.16.",
    "172.17.",
    "172.18.",
    "172.19.",
    "172.20.",
    "172.21.",
    "172.22.",
    "172.23.",
    "172.24.",
    "172.25.",
    "172.26.",
    "172.27.",
    "172.28.",
    "172.29.",
    "172.30.",
    "172.31.",
    "192.168.",
)


def _is_private_or_loopback(host: str) -> bool:
    """Heuristic check for private / loopback IP addresses.

    This is a string-based check — it does NOT perform DNS resolution,
    so it won't catch hostnames that *resolve* to private IPs.
    Full SSRF prevention would require a DNS-resolve + IP-range check
    at runtime, which adds latency and complexity.
    """
    host = host.strip().lower()

    # IPv6 loopback
    if host == "::1":
        return True

    # Strip brackets for IPv6 literals
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]

    # Loopback
    if host == "127.0.0.1":
        return True

    # Private ranges
    if host.startswith(_PRIVATE_PREFIXES):
        return True

    # Link-local
    if host.startswith("169.254."):
        return True

    return False
