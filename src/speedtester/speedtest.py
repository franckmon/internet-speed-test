import argparse
import sys
import json
import time
import statistics
import logging
from dataclasses import dataclass
from typing import List, Optional

import requests

MAX_RETRIES = 2
RETRY_BACKOFF = 0.3
CHUNK_SIZE = 8192
DEFAULT_COUNT = 10
DEFAULT_TIMEOUT = 5.0
BYTES_IN_MIB = 1024 * 1024


logger = logging.getLogger("speedtester")


@dataclass
class DownloadResult:
    """
    Result of a single HTTP download request
    Attributes:
        duration (float): Request execution time
        size_bytes (int): Downloaded data size in bytes
    """

    duration: float
    size_bytes: int


@dataclass
class SpeedStats:
    """
    Aggregated statistics for a series of HTTP requests
    Attributes:
        avg_response_time (float): Average response time (seconds)
        total_mib (float): Total downloaded data in MiB
        avg_speed_mib_s (float): Average transfer speed (MiB/s)
        p50 (float): 50th percentile
        p95 (float): 95th percentile
    """

    avg_response_time: float
    total_mib: float
    avg_speed_mib_s: float
    p50: float
    p95: float


def download(
    session: requests.Session, url: str, timeout: float, verify_ssl: bool
) -> Optional[DownloadResult]:
    """
    Performs an HTTP GET request and measures execution time and response size
    Uses stream=True to read data in chunks without loading the full response into memory
    Args:
        session (requests.Session): Active HTTP session for connection reuse
        url (str): Target URL
        timeout (float): Request timeout
        verify_ssl (bool): SSL certificate verification flag
    Returns:
        Optional[DownloadResult]: Download result or None if an error occurred
    """

    for attempt in range(1, MAX_RETRIES + 1):
        start = time.perf_counter()

        try:
            with session.get(
                url, timeout=timeout, verify=verify_ssl, stream=True
            ) as resp:
                resp.raise_for_status()

                size_bytes = 0
                for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        size_bytes += len(chunk)

            duration = time.perf_counter() - start
            return DownloadResult(duration, size_bytes)

        except (requests.Timeout, requests.ConnectionError) as e:
            logger.warning(
                "Attempt %s/%s failed for %s: %s", attempt, MAX_RETRIES, url, e
            )

            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF)
                continue

            return None

        except requests.HTTPError as e:
            logger.warning("HTTP error %s (no retry) %s", e, url)
            return None

        except requests.RequestException as e:
            logger.error("Unexpected request error: %s", e)
            return None


def calculate_speed(results: List[DownloadResult]) -> SpeedStats:
    """
    Calculates aggregated download speed statistics
    Args:
        results (List[DownloadResult]): List of successful download results
    Returns:
        SpeedStats: Aggregated statistics (avg response time, total size, avg speed, p50, p95)
    """

    if not results:
        return SpeedStats(0.0, 0.0, 0.0, 0.0, 0.0)

    durations = [r.duration for r in results]
    total_bytes = sum(r.size_bytes for r in results)
    total_time = sum(durations)

    if total_time <= 0:
        return SpeedStats(0.0, 0.0, 0.0, 0.0, 0.0)

    p50 = 0.0
    p95 = 0.0

    if len(durations) >= 2:
        p50 = statistics.median(durations)
        p95 = sorted(durations)[int(len(durations) * 0.95) - 1]

    return SpeedStats(
        avg_response_time=statistics.mean(durations),
        total_mib=total_bytes / BYTES_IN_MIB,
        avg_speed_mib_s=(total_bytes / total_time) / BYTES_IN_MIB,
        p50=p50,
        p95=p95,
    )


def print_stats(stats: SpeedStats, total_count: int, success_count: int) -> None:
    """
    Prints final statistics to logs
    Args:
        stats (SpeedStats): Calculated statistics
        total_count (int): Total number of requests
        success_count (int): Number of successful requests
    """

    logger.info("=== TEST RESULTS ===")
    logger.info("Total requests: %s", total_count)
    logger.info("Successful requests: %s", success_count)
    logger.info("Failed requests: %s", total_count - success_count)
    logger.info("Average response time: %.3f sec", stats.avg_response_time)
    logger.info("P50 response time: %.3f sec", stats.p50)
    logger.info("P95 response time: %.3f sec", stats.p95)
    logger.info("Total downloaded: %.2f MiB", stats.total_mib)
    logger.info("Average speed: %.2f MiB/s", stats.avg_speed_mib_s)
    logger.info("====================")


def save_results(
    path: str, stats: SpeedStats, total_requests: int, successful_requests: int
) -> None:
    """
    Saves calculated statistics to a JSON file
    Args:
        path (str): Output file path.
        stats (SpeedStats): Calculated statistics.
        total_requests (int): Total number of requests.
        successful_requests (int): Number of successful requests.
    """
    failed_requests = total_requests - successful_requests

    data = {
        "requests": {
            "total": total_requests,
            "successful": successful_requests,
            "failed": failed_requests,
        },
        "statistics": {
            "average_response_time": stats.avg_response_time,
            "p50": stats.p50,
            "p95": stats.p95,
            "total_downloaded_mib": stats.total_mib,
            "average_speed_mib_s": stats.avg_speed_mib_s,
        },
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def run_test(
    url: str, count: int, timeout: float, verify_ssl: bool, output: Optional[str] = None
) -> None:
    """
    Runs full speed test cycle:
    - performs multiple HTTP requests
    - collects results
    - calculates statistics
    - prints final report
    Args:
        url (str): Target URL
        count (int): Number of requests
        timeout (float): Request timeout
        verify_ssl (bool): SSL verification flag
        output (Optional[str]): Output JSON file path
    """

    results: List[DownloadResult] = []

    logger.info("Starting measurement: %s", url)
    logger.info("Requests count: %s", count)

    with requests.Session() as session:
        for i in range(1, count + 1):
            result = download(session, url, timeout, verify_ssl)

            if result is None:
                logger.warning("Request %s/%s FAILED", i, count)
                continue

            results.append(result)

            logger.info(
                "Request %s/%s: %.3fs, %.2f MiB",
                i,
                count,
                result.duration,
                result.size_bytes / BYTES_IN_MIB,
            )

    if not results:
        raise RuntimeError("No successful requests completed")

    stats = calculate_speed(results)
    print_stats(stats, count, len(results))

    if output:
        try:
            save_results(output, stats, count, len(results))
            logger.info("Results saved to %s", output)
        except OSError as e:
            logger.error("Failed to save results: %s", e)


class CLIError(ValueError):
    """
    Exception raised for invalid CLI arguments
    """

    pass


def parse_args() -> argparse.Namespace:
    """
    Parses command line arguments
    Returns:
        argparse.Namespace: Parsed arguments (url, count, timeout, insecure)
    """
    parser = argparse.ArgumentParser(description="HTTP speed tester")

    parser.add_argument("url", help="URL to test")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--insecure", action="store_true")
    parser.add_argument("--output", metavar="FILE", help="Save statistics to JSON file")

    return parser.parse_args()


def validate_args(args) -> None:
    """
    Validates CLI arguments
    Args:
        args: result of parse_args()
    """

    if not args.url.startswith(("http://", "https://")):
        raise CLIError("URL must start with http:// or https://")

    if args.output and not args.output.endswith(".json"):
        raise CLIError("--output must be a JSON file")

    if args.count <= 0:
        raise CLIError("--count must be > 0")

    if args.timeout <= 0:
        raise CLIError("--timeout must be > 0")


def main():
    """
    Application entry point
    Execution flow:
    1. Configure logging
    2. Parse CLI arguments
    3. Validate arguments
    4. Run test
    5. Handle errors
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    try:
        args = parse_args()
        validate_args(args)

        run_test(
            url=args.url,
            count=args.count,
            timeout=args.timeout,
            verify_ssl=not args.insecure,
            output=args.output,
        )

    except CLIError as e:
        logger.error("CLI ERROR: %s", e)
        sys.exit(2)

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(130)

    except RuntimeError as e:
        logger.error("%s", e)
        sys.exit(1)

    except Exception:
        logger.exception("Unexpected error")
        sys.exit(1)


if __name__ == "__main__":
    main()
