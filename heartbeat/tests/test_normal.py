"""Cenário normal: 5 nós vivos por 20 s, depois do aquecimento ninguém é suspeito.

Precisa de Docker. Rodar na raiz: python3 -m pytest heartbeat/tests/test_normal.py
"""
import json
import os
import subprocess
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]  # onde fica o compose.yaml
N = 5
AQUECIMENTO = 5  # segundos depois do último nó iniciar
DURACAO = 20


def ler_logs(run_id):
    eventos = []
    for arquivo in (RAIZ / "heartbeat" / "logs" / run_id).glob("node*.jsonl"):
        for linha in arquivo.read_text().splitlines():
            eventos.append(json.loads(linha))
    return eventos


def test_cenario_normal():
    run_id = f"normal_{int(time.time())}"  # um id novo por execução, não precisa limpar logs
    env = {**os.environ, "N": str(N), "RUN_ID": run_id}
    compose = ["docker", "compose", "--profile", "heartbeat"]
    nos = [f"node{i}" for i in range(1, N + 1)]

    subprocess.run(compose + ["up", "-d", "--build"] + nos, cwd=RAIZ, env=env, check=True)
    time.sleep(DURACAO)
    subprocess.run(compose + ["down"], cwd=RAIZ, env=env, check=True)

    eventos = ler_logs(run_id)

    # todos os nós iniciaram
    inicios = [e["ts_wall"] for e in eventos if e["event"] == "start"]
    assert len(inicios) == N
    fim_aquecimento = max(inicios) + AQUECIMENTO

    # ninguém suspeito depois do aquecimento
    suspeitas = [e for e in eventos if e["event"] == "suspect" and e["ts_wall"] > fim_aquecimento]
    assert suspeitas == []

    # cada nó recebeu heartbeats de todos os outros
    for no in range(1, N + 1):
        recebidos = {e["peer"] for e in eventos if e["event"] == "hb_recv" and e["node"] == no}
        assert recebidos == set(range(1, N + 1)) - {no}
