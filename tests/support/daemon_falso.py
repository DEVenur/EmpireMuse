"""Daemon do Docker falso em socket Unix (só stdlib) e cliente HTTP cru, para os testes do proxy de atualização (item 18, P3).

O daemon registra cada requisição que recebe, na ordem; os testes de negação conferem que NADA chegou aqui. Os contes vivem num
dicionário e as respostas seguem a API do Docker (inclusive o fluxo multiplexado de ``logs``, 8 bytes de cabeçalho por quadro).
"""

import json
import re
import socket
import socketserver
import struct
import threading
from http.server import BaseHTTPRequestHandler
from urllib.parse import unquote, urlsplit

PREFIXO_VERSAO_API = re.compile(r"^/v1\.\d+")


class Requisicao:
    def __init__(self, metodo, caminho, query, cabecalhos, corpo, bruto):
        self.metodo, self.caminho, self.query = metodo, caminho, query
        self.cabecalhos, self.corpo, self.bruto = cabecalhos, corpo, bruto

    def __repr__(self):
        return f"{self.metodo} {self.caminho}?{self.query}"


class _Servidor(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


class DaemonFalso:
    def __init__(self, caminho_do_socket: str):
        self.caminho_do_socket = caminho_do_socket
        self.trava = threading.Lock()
        self.reiniciar()
        daemon = self

        class Manipulador(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def address_string(self):
                return "unix"

            def _tratar(self):
                partes = urlsplit(self.path)
                caminho = PREFIXO_VERSAO_API.sub("", unquote(partes.path))
                tamanho = int(self.headers.get("Content-Length") or 0)
                corpo = self.rfile.read(tamanho) if tamanho else b""
                cabecalhos = {nome.lower(): valor for nome, valor in self.headers.items()}
                requisicao = Requisicao(self.command, caminho, partes.query, cabecalhos, corpo, self.path)
                with daemon.trava:
                    daemon.requisicoes.append(requisicao)
                    status, tipo, resposta = daemon._responder(requisicao)
                self.send_response(status)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(resposta)))
                self.end_headers()
                self.wfile.write(resposta)

            do_GET = do_POST = do_DELETE = do_PUT = do_HEAD = _tratar

        self.servidor = _Servidor(caminho_do_socket, Manipulador)
        self.fio = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.fio.start()

    def reiniciar(self):
        self.requisicoes: list[Requisicao] = []
        self.containers: dict[str, dict] = {}
        self.imagem_presente = False

    def adicionar_container(self, nome: str, *, rotulos=None, linhas_de_log=(), estado=None):
        self.containers[nome] = {
            "labels": {"org.empiremuse.role": "updater"} if rotulos is None else rotulos,
            "logs": list(linhas_de_log),
            "state": {
                "Status": "exited",
                "Running": False,
                "ExitCode": 70,
                "StartedAt": "2026-10-27T10:00:00Z",
                "FinishedAt": "2026-10-27T10:01:00Z",
                "Pid": 4242,
                "Error": "detalhe interno",
                "OOMKilled": False,
                **(estado or {}),
            },
        }

    def parar(self):
        self.servidor.shutdown()
        self.servidor.server_close()

    # ---- respostas ----

    def _json(self, status, dados):
        return status, "application/json", json.dumps(dados).encode()

    def _responder(self, req: Requisicao):
        partes = [p for p in req.caminho.split("/") if p]
        if req.metodo == "GET" and req.caminho.startswith("/images/") and req.caminho.endswith("/json"):
            return (
                self._json(200, {"Id": "sha256:" + "0" * 64})
                if self.imagem_presente
                else self._json(404, {"message": "no such image"})
            )
        if req.metodo == "POST" and req.caminho == "/images/create":
            self.imagem_presente = True
            return 200, "application/json", b'{"status":"done"}\n'
        if req.metodo == "POST" and req.caminho == "/containers/create":
            nome = dict(p.split("=", 1) for p in req.query.split("&") if "=" in p).get("name", "")
            if nome in self.containers:
                return self._json(409, {"message": "Conflict. The container name is already in use"})
            corpo = json.loads(req.corpo or b"{}")
            self.containers[nome] = {"labels": corpo.get("Labels", {}), "logs": [], "state": {}, "criado": corpo}
            return self._json(201, {"Id": "a" * 64, "Warnings": []})
        if len(partes) >= 2 and partes[0] == "containers":
            nome = partes[1]
            if nome not in self.containers:
                return self._json(404, {"message": "no such container"})
            cont = self.containers[nome]
            ultimo = partes[2] if len(partes) > 2 else ""
            if req.metodo == "GET" and ultimo == "json":
                return self._json(
                    200,
                    {"Id": "a" * 64, "Name": "/" + nome, "State": cont["state"], "Config": {"Labels": cont["labels"]}},
                )
            if req.metodo == "POST" and ultimo == "start":
                return 204, "text/plain", b""
            if req.metodo == "GET" and ultimo == "logs":
                quadros = b"".join(
                    struct.pack(">BxxxI", 1, len(linha.encode()) + 1) + linha.encode() + b"\n" for linha in cont["logs"]
                )
                return 200, "application/vnd.docker.multiplexed-stream", quadros
            if req.metodo == "DELETE" and not ultimo:
                del self.containers[nome]
                return 204, "text/plain", b""
        return self._json(404, {"message": "rota desconhecida do daemon falso"})


def requisicao_crua(
    socket_path: str, metodo: str, alvo: str, cabecalhos=(), corpo: bytes = b"", *, content_length=True
):
    """Envia HTTP/1.1 cru (cabeçalhos repetidos e fora do padrão passam como estão) e devolve ``(status, corpo_da_resposta)``."""
    linhas = [f"{metodo} {alvo} HTTP/1.1", "Host: localhost"]
    linhas += [f"{nome}: {valor}" for nome, valor in cabecalhos]
    if corpo and content_length and not any(n.lower() == "content-length" for n, _ in cabecalhos):
        linhas.append(f"Content-Length: {len(corpo)}")
    pedido = ("\r\n".join(linhas) + "\r\nConnection: close\r\n\r\n").encode() + corpo
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as cliente:
        cliente.settimeout(20)
        cliente.connect(socket_path)
        try:
            cliente.sendall(pedido)
        except BrokenPipeError:
            pass
        resposta = b""
        try:
            while pedaco := cliente.recv(65536):
                resposta += pedaco
        except ConnectionResetError, TimeoutError:
            pass
    cabeca, _, resto = resposta.partition(b"\r\n\r\n")
    primeira = cabeca.split(b"\r\n", 1)[0].decode("latin-1")
    status = int(primeira.split()[1]) if primeira.startswith("HTTP/") else 0
    return status, resto
