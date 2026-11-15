import argparse
import csv
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
GRUPO = "experimento" 
PASTA_LOGS = RAIZ / "logs" / "bully" / GRUPO
PASTA_RESULTADOS = Path(__file__).resolve().parent / "resultados"
PORT_PREFIX = os.environ.get("PORT_PREFIX", "800")

NIVEIS_N = [3, 5, 7, 9]
CENARIOS = ["pior", "melhor", "recuperacao"]
T_OK_MS = 300        # timeout de cada mensagem
T_COORD_MS = 1000    # espera pelo COORDINATOR depois de um OK
PING_MS = 200        # período do monitor (só no cenário recuperacao)
AQUECIMENTO = 1      # s com o líder N estável antes de derrubá-lo
ASSENTAR = 0.5       # s depois que todos aceitam o novo líder, para as últimas mensagens entrarem no log
JANELA = 0.4         # s depois da última aceitação em que ainda se contam mensagens

COLUNAS = ["run_id", "n", "cenario", "rep", "convergiu", "iniciador", "eleicoes",
           "eleicao_ms", "deteccao_ms", "recuperacao_ms",
           "msgs_election", "msgs_ok", "msgs_coordinator", "msgs_total", "msgs_teorico"]



def compose(*args, env=None):
    r = subprocess.run(["docker", "compose", "--profile", "bully", *args],
                       cwd=RAIZ, env=env, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"docker compose {' '.join(args)} falhou:\n{r.stderr.strip()}")


def derrubar(no, run_id, env):
    """Mata o contêiner com SIGKILL (docker kill). Como o nó não consegue logar a própria queda,
    o instante é registrado aqui, no log do nó, como evento "crash"."""
    t = time.time()
    compose("kill", "-s", "SIGKILL", f"bully{no}", env=env)
    evento = {"seq": 0, "ts": t, "node": no, "run_id": run_id, "inc": 0, "event": "crash"}
    with open(PASTA_LOGS / f"node{no}.jsonl", "a") as f:
        f.write(json.dumps(evento) + "\n")


def http(no, caminho, metodo="GET"):
    req = urllib.request.Request(f"http://localhost:{PORT_PREFIX}{no}{caminho}", method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=0.5) as r:
            return json.loads(r.read())
    except (OSError, ValueError):
        return None


def esperar(condicao, prazo, passo=0.02):
    fim = time.time() + prazo
    while time.time() < fim:
        if condicao():
            return True
        time.sleep(passo)
    return False


def todos_concordam(nos, lider):
    for no in nos:
        s = http(no, "/status")
        if not s or s["leader"] != lider or s["electing"]:
            return False
    return True


def rodar(n, cenario, rep):
    run_id = f"exp_n{n}_{cenario}_r{rep}_{int(time.time())}"
    env = {**os.environ, "N": str(n), "RUN_ID": run_id, "LOG_GROUP": GRUPO, "AUTO_START": "0",
           "MONITOR": "1" if cenario == "recuperacao" else "0",
           "T_OK_MS": str(T_OK_MS), "T_COORD_MS": str(T_COORD_MS), "PING_MS": str(PING_MS)}
    iniciador = {"pior": 1, "melhor": n - 1}.get(cenario)
    try:
        compose("up", "-d", *[f"bully{i}" for i in range(1, n + 1)], env=env)
        if not esperar(lambda: all(http(i, "/status") for i in range(1, n + 1)), 30):
            print("   ERRO: nem todos os nós responderam")
            return
        http(n, "/trigger", "POST")
        if not esperar(lambda: todos_concordam(range(1, n + 1), n), 30):
            print(f"   ERRO: o nó {n} não foi eleito")
            return
        time.sleep(AQUECIMENTO)

        derrubar(n, run_id, env)
        esperar(lambda: http(n, "/ping") is None, 5)
        if iniciador:
            http(iniciador, "/trigger", "POST")
        if not esperar(lambda: todos_concordam(range(1, n), n - 1), 15):
            print(f"   ERRO: os sobreviventes não convergiram para o nó {n - 1}")
        time.sleep(ASSENTAR)
    finally:
        compose("down", "-t", "1", env=env)



def ler_execucoes():
    execucoes = {}
    for arquivo in PASTA_LOGS.glob("node*.jsonl"):
        for linha in arquivo.read_text().splitlines():
            try:
                e = json.loads(linha)
            except ValueError:
                continue
            execucoes.setdefault(e["run_id"], []).append(e)
    return {run_id: sorted(ev, key=lambda e: e["ts"]) for run_id, ev in execucoes.items()}


def teorico_total(n, k):
    election = (n - k) * (n - k + 1) // 2
    ok = (n - k - 1) * (n - k) // 2
    return election + ok + (n - 2)


def analisar(run_id, ev):
    """Calcula as métricas de uma execução a partir dos seus eventos (uma linha de execucoes.csv)."""
    _, n_txt, cenario, rep_txt, _ = run_id.split("_")
    n, rep = int(n_txt[1:]), int(rep_txt[1:])
    linha = {"run_id": run_id, "n": n, "cenario": cenario, "rep": rep, "convergiu": 0}
    sobreviventes, novo = range(1, n), n - 1

    quedas = [e["ts"] for e in ev if e["node"] == n and e["event"] == "crash"]
    if not quedas:
        return linha
    t_crash = quedas[0]

    inicio = "leader_down" if cenario == "recuperacao" else "trigger"
    inicios = [e for e in ev if e["event"] == inicio and e["ts"] >= t_crash]
    if not inicios:
        return linha
    t0, iniciador = inicios[0]["ts"], inicios[0]["node"]

    aceitacoes = []
    for e in ev:
        if e["ts"] >= t0 and e["node"] in sobreviventes:
            if e["event"] == "become_leader":
                aceitacoes.append((e["node"], e["ts"], e["node"]))
            elif e["event"] == "recv_coordinator":
                aceitacoes.append((e["node"], e["ts"], e["peer"]))

    aceite = {}  # quando cada sobrevivente aceitou o nó N-1 pela primeira vez
    for no, ts, lider in aceitacoes:
        if lider == novo:
            aceite.setdefault(no, ts)
    if len(aceite) < len(sobreviventes):
        return linha  # alguém nunca aceitou o nó N-1

    t_fim = max(aceite.values())
    ultimo = {no: lider for no, ts, lider in aceitacoes if ts <= t_fim + JANELA}
    if any(ultimo[s] != novo for s in sobreviventes):
        return linha  # alguém terminou aceitando outro líder

    janela = [e for e in ev if t0 <= e["ts"] <= t_fim + JANELA and e["node"] in sobreviventes]
    envios = [e for e in janela if e["event"] == "send"]
    election = sum(e["kind"] == "election" for e in envios)
    ok = sum(e["kind"] == "election" and e["ok"] for e in envios)
    coordinator = sum(e["kind"] == "coordinator" for e in envios)
    linha.update(
        convergiu=1, iniciador=iniciador,
        eleicoes=sum(e["event"] == "election_start" for e in janela),
        eleicao_ms=round((t_fim - t0) * 1000, 1),
        msgs_election=election, msgs_ok=ok, msgs_coordinator=coordinator,
        msgs_total=election + ok + coordinator,
    )
    if cenario == "recuperacao":
        linha.update(deteccao_ms=round((t0 - t_crash) * 1000, 1),
                     recuperacao_ms=round((t_fim - t_crash) * 1000, 1))
    else:
        linha["msgs_teorico"] = teorico_total(n, iniciador)
    return linha


def extrair():
    execucoes = ler_execucoes()
    linhas = [analisar(run_id, ev) for run_id, ev in sorted(execucoes.items())
              if run_id.startswith("exp_")]
    if not linhas:
        print(f"Nenhuma execução nos logs de {PASTA_LOGS}")
        return
    PASTA_RESULTADOS.mkdir(exist_ok=True)
    caminho = PASTA_RESULTADOS / "execucoes.csv"
    with open(caminho, "w", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUNAS)
        escritor.writeheader()
        escritor.writerows(linhas)
    sem_convergir = [l["run_id"] for l in linhas if not l["convergiu"]]
    print(f"{len(linhas)} linhas em {caminho}")
    if sem_convergir:
        print(f"ATENÇÃO: {len(sem_convergir)} execuções sem convergir: {', '.join(sem_convergir)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=10, help="repetições por configuração")
    ap.add_argument("--so-extrair", action="store_true", help="não roda nada, só gera o CSV")
    args = ap.parse_args()

    if not args.so_extrair:
        compose("build", *[f"bully{i}" for i in range(1, max(NIVEIS_N) + 1)])
        total = args.reps * len(NIVEIS_N) * len(CENARIOS)
        print(f"{total} execuções, cerca de {total * 5 // 60} min")
        i = 0
        for rep in range(1, args.reps + 1):
            for n in NIVEIS_N:
                for cenario in CENARIOS:
                    i += 1
                    print(f"[{i}/{total}] N={n}, {cenario}, repetição {rep}", flush=True)
                    rodar(n, cenario, rep)
    extrair()


if __name__ == "__main__":
    main()
