# go2web - A command-line HTTP client built on raw TCP sockets.
# No built-in/third-party HTTP libraries used — only raw sockets.

import sys
import socket
import ssl
import re
import json
import os
import hashlib
import time
from urllib.parse import urlparse, quote_plus, parse_qs

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

# Constants
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".go2web_cache")
CACHE_TTL = 300  # seconds (5 minutes)

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
        "Accept": "text/html, application/json, text/plain;q=0.9, */*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
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

# HTTP cache (file-based, JSON)

def _cache_path(url):
    key = hashlib.md5(url.encode()).hexdigest()
    return os.path.join(CACHE_DIR, key + ".json")


def cache_get(url):
    """Return cached (body, content_type) tuple or None."""
    filepath = _cache_path(url)
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        if time.time() - data.get("timestamp", 0) < CACHE_TTL:
            return (data.get("body"), data.get("content_type", ""))
    except (json.JSONDecodeError, OSError):
        pass
    return None


def cache_set(url, body, content_type):
    """Persist a response body and content_type to disk."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    filepath = _cache_path(url)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump({"timestamp": time.time(), "body": body, "content_type": content_type}, f)
    except OSError:
        pass


def http_get(url, max_redirects=10):
    """Perform an HTTP GET with redirect following. Returns (body, content_type) tuple."""
    visited = set()

    for _ in range(max_redirects):
        scheme, host, port, path = parse_url(url)

        if url in visited:
            print("Error: Redirect loop detected.")
            return None, ""
        visited.add(url)

        # Cache lookup
        cached = cache_get(url)
        if cached is not None:
            print(f"[Cache hit for {url}]")
            return cached

        raw = send_request(scheme, host, port, path)
        status, headers, body = parse_response(raw)

        # Follow redirects
        if status in (301, 302, 303, 307, 308) and "location" in headers:
            redirect_url = headers["location"]
            if redirect_url.startswith("/"):
                redirect_url = f"{scheme}://{host}{redirect_url}"
            elif not redirect_url.startswith("http"):
                redirect_url = f"{scheme}://{host}/{redirect_url}"
            print(f"[Redirect {status} -> {redirect_url}]")
            url = redirect_url
            continue

        content_type = headers.get("content-type", "")
        charset = "utf-8"
        if "charset=" in content_type:
            charset = content_type.split("charset=")[-1].split(";")[0].strip()

        body_text = body.decode(charset, errors="replace")
        cache_set(url, body_text, content_type)
        return body_text, content_type

    print("Error: Too many redirects.")
    return None, ""

# Content rendering

def html_to_text(html_content):
    """Convert an HTML document to readable plain text."""
    if HAS_BS4:
        soup = BeautifulSoup(html_content, "html.parser")
        for tag in soup(["script", "style", "noscript", "head"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
    else:
        import html as html_mod
        text = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', '', text)
        text = html_mod.unescape(text)

    lines = [line.strip() for line in text.splitlines()]
    lines = [l for l in lines if l]
    return "\n".join(lines)


def format_response(body, content_type=""):
    """Return a human-readable string based on the content type."""
    if body is None:
        return "Error: No response received."

    if "application/json" in content_type:
        try:
            parsed = json.loads(body)
            return json.dumps(parsed, indent=2, ensure_ascii=False)
        except json.JSONDecodeError:
            return body
    elif "text/html" in content_type:
        return html_to_text(body)
    else:
        return html_to_text(body)

# Search functionality (DuckDuckGo HTML)

def search(term):
    """Query DuckDuckGo's HTML endpoint and return up to 10 results."""
    query = quote_plus(term)
    url = f"https://html.duckduckgo.com/html/?q={query}"

    body = http_get(url)
    results = []

    if body[0] is None:
        print("Error: Could not perform search.")
        return []

    body_text = body[0]
    if HAS_BS4:
        soup = BeautifulSoup(body_text, "html.parser")
        for link in soup.select("a.result__a"):
            title = link.get_text(strip=True)
            href = link.get("href", "")
            # DuckDuckGo wraps real URLs inside an "uddg" query parameter
            if "uddg=" in href:
                qs = parse_qs(urlparse(href).query)
                if "uddg" in qs:
                    href = qs["uddg"][0]
            if title and href:
                results.append({"title": title, "url": href})
            if len(results) >= 10:
                break
    else:
        pattern = r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>'
        matches = re.findall(pattern, body_text, re.DOTALL)
        for href, title in matches[:10]:
            clean_title = re.sub(r'<[^>]+>', '', title).strip()
            results.append({"title": clean_title, "url": href})

    return results


def print_search_results(results):
    """Display search results and optionally let the user open one."""
    if not results:
        print("No results found.")
        return

    for i, r in enumerate(results, 1):
        print(f"\n{i}. {r['title']}")
        print(f"   {r['url']}")

    print("\n" + "-" * 50)
    print("Enter a result number to open it, or press Enter / 'q' to quit:")

    while True:
        try:
            choice = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if choice.lower() in ("q", ""):
            break

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(results):
                target_url = results[idx]["url"]
                print(f"\nFetching: {target_url}\n")
                body, ct = http_get(target_url)
                print(format_response(body, ct))
            else:
                print("Invalid number. Try again or 'q' to quit.")
        except ValueError:
            print("Enter a number or 'q'.")

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
        body, content_type = http_get(url)
        print(format_response(body, content_type))

    elif "-s" in args:
        idx = args.index("-s")
        if idx + 1 >= len(args):
            print("Error: -s requires a search term.")
            sys.exit(1)
        term = " ".join(args[idx + 1:])
        results = search(term)
        print_search_results(results)

    else:
        print("Error: Unknown option. Use -h for help.")
        sys.exit(1)


if __name__ == "__main__":
    main()
