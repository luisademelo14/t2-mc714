import asyncio
import json
import os
import time
from collections import Counter, deque
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

NODE_ID = int(os.environ["NODE_ID"])
N = int(os.environ.get("N", "5"))
PORT = int(os.environ.get("PORT", "8000"))
PEER_URL = os.environ.get("PEER_URL", "http://node{id}:8000")
T_OK = int(os.environ.get("T_OK_MS", "300")) / 1000
T_COORD = int(os.environ.get("T_COORD_MS", "1000")) / 1000
PING_S = int(os.environ.get("PING_MS", "200")) / 1000
RUN_ID = os.environ.get("RUN_ID", "run")
LOG_DIR = os.environ.get("LOG_DIR", "")
START_WAIT = int(os.environ.get("START_WAIT_MS", "3000")) / 1000
AUTO_START = os.environ.get("AUTO_START", "1") == "1"
MONITOR = os.environ.get("MONITOR", "1") == "1"
EVENTS = deque(maxlen=500)
SEQ = 0


def open_logfile():
    if not LOG_DIR:
        return None, 0
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, f"node{NODE_ID}.jsonl")
    inc = 0
    if os.path.exists(path):
        with open(path) as f:
            inc = sum('"event": "boot"' in line for line in f)
    return open(path, "a", buffering=1), inc


LOGFILE, INC = open_logfile()


def log(event, **kw):
    global SEQ
    SEQ += 1
    rec = {"seq": SEQ, "ts": time.time(), "node": NODE_ID, "run_id": RUN_ID,
           "inc": INC, "event": event, **kw}
    EVENTS.append(rec)
    line = json.dumps(rec)
    print(line, flush=True)
    if LOGFILE:
        LOGFILE.write(line + "\n")


class ElectionMsg(BaseModel):
    from_id: int


class CoordMsg(BaseModel):
    leader_id: int


class Node:
    def __init__(self, node_id=NODE_ID, n=N):
        self.id = node_id
        self.peers = [i for i in range(1, n + 1) if i != node_id]
        self.leader = None
        self.electing = False
        self.coordinator_event = asyncio.Event()
        self.heard = 0
        self.sent = Counter()
        self.client = httpx.AsyncClient()
        self.tasks = set()
        self.t_start = None
        self.t_done = None

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def call(self, peer, path, kind, body=None):
        self.sent[kind] += 1
        try:
            r = await self.client.request(
                "POST" if body else "GET",
                PEER_URL.format(id=peer) + path,
                json=body,
                timeout=T_OK,
            )
            ok = r.status_code == 200
        except httpx.HTTPError:
            ok = False
        log("send", kind=kind, peer=peer, ok=ok)
        return ok

    def send_election(self, peer):
        return self.call(peer, "/election", "election", {"from_id": self.id})

    def send_coordinator(self, peer):
        return self.call(peer, "/coordinator", "coordinator", {"leader_id": self.id})

    def ping(self, peer):
        return self.call(peer, "/ping", "ping")

    async def reachable(self, peer):
        try:
            r = await self.client.get(PEER_URL.format(id=peer) + "/ping", timeout=T_OK)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def wait_peers(self):
        start = time.time()
        pending = set(self.peers)
        while pending and time.time() - start < START_WAIT:
            peers = sorted(pending)
            up = await asyncio.gather(*(self.reachable(p) for p in peers))
            pending -= {p for p, ok in zip(peers, up) if ok}
            if pending:
                await asyncio.sleep(0.05)
        log("start_barrier", waited_ms=round((time.time() - start) * 1000), missing=sorted(pending))

    async def boot_election(self):
        await self.wait_peers()
        await self.start_election()

    async def start_election(self):
        if self.electing:
            return
        self.electing = True
        self.t_start = time.time()
        self.coordinator_event.clear()
        log("election_start")
        try:
            while True:
                higher = [p for p in self.peers if p > self.id]
                self.heard = 0
                replies = await asyncio.gather(*(self.send_election(p) for p in higher))
                alive = [p for p, ok in zip(higher, replies) if ok]
                if not alive:
                    await self.become_leader()
                    return
                try:
                    await asyncio.wait_for(self.wait_coordinator(max(alive)), T_COORD)
                    return
                except asyncio.TimeoutError:
                    log("coordinator_timeout")
        finally:
            self.electing = False

    async def wait_coordinator(self, min_id):
        while self.heard < min_id:
            self.coordinator_event.clear()
            await self.coordinator_event.wait()

    async def become_leader(self):
        self.leader = self.id
        self.t_done = time.time()
        log("become_leader")
        await asyncio.gather(*(self.send_coordinator(p) for p in self.peers if p < self.id))

    async def monitor(self):
        while True:
            await asyncio.sleep(PING_S)
            if self.electing or self.leader in (None, self.id):
                continue
            leader = self.leader
            ok = await self.ping(leader)
            if not ok and self.leader == leader and not self.electing:
                log("leader_down", leader=leader)
                await self.start_election()


node = Node()

@asynccontextmanager
async def lifespan(app):
    log("boot", n=N, peers=node.peers, t_ok_ms=int(T_OK * 1000),
        t_coord_ms=int(T_COORD * 1000), ping_ms=int(PING_S * 1000),
        auto_start=AUTO_START, monitor=MONITOR, start_wait_ms=int(START_WAIT * 1000))
    if AUTO_START:
        node.spawn(node.boot_election())
    if MONITOR:
        node.spawn(node.monitor())
    yield


app = FastAPI(lifespan=lifespan)


@app.post("/election")
async def on_election(msg: ElectionMsg):
    node.sent["ok"] += 1
    log("recv_election", peer=msg.from_id)
    node.spawn(node.start_election())
    return {"ok": True}


@app.post("/coordinator")
async def on_coordinator(msg: CoordMsg):
    log("recv_coordinator", peer=msg.leader_id)
    node.leader = msg.leader_id
    node.heard = max(node.heard, msg.leader_id)
    node.t_done = time.time()
    node.coordinator_event.set()
    return {"ok": True}


@app.get("/ping")
async def ping():
    return {"id": node.id}


@app.get("/status")
async def status():
    return {
        "id": node.id,
        "leader": node.leader,
        "electing": node.electing,
        "t_start": node.t_start,
        "t_done": node.t_done,
    }


@app.post("/trigger")
async def trigger():
    log("trigger")
    node.spawn(node.start_election())
    return {"started": True}


@app.post("/crash")
async def crash():
    log("crash")
    asyncio.get_running_loop().call_later(0.01, os._exit, 1)
    return {"crashing": True}


@app.get("/metrics")
async def metrics():
    return dict(node.sent)

@app.get("/snapshot")
async def snapshot(after: int = 0):
    return {
        "n": N,
        "status": {"leader": node.leader, "electing": node.electing},
        "metrics": dict(node.sent),
        "events": [e for e in EVENTS if e["seq"] > after],
        "next": SEQ,
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")