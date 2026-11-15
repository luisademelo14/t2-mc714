import asyncio
import json
import os
import random
import time

from detector import FailureDetector

# Configuração via variáveis de ambiente
NODE_ID = int(os.environ["NODE_ID"])
N = int(os.environ["N"])
T = int(os.environ.get("T_MS", "250")) / 1000  # período do heartbeat (s)
K = int(os.environ.get("K", "3"))              # suspeito após K*T sem heartbeat
LOSS = float(os.environ.get("LOSS", "0"))      # probabilidade de descartar cada heartbeat enviado (0 a 1)
SEED = int(os.environ.get("SEED", "0"))        # semente da perda, registrada no log para repetir o ensaio
RUN_ID = os.environ.get("RUN_ID", "run")
LOG_DIR = os.environ.get("LOG_DIR", "/logs")
PORT = 5000


class Node(asyncio.DatagramProtocol):
    def __init__(self):
        self.peers = [i for i in range(1, N + 1) if i != NODE_ID]
        self.detector = FailureDetector(self.peers, K * T, time.monotonic())
        self.incarnation = int(time.time() * 1000)  # muda a cada (re)início do nó
        self.seq = 0
        # Gerador próprio por nó: com a mesma SEED, cada nó descarta sempre as mesmas mensagens.
        self.rng = random.Random(SEED * 1000 + NODE_ID)
        self.transport = None
        os.makedirs(LOG_DIR, exist_ok=True)
        self.logfile = open(f"{LOG_DIR}/node{NODE_ID}.jsonl", "a", buffering=1)

    def log(self, event, **campos):
        linha = {
            "ts_wall": time.time(),
            "ts_mono": time.monotonic(),
            "run_id": RUN_ID,
            "node": NODE_ID,
            "event": event,
        }
        linha.update(campos)
        self.logfile.write(json.dumps(linha) + "\n")

    # --- recebimento ---

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        msg = json.loads(data)
        peer = msg["from"]
        self.log("hb_recv", peer=peer, seq=msg["seq"])

        restaurado = self.detector.on_heartbeat(peer, msg["inc"], msg["seq"], time.monotonic())
        if restaurado:
            self.log("restore", peer=peer)

    # --- envio ---

    async def send_loop(self):
        proximo = time.monotonic()
        while True:
            self.seq += 1
            msg = json.dumps({"from": NODE_ID, "inc": self.incarnation, "seq": self.seq}).encode()
            descartadas = 0
            for peer in self.peers:
                # Simula perda na rede: o heartbeat nem sai do nó.
                if self.rng.random() < LOSS:
                    descartadas += 1
                    continue
                try:
                    self.transport.sendto(msg, (f"node{peer}", PORT))
                except OSError:
                    pass  # par fora do ar (o nome some do DNS do Docker)
            # msgs = quantas foram tentadas; dropped = quantas a perda simulada descartou
            self.log("hb_sent", seq=self.seq, msgs=len(self.peers), dropped=descartadas)

            # agenda pelo prazo absoluto, para o período não acumular atraso
            proximo += T
            await asyncio.sleep(max(0, proximo - time.monotonic()))

    # --- verificação de suspeitos ---

    async def check_loop(self):
        while True:
            for peer, silencio in self.detector.check(time.monotonic()):
                self.log("suspect", peer=peer, silence_ms=round(silencio * 1000))
            await asyncio.sleep(T / 10)


async def main():
    node = Node()
    loop = asyncio.get_running_loop()
    await loop.create_datagram_endpoint(lambda: node, local_addr=("0.0.0.0", PORT))
    node.log("start", n=N, t_ms=int(T * 1000), k=K, loss=LOSS, seed=SEED)
    await asyncio.gather(node.send_loop(), node.check_loop())


asyncio.run(main())