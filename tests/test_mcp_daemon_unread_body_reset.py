"""Ответ демона на POST с непрочитанным телом не должен рвать соединение.

16.09.2026 CI на Windows уронил test_fix_g18_sse_auth: вместо 401 клиент
получил ConnectionAbortedError (WinError 10053). Демон отвечал, не дочитав
тело POST, и закрывал соединение. Если к закрытию в сокете остались
непрочитанные байты или они пришли после него, ОС обрывает соединение
сбросом (RST), а Windows при сбросе выбрасывает уже пришедший клиенту ответ.
http.client шлёт заголовки и тело двумя send(), поэтому тело легко приходит
уже после ответа сервера.

Тест шлёт заголовки, даёт серверу время ответить, досылает тело и читает
ответ до конца. Соединение должно закончиться обычным EOF. На macOS без
дочитывания ответ ещё доходит, но чтение кончается ConnectionResetError;
на Windows пропадает и сам ответ.
"""

import json
import select
import socket
import time

import pytest

from gemini_translator.mcp import daemon as daemon_mod


@pytest.fixture
def daemon(tmp_path):
    instance = daemon_mod.McpDaemon(tmp_path, host="127.0.0.1", port=0, concurrency=1)
    instance.start_in_thread()
    yield instance
    instance.stop()


def _post_with_late_body(daemon, target, *, with_token):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode("utf-8")
    head = [
        f"POST {target} HTTP/1.1",
        f"Host: {daemon.host}:{daemon.port}",
        "Content-Type: application/json",
        f"Content-Length: {len(body)}",
    ]
    if with_token:
        head.append(f"{daemon_mod.TOKEN_HEADER}: {daemon.token}")

    with socket.create_connection((daemon.host, daemon.port), timeout=5) as sock:
        sock.sendall(("\r\n".join(head) + "\r\n\r\n").encode("ascii"))
        # Сервер, который отвечает, не читая тела, успевает ответить и закрыть соединение.
        select.select([sock], [], [], 0.3)
        sock.sendall(body)
        # Сброс, если он будет, должен успеть дойти до того, как ответ дочитан.
        time.sleep(0.1)
        response = b""
        try:
            while chunk := sock.recv(65536):
                response += chunk
        except (ConnectionResetError, ConnectionAbortedError) as exc:
            pytest.fail(
                f"соединение оборвано сбросом вместо обычного закрытия: {exc!r}; "
                f"до сброса пришло {response[:40]!r}"
            )
    return response


@pytest.mark.parametrize(
    ("target", "with_token", "status"),
    [
        ("/messages?session_id=abc", False, 401),  # нет токена
        ("/messages", True, 400),  # нет session_id: ошибка до чтения тела
        ("/no-such-endpoint", True, 404),
    ],
)
def test_early_response_to_post_closes_cleanly_after_late_body(daemon, target, with_token, status):
    response = _post_with_late_body(daemon, target, with_token=with_token)

    assert response.startswith(f"HTTP/1.0 {status} ".encode("ascii")), response[:80]
