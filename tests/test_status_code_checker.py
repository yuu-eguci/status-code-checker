import io
import sys
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
        (["/no/such/file.txt"], "file.txt"),
        (["--timeout", "0", "-"], "timeout"),
        (["--timeout", "-1", "-"], "timeout"),
    ],
)
def test_main_exits_2_on_usage_errors(argv, message, capsys):
    with pytest.raises(SystemExit) as exc:
        scc.main(argv)

    assert exc.value.code == 2
    assert message in capsys.readouterr().err


def test_main_exits_2_when_no_urls(tmp_path: Path, capsys):
    (tmp_path / "empty.txt").write_text("\n# nothing\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        scc.main([str(tmp_path / "empty.txt")])

    assert exc.value.code == 2
    assert "URL" in capsys.readouterr().err
