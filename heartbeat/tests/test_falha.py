"""Cenário de falha: um nó é morto, os outros o suspeitam em até K*T, e ao reiniciar ele é restaurado.

Precisa de Docker. Rodar na raiz: python3 -m pytest heartbeat/tests/test_falha.py
"""
import json
import os
import subprocess
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]  # onde fica o compose.yaml
N = 5
T_MS = 250
K = 3
VITIMA = 3
AQUECIMENTO = 5  # segundos antes de matar o nó
MARGEM = 0.5     # folga (s) sobre K*T para o intervalo de verificação e o escalonamento do Docker


def ler_logs(run_id):
    eventos = []
    for arquivo in (RAIZ / "heartbeat" / "logs" / run_id).glob("node*.jsonl"):
        for linha in arquivo.read_text().splitlines():
            eventos.append(json.loads(linha))
    return eventos


def test_cenario_falha():
    run_id = f"falha_{int(time.time())}"  # um id novo por execução, não precisa limpar logs
    env = {**os.environ, "N": str(N), "T_MS": str(T_MS), "K": str(K), "RUN_ID": run_id}
    compose = ["docker", "compose", "--profile", "heartbeat"]
    nos = [f"node{i}" for i in range(1, N + 1)]

    def docker(*args):
        subprocess.run(compose + list(args), cwd=RAIZ, env=env, check=True)

    try:
        docker("up", "-d", "--build", *nos)
        time.sleep(AQUECIMENTO)

        # Falha: kill derruba o contêiner de uma vez, como um crash.
        t_kill = time.time()
        docker("kill", f"node{VITIMA}")
        time.sleep(3)  # bem mais que K*T = 0,75 s

        # Recuperação: o nó volta com uma incarnation maior.
        t_restart = time.time()
        docker("start", f"node{VITIMA}")
        time.sleep(3)
    finally:
        docker("down")

    eventos = ler_logs(run_id)
    outros = [i for i in range(1, N + 1) if i != VITIMA]

    # Completeness: todo nó vivo suspeitou da vítima, dentro do limite K*T (mais a margem).
    limite = K * T_MS / 1000 + MARGEM
    for no in outros:
        suspeitas = [e for e in eventos
                     if e["event"] == "suspect" and e["node"] == no
                     and e["peer"] == VITIMA and e["ts_wall"] >= t_kill]
        assert len(suspeitas) == 1, f"nó {no} deveria suspeitar da vítima exatamente uma vez"
        assert suspeitas[0]["ts_wall"] - t_kill <= limite, f"nó {no} demorou demais para detectar"

    # Accuracy: ninguém além da vítima foi suspeito depois do aquecimento.
    falsos = [e for e in eventos
              if e["event"] == "suspect" and e["peer"] != VITIMA and e["ts_wall"] >= t_kill - 1]
    assert falsos == []

    # Reinício: todo nó vivo voltou a confiar na vítima.
    for no in outros:
        restauros = [e for e in eventos
                     if e["event"] == "restore" and e["node"] == no
                     and e["peer"] == VITIMA and e["ts_wall"] >= t_restart]
        assert len(restauros) == 1, f"nó {no} deveria restaurar a vítima exatamente uma vez"
