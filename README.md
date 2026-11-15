# MC714 — Trabalho 2

Implementação e avaliação experimental de dois algoritmos distribuídos: Bully e Heartbeat.

## Preparação

Execute os comandos deste README a partir da raiz do repositório, onde está o `compose.yaml`.
São necessários Python 3.10 ou superior, Docker com Docker Compose v2 ou compatível, Bash e `curl`.
O Docker deve estar em execução e acessível ao usuário:

```bash
docker compose version
docker info
```

### Dependências Python

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r bully/requirements-dev.txt -r heartbeat/requirements-dev.txt
```

Os testes unitários e as análises usam esse ambiente Python. Os nós executados pelo Compose
usam as dependências instaladas nas respectivas imagens.

Se `docker info` retornar erro de permissão e o Docker estiver disponível via `sudo`,
execute os comandos Docker e os scripts que os chamam com `sudo`. Para os testes de integração,
use `sudo .venv/bin/python -m pytest ...` para preservar o uso das dependências do ambiente virtual.

Execute as suítes de Bully e Heartbeat em chamadas separadas do pytest, como mostrado abaixo.
Atualmente, coletar ambas na mesma chamada causa um conflito de importação entre os arquivos `node.py`.
Os testes de integração e os experimentos usam o mesmo projeto Compose; execute uma atividade por vez
e remova o ambiente anterior antes de iniciar a próxima.

## Bully

### Comandos para construir, subir, inspecionar e remover

```bash
export N=5 RUN_ID=manual_bully
docker compose --profile bully up -d --build bully1 bully2 bully3 bully4 bully5

curl localhost:8001/status                       # líder visto pelo nó 1
curl localhost:8001/metrics                      # mensagens enviadas por tipo
docker compose --profile bully kill bully5       # derruba o líder (queda abrupta)
docker compose --profile bully start bully5      # o nó 5 volta e retoma a liderança
curl -X POST localhost:8001/trigger              # força uma eleição no nó 1

docker compose --profile bully down -t 1         # remove contêineres e rede
```

A eleição é assíncrona em relação aos comandos: aguarde a estabilização e consulte `/status`
após subir, derrubar ou reiniciar um nó. Com todos ativos, o líder esperado é o nó 5;
enquanto ele estiver parado, o líder esperado é o nó 4.

### Demonstração (cenário normal, falha injetada e recuperação)

```bash
./bully/demo.sh
```

Os logs da demonstração ficam em `logs/bully/<RUN_ID>/`. Se `RUN_ID` não estiver definido,
o script usa `demo_<timestamp>`; se estiver exportado, usa o valor existente.

### Testes

```bash
python3 -m pytest bully/tests/test_unit.py -q         # sem Docker

python3 -m pytest bully/tests/test_integration.py -q  # requer Docker
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
separa as execuções). Rodadas adicionais acumulam execuções nesses logs; para iniciar um conjunto independente,
arquive a pasta de logs anterior antes de rodar novamente. Os resultados ficam em `bully/resultados/` (`execucoes.csv`, `resumo.csv`, `eleicao.png`, `mensagens.png` e
`recuperacao.png`). Se as portas 8001..8009 estiverem ocupadas, use `PORT_PREFIX=810 python3 bully/experimento.py`.

O CSV versionado contém 20 execuções por configuração, enquanto o resumo salvo registra 10.
Regenere o resumo e os gráficos com `python3 bully/analise.py` antes de usá-los na análise final.
O comando `--so-extrair` depende dos logs JSONL originais, que não estão incluídos neste checkout;
o comando de análise pode ser executado diretamente sobre o CSV existente.

## Heartbeat

### Comandos para construir, subir e remover

```bash
export N=5 RUN_ID=manual_heartbeat T_MS=250 K=3 LOSS=0 SEED=0
docker compose --profile heartbeat up -d --build node1 node2 node3 node4 node5
docker compose --profile heartbeat kill node3   # queda abrupta do nó 3
docker compose --profile heartbeat start node3  # os outros restauram a confiança nele
docker compose --profile heartbeat down -t 1
```

Logs em `heartbeat/logs/<RUN_ID>/node<i>.jsonl`. Aguarde alguns segundos entre as etapas para
observar os eventos `suspect` após a queda e `restore` após o reinício. Com esses parâmetros,
o limiar de silêncio para suspeitar é K × T = 750 ms.

### Demonstração

```bash
./heartbeat/demo.sh
```

Se o acesso ao Docker exigir `sudo`, use `sudo ./heartbeat/demo.sh`.

A tabela no terminal mostra os heartbeats recebidos e os suspeitos de cada nó.
Pressione Enter para derrubar o nó 3, Enter para reiniciá-lo e Enter para encerrar.
Cada etapa atualiza a tabela por 5 segundos e depois pausa para a explicação do vídeo.
O demo usa 5 nós, T = 500 ms, K = 3 e nenhuma perda de mensagens.
Os eventos `suspect` e `restore` aparecem abaixo da tabela, lidos dos logs dos nós.
Os contêineres são removidos ao encerrar, e os logs ficam em `heartbeat/logs/demo_<timestamp>_<pid>/`.

### Testes

```bash
python3 -m pytest heartbeat/tests/test_detector.py -q  # sem Docker
python3 -m pytest heartbeat/tests/test_normal.py -q    # requer Docker
python3 -m pytest heartbeat/tests/test_falha.py -q     # requer Docker
```

### Experimentos

```bash
python3 heartbeat/experimento.py               # 5 configurações × 5 repetições; gera heartbeat/resultados/*.csv
python3 heartbeat/experimento.py --reps 10      # alternativa: 10 repetições por configuração
python3 heartbeat/experimento.py --so-extrair   # refaz os CSVs a partir dos logs já gravados
python3 heartbeat/analise.py                   # analisa os novos CSVs em heartbeat/resultados/
```

O experimento usa 5 nós, K = 3 e derruba o nó 3. Varia T em 100, 250 e 500 ms sem perda
e a perda em 0%, 10% e 30% com T = 250 ms, totalizando 5 configurações distintas.
Cada execução tem 5 s de aquecimento, 15 s de regime normal e 5 s após a falha,
além do tempo para iniciar e remover os contêineres. A semente corresponde ao número da repetição.

Os logs de novas execuções ficam em `heartbeat/logs/exp_*/`. A extração lê todas as pastas `exp_*`
nesse diretório; arquive rodadas anteriores se quiser analisar apenas um novo conjunto.
`--so-extrair` requer esses logs, que não estão incluídos neste checkout.

### Analisar os dados já incluídos no repositório

Os CSVs versionados do Heartbeat estão em `heartbeat/resultados/`, com 8 repetições por configuração.
Os experimentos e a análise usam essa mesma pasta por padrão. Para regenerar o resumo e os gráficos:

```bash
python3 heartbeat/analise.py
```

Esse comando lê `execucoes.csv` e `deteccoes.csv` e sobrescreve `resumo.csv`, `deteccao.png`,
`falsos_positivos.png` e `mensagens.png` em `heartbeat/resultados/`. Novos experimentos também
sobrescrevem os CSVs nessa pasta; arquive o conjunto existente antes de substituí-lo, caso queira preservá-lo.
Para analisar dados em outra pasta, use `python3 heartbeat/analise.py caminho/da/pasta`.
As definições e limitações das métricas existentes estão em `heartbeat/resultados/verificacao.txt`.
