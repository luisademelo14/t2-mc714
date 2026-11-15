# MC714 — Trabalho 2

Implementação e avaliação experimental de dois algoritmos distribuídos: Bully e Heartbeat.

### Dependências Python

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r bully/requirements-dev.txt       # para o bully
pip install -r heartbeat/requirements-dev.txt   # para o heartbeat
```
---

## Bully

### Comandos para construir, subir, inspecionar e remover

```bash
export COMPOSE_PROFILES=bully                    # evita repetir --profile bully
N=5 RUN_ID=manual docker compose up -d --build bully1 bully2 bully3 bully4 bully5

curl localhost:8001/status                       # líder visto pelo nó 1
curl localhost:8001/metrics                      # mensagens enviadas por tipo
docker compose kill bully5                       # derruba o líder (queda abrupta)
docker compose start bully5                      # o nó 5 volta e retoma a liderança
curl -X POST localhost:8001/trigger              # força uma eleição no nó 1

docker compose down -t 1                         # remove contêineres e rede
```

### Demonstração (cenário normal, falha injetada e recuperação)

```bash
./bully/demo.sh
```

Os logs da demonstração ficam em `logs/bully/demo_<timestamp>/`.

### Testes

```bash
python3 -m pytest bully/tests/test_unit.py -q

python3 -m pytest bully/tests/test_integration.py -q
```

### Experimentos

```bash
python3 bully/experimento.py               # roda tudo (N = 3, 5, 7, 9 x 3 cenários x 10 repetições, ~10 min)
python3 bully/experimento.py --reps 5      # menos repetições
python3 bully/experimento.py --so-extrair  # refaz o CSV a partir dos logs já gravados

python3 bully/analise.py                   # resumo.csv e gráficos em bully/resultados/
```

Cenários: `pior` (o nó 1 inicia a eleição), `melhor` (o nó N−1 inicia) e `recuperacao` (monitor ligado,
os seguidores detectam a queda por ping). Os logs ficam em `logs/bully/experimento/node<i>.jsonl` (um arquivo por nó; o campo `run_id`
separa as execuções; apague a pasta para recomeçar do zero) e os resultados em `bully/resultados/` (`execucoes.csv`, `resumo.csv`, `eleicao.png`, `mensagens.png` e
`recuperacao.png`). Se as portas 8001..8009 estiverem ocupadas, use `PORT_PREFIX=810 python3 bully/experimento.py`.

## Heartbeat

### Comandos para construir, subir e remover

```bash
export COMPOSE_PROFILES=heartbeat
N=5 RUN_ID=manual docker compose up -d --build node1 node2 node3 node4 node5
docker compose kill node3                  # queda abrupta do nó 3
docker compose start node3                 # os outros restauram a confiança nele
docker compose down -t 1
```

Logs em `heartbeat/logs/<RUN_ID>/node<i>.jsonl`.

### Demonstração

```bash
sudo ./heartbeat/demo.sh
```

A tabela no terminal mostra os heartbeats recebidos e os suspeitos de cada nó.
Pressione Enter para derrubar o nó 3, Enter para reiniciá-lo e Enter para encerrar.
Cada etapa atualiza a tabela por 5 segundos e depois pausa para a explicação do vídeo.
O demo usa 5 nós, T = 500 ms, K = 3 e nenhuma perda de mensagens.
Os eventos `suspect` e `restore` aparecem abaixo da tabela, lidos dos logs dos nós.
Os contêineres são removidos ao encerrar, e os logs ficam em `heartbeat/logs/demo_<timestamp>_<pid>/`.
O comando `sudo ./demo.sh`, na raiz, também inicia essa demonstração.

### Testes

```bash
python3 -m pytest heartbeat/tests/test_detector.py -q  # sem Docker
sudo python3 -m pytest heartbeat/tests/test_normal.py -q
sudo python3 -m pytest heartbeat/tests/test_falha.py -q
```

### Experimentos

```bash
cd heartbeat
python3 experimento.py                     # roda tudo e gera resultados/*.csv (~15 min)
python3 experimento.py --reps 10
python3 experimento.py --so-extrair        # refaz os CSVs a partir dos logs já gravados
python3 analise.py                         # resumo.csv e gráficos em resultados/
```
