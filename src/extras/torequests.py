import os
from random import choice

import requests

from extras.tse_client import TSE_REFERER

TOR_PROXY_HOST = os.environ.get("TOR_PROXY_HOST", "rotating-tor")


def _get_random_ua():
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.121 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.105 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.132 Safari/537.36",
        "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.88 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.72 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.87 Safari/537.36",
    ]
    return choice(user_agents)


def check_tor_status(tor_enabled=True):
    r = execute("https://check.torproject.org/api/ip", "GET", tor_enabled=tor_enabled)
    if r["req"] is None:
        print("RIP")
        return None
    return r["req"].text


def execute(url, mode, timeout=10, data=None, has_random_ua=True, tor_enabled=True):
    headers = {}
    if has_random_ua:
        headers["User-Agent"] = _get_random_ua()
    if "resultados.tse.jus.br" in url:
        headers["Referer"] = TSE_REFERER

    proxies = (
        {
            "http": f"http://{TOR_PROXY_HOST}:3128",
            "https": f"http://{TOR_PROXY_HOST}:3128",
        }
        if tor_enabled
        else {}
    )
    try:
        mode = mode.upper()
        if mode == "GET":
            req = requests.get(url, headers=headers, proxies=proxies, timeout=timeout)
        elif mode == "POST":
            req = requests.post(
                url, headers=headers, proxies=proxies, data=data, timeout=timeout
            )
        else:
            return {"status": "invalidmode", "req": None, "err": None}
        return {"status": "ok", "req": req, "err": None}
    except Exception as err:
        return {"status": "fail", "req": None, "err": err}
