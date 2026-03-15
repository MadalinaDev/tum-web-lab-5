# go2web - A command-line HTTP client built on raw TCP sockets.
# No built-in/third-party HTTP libraries used — only raw sockets.

import sys
import socket
import ssl
from urllib.parse import urlparse

# URL helpers

def parse_url(url):
    """Return (scheme, host, port, path) from a URL string."""
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    parsed = urlparse(url)
    scheme = parsed.scheme
    host = parsed.hostname
    port = parsed.port or (443 if scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return scheme, host, port, path

# Raw-socket HTTP engine

def build_request(method, host, path):
    """Build an HTTP/1.1 request string."""
    headers = {
        "Host": host,
        "User-Agent": "go2web/1.0",
        "Accept": "*/*",
        "Accept-Encoding": "identity",
        "Connection": "close",
    }

    request = f"{method} {path} HTTP/1.1\r\n"
    for key, value in headers.items():
        request += f"{key}: {value}\r\n"
    request += "\r\n"
    return request


def send_request(scheme, host, port, path):
    """Open a TCP (+ optional TLS) connection, send the request, return raw bytes."""
    request = build_request("GET", host, path)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)

    try:
        if scheme == "https":
            context = ssl.create_default_context()
            sock = context.wrap_socket(sock, server_hostname=host)

        sock.connect((host, port))
        sock.sendall(request.encode("utf-8"))

        response = b""
        while True:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
            except socket.timeout:
                break
    finally:
        sock.close()

    return response


def decode_chunked(data):
    """Decode a chunked transfer-encoded body."""
    decoded = b""
    while data:
        line_end = data.find(b"\r\n")
        if line_end == -1:
            break

        size_str = data[:line_end].decode("utf-8", errors="replace").strip()
        if ";" in size_str:
            size_str = size_str.split(";")[0]

        try:
            chunk_size = int(size_str, 16)
        except ValueError:
            break

        if chunk_size == 0:
            break

        chunk_start = line_end + 2
        chunk_end = chunk_start + chunk_size
        decoded += data[chunk_start:chunk_end]
        data = data[chunk_end + 2:]

    return decoded


def parse_response(raw_response):
    """Split a raw HTTP response into (status_code, headers_dict, body_bytes)."""
    header_end = raw_response.find(b"\r\n\r\n")
    if header_end == -1:
        return 0, {}, b""

    header_data = raw_response[:header_end].decode("utf-8", errors="replace")
    body = raw_response[header_end + 4:]

    lines = header_data.split("\r\n")
    parts = lines[0].split(" ", 2)
    status_code = int(parts[1]) if len(parts) >= 2 else 0

    headers = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()

    if headers.get("transfer-encoding", "").lower() == "chunked":
        body = decode_chunked(body)

    return status_code, headers, body


def http_get(url):
    """Perform a simple HTTP GET and return the body as a string."""
    scheme, host, port, path = parse_url(url)
    raw = send_request(scheme, host, port, path)
    status, headers, body = parse_response(raw)

    content_type = headers.get("content-type", "")
    charset = "utf-8"
    if "charset=" in content_type:
        charset = content_type.split("charset=")[-1].split(";")[0].strip()

    return body.decode(charset, errors="replace")

# CLI

HELP_TEXT = """\
Usage: go2web [option]

Options:
  -u <URL>           Make an HTTP request to the specified URL and print the response
  -s <search-term>   Search the term using DuckDuckGo and print top 10 results
  -h                 Show this help message

Examples:
  go2web -u https://example.com
  go2web -s "python programming"
  go2web -h
"""


def main():
    args = sys.argv[1:]

    if not args or "-h" in args:
        print(HELP_TEXT)
        return

    if "-u" in args:
        idx = args.index("-u")
        if idx + 1 >= len(args):
            print("Error: -u requires a URL argument.")
            sys.exit(1)
        url = args[idx + 1]
        body = http_get(url)
        print(body)

    elif "-s" in args:
        idx = args.index("-s")
        if idx + 1 >= len(args):
            print("Error: -s requires a search term.")
            sys.exit(1)
        term = " ".join(args[idx + 1:])
        print(f"TODO: search for '{term}'")

    else:
        print("Error: Unknown option. Use -h for help.")
        sys.exit(1)


if __name__ == "__main__":
    main()
