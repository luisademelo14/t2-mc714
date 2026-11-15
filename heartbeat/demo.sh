#!/usr/bin/env bash
# Demonstração para o vídeo: funcionamento normal, queda e recuperação do nó 3.
# Uso: sudo ./heartbeat/demo.sh
set -euo pipefail
cd "$(dirname "$0")/.."

export N=5
export T_MS=500
export K=3
export LOSS=0
export SEED=0
export RUN_ID="demo_$(date +%s)_$$"

# Um projeto separado evita derrubar os contêineres dos experimentos ou do Bully.
COMPOSE=(docker compose -p "heartbeat-demo-$$" --profile heartbeat)
NOS=(node1 node2 node3 node4 node5)
LOGS="heartbeat/logs/$RUN_ID"

limpar() {
    "${COMPOSE[@]}" down -t 1
    # Devolve os logs ao usuário que chamou sudo, para não atrapalhar o Git.
    if [[ "$EUID" -eq 0 && -n "${SUDO_UID:-}" && -d "$LOGS" ]]; then
        chown -R "$SUDO_UID:$SUDO_GID" "$LOGS"
    fi
    echo "Logs desta demonstração: $LOGS/"
}

pausar() {
    if [[ -t 0 ]]; then
        read -r -p "$1 [Enter] "
    fi
}

trap limpar EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "Subindo 5 nós, sem perda de mensagens. Timeout: $((K * T_MS)) ms."
"${COMPOSE[@]}" up -d --build "${NOS[@]}"
echo "Aquecimento de 5 segundos..."
sleep 5

python3 heartbeat/monitor_demo.py "$LOGS" "1/3 - Todos os nós ativos" 0
pausar "Observe que ninguém é suspeito. Derrubar o nó 3?"

"${COMPOSE[@]}" kill node3
python3 heartbeat/monitor_demo.py "$LOGS" "2/3 - Nó 3 parado: aguardando as suspeitas" 3
pausar "Observe os nós 1, 2, 4 e 5 suspeitando do nó 3. Reiniciar o nó 3?"

"${COMPOSE[@]}" start node3
python3 heartbeat/monitor_demo.py "$LOGS" "3/3 - Nó 3 reiniciado: aguardando a recuperação" 0
pausar "Observe os eventos de recuperação e as listas de suspeitos vazias. Encerrar?"
