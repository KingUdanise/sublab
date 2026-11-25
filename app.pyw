"""SubLab — applicazione desktop.

Avvia il backend (FastAPI) in un thread e apre la UI in una finestra nativa
(WebView2 via pywebview): nessun browser, nessuna barra degli indirizzi.

Doppio click su SubLab (o dalla Start Menu) -> questa è l'app.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

LOG = os.path.join(HERE, "out", "app.log")


def _hook_streams():
    """Con pythonw stdout/stderr sono None: uvicorn (e altre lib) esplodono.
    Li dirottiamo sul file di log."""
    if sys.stdout is None or sys.stderr is None:
        try:
            os.makedirs(os.path.dirname(LOG), exist_ok=True)
            fh = open(LOG, "a", encoding="utf-8", buffering=1)
        except Exception:
            import io

            fh = io.StringIO()
        if sys.stdout is None:
            sys.stdout = fh
        if sys.stderr is None:
            sys.stderr = fh


def log(msg: str):
    """Log su file: l'app gira con pythonw, quindi senza console."""
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")
    except Exception:
        pass


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _already_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=0.6) as r:
            return r.status == 200
    except Exception:
        return False


def _wait_ready(port: int, timeout: float = 40.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if _already_running(port):
            return True
        time.sleep(0.25)
    return False


def _port_available(port: int) -> bool:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def main() -> int:
    _hook_streams()
    # porta fissa (8777) se libera: cosi' il plugin di Resolve e l'app condividono
    # lo stesso backend; altrimenti una porta libera a caso.
    wanted = int(os.environ.get("SUBLAB_PORT") or 8777)
    port = wanted if _port_available(wanted) else _free_port()
    os.environ["SUBLAB_PORT"] = str(port)

    log(f"--- avvio SubLab (porta {port}, python {sys.version.split()[0]}, {sys.executable})")
    if not _already_running(port):
        import uvicorn

        from server import app as fastapi_app

        def serve():
            try:
                uvicorn.run(fastapi_app, host="127.0.0.1", port=port, log_level="warning")
            except Exception:
                import traceback

                log("ERRORE backend:\n" + traceback.format_exc())

        threading.Thread(target=serve, daemon=True, name="sublab-http").start()
        log("backend avviato, attendo la porta…")
        if not _wait_ready(port):
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                0, "Il backend di SubLab non si è avviato.\nControlla le dipendenze Python.",
                "SubLab", 0x10)
            return 1

    log("backend pronto, apro la finestra")
    import webview

    window = webview.create_window(
        "SubLab — sottotitoli per DaVinci Resolve",
        f"http://127.0.0.1:{port}",
        width=1480,
        height=940,
        min_size=(1120, 700),
        background_color="#0d0f13",
    )
    try:
        webview.start(debug=False, private_mode=False, gui="edgechromium")
    except Exception:
        import traceback

        log("ERRORE webview:\n" + traceback.format_exc())
        raise
    log("finestra chiusa, esco")
    _ = window
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        import traceback

        log("ERRORE fatale:\n" + traceback.format_exc())
        sys.exit(1)
