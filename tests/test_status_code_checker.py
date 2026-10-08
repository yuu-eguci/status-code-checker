import io
import sys
import time
from pathlib import Path

import pytest

import status_code_checker as scc


def test_parse_urls_strips_blank_comment_and_duplicate_lines():
    text = "\n  http://a/ \r\nhttp://b/\n\n# comment\nhttp://a/\n   \n"
    assert scc.parse_urls(text) == ["http://a/", "http://b/"]


def test_classify_groups_by_status_and_does_not_follow_redirects(server):
    urls = [
        f"{server.url}/status/200",
        f"{server.url}/status/404",
        f"{server.url}/status/301",
        f"{server.url}/status/302",
        f"{server.url}/status/500",
    ]
    result = scc.classify(urls)
    assert result == {
        "200": [urls[0]],
        "404": [urls[1]],
        "301": [urls[2]],
        "302": [urls[3]],
        "500": [urls[4]],
    }
    assert "/redirected" not in server.hits


def test_classify_keeps_input_order_within_a_group(server):
    urls = [f"{server.url}/status/200?n={n}" for n in ("b", "a", "c")]
    assert scc.classify(urls) == {"200": urls}


def test_classify_workers_run_requests_in_parallel(server):
    urls = [f"{server.url}/sleep?n={n}" for n in range(4)]

    started = time.monotonic()
    result = scc.classify(urls, timeout=5, workers=4)

    assert time.monotonic() - started < 1.5  # 4 x 0.5 秒が直列なら 2 秒以上
    assert result == {"200": urls}


def test_classify_workers_keep_input_order_even_when_later_urls_finish_first(
    server,
):
    slow = f"{server.url}/sleep"
    fast = f"{server.url}/status/200"

    assert scc.classify([slow, fast], timeout=5, workers=2) == {"200": [slow, fast]}


def test_classify_reports_timeout_without_crashing(server):
    urls = [f"{server.url}/sleep", f"{server.url}/status/200"]
    result = scc.classify(urls, timeout=0.1)
    assert result == {"TIMEOUT": [urls[0]], "200": [urls[1]]}


def test_classify_reports_connection_error(closed_port):
    url = f"http://127.0.0.1:{closed_port}/"
    assert scc.classify([url]) == {"CONNECTION_ERROR": [url]}


def test_classify_reports_invalid_urls_without_requesting(server):
    urls = [
        "example.com",
        "ftp://example.com/",
        "http://",
        "not a url",
        "http://[::1/",
        "http://exa mple.com/",
        "http://localhost:99999/",
    ]
    assert scc.classify(urls) == {"INVALID_URL": urls}
    assert server.hits == []


def test_classify_sends_identifying_user_agent(server):
    url = f"{server.url}/ua"
    assert scc.classify([url]) == {"200": [url]}


def test_format_result_sorts_status_codes_then_error_groups():
    result = {
        "TIMEOUT": ["http://t/"],
        "404": ["http://n/"],
        "200": ["http://a/", "http://b/"],
        "CONNECTION_ERROR": ["http://c/"],
    }
    assert scc.format_result(result) == (
        "200\n  http://a/\n  http://b/\n"
        "404\n  http://n/\n"
        "CONNECTION_ERROR\n  http://c/\n"
        "TIMEOUT\n  http://t/"
    )


@pytest.mark.parametrize(
    ("group", "patterns", "expected"),
    [
        ("200", ["200"], True),
        ("204", ["2xx"], True),
        ("404", ["2xx", "404"], True),
        ("301", ["3xx"], True),
        ("404", ["4"], False),
        ("404", ["2xx"], False),
        ("200", ["2xx"], True),
        ("TIMEOUT", ["TIMEOUT"], True),
        ("TIMEOUT", ["2xx", "4xx"], False),
        ("200", [], False),
    ],
)
def test_matches(group, patterns, expected):
    assert scc.matches(group, patterns) is expected


def test_main_expect_exits_1_and_reports_count_when_a_url_does_not_match(
    server, tmp_path: Path, capsys
):
    urls = [f"{server.url}/status/200", f"{server.url}/status/404"]
    (tmp_path / "u.txt").write_text("\n".join(urls) + "\n", encoding="utf-8")

    code = scc.main(["--expect", "2xx", str(tmp_path / "u.txt")])

    out, err = capsys.readouterr()
    assert code == 1
    assert out == f"200\n  {urls[0]}\n404\n  {urls[1]}\n"
    assert err == "1 件の URL が --expect に合いませんでした。\n"


def test_main_expect_exits_0_when_all_urls_match(server, tmp_path: Path, capsys):
    urls = [f"{server.url}/status/200", f"{server.url}/status/404"]
    (tmp_path / "u.txt").write_text("\n".join(urls) + "\n", encoding="utf-8")

    assert scc.main(["--expect", "2xx,404", str(tmp_path / "u.txt")]) == 0
    assert capsys.readouterr().err == ""


def test_main_expect_never_matches_error_groups(closed_port, tmp_path: Path, capsys):
    (tmp_path / "u.txt").write_text(f"http://127.0.0.1:{closed_port}/\n")

    assert scc.main(["--expect", "2xx", str(tmp_path / "u.txt")]) == 1
    assert "1 件" in capsys.readouterr().err


def test_main_expect_counts_hidden_urls_too(server, tmp_path: Path, capsys):
    ok = f"{server.url}/status/200"
    missing = [f"{server.url}/status/404", f"{server.url}/status/410"]
    (tmp_path / "u.txt").write_text("\n".join([ok, *missing]) + "\n", encoding="utf-8")

    code = scc.main(["--expect", "2xx", "--only", "2xx", str(tmp_path / "u.txt")])

    out, err = capsys.readouterr()
    assert code == 1
    assert out == f"200\n  {ok}\n"
    assert err == "2 件の URL が --expect に合いませんでした。\n"


def test_main_only_and_exclude_filter_display_but_not_exit_code(
    server, closed_port, tmp_path: Path, capsys
):
    ok = f"{server.url}/status/200"
    missing = f"{server.url}/status/404"
    down = f"http://127.0.0.1:{closed_port}/"
    (tmp_path / "u.txt").write_text(f"{ok}\n{missing}\n{down}\n", encoding="utf-8")

    assert scc.main(["--only", "2xx,4xx", str(tmp_path / "u.txt")]) == 1
    assert capsys.readouterr().out == f"200\n  {ok}\n404\n  {missing}\n"

    assert scc.main(["--exclude", "CONNECTION_ERROR,200", str(tmp_path / "u.txt")]) == 1
    assert capsys.readouterr().out == f"404\n  {missing}\n"

    assert scc.main(["--only", "4xx", "--exclude", "404", str(tmp_path / "u.txt")]) == 1
    assert capsys.readouterr().out == ""


def test_main_reads_files_and_prints_groups(server, tmp_path: Path, capsys):
    ok = f"{server.url}/status/200"
    missing = f"{server.url}/status/404"
    (tmp_path / "a.txt").write_text(f"{ok}\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text(f"{missing}\n", encoding="utf-8")

    code = scc.main([str(tmp_path / "a.txt"), str(tmp_path / "b.txt")])

    assert code == 0
    assert capsys.readouterr().out == f"200\n  {ok}\n404\n  {missing}\n"


def test_main_reads_stdin_when_no_file_given(server, monkeypatch, capsys):
    ok = f"{server.url}/status/200"
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"{ok}\n"))

    assert scc.main([]) == 0
    assert capsys.readouterr().out == f"200\n  {ok}\n"


def test_main_passes_timeout_option(server, tmp_path: Path, capsys):
    slow = f"{server.url}/sleep"
    (tmp_path / "u.txt").write_text(f"{slow}\n", encoding="utf-8")

    code = scc.main(["--timeout", "0.1", str(tmp_path / "u.txt")])

    assert code == 1
    assert capsys.readouterr().out == f"TIMEOUT\n  {slow}\n"


def test_main_reads_file_with_utf8_bom(server, tmp_path: Path, capsys):
    ok = f"{server.url}/status/200"
    (tmp_path / "bom.txt").write_text(f"{ok}\n", encoding="utf-8-sig")

    assert scc.main([str(tmp_path / "bom.txt")]) == 0
    assert capsys.readouterr().out == f"200\n  {ok}\n"


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["/no/such/file.txt"], "No such file or directory: '/no/such/file.txt'"),
        (["--timeout", "0", "-"], "timeout は 0 より大きい"),
        (["--timeout", "-1", "-"], "timeout は 0 より大きい"),
        (["--timeout", "inf", "-"], "timeout は 0 より大きい"),
        (["--timeout", "nan", "-"], "timeout は 0 より大きい"),
        (["--workers", "0", "-"], "workers は 1 以上"),
        (["--workers", "1.5", "-"], "invalid"),
        (["--expect", "2x", "-"], "不正なパターンです: '2x'"),
        (["--expect", "2XX", "-"], "不正なパターンです: '2XX'"),
        (["--expect", "２００", "-"], "不正なパターンです: '２００'"),  # noqa: RUF001
        (["--expect", "", "-"], "不正なパターンです: ''"),
        (["--expect", "200,TIMEOUT", "-"], "不正なパターンです: 'TIMEOUT'"),
        (["--only", "20", "-"], "不正なパターンです: '20'"),
        (["--only", "200,", "-"], "不正なパターンです: ''"),
        (["--exclude", "timeout", "-"], "不正なパターンです: 'timeout'"),
        (["{tmp_path}/binary.txt"], "'utf-8' codec can't decode"),
    ],
)
def test_main_exits_2_on_usage_errors(argv, message, tmp_path: Path, capsys):
    (tmp_path / "binary.txt").write_bytes(b"\xff\xfe\x00http://a/\n")
    argv = [arg.format(tmp_path=tmp_path) for arg in argv]

    with pytest.raises(SystemExit) as exc:
        scc.main(argv)

    assert exc.value.code == 2
    assert message in capsys.readouterr().err


def test_main_passes_workers_option(monkeypatch, tmp_path: Path, capsys):
    (tmp_path / "u.txt").write_text("http://a/\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        scc, "classify", lambda urls, **kw: calls.append((urls, kw)) or {}
    )

    assert scc.main(["--workers", "3", str(tmp_path / "u.txt")]) == 0
    assert calls == [(["http://a/"], {"timeout": 10.0, "workers": 3})]


def test_main_exits_2_when_no_urls(tmp_path: Path, capsys):
    (tmp_path / "empty.txt").write_text("\n# nothing\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        scc.main([str(tmp_path / "empty.txt")])

    assert exc.value.code == 2
    assert "URL" in capsys.readouterr().err
