# Internet Speed Test

CLI-утилита на Python для измерения скорости загрузки данных по HTTP.

Последовательно выполняет N запросов к указанному URL, измеряет latency и throughput, а также рассчитывает статистические метрики (p50, p95).

[![Python](https://img.shields.io/badge/python-%3E%3D3.12-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)

## Возможности

- Последовательные HTTP-запросы к заданному URL
- Retry-механизм для повышения устойчивости к сетевым сбоям
- Измерение latency (времени ответа)
- Расчёт throughput (MiB/s)
- Статистики:
  - average response time
  - p50 (median)
  - p95 percentile
- Сохранение результатов в JSON

## Как это работает

Утилита выполняет последовательные HTTP GET запросы и измеряет:
- время ответа каждого запроса (latency)
- размер загруженных данных
- скорость передачи данных
- агрегированные статистики по серии запросов

> Percentile-метрики рассчитываются без сторонних зависимостей (без numpy), с использованием встроенных методов Python.

## CLI параметры

| Параметр | Описание | По умолчанию |
|----------|----------|--------------|
| `url` | URL файла для загрузки | required |
| `--count` | Количество запросов | 10 |
| `--timeout` | Таймаут запроса (сек) | 5 |
| `--insecure` | Отключить SSL verification | False |
| `--output` | Путь к JSON файлу с результатами | None |

## Быстрый старт

### Через uv

```bash
uv sync
uv run python speedtest.py https://example.com/file.jpg
```

## Через venv + pip

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -r requirements.txt

python speedtest.py https://example.com/file.jpg --count 10 --timeout 3
```

## Пример вывода

```text
=== TEST RESULTS ===
Total requests: 10
Successful requests: 10
Failed requests: 0

Average response time: 0.421 sec
P50 response time: 0.392 sec
P95 response time: 0.612 sec

Total downloaded: 5.20 MiB
Average speed: 0.31 MiB/s
====================
```

## JSON output

```json
{
    "requests": {
        "total": 10,
        "successful": 10,
        "failed": 0
    },
    "statistics": {
        "average_response_time": 0.421,
        "p50": 0.392,
        "p95": 0.612,
        "total_downloaded_mib": 5.2,
        "average_speed_mib_s": 0.31
    }
}
```

## Особенности реализации

* Retry-механизм с backoff для сетевых ошибок
* Stream-based download (без загрузки файла в память)
* Percentile расчёт через statistics + sorted fallback
* Учитываются только успешные запросы
* Последовательное выполнение (без параллелизма)

## Ограничения

* нет параллельных запросов (intentionally sequential)
* результаты зависят от состояния сети и сервера
* p95 является приближённой оценкой (small sample estimation)
* не является полноценным ISP speed test

## Архитектура

```text
CLI
 └── Argument Parser
      └── Runner
           └── Download Layer (HTTP + retry)
                └── Metrics Engine
                     └── Output (logs / JSON)
```

## Требования

* Python ≥ 3.12
* requests

## Тестирование

Запуск тестов:
```bash
pytest
```
Запуск с покрытием:

```bash
pytest --cov=speedtester
```

## Лицензия

MIT