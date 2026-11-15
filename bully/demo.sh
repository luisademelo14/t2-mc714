#!/usr/bin/env bash

set -euo pipefail
cd "$(dirname "$0")/.."

export N=5
export T_OK_MS=300
export T_COORD_MS=1000
export PING_MS=200
export COMPOSE_PROFILES=bully
export RUN_ID="${RUN_ID:-demo_$(date +%s)}"
LOG_DIR="logs/bully/$RUN_ID"

COMPOSE="docker compose"
NOS="bully1 bully2 bully3 bully4 bully5"
LIDER=bully5
LIDER_ID=5

passo() { printf '\n\033[1;36m== %s\033[0m\n' "$1"; }

agora() { python3 -c 'import time; print(time.time())'; }

consultar() {
    $COMPOSE exec -T "$1" python -c '
import os, sys, urllib.request
porta = os.environ.get("PORT", "8000")
print(urllib.request.urlopen("http://localhost:" + porta + sys.argv[1]).read().decode())
' "$2"
}

lider_de() {
    consultar "$1" /status | python3 -c 'import json, sys; print(json.load(sys.stdin)["leader"])'
}

mostrar_lideres() {
    for no in "$@"; do
        echo "  $no enxerga como líder: nó $(lider_de "$no")"
    done
}

mostrar_metricas() {
    for no in "$@"; do
        echo "  $no: $(consultar "$no" /metrics)"
    done
}

mostrar_eventos() {
    DESDE="$1" LOG_DIR="$LOG_DIR" python3 - <<'EOF'
import glob, json, os

desde = float(os.environ["DESDE"])
descricao = {
    "election_start": lambda e: "iniciou uma eleição",
    "leader_down": lambda e: f"detectou a queda do líder (nó {e['leader']})",
    "become_leader": lambda e: "virou líder e anunciou COORDINATOR",
    "recv_coordinator": lambda e: f"aceitou o nó {e['peer']} como líder",
    "coordinator_timeout": lambda e: "timeout esperando COORDINATOR, refazendo a eleição",
}

achados = []
for arq in glob.glob(os.path.join(os.environ["LOG_DIR"], "node*.jsonl")):
    with open(arq) as f:
        for linha in f:
            try:
                e = json.loads(linha)
            except ValueError:
                continue
            if e.get("event") in descricao and e["ts"] >= desde:
                achados.append(e)

if not achados:
    print("  (nenhum evento)")
for e in sorted(achados, key=lambda e: e["ts"]):
    print(f"  +{e['ts'] - desde:5.2f}s  nó {e['node']}: {descricao[e['event']](e)}")
EOF
}

passo "1) Subindo $N nós (todos iniciam uma eleição no boot). Logs em $LOG_DIR/"
$COMPOSE up -d --build $NOS

passo "2) Aquecimento de 5 s: o nó de maior id deve vencer"
sleep 5
echo "Eventos desde o boot:"
mostrar_eventos 0
echo
echo "Líder visto por cada nó (esperado: nó $LIDER_ID):"
mostrar_lideres $NOS

passo "3) Matando o líder $LIDER com docker kill"
T_KILL=$(agora)
$COMPOSE kill $LIDER

passo "4) Esperando a detecção e a nova eleição"
sleep 4
echo "O que aconteceu depois do kill:"
mostrar_eventos "$T_KILL"
echo
echo "Líder visto pelos nós vivos (esperado: nó $((LIDER_ID - 1))):"
mostrar_lideres bully1 bully2 bully3 bully4

passo "5) Reiniciando $LIDER: o nó de maior id retoma a liderança"
T_RESTART=$(agora)
$COMPOSE start $LIDER
sleep 4
echo "O que aconteceu depois do restart:"
mostrar_eventos "$T_RESTART"
echo
echo "Líder visto por cada nó (esperado: nó $LIDER_ID):"
mostrar_lideres $NOS

passo "6) Mensagens enviadas por cada nó (contadores desde o último boot)"
mostrar_metricas $NOS

passo "7) Limpando o ambiente (os logs continuam em $LOG_DIR/)"
$COMPOSE down