"""StatusCodeChecker

好きなだけ URL 書いてください。
ステータスコードごとに整理します。
リダイレクトは追いかけません (3xx はそのまま 3xx として報告します)。

    $ python status_code_checker.py urls.txt
    $ cat urls.txt | python status_code_checker.py

オプションの一覧は docs/options.md にあります。
"""

import argparse
import csv
import functools
import io
import json
import math
import re
import sys
import threading
import time
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, astuple, dataclass, fields
from pathlib import Path
from urllib.parse import urlsplit

import requests

USER_AGENT = "status-code-checker"
DEFAULT_TIMEOUT = 10.0

TIMEOUT = "TIMEOUT"
CONNECTION_ERROR = "CONNECTION_ERROR"
INVALID_URL = "INVALID_URL"
ERROR = "ERROR"
ERROR_GROUPS = {TIMEOUT, CONNECTION_ERROR, INVALID_URL, ERROR}
RETRY_GROUPS = ERROR_GROUPS - {INVALID_URL}  # 調べ直しても意味がないものは除く


def parse_urls(text: str) -> list[str]:
    """1 行 1 URL のテキストを URL のリストにします。

    空行と ``#`` で始まる行は無視し、重複は最初の 1 つだけ残します。
    """
    lines = (line.strip() for line in text.splitlines())
    return list(dict.fromkeys(line for line in lines if line and line[0] != "#"))


def is_valid_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in {"http", "https"} and bool(parts.netloc)


@dataclass(frozen=True)
class Result:
    """URL 1 つの調査結果です。``group`` はステータスコードの文字列かエラー種別です。"""

    url: str
    group: str
    status: int | None = None
    location: str | None = None
    content_type: str | None = None
    elapsed_ms: int | None = None  # 応答ヘッダが届くまでの時間


def check(
    session: requests.Session, url: str, timeout: float, retry: int = 0
) -> Result:
    """URL 1 つを調べます。一時的なエラーなら ``retry`` 回まで調べ直します。"""
    result = _check_once(session, url, timeout)
    for _ in range(retry):
        if result.group not in RETRY_GROUPS:
            break
        result = _check_once(session, url, timeout)
    return result


def _check_once(session: requests.Session, url: str, timeout: float) -> Result:
    """URL 1 つを 1 回だけ調べます。本文はダウンロードしません。"""
    if not is_valid_url(url):
        return Result(url, INVALID_URL)
    started = time.perf_counter()
    try:
        with session.get(
            url, allow_redirects=False, stream=True, timeout=timeout
        ) as response:
            return Result(
                url,
                str(response.status_code),
                response.status_code,
                response.headers.get("Location"),
                response.headers.get("Content-Type"),
                _elapsed_ms(started),
            )
    except requests.Timeout:
        group = TIMEOUT
    except requests.ConnectionError:
        group = CONNECTION_ERROR
    except requests.exceptions.InvalidURL:
        return Result(url, INVALID_URL)
    except requests.RequestException:
        group = ERROR
    return Result(url, group, elapsed_ms=_elapsed_ms(started))


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def check_all(
    urls: Iterable[str],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    workers: int = 1,
    retry: int = 0,
    headers: Mapping[str, str] | None = None,
) -> list[Result]:
    """すべての URL を調べ、入力順の結果を返します。

    ``workers`` 本のスレッドで同時に調べますが、結果は入力順に並びます。
    """
    local = threading.local()
    sessions: list[requests.Session] = []

    def check_with_thread_session(url: str) -> Result:
        if not hasattr(local, "session"):
            local.session = requests.Session()
            local.session.headers["User-Agent"] = USER_AGENT
            local.session.headers.update(headers or {})
            sessions.append(local.session)
        return check(local.session, url, timeout, retry)

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            # workers=1 ではスレッドを使わず、Ctrl-C がすぐ効くようにします。
            run = pool.map if workers > 1 else map
            return list(run(check_with_thread_session, urls))
    finally:
        for session in sessions:
            session.close()


def group(results: Iterable[Result]) -> dict[str, list[Result]]:
    """結果をステータスコード (またはエラー種別) ごとに分けます。"""
    groups: dict[str, list[Result]] = {}
    for result in results:
        groups.setdefault(result.group, []).append(result)
    return groups


def matches(group: str, patterns: Iterable[str]) -> bool:
    """グループが ``200`` / ``4xx`` / ``TIMEOUT`` 形式のパターンのどれかに合うか。"""
    return any(
        group == pattern
        or (pattern.endswith("xx") and group.isdigit() and group[0] == pattern[0])
        for pattern in patterns
    )


def _group_order(group: str) -> tuple[int, int | str]:
    return (0, int(group)) if group.isdigit() else (1, group)


def _details(result: Result) -> list[str]:
    details = []
    if result.elapsed_ms is not None:
        details.append(f"{result.elapsed_ms}ms")
    if result.content_type is not None:
        details.append(result.content_type)
    if result.location is not None:
        details.append(f"-> {result.location}")
    return details


def format_result(groups: dict[str, list[Result]], *, verbose: bool = False) -> str:
    """ステータスコード昇順、その後にエラー種別を並べて整形します。"""
    lines = []
    for name in sorted(groups, key=_group_order):
        lines.append(name)
        for result in groups[name]:
            details = _details(result) if verbose else []
            lines.append("  ".join(["", result.url, *details]))
    return "\n".join(lines)


def format_json(results: Iterable[Result]) -> str:
    """入力順に 1 URL 1 レコードの JSON にします (docs/options.md 参照)。"""
    payload = {"schema": 1, "results": [asdict(result) for result in results]}
    return json.dumps(payload, ensure_ascii=False, indent=2)


def format_csv(results: Iterable[Result]) -> str:
    """見出し行付きの CSV にします。分からない項目は空欄です。"""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(field.name for field in fields(Result))
    writer.writerows(astuple(result) for result in results)
    return buffer.getvalue()


def _read(name: str) -> str:
    if name == "-":
        return sys.stdin.read()
    return Path(name).read_text(encoding="utf-8-sig")


def _positive_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("timeout は 0 より大きい秒数にしてください。")
    return value


CODE_PATTERN = r"[0-9]{3}|[0-9]xx"
GROUP_PATTERN = CODE_PATTERN + "|" + "|".join(sorted(ERROR_GROUPS))


def _patterns(text: str, *, allowed: str) -> list[str]:
    patterns = [pattern.strip() for pattern in text.split(",")]
    for pattern in patterns:
        if not re.fullmatch(allowed, pattern):
            raise argparse.ArgumentTypeError(f"不正なパターンです: {pattern!r}")
    return patterns


def _header(text: str) -> tuple[str, str]:
    name, colon, value = text.partition(":")
    if (
        not colon
        or not name.strip()
        or not text.isascii()
        or "\n" in text
        or "\r" in text
    ):
        raise argparse.ArgumentTypeError(f"不正なヘッダです: {text!r}")
    return name.strip(), value.strip()


def _int_at_least(text: str, *, minimum: int, name: str) -> int:
    value = int(text)
    if value < minimum:
        raise argparse.ArgumentTypeError(
            f"{name} は {minimum} 以上の整数にしてください。"
        )
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "URL を HTTP ステータスコードごとに整理します (リダイレクトは追いません)。"
        ),
    )
    parser.add_argument(
        "files",
        nargs="*",
        metavar="FILE",
        help="1 行 1 URL のファイル。省略または '-' で標準入力を読みます。",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_float,
        default=DEFAULT_TIMEOUT,
        help=f"1 URL あたりの接続・読み取りタイムアウト秒 (既定: {DEFAULT_TIMEOUT:g})",
    )
    parser.add_argument(
        "--workers",
        type=functools.partial(_int_at_least, minimum=1, name="workers"),
        default=1,
        help="同時に調べる URL の数 (既定: 1)",
    )
    parser.add_argument(
        "--retry",
        type=functools.partial(_int_at_least, minimum=0, name="retry"),
        default=0,
        help="一時的なエラーになった URL を調べ直す回数 (既定: 0)",
    )
    parser.add_argument(
        "--header",
        type=_header,
        action="append",
        default=[],
        metavar="'NAME: VALUE'",
        help="すべてのリクエストに付けるヘッダ (複数可)",
    )
    parser.add_argument(
        "--expect",
        type=functools.partial(_patterns, allowed=CODE_PATTERN),
        metavar="PATTERNS",
        help="期待するコード (例: 200,3xx)。合わない URL があれば終了コード 1",
    )
    parser.add_argument(
        "--only",
        type=functools.partial(_patterns, allowed=GROUP_PATTERN),
        default=[],
        metavar="PATTERNS",
        help="表示するグループ (例: 4xx,5xx,TIMEOUT)",
    )
    parser.add_argument(
        "--exclude",
        type=functools.partial(_patterns, allowed=GROUP_PATTERN),
        default=[],
        metavar="PATTERNS",
        help="表示しないグループ (例: 200)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="各 URL に応答時間、Content-Type、Location を添えます",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json", "csv"],
        default="text",
        help="出力形式 (既定: text)",
    )
    args = parser.parse_args(argv)

    try:
        urls = parse_urls("\n".join(_read(name) for name in args.files or ["-"]))
    except (OSError, UnicodeDecodeError) as exc:
        parser.error(str(exc))
    if not urls:
        parser.error("URL がありません。")

    results = check_all(
        urls,
        timeout=args.timeout,
        workers=args.workers,
        retry=args.retry,
        headers=dict(args.header),
    )
    shown = [
        result
        for result in results
        if (not args.only or matches(result.group, args.only))
        and not matches(result.group, args.exclude)
    ]
    if args.format == "json":
        print(format_json(shown))
    elif args.format == "csv":
        print(format_csv(shown), end="")
    elif shown:
        print(format_result(group(shown), verbose=args.verbose))

    unexpected = 0
    if args.expect is not None:
        unexpected = sum(
            1 for result in results if not matches(result.group, args.expect)
        )
        if unexpected:
            print(
                f"{unexpected} 件の URL が --expect に合いませんでした。",
                file=sys.stderr,
            )
    failed = any(result.group in ERROR_GROUPS for result in results)
    return 1 if unexpected or failed else 0


if __name__ == "__main__":
    sys.exit(main())
