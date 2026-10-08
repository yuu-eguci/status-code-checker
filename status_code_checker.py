"""StatusCodeChecker

好きなだけ URL 書いてください。
ステータスコードごとに整理します。
リダイレクトは追いかけません (3xx はそのまま 3xx として報告します)。

    $ python status_code_checker.py urls.txt
    $ cat urls.txt | python status_code_checker.py

オプションの一覧は docs/options.md にあります。
"""

import argparse
import math
import sys
import threading
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
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


def check(session: requests.Session, url: str, timeout: float) -> str:
    """URL 1 つを調べ、ステータスコード (文字列) かエラー種別を返します。"""
    if not is_valid_url(url):
        return INVALID_URL
    try:
        with session.get(
            url, allow_redirects=False, stream=True, timeout=timeout
        ) as response:
            return str(response.status_code)
    except requests.Timeout:
        return TIMEOUT
    except requests.ConnectionError:
        return CONNECTION_ERROR
    except requests.exceptions.InvalidURL:
        return INVALID_URL
    except requests.RequestException:
        return ERROR


def classify(
    urls: Iterable[str], *, timeout: float = DEFAULT_TIMEOUT, workers: int = 1
) -> dict[str, list[str]]:
    """URL をステータスコード (またはエラー種別) ごとに分けます。

    ``workers`` 本のスレッドで同時に調べますが、結果は入力順に並びます。
    """
    local = threading.local()
    sessions: list[requests.Session] = []

    def check_with_thread_session(url: str) -> str:
        if not hasattr(local, "session"):
            local.session = requests.Session()
            local.session.headers["User-Agent"] = USER_AGENT
            sessions.append(local.session)
        return check(local.session, url, timeout)

    urls = list(urls)
    result: dict[str, list[str]] = {}
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            # workers=1 ではスレッドを使わず、Ctrl-C がすぐ効くようにします。
            run = pool.map if workers > 1 else map
            for url, group in zip(
                urls, run(check_with_thread_session, urls), strict=True
            ):
                result.setdefault(group, []).append(url)
    finally:
        for session in sessions:
            session.close()
    return result


def _group_order(group: str) -> tuple[int, int | str]:
    return (0, int(group)) if group.isdigit() else (1, group)


def format_result(result: dict[str, list[str]]) -> str:
    """ステータスコード昇順、その後にエラー種別を並べて整形します。"""
    lines = []
    for group in sorted(result, key=_group_order):
        lines.append(group)
        lines.extend(f"  {url}" for url in result[group])
    return "\n".join(lines)


def _read(name: str) -> str:
    if name == "-":
        return sys.stdin.read()
    return Path(name).read_text(encoding="utf-8-sig")


def _positive_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("timeout は 0 より大きい秒数にしてください。")
    return value


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("workers は 1 以上の整数にしてください。")
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
        type=_positive_int,
        default=1,
        help="同時に調べる URL の数 (既定: 1)",
    )
    args = parser.parse_args(argv)

    try:
        urls = parse_urls("\n".join(_read(name) for name in args.files or ["-"]))
    except (OSError, UnicodeDecodeError) as exc:
        parser.error(str(exc))
    if not urls:
        parser.error("URL がありません。")

    result = classify(urls, timeout=args.timeout, workers=args.workers)
    print(format_result(result))
    return 1 if ERROR_GROUPS & result.keys() else 0


if __name__ == "__main__":
    sys.exit(main())
