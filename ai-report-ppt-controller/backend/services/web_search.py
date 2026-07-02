from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import socket
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any


SEARCH_PROVIDER = "bing_via_chrome_cdp"
EXECUTOR_NAME = "local_web_search"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _clean_text(value: Any, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text).strip()
    return text[:limit]


def _unwrap_bing_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return url
    domain = (parsed.hostname or "").lower()
    if not domain.endswith("bing.com") or not parsed.path.startswith("/ck/"):
        return url
    encoded = urllib.parse.parse_qs(parsed.query).get("u", [""])[0]
    if not encoded:
        return url
    if encoded.startswith("a1"):
        encoded = encoded[2:]
    padding = "=" * (-len(encoded) % 4)
    try:
        decoded = base64.urlsafe_b64decode((encoded + padding).encode("ascii")).decode("utf-8", errors="replace")
    except (ValueError, OSError):
        return url
    return decoded if decoded.startswith(("http://", "https://")) else url


def _domain_from_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(_unwrap_bing_url(url))
    except ValueError:
        return ""
    return (parsed.hostname or "").lower().removeprefix("www.")


def _normalize_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(_unwrap_bing_url(url.strip()))
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    path = parsed.path or "/"
    normalized = urllib.parse.urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), path.rstrip("/") or "/", parsed.query, "")
    )
    return normalized


def _is_search_internal_url(url: str) -> bool:
    unwrapped = _unwrap_bing_url(url)
    domain = _domain_from_url(unwrapped)
    if domain.endswith("bing.com") and re.search(r"/(search|ck/|aclick)", unwrapped, flags=re.IGNORECASE):
        return True
    return False


def _looks_zh(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def _classify_source_type(url: str, title: str, snippet: str) -> tuple[str, str]:
    domain = _domain_from_url(url)
    text = f"{domain} {title} {snippet}".lower()
    paper_domains = (
        "arxiv.org",
        "doi.org",
        "nature.com",
        "ieee.org",
        "sciencedirect.com",
        "springer.com",
        "acs.org",
        "wiley.com",
        "mdpi.com",
        "pubmed.ncbi.nlm.nih.gov",
        "researchgate.net",
        "semanticscholar.org",
    )
    patent_domains = ("patents.google.com", "lens.org", "wipo.int", "uspto.gov", "cnipa.gov.cn")
    industry_domains = (
        "mckinsey.com",
        "gartner.com",
        "idc.com",
        "deloitte.com",
        "pwc.com",
        "accenture.com",
        "forrester.com",
        "bcg.com",
        "kpmg.com",
        "statista.com",
        "marketsandmarkets.com",
        "grandviewresearch.com",
        "cbinsights.com",
    )
    news_domains = (
        "reuters.com",
        "bloomberg.com",
        "wsj.com",
        "nytimes.com",
        "bbc.com",
        "bbc.co.uk",
        "cnbc.com",
        "apnews.com",
        "caixin.com",
        "yicai.com",
        "36kr.com",
    )
    official_domains = (
        ".gov",
        ".gov.cn",
        ".edu",
        "iso.org",
        "iec.ch",
        "w3.org",
        "openai.com",
        "microsoft.com",
        "google.com",
        "nvidia.com",
        "apple.com",
        "meta.com",
        "amazon.com",
    )
    if any(domain.endswith(item) or item in domain for item in patent_domains):
        return "patent", "high"
    if any(domain.endswith(item) or item in domain for item in paper_domains):
        return "paper", "high"
    if any(domain.endswith(item) or item in domain for item in industry_domains):
        return "industry_report", "high"
    if any(domain.endswith(item) or item in domain for item in news_domains):
        return "news", "high"
    if any(item in domain for item in official_domains) or "official" in text:
        return "official", "medium"
    return "unknown", "low"


class _CDPSession:
    def __init__(self, websocket_url: str, timeout: float = 10.0):
        self.websocket_url = websocket_url
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self.next_id = 1

    def __enter__(self) -> "_CDPSession":
        parsed = urllib.parse.urlparse(self.websocket_url)
        if parsed.scheme != "ws":
            raise RuntimeError(f"Unsupported Chrome websocket URL: {self.websocket_url}")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = urllib.parse.urlunparse(("", "", parsed.path or "/", "", parsed.query, ""))
        sock = socket.create_connection((host, port), timeout=self.timeout)
        sock.settimeout(self.timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = self._recv_http_response(sock)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError("Chrome CDP websocket handshake failed.")
        expected_accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        if expected_accept.encode("ascii") not in response:
            raise RuntimeError("Chrome CDP websocket handshake returned an invalid accept key.")
        self.sock = sock
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def command(self, method: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> dict[str, Any]:
        command_id = self.next_id
        self.next_id += 1
        payload = {"id": command_id, "method": method, "params": params or {}}
        self._send_frame(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        started = time.perf_counter()
        while True:
            if timeout and time.perf_counter() - started > timeout:
                raise TimeoutError(f"Chrome CDP command timed out: {method}")
            message = self._read_message()
            if message.get("id") == command_id:
                if "error" in message:
                    raise RuntimeError(f"Chrome CDP command failed: {message['error']}")
                return message

    @staticmethod
    def _recv_http_response(sock: socket.socket) -> bytes:
        chunks = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\r\n\r\n" in b"".join(chunks):
                break
        return b"".join(chunks)

    def _send_frame(self, payload: bytes, opcode: int = 1) -> None:
        if not self.sock:
            raise RuntimeError("Chrome CDP websocket is not connected.")
        length = len(payload)
        header = bytearray([0x80 | opcode])
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.extend([0x80 | 126])
            header.extend(struct.pack("!H", length))
        else:
            header.extend([0x80 | 127])
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def _read_exact(self, size: int) -> bytes:
        if not self.sock:
            raise RuntimeError("Chrome CDP websocket is not connected.")
        data = bytearray()
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise RuntimeError("Chrome CDP websocket closed unexpectedly.")
            data.extend(chunk)
        return bytes(data)

    def _read_message(self) -> dict[str, Any]:
        payload_parts = []
        while True:
            first, second = self._read_exact(2)
            fin = bool(first & 0x80)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8))[0]
            mask = self._read_exact(4) if masked else b""
            payload = self._read_exact(length) if length else b""
            if masked:
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
            if opcode == 8:
                raise RuntimeError("Chrome CDP websocket was closed.")
            if opcode == 9:
                self._send_frame(payload, opcode=10)
                continue
            if opcode in {1, 0}:
                payload_parts.append(payload)
            if fin:
                break
        text = b"".join(payload_parts).decode("utf-8", errors="replace")
        return json.loads(text)


def _http_json(url: str, method: str = "GET", timeout: float = 8.0) -> dict[str, Any]:
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    data = json.loads(raw or "{}")
    return data if isinstance(data, dict) else {}


def _new_chrome_target(chrome_host: str, chrome_port: int) -> dict[str, Any]:
    url = f"http://{chrome_host}:{chrome_port}/json/new?{urllib.parse.quote('about:blank', safe='')}"
    try:
        return _http_json(url, method="PUT", timeout=8.0)
    except urllib.error.HTTPError:
        return _http_json(url, method="GET", timeout=8.0)


def _close_chrome_target(chrome_host: str, chrome_port: int, target_id: str | None) -> None:
    if not target_id:
        return
    url = f"http://{chrome_host}:{chrome_port}/json/close/{urllib.parse.quote(target_id, safe='')}"
    try:
        urllib.request.urlopen(url, timeout=3).read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return


def _extract_results_expression() -> str:
    return r"""
(() => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const unwrapBing = (url) => {
    try {
      const parsed = new URL(url);
      if (!/bing\.com$/i.test(parsed.hostname) || !parsed.pathname.startsWith('/ck/')) return url;
      let encoded = parsed.searchParams.get('u') || '';
      if (!encoded) return url;
      if (encoded.startsWith('a1')) encoded = encoded.slice(2);
      encoded = encoded.replace(/-/g, '+').replace(/_/g, '/');
      while (encoded.length % 4) encoded += '=';
      const decoded = atob(encoded);
      return /^https?:\/\//i.test(decoded) ? decoded : url;
    } catch (err) {
      return url;
    }
  };
  const results = [];
  const push = (title, url, snippet) => {
    title = clean(title);
    url = clean(unwrapBing(url));
    snippet = clean(snippet);
    if (!title || !url || !/^https?:\/\//i.test(url)) return;
    if (/bing\.com\/(search|ck\/|aclick)/i.test(url)) return;
    results.push({title, url, snippet});
  };
  for (const node of Array.from(document.querySelectorAll('li.b_algo'))) {
    const link = node.querySelector('h2 a') || node.querySelector('a[href^="http"]');
    const snippetNode = node.querySelector('.b_caption p') || node.querySelector('p') || node.querySelector('.b_caption');
    const titleNode = node.querySelector('h2') || link;
    push((link && link.innerText) || (titleNode && titleNode.innerText) || (link && link.getAttribute('aria-label')), link && link.href, snippetNode && snippetNode.innerText);
  }
  if (!results.length) {
    for (const link of Array.from(document.querySelectorAll('a[href^="http"]'))) {
      const box = link.closest('article, li, div');
      const snippet = box ? clean(box.innerText).slice(0, 500) : '';
      if (clean(link.innerText).length >= 8) {
        push(link.innerText, link.href, snippet);
      }
    }
  }
  return results.slice(0, 12);
})()
"""


def _strip_html(value: str) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", value or "", flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return _clean_text(html.unescape(text))


def _extract_bing_http_results(raw_html: str, max_results: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    blocks = re.findall(r"<li\b[^>]*class=\"[^\"]*\bb_algo\b[^\"]*\"[^>]*>(.*?)</li>", raw_html, flags=re.IGNORECASE | re.DOTALL)
    for block in blocks:
        link_match = re.search(r"<h2\b[^>]*>.*?<a\b[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", block, flags=re.IGNORECASE | re.DOTALL)
        if not link_match:
            continue
        url = _unwrap_bing_url(html.unescape(link_match.group(1)))
        if _is_search_internal_url(url):
            continue
        title = _strip_html(link_match.group(2))
        snippet_match = re.search(r"<p\b[^>]*>(.*?)</p>", block, flags=re.IGNORECASE | re.DOTALL)
        snippet = _strip_html(snippet_match.group(1)) if snippet_match else ""
        if title and _normalize_url(url):
            results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= max_results:
            return results

    if not results:
        for href, title_html in re.findall(r"<a\b[^>]*href=\"(https?://[^\"]+)\"[^>]*>(.*?)</a>", raw_html, flags=re.IGNORECASE | re.DOTALL):
            url = _unwrap_bing_url(html.unescape(href))
            if _is_search_internal_url(url):
                continue
            title = _strip_html(title_html)
            if len(title) < 8:
                continue
            results.append({"title": title, "url": url, "snippet": ""})
            if len(results) >= max_results:
                break
    return results


def _search_url(query: str, language: str) -> str:
    params = {"q": query}
    if language == "zh":
        params["setlang"] = "zh-Hans"
    elif language == "en":
        params["setlang"] = "en-US"
    return "https://www.bing.com/search?" + urllib.parse.urlencode(params)


def _search_query_with_http(query: dict[str, Any], max_results: int, timeout: float) -> list[dict[str, Any]]:
    query_text = _clean_text(query.get("query"), limit=240)
    language = _clean_text(query.get("language") or "unknown", limit=16) or "unknown"
    url = _search_url(query_text, language)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        raw_html = response.read().decode(charset, errors="replace")
    return _extract_bing_http_results(raw_html, max_results=max_results)


def _search_query_with_chrome(
    session: _CDPSession,
    query: dict[str, Any],
    max_results: int,
    timeout: float,
) -> list[dict[str, Any]]:
    query_text = _clean_text(query.get("query"), limit=240)
    language = _clean_text(query.get("language") or "unknown", limit=16) or "unknown"
    url = _search_url(query_text, language)
    session.command("Page.navigate", {"url": url}, timeout=timeout)
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        state = session.command(
            "Runtime.evaluate",
            {"expression": "document.readyState", "returnByValue": True},
            timeout=3,
        )
        ready_state = state.get("result", {}).get("result", {}).get("value")
        if ready_state in {"interactive", "complete"}:
            break
        time.sleep(0.4)
    time.sleep(1.0)
    response = session.command(
        "Runtime.evaluate",
        {
            "expression": _extract_results_expression(),
            "returnByValue": True,
            "awaitPromise": True,
        },
        timeout=timeout,
    )
    value = response.get("result", {}).get("result", {}).get("value")
    return value[:max_results] if isinstance(value, list) else []


def _source_item(source_id: int, query: dict[str, Any], rank: int, raw: dict[str, Any], retrieved_at: str) -> dict[str, Any] | None:
    title = _clean_text(raw.get("title"), limit=240)
    url = _normalize_url(str(raw.get("url") or ""))
    if not title or not url:
        return None
    snippet = _clean_text(raw.get("snippet"), limit=700)
    domain = _domain_from_url(url)
    source_type, confidence = _classify_source_type(url, title, snippet)
    language = _clean_text(query.get("language") or "", limit=16)
    if language not in {"zh", "en"}:
        language = "zh" if _looks_zh(f"{title} {snippet}") else "unknown"
    return {
        "id": f"s{source_id:03d}",
        "query_id": query.get("id") or "",
        "query": query.get("query") or "",
        "rank": rank,
        "title": title,
        "url": url,
        "domain": domain,
        "snippet": snippet,
        "source_type": source_type,
        "published_at": None,
        "retrieved_at": retrieved_at,
        "language": language,
        "confidence": confidence,
    }


def _query_error(query: dict[str, Any], stage: str, message: str) -> dict[str, Any]:
    return {
        "query_id": query.get("id") or "",
        "query": query.get("query") or "",
        "stage": stage,
        "message": _clean_text(message, limit=500),
        "recoverable": True,
    }


def fallback_sources(
    search_plan: dict[str, Any],
    task_id: str,
    reason: str,
    stage: str = "web_search",
) -> dict[str, Any]:
    queries = search_plan.get("queries") if isinstance(search_plan, dict) else []
    if not isinstance(queries, list):
        queries = []
    error = {
        "query_id": None,
        "query": None,
        "stage": stage,
        "message": _clean_text(reason, limit=500),
        "recoverable": True,
    }
    return {
        "schema_version": "phase2.sources.v1",
        "task_id": task_id,
        "created_at": _now(),
        "search_plan_schema_version": search_plan.get("schema_version") if isinstance(search_plan, dict) else None,
        "query_count": len(queries),
        "executed_query_count": 0,
        "items": [],
        "deduplication": {
            "enabled": True,
            "input_count": 0,
            "output_count": 0,
            "removed_count": 0,
        },
        "errors": [error],
        "fallback": {
            "used": True,
            "reason": _clean_text(reason, limit=500),
        },
        "diagnostics": {
            "executor": EXECUTOR_NAME,
            "provider": SEARCH_PROVIDER,
            "network_enabled": False,
            "max_results_per_query": 0,
            "max_total_results": 0,
            "total_results": 0,
            "warnings": [_clean_text(reason, limit=500)],
        },
    }


def execute_search_plan(
    search_plan: dict[str, Any],
    task_id: str,
    chrome_host: str,
    chrome_port: int,
    max_results_per_query: int = 5,
    max_total_results: int = 40,
    per_query_timeout: float = 10.0,
) -> dict[str, Any]:
    queries = search_plan.get("queries") if isinstance(search_plan, dict) else []
    if not isinstance(queries, list) or not queries:
        return fallback_sources(search_plan, task_id, "search_plan.json does not contain executable queries.")

    created_at = _now()
    target_id = None
    try:
        _http_json(f"http://{chrome_host}:{chrome_port}/json/version", timeout=5.0)
        target = _new_chrome_target(chrome_host, chrome_port)
        target_id = target.get("id")
        websocket_url = target.get("webSocketDebuggerUrl")
        if not websocket_url:
            raise RuntimeError("Chrome target did not expose webSocketDebuggerUrl.")
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, RuntimeError) as exc:
        reason = f"Cannot initialize Chrome CDP search session at {chrome_host}:{chrome_port}: {exc}"
        sources = fallback_sources(search_plan, task_id, reason, stage="chrome_cdp")
        sources["errors"] = [_query_error(query, "chrome_cdp", reason) for query in queries]
        sources["diagnostics"]["warnings"] = [reason]
        return sources

    raw_count = 0
    executed_query_count = 0
    http_fallback_count = 0
    items: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    warnings: list[str] = []
    try:
        with _CDPSession(websocket_url, timeout=max(8.0, per_query_timeout)) as session:
            session.command("Page.enable", timeout=5)
            session.command("Runtime.enable", timeout=5)
            for query in queries:
                if len(items) >= max_total_results:
                    warnings.append("Max total source limit reached; remaining queries were not executed.")
                    break
                query_text = _clean_text(query.get("query"), limit=240)
                if not query_text:
                    errors.append(_query_error(query, "web_search", "Query text is empty."))
                    continue
                executed_query_count += 1
                try:
                    chrome_error = ""
                    try:
                        raw_results = _search_query_with_chrome(
                            session,
                            query,
                            max_results=max_results_per_query,
                            timeout=per_query_timeout,
                        )
                    except Exception as exc:  # noqa: BLE001 - HTTP fallback remains recoverable
                        chrome_error = str(exc)
                        raw_results = []
                    if not raw_results:
                        try:
                            raw_results = _search_query_with_http(
                                query,
                                max_results=max_results_per_query,
                                timeout=per_query_timeout,
                            )
                            if raw_results:
                                http_fallback_count += 1
                                warnings.append(f"HTTP search fallback used for {query.get('id') or query_text}.")
                        except Exception as exc:  # noqa: BLE001 - keep per-query failure recoverable
                            if chrome_error:
                                raise RuntimeError(f"Chrome extraction failed or returned no results: {chrome_error}; HTTP fallback failed: {exc}") from exc
                            raise
                    raw_count += len(raw_results)
                    accepted_for_query = 0
                    for rank, raw in enumerate(raw_results, start=1):
                        candidate = _source_item(len(items) + 1, query, rank, raw, _now())
                        if not candidate:
                            continue
                        key = _normalize_url(candidate["url"])
                        if key in seen_urls:
                            continue
                        seen_urls.add(key)
                        items.append(candidate)
                        accepted_for_query += 1
                        if len(items) >= max_total_results:
                            break
                    if accepted_for_query == 0:
                        errors.append(_query_error(query, "web_search", "No usable search result with both title and URL was extracted."))
                except Exception as exc:  # noqa: BLE001 - each query must fail independently
                    errors.append(_query_error(query, "web_search", str(exc)))
    except Exception as exc:  # noqa: BLE001 - keep the whole task recoverable
        errors.append(
            {
                "query_id": None,
                "query": None,
                "stage": "chrome_cdp",
                "message": _clean_text(str(exc), limit=500),
                "recoverable": True,
            }
        )
    finally:
        _close_chrome_target(chrome_host, chrome_port, target_id)

    if errors and items:
        warnings.append("Partial search failure: some queries failed or returned no usable results.")
    if not items:
        warnings.append("No usable sources were collected; see errors for recoverable failure details.")
    fallback_used = not items
    fallback_reason = "All searches failed or returned no usable results." if fallback_used else None
    return {
        "schema_version": "phase2.sources.v1",
        "task_id": task_id,
        "created_at": created_at,
        "search_plan_schema_version": search_plan.get("schema_version"),
        "query_count": len(queries),
        "executed_query_count": executed_query_count,
        "items": items,
        "deduplication": {
            "enabled": True,
            "input_count": raw_count,
            "output_count": len(items),
            "removed_count": max(0, raw_count - len(items)),
        },
        "errors": errors,
        "fallback": {
            "used": fallback_used,
            "reason": fallback_reason,
        },
        "diagnostics": {
            "executor": EXECUTOR_NAME,
            "provider": SEARCH_PROVIDER,
            "network_enabled": True,
            "chrome_host": chrome_host,
            "chrome_port": chrome_port,
            "http_fallback_count": http_fallback_count,
            "max_results_per_query": max_results_per_query,
            "max_total_results": max_total_results,
            "total_results": len(items),
            "warnings": warnings,
        },
    }
