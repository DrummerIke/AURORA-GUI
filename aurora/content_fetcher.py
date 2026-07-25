from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

ALLOWED_MIME_TYPES = {"text/html", "text/plain", "application/xhtml+xml", "application/json"}


class UnsafeUrlError(ValueError):
    pass


@dataclass(frozen=True)
class FetchedContent:
    final_url: str
    status: int
    content_type: str
    body: bytes
    resolved_ip: str


def _public_addresses(hostname: str) -> list[str]:
    addresses = sorted({item[4][0] for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)})
    if not addresses:
        raise UnsafeUrlError("hostname did not resolve")
    for value in addresses:
        address = ipaddress.ip_address(value)
        if not address.is_global:
            raise UnsafeUrlError("private or special-use destination is blocked")
    return addresses


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname: str, ip: str, port: int, timeout: float):
        super().__init__(hostname, port=port, timeout=timeout, context=ssl.create_default_context())
        self._ip = ip

    def connect(self) -> None:
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def fetch_url(url: str, *, timeout: float = 8, max_bytes: int = 1_000_000, max_redirects: int = 3) -> FetchedContent:
    current = url
    for redirect in range(max_redirects + 1):
        parsed = urlparse(current)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise UnsafeUrlError("only credential-free HTTP(S) URLs are allowed")
        ips = _public_addresses(parsed.hostname)
        ip = ips[0]
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        connection = _PinnedHTTPSConnection(parsed.hostname, ip, port, timeout) if parsed.scheme == "https" else http.client.HTTPConnection(ip, port=port, timeout=timeout)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        connection.request("GET", path, headers={"Host": parsed.netloc, "User-Agent": "AURORA/1.0", "Accept": ", ".join(sorted(ALLOWED_MIME_TYPES)), "Connection": "close"})
        response = connection.getresponse()
        if response.status in {301, 302, 303, 307, 308}:
            location = response.getheader("Location")
            connection.close()
            if not location or redirect == max_redirects:
                raise UnsafeUrlError("redirect limit exceeded")
            current = urljoin(current, location)
            continue
        content_type = (response.getheader("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type not in ALLOWED_MIME_TYPES:
            connection.close()
            raise UnsafeUrlError(f"content type is not allowed: {content_type or 'missing'}")
        length = response.getheader("Content-Length")
        if length and int(length) > max_bytes:
            connection.close()
            raise UnsafeUrlError("response is too large")
        body = response.read(max_bytes + 1)
        connection.close()
        if len(body) > max_bytes:
            raise UnsafeUrlError("response is too large")
        return FetchedContent(current, response.status, content_type, body, ip)
    raise UnsafeUrlError("redirect limit exceeded")
