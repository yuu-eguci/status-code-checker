import io
import json
import re
import sys
import time
import tomllib
from pathlib import Path

import pytest

import status_code_checker as scc


def classify(urls, **kwargs):
    """旧 API と同じ {グループ: [URL]} を作るテスト用ヘルパーです。"""
    groups = scc.group(scc.check_all(urls, **kwargs))
    return {
        name: [result.url for result in results] for name, results in groups.items()
    }


def test_version_matches_pyproject_and_console_script_points_at_main(capsys):
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert scc.__version__ == pyproject["project"]["version"]
    assert pyproject["project"]["scripts"] == {
        "status-code-checker": "status_code_checker:main"
    }

    with pytest.raises(SystemExit) as exc:
        scc.main(["--version"])

    assert exc.value.code == 0
    assert capsys.readouterr().out == f"status-code-checker {scc.__version__}\n"


def test_parse_urls_strips_blank_comment_and_duplicate_lines():
    text = "\n  http://a/ \r\nhttp://b/\n\n# comment\nhttp://a/\n   \n"
    assert scc.parse_urls(text) == ["http://a/", "http://b/"]


def test_check_all_groups_by_status_and_does_not_follow_redirects(server):
    urls = [
        f"{server.url}/status/200",
        f"{server.url}/status/404",
        f"{server.url}/status/301",
        f"{server.url}/status/302",
        f"{server.url}/status/500",
    ]
    result = classify(urls)
    assert result == {
        "200": [urls[0]],
        "404": [urls[1]],
        "301": [urls[2]],
        "302": [urls[3]],
        "500": [urls[4]],
    }
    assert "/redirected" not in server.hits


def test_check_all_keeps_input_order_within_a_group(server):
    urls = [f"{server.url}/status/200?n={n}" for n in ("b", "a", "c")]
    assert classify(urls) == {"200": urls}


def test_check_all_workers_run_requests_in_parallel(server):
    urls = [f"{server.url}/sleep?n={n}" for n in range(4)]

    started = time.monotonic()
    result = classify(urls, timeout=5, workers=4)

    assert time.monotonic() - started < 1.5  # 4 x 0.5 秒が直列なら 2 秒以上
    assert result == {"200": urls}


def test_check_all_workers_keep_input_order_even_when_later_urls_finish_first(
    server,
):
    slow = f"{server.url}/sleep"
    fast = f"{server.url}/status/200"

    assert classify([slow, fast], timeout=5, workers=2) == {"200": [slow, fast]}


def test_check_all_retries_transient_errors_up_to_the_given_count(server):
    flaky = f"{server.url}/flaky/2"

    assert classify([flaky], retry=1) == {"CONNECTION_ERROR": [flaky]}
    assert server.hits.count("/flaky/2") == 2

    server.attempts.clear()
    server.hits.clear()
    assert classify([flaky], retry=2) == {"200": [flaky]}
    assert server.hits.count("/flaky/2") == 3


def test_check_all_stops_retrying_once_a_response_arrives(server):
    flaky = f"{server.url}/flaky/1"

    assert classify([flaky], retry=3) == {"200": [flaky]}
    assert server.hits.count("/flaky/1") == 2


def test_check_all_retries_timeouts(server):
    slow = f"{server.url}/sleep"

    assert classify([slow], timeout=0.1, retry=1) == {"TIMEOUT": [slow]}
    assert server.hits.count("/sleep") == 2


def test_check_all_does_not_retry_responses_or_invalid_urls(server):
    failing = f"{server.url}/status/503"

    assert classify([failing, "nope"], retry=3) == {
        "503": [failing],
        "INVALID_URL": ["nope"],
    }
    assert server.hits == ["/status/503"]


def test_check_all_reports_timeout_without_crashing(server):
    urls = [f"{server.url}/sleep", f"{server.url}/status/200"]
    results = scc.check_all(urls, timeout=0.1)

    assert [r.group for r in results] == ["TIMEOUT", "200"]
    assert results[0].elapsed_ms >= 100


def test_check_all_reports_connection_error(closed_port):
    url = f"http://127.0.0.1:{closed_port}/"
    assert classify([url]) == {"CONNECTION_ERROR": [url]}


def test_check_all_reports_invalid_urls_without_requesting(server):
    urls = [
        "example.com",
        "ftp://example.com/",
        "http://",
        "not a url",
        "http://[::1/",
        "http://exa mple.com/",
        "http://localhost:99999/",
    ]
    assert classify(urls) == {"INVALID_URL": urls}
    assert server.hits == []


def test_header_option_splits_on_first_colon_and_strips():
    assert scc._header(" Authorization : Basic a:b ") == ("Authorization", "Basic a:b")


def test_check_all_uses_get_by_default_and_head_on_request(server):
    url = f"{server.url}/status/204"

    assert classify([url]) == {"204": [url]}
    assert classify([url], method="HEAD") == {"204": [url]}
    assert server.methods == ["GET", "HEAD"]


def test_check_all_keeps_head_across_retries_and_still_sees_location(server):
    flaky = f"{server.url}/flaky/1"
    moved = f"{server.url}/status/301"

    results = scc.check_all([flaky, moved], retry=1, method="HEAD")

    assert [r.group for r in results] == ["200", "301"]
    assert results[1].location == "/redirected"
    assert server.methods == ["HEAD", "HEAD", "HEAD"]


def test_check_all_sends_extra_headers(server):
    url = f"{server.url}/need-auth"

    assert classify([url]) == {"401": [url]}
    assert classify([url], headers={"Authorization": "Bearer secret"}) == {"200": [url]}


def test_check_all_sends_identifying_user_agent(server):
    url = f"{server.url}/ua"
    assert classify([url]) == {"200": [url]}


def test_format_result_sorts_status_codes_then_error_groups():
    result = {
        "TIMEOUT": [scc.Result("http://t/", "TIMEOUT")],
        "404": [scc.Result("http://n/", "404")],
        "200": [scc.Result("http://a/", "200"), scc.Result("http://b/", "200")],
        "CONNECTION_ERROR": [scc.Result("http://c/", "CONNECTION_ERROR")],
    }
    assert scc.format_result(result) == (
        "200\n  http://a/\n  http://b/\n"
        "404\n  http://n/\n"
        "CONNECTION_ERROR\n  http://c/\n"
        "TIMEOUT\n  http://t/"
    )


def test_format_summary_counts_urls_in_the_same_order_as_text_output():
    result = {
        "TIMEOUT": [scc.Result("http://t/", "TIMEOUT")],
        "404": [scc.Result("http://n/", "404")],
        "200": [scc.Result("http://a/", "200"), scc.Result("http://b/", "200")],
    }
    assert scc.format_summary(result) == "200: 2\n404: 1\nTIMEOUT: 1"


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


def test_check_all_collects_metadata(server, closed_port):
    ok = f"{server.url}/status/200"
    moved = f"{server.url}/status/301"
    down = f"http://127.0.0.1:{closed_port}/"

    bad_port = "http://localhost:99999/"

    results = scc.check_all([ok, moved, down, "nope", bad_port])

    assert [r.url for r in results] == [ok, moved, down, "nope", bad_port]
    assert results[0].status == 200
    assert results[0].location is None
    assert results[0].content_type == "text/plain"
    assert isinstance(results[0].elapsed_ms, int) and results[0].elapsed_ms >= 0
    assert (results[1].status, results[1].location) == (301, "/redirected")
    assert (results[2].group, results[2].status, results[2].content_type) == (
        "CONNECTION_ERROR",
        None,
        None,
    )
    assert isinstance(results[2].elapsed_ms, int)
    assert results[3] == scc.Result("nope", "INVALID_URL")
    assert results[4] == scc.Result(bad_port, "INVALID_URL")


def test_format_result_verbose_appends_known_metadata():
    result = {
        "200": [
            scc.Result(
                "http://a/", "200", status=200, content_type="text/html", elapsed_ms=12
            )
        ],
        "301": [
            scc.Result("http://m/", "301", status=301, location="/new", elapsed_ms=7)
        ],
        "TIMEOUT": [scc.Result("http://t/", "TIMEOUT", elapsed_ms=10002)],
        "INVALID_URL": [scc.Result("nope", "INVALID_URL")],
    }
    assert scc.format_result(result, verbose=True) == (
        "200\n  http://a/  12ms  text/html\n"
        "301\n  http://m/  7ms  -> /new\n"
        "INVALID_URL\n  nope\n"
        "TIMEOUT\n  http://t/  10002ms"
    )


SAMPLE_RESULTS = [
    scc.Result("http://a/", "200", status=200, content_type="text/html", elapsed_ms=12),
    scc.Result("http://m/", "301", status=301, location="/new", elapsed_ms=7),
    scc.Result("http://t/", "TIMEOUT", elapsed_ms=10002),
    scc.Result("nope", "INVALID_URL"),
    scc.Result('http://q/?a=1,2&b="x"', "200", status=200),
]


def test_format_json_keeps_input_order_and_nulls():
    assert json.loads(scc.format_json(SAMPLE_RESULTS)) == {
        "schema": 1,
        "results": [
            {
                "url": "http://a/",
                "group": "200",
                "status": 200,
                "location": None,
                "content_type": "text/html",
                "elapsed_ms": 12,
            },
            {
                "url": "http://m/",
                "group": "301",
                "status": 301,
                "location": "/new",
                "content_type": None,
                "elapsed_ms": 7,
            },
            {
                "url": "http://t/",
                "group": "TIMEOUT",
                "status": None,
                "location": None,
                "content_type": None,
                "elapsed_ms": 10002,
            },
            {
                "url": "nope",
                "group": "INVALID_URL",
                "status": None,
                "location": None,
                "content_type": None,
                "elapsed_ms": None,
            },
            {
                "url": 'http://q/?a=1,2&b="x"',
                "group": "200",
                "status": 200,
                "location": None,
                "content_type": None,
                "elapsed_ms": None,
            },
        ],
    }
    assert json.loads(scc.format_json([])) == {"schema": 1, "results": []}


def test_format_csv_has_header_and_blank_cells():
    assert scc.format_csv(SAMPLE_RESULTS) == (
        "url,group,status,location,content_type,elapsed_ms\n"
        "http://a/,200,200,,text/html,12\n"
        "http://m/,301,301,/new,,7\n"
        "http://t/,TIMEOUT,,,,10002\n"
        "nope,INVALID_URL,,,,\n"
        '"http://q/?a=1,2&b=""x""",200,200,,,\n'
    )
    assert scc.format_csv([]) == "url,group,status,location,content_type,elapsed_ms\n"


def test_main_format_json_applies_filters_and_expect(
    server, closed_port, tmp_path: Path, capsys
):
    ok = f"{server.url}/status/200"
    missing = f"{server.url}/status/404"
    down = f"http://127.0.0.1:{closed_port}/"
    (tmp_path / "u.txt").write_text(f"{ok}\n{missing}\n{down}\n", encoding="utf-8")

    options = ["--format", "json", "--exclude", "CONNECTION_ERROR", "--expect", "2xx"]
    code = scc.main([*options, str(tmp_path / "u.txt")])

    out, err = capsys.readouterr()
    assert code == 1
    assert err == "2 件の URL が --expect に合いませんでした。\n"
    assert [(r["url"], r["status"]) for r in json.loads(out)["results"]] == [
        (ok, 200),
        (missing, 404),
    ]


def test_main_format_csv(server, tmp_path: Path, capsys):
    moved = f"{server.url}/status/301"
    (tmp_path / "u.txt").write_text(f"{moved}\n", encoding="utf-8")

    assert scc.main(["--format", "csv", str(tmp_path / "u.txt")]) == 0
    assert re.fullmatch(
        "url,group,status,location,content_type,elapsed_ms\n"
        f"{re.escape(moved)},301,301,/redirected,text/plain,\\d+\n",
        capsys.readouterr().out,
    )


def test_format_diff_lists_changed_added_and_removed_urls():
    previous = {"http://same/": "200", "http://old/": "200", "http://gone/": "301"}
    results = [
        scc.Result("http://same/", "200"),
        scc.Result("http://old/", "404"),
        scc.Result("http://new/", "TIMEOUT"),
    ]
    assert scc.format_diff(previous, results) == (
        "CHANGED\n  http://old/: 200 -> 404\n"
        "ADDED\n  http://new/: TIMEOUT\n"
        "REMOVED\n  http://gone/: 301"
    )
    assert scc.format_diff({"http://same/": "200"}, results[:1]) == ""


def test_main_diff_compares_with_a_saved_json_run(server, tmp_path: Path, capsys):
    flaky = f"{server.url}/flaky/1"  # 1 回目は切断、2 回目から 200
    gone = f"{server.url}/status/404"
    new = f"{server.url}/status/301"
    (tmp_path / "before.txt").write_text(f"{flaky}\n{gone}\n", encoding="utf-8")
    (tmp_path / "after.txt").write_text(f"{flaky}\n{new}\n", encoding="utf-8")

    assert scc.main(["--format", "json", str(tmp_path / "before.txt")]) == 1
    (tmp_path / "last.json").write_text(capsys.readouterr().out, encoding="utf-8")

    code = scc.main(
        ["--diff", str(tmp_path / "last.json"), str(tmp_path / "after.txt")]
    )

    assert code == 0
    assert capsys.readouterr().out == (
        f"CHANGED\n  {flaky}: CONNECTION_ERROR -> 200\n"
        f"ADDED\n  {new}: 301\n"
        f"REMOVED\n  {gone}: 404\n"
    )

    (tmp_path / "last.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "results": [
                    {"url": flaky, "group": "200"},
                    {"url": new, "group": "301"},
                ],
            }
        )
    )
    assert (
        scc.main(["--diff", str(tmp_path / "last.json"), str(tmp_path / "after.txt")])
        == 0
    )
    assert capsys.readouterr().out == ""


def test_main_diff_ignores_filters_and_keeps_exit_code(server, tmp_path: Path, capsys):
    ok = f"{server.url}/status/200"
    (tmp_path / "last.json").write_text(
        json.dumps({"schema": 1, "results": [{"url": ok, "group": "200"}]})
    )
    (tmp_path / "u.txt").write_text(f"{ok}\nnope\n", encoding="utf-8")
    options = ["--diff", str(tmp_path / "last.json"), "--only", "200", "-v"]

    assert scc.main([*options, str(tmp_path / "u.txt")]) == 1
    assert capsys.readouterr().out == "ADDED\n  nope: INVALID_URL\n"


def test_main_summary_applies_filters_ignores_verbose_and_keeps_exit_code(
    server, tmp_path: Path, capsys
):
    ok = f"{server.url}/status/200"
    (tmp_path / "u.txt").write_text(
        f"{ok}\n{ok}?2\n{server.url}/status/404\n{server.url}/status/500\nnope\n",
        encoding="utf-8",
    )
    options = ["--summary", "--exclude", "5xx", "-v", "--expect", "2xx"]

    assert scc.main([*options, str(tmp_path / "u.txt")]) == 1
    captured = capsys.readouterr()
    assert captured.out == "200: 2\n404: 1\nINVALID_URL: 1\n"
    assert "3 件の URL が --expect に合いませんでした。" in captured.err


def test_main_summary_prints_nothing_when_everything_is_filtered(
    server, tmp_path: Path, capsys
):
    (tmp_path / "u.txt").write_text(f"{server.url}/status/200\n", encoding="utf-8")

    assert scc.main(["--summary", "--only", "4xx", str(tmp_path / "u.txt")]) == 0
    assert capsys.readouterr().out == ""


def test_main_verbose_option(server, tmp_path: Path, capsys):
    moved = f"{server.url}/status/302"
    (tmp_path / "u.txt").write_text(f"{moved}\n", encoding="utf-8")

    assert scc.main(["-v", str(tmp_path / "u.txt")]) == 0
    assert re.fullmatch(
        f"302\n  {re.escape(moved)}  \\d+ms  text/plain  -> /redirected\n",
        capsys.readouterr().out,
    )


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
        (["--retry", "-1", "-"], "retry は 0 以上"),
        (["--header", "nocolon", "-"], "不正なヘッダです: 'nocolon'"),
        (["--header", ": value", "-"], "不正なヘッダです: ': value'"),
        (["--header", "X: a\nb", "-"], "不正なヘッダです"),
        (["--header", "X: 日本", "-"], "不正なヘッダです"),
        (["--expect", "2x", "-"], "不正なパターンです: '2x'"),
        (["--expect", "2XX", "-"], "不正なパターンです: '2XX'"),
        (["--expect", "２００", "-"], "不正なパターンです: '２００'"),  # noqa: RUF001
        (["--expect", "", "-"], "不正なパターンです: ''"),
        (["--expect", "200,TIMEOUT", "-"], "不正なパターンです: 'TIMEOUT'"),
        (["--only", "20", "-"], "不正なパターンです: '20'"),
        (["--only", "200,", "-"], "不正なパターンです: ''"),
        (["--exclude", "timeout", "-"], "不正なパターンです: 'timeout'"),
        (["--format", "xml", "-"], "invalid choice: 'xml'"),
        (["--diff", "/no/such/last.json", "-"], "No such file or directory"),
        (["--diff", "{tmp_path}/list.json", "-"], "schema が 1 ではありません"),
        (
            ["--diff", "{tmp_path}/noresults.json", "-"],
            "--format json の出力ではありません",
        ),
        (
            ["--diff", "{tmp_path}/nogroup.json", "-"],
            "--format json の出力ではありません",
        ),
        (["--diff", "{tmp_path}/binary.txt", "-"], "'utf-8' codec can't decode"),
        (["--diff", "{tmp_path}/schema2.json", "-"], "schema"),
        (["--diff", "{tmp_path}/schema2.json", "--format", "json", "-"], "text 形式"),
        (["--summary", "--format", "csv", "-"], "--summary は text 形式"),
        (["--summary", "--format", "json", "-"], "--summary は text 形式"),
        (["--summary", "--diff", "{tmp_path}/schema2.json", "-"], "同時に使えません"),
        (["{tmp_path}/binary.txt"], "'utf-8' codec can't decode"),
    ],
)
def test_main_exits_2_on_usage_errors(argv, message, tmp_path: Path, capsys):
    (tmp_path / "binary.txt").write_bytes(b"\xff\xfe\x00http://a/\n")
    (tmp_path / "schema2.json").write_text('{"schema": 2, "results": []}')
    (tmp_path / "list.json").write_text("[]")
    (tmp_path / "noresults.json").write_text('{"schema": 1}')
    (tmp_path / "nogroup.json").write_text('{"schema": 1, "results": [{"url": "x"}]}')
    argv = [arg.format(tmp_path=tmp_path) for arg in argv]

    with pytest.raises(SystemExit) as exc:
        scc.main(argv)

    assert exc.value.code == 2
    assert message in capsys.readouterr().err


def test_main_header_option_is_repeatable_and_can_override_user_agent(
    server, tmp_path: Path, capsys
):
    auth = f"{server.url}/need-auth"
    ua = f"{server.url}/ua"
    (tmp_path / "u.txt").write_text(f"{auth}\n{ua}\n", encoding="utf-8")
    headers = [
        *["--header", "Authorization: Bearer wrong"],
        *["--header", "Authorization: Bearer secret"],
        *["--header", "User-Agent:x"],
    ]

    assert scc.main([*headers, str(tmp_path / "u.txt")]) == 0
    assert capsys.readouterr().out == f"200\n  {auth}\n403\n  {ua}\n"


def test_main_passes_check_options(monkeypatch, tmp_path: Path, capsys):
    (tmp_path / "u.txt").write_text("http://a/\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        scc, "check_all", lambda urls, **kw: calls.append((urls, kw)) or []
    )

    assert scc.main([str(tmp_path / "u.txt")]) == 0
    options = ["--workers", "3", "--retry", "2", "--head"]
    assert scc.main([*options, str(tmp_path / "u.txt")]) == 0
    assert calls == [
        (
            ["http://a/"],
            {"timeout": 10.0, "workers": 1, "retry": 0, "headers": {}, "method": "GET"},
        ),
        (
            ["http://a/"],
            {
                "timeout": 10.0,
                "workers": 3,
                "retry": 2,
                "headers": {},
                "method": "HEAD",
            },
        ),
    ]


def test_main_exits_2_when_no_urls(tmp_path: Path, capsys):
    (tmp_path / "empty.txt").write_text("\n# nothing\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        scc.main([str(tmp_path / "empty.txt")])

    assert exc.value.code == 2
    assert "URL" in capsys.readouterr().err
