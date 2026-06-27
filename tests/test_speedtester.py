import json
import math
import logging
import pytest
import requests
import time

from types import SimpleNamespace

from speedtester.speedtest import (
    DownloadResult,
    SpeedStats,
    calculate_speed,
    validate_args,
    CLIError,
    download,
    run_test,
    save_results,
    print_stats,
)

# =========================
# FIXTURES
# =========================


@pytest.fixture
def sample_results():
    return [
        DownloadResult(1.0, 1_048_576),
        DownloadResult(2.0, 1_048_576),
        DownloadResult(3.0, 1_048_576),
    ]


# =========================
# calculate_speed
# =========================


def test_calculate_speed(sample_results):
    stats = calculate_speed(sample_results)

    assert math.isclose(stats.avg_response_time, 2.0)
    assert stats.total_mib > 0
    assert stats.avg_speed_mib_s > 0
    assert stats.p50 > 0
    assert stats.p95 >= stats.p50


def test_calculate_speed_empty():
    assert calculate_speed([]) == SpeedStats(0.0, 0.0, 0.0, 0.0, 0.0)


def test_calculate_speed_zero_time():
    stats = calculate_speed([DownloadResult(0.0, 1000)])
    assert stats.avg_response_time == 0.0


def test_calculate_speed_single():
    stats = calculate_speed([DownloadResult(1.0, 1000)])
    assert stats.p50 == 0.0
    assert stats.p95 == 0.0


# =========================
# validate_args
# =========================


@pytest.mark.parametrize(
    "url, output, count, timeout, should_fail",
    [
        ("https://x.com", "file.json", 1, 1.0, False),
        ("http://x.com", None, 1, 1.0, False),
        ("ftp://x.com", None, 1, 1.0, True),
        ("https://x.com", "file.txt", 1, 1.0, True),
        ("https://x.com", None, 0, 1.0, True),
        ("https://x.com", None, 1, 0.0, True),
    ],
)
def test_validate_args(url, output, count, timeout, should_fail):
    args = SimpleNamespace(
        url=url,
        output=output,
        count=count,
        timeout=timeout,
    )

    if should_fail:
        with pytest.raises(CLIError):
            validate_args(args)
    else:
        validate_args(args)


# =========================
# download
# =========================


class FakeResponse:
    def __init__(self, chunks=None):
        self._chunks = chunks or []

    def iter_content(self, chunk_size=8192):
        yield from self._chunks

    def raise_for_status(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_download_success():
    class FakeSession:
        def get(self, *args, **kwargs):
            return FakeResponse([b"a" * 1000, b"b" * 2000])

    result = download(FakeSession(), "http://test", 1, True)

    assert result.size_bytes == 3000
    assert result.duration > 0


def test_download_http_error():
    class BadResponse(FakeResponse):
        def raise_for_status(self):
            raise requests.HTTPError()

    class FakeSession:
        def get(self, *args, **kwargs):
            return BadResponse([b"x"])

    assert download(FakeSession(), "http://test", 1, True) is None


def test_download_timeout():
    class FakeSession:
        def get(self, *args, **kwargs):
            raise requests.Timeout()

    assert download(FakeSession(), "http://test", 1, True) is None


def test_download_connection_error():
    class FakeSession:
        def get(self, *args, **kwargs):
            raise requests.ConnectionError()

    assert download(FakeSession(), "http://test", 1, True) is None


def test_download_request_exception():
    class FakeSession:
        def get(self, *args, **kwargs):
            raise requests.RequestException()

    assert download(FakeSession(), "http://test", 1, True) is None


def test_download_retry_success(monkeypatch):
    calls = {"n": 0}

    def fake_sleep(_):
        calls["sleep"] = True

    monkeypatch.setattr(time, "sleep", fake_sleep)

    class FakeResponse:
        def __init__(self, chunks):
            self._chunks = chunks

        def iter_content(self, chunk_size=8192):
            yield from self._chunks

        def raise_for_status(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class FakeSession:
        def get(self, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise requests.ConnectionError("fail once")
            return FakeResponse([b"a" * 1000])

    result = download(FakeSession(), "http://test", 1, True)

    assert result is not None
    assert calls["n"] == 2
    assert calls["sleep"] is True


# =========================
# run_test
# =========================


def test_run_test_success(monkeypatch):
    monkeypatch.setattr(
        "speedtester.speedtest.download", lambda *a, **k: DownloadResult(1.0, 1000)
    )

    run_test("http://test", 3, 1, True)


def test_run_test_no_success(monkeypatch):
    monkeypatch.setattr("speedtester.speedtest.download", lambda *a, **k: None)

    with pytest.raises(RuntimeError):
        run_test("http://test", 3, 1, True)


def test_run_test_save_success(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "speedtester.speedtest.download", lambda *a, **k: DownloadResult(1.0, 1000)
    )

    path = tmp_path / "out.json"

    run_test("http://test", 2, 1, True, output=str(path))

    assert path.exists()


def test_run_test_save_error(monkeypatch):
    monkeypatch.setattr(
        "speedtester.speedtest.download", lambda *a, **k: DownloadResult(1.0, 1000)
    )

    monkeypatch.setattr(
        "speedtester.speedtest.save_results",
        lambda *a, **k: (_ for _ in ()).throw(OSError("disk")),
    )

    run_test("http://test", 2, 1, True, output="out.json")


# =========================
# save_results
# =========================


def test_save_results(tmp_path):
    stats = SpeedStats(1.0, 2.0, 3.0, 1.0, 2.0)

    file_path = tmp_path / "out.json"

    save_results(str(file_path), stats, 10, 8)

    data = json.loads(file_path.read_text())

    assert data["requests"]["total"] == 10
    assert data["requests"]["successful"] == 8


def test_save_results_oserror(monkeypatch):
    monkeypatch.setattr(
        "builtins.open", lambda *a, **k: (_ for _ in ()).throw(OSError())
    )

    stats = SpeedStats(1, 1, 1, 1, 1)

    with pytest.raises(OSError):
        save_results("file.json", stats, 1, 1)


# =========================
# print_stats
# =========================


def test_print_stats_logs(caplog):
    stats = SpeedStats(1.0, 2.0, 3.0, 1.0, 2.0)

    with caplog.at_level(logging.INFO):
        print_stats(stats, 10, 8)

    assert "TEST RESULTS" in caplog.text
