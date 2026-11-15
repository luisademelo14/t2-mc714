"""Experimentos do detector de falhas por heartbeat.

Para cada configuração (intervalo T e taxa de perda) e cada repetição, o script sobe N nós,
espera o aquecimento, observa o regime normal, mata um nó e espera os outros detectarem.

Resultados, na pasta resultados/:
  execucoes.csv  uma linha por execução: mensagens por segundo e falsos positivos
  deteccoes.csv  uma linha por (execução, nó observador): tempo até suspeitar do nó morto

Uso, a partir da pasta heartbeat/:
  python3 experimento.py               # roda tudo (5 repetições) e gera os CSVs
  python3 experimento.py --reps 10
  python3 experimento.py --so-extrair  # só refaz os CSVs a partir dos logs já gravados

Se uma execução falhar no meio, apague a pasta dela em heartbeat/logs/ antes de extrair de novo.
"""
import argparse
import csv
import json
import os
import subprocess
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent  # onde fica o compose.yaml
PASTA_LOGS = Path(__file__).resolve().parent / "logs"
PASTA_RESULTADOS = Path(__file__).resolve().parent / "resultados"

N = 5
K = 3
VITIMA = 3           # nó que será morto
AQUECIMENTO = 5      # s depois que o último nó inicia, antes de começar a medir
REGIME_NORMAL = 15   # s medindo com todos os nós vivos (antes do kill)
APOS_KILL = 5        # s esperando os outros nós detectarem a falha

# Níveis do parâmetro: varia T sem perda, e varia a perda com T fixo em T_BASE.
T_BASE = 250  # ms
NIVEIS_T = [100, 250, 500]  # ms
NIVEIS_PERDA = [0.0, 0.1, 0.3]
CONFIGS = [(t, 0.0) for t in NIVEIS_T] + [(T_BASE, p) for p in NIVEIS_PERDA if p > 0]


# ---------------------------------------------------------------- execução

def compose(*args, env=None):
    subprocess.run(["docker", "compose", "--profile", "heartbeat", *args],
                   cwd=RAIZ, env=env, check=True)


def rodar(t_ms, loss, rep):
    """Uma execução: sobe os nós, mede, mata a vítima e derruba tudo."""
    run_id = f"exp_T{t_ms}_L{round(loss * 100)}_r{rep}_{int(time.time())}"
    env = {**os.environ, "N": str(N), "T_MS": str(t_ms), "K": str(K),
           "LOSS": str(loss), "SEED": str(rep), "RUN_ID": run_id}
    nos = [f"node{i}" for i in range(1, N + 1)]
    try:
        compose("up", "-d", *nos, env=env)
        time.sleep(AQUECIMENTO + REGIME_NORMAL)
        compose("kill", f"node{VITIMA}", env=env)
        time.sleep(APOS_KILL)
    finally:
        # -t 1: os nós não tratam SIGTERM, então não adianta esperar os 10 s padrão
        compose("down", "-t", "1", env=env)


# ---------------------------------------------------------------- extração

def ler_eventos(pasta):
    eventos = []
    for arquivo in pasta.glob("node*.jsonl"):
        for linha in arquivo.read_text().splitlines():
            eventos.append(json.loads(linha))
    return eventos


def analisar(pasta):
    """Calcula as métricas de uma execução a partir dos logs.

    Retorna (linha de execucoes.csv, lista de linhas de deteccoes.csv).
    """
    ev = ler_eventos(pasta)
    inicios = [e for e in ev if e["event"] == "start"]
    cfg = inicios[0]  # traz n, t_ms, k, loss e seed desta execução
    fim_aquecimento = max(e["ts_wall"] for e in inicios) + AQUECIMENTO
    # O kill não deixa registro no log: consideramos que o nó morreu no último heartbeat que enviou.
    t_morte = max(e["ts_wall"] for e in ev if e["node"] == VITIMA and e["event"] == "hb_sent")
    t_fim = max(e["ts_wall"] for e in ev)

    # Regime normal: todos vivos, depois do aquecimento e antes da morte.
    envios = [e for e in ev if e["event"] == "hb_sent" and fim_aquecimento <= e["ts_wall"] < t_morte]
    janela = t_morte - fim_aquecimento
    tentadas = sum(e["msgs"] for e in envios)
    descartadas = sum(e["dropped"] for e in envios)

    # Falso positivo: suspeitar de um nó vivo (qualquer um que não seja a vítima depois que ela morreu).
    falsos = [e for e in ev
              if e["event"] == "suspect" and e["ts_wall"] >= fim_aquecimento
              and (e["peer"] != VITIMA or e["ts_wall"] < t_morte)]

    execucao = {
        "run_id": pasta.name,
        "n": cfg["n"], "t_ms": cfg["t_ms"], "k": cfg["k"], "loss": cfg["loss"], "seed": cfg["seed"],
        "janela_s": round(janela, 2),
        "msgs_por_s": round(tentadas / janela, 1),          # tentativas de envio de todos os nós
        "perda_obs": round(descartadas / tentadas, 3),      # confere se a perda injetada bate com LOSS
        "falsos_positivos": len(falsos),
        "falsos_por_min": round(len(falsos) / ((t_fim - fim_aquecimento) / 60), 2),
    }

    deteccoes = []
    for no in range(1, N + 1):
        if no == VITIMA:
            continue
        mudancas = sorted((e for e in ev if e["node"] == no and e.get("peer") == VITIMA
                           and e["event"] in ("suspect", "restore")), key=lambda e: e["ts_wall"])
        antes = [e for e in mudancas if e["ts_wall"] < t_morte]
        depois = [e for e in mudancas if e["ts_wall"] >= t_morte and e["event"] == "suspect"]

        # Com perda alta, o nó pode já estar suspeitando da vítima (por engano) quando ela morre.
        # Não há detecção da morte para medir; fica vazio e marcado.
        ja_suspeito = bool(antes) and antes[-1]["event"] == "suspect"
        deteccao_ms = None
        if not ja_suspeito and depois:
            deteccao_ms = round((depois[0]["ts_wall"] - t_morte) * 1000)
        deteccoes.append({
            "run_id": pasta.name, "t_ms": cfg["t_ms"], "loss": cfg["loss"], "seed": cfg["seed"],
            "observador": no, "deteccao_ms": deteccao_ms, "ja_suspeito": int(ja_suspeito),
        })
    return execucao, deteccoes


def escrever_csv(caminho, linhas):
    with open(caminho, "w", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
        escritor.writeheader()
        escritor.writerows(linhas)
    print(f"{len(linhas)} linhas em {caminho}")


def extrair():
    execucoes, deteccoes = [], []
    for pasta in sorted(PASTA_LOGS.glob("exp_*")):
        execucao, dets = analisar(pasta)
        execucoes.append(execucao)
        deteccoes.extend(dets)
    if not execucoes:
        print(f"Nenhum log exp_* em {PASTA_LOGS}")
        return
    PASTA_RESULTADOS.mkdir(exist_ok=True)
    escrever_csv(PASTA_RESULTADOS / "execucoes.csv", execucoes)
    escrever_csv(PASTA_RESULTADOS / "deteccoes.csv", deteccoes)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=5, help="repetições por configuração")
    ap.add_argument("--so-extrair", action="store_true", help="não roda nada, só gera os CSVs")
    args = ap.parse_args()

    if not args.so_extrair:
        compose("build", *[f"node{i}" for i in range(1, N + 1)])  # constrói a imagem uma vez só
        total = args.reps * len(CONFIGS)
        por_execucao = AQUECIMENTO + REGIME_NORMAL + APOS_KILL + 8  # +8 s de subir e derrubar
        print(f"{total} execuções, cerca de {total * por_execucao // 60} min")
        i = 0
        # Intercala as configurações: se a máquina esquentar ou ficar carregada no meio,
        # o efeito se espalha por todas as configurações em vez de cair numa só.
        for rep in range(1, args.reps + 1):
            for t_ms, loss in CONFIGS:
                i += 1
                print(f"[{i}/{total}] T={t_ms} ms, perda={loss:.0%}, repetição {rep}", flush=True)
                rodar(t_ms, loss, rep)
    extrair()


if __name__ == "__main__":
    main()
