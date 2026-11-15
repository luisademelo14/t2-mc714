import asyncio

import node as bully


def make(node_id, n=5, up=()):
    nd = bully.Node(node_id, n)
    nd.msgs = []

    async def send_election(peer):
        nd.msgs.append(("election", peer))
        return peer in up

    async def send_coordinator(peer):
        nd.msgs.append(("coordinator", peer))
        return True

    nd.send_election = send_election
    nd.send_coordinator = send_coordinator
    return nd


def test_highest_id_becomes_leader_and_announces_to_all_lower():
    nd = make(5)

    async def go():
        nd.coordinator_event = asyncio.Event()
        await nd.start_election()

    asyncio.run(go())
    assert nd.leader == 5
    assert sorted(m for m in nd.msgs if m[0] == "coordinator") == [("coordinator", p) for p in (1, 2, 3, 4)]
    assert not any(m[0] == "election" for m in nd.msgs)


def test_becomes_leader_when_no_higher_node_replies():
    nd = make(2, up=())

    async def go():
        nd.coordinator_event = asyncio.Event()
        await nd.start_election()

    asyncio.run(go())
    assert nd.leader == 2
    assert sorted(m for m in nd.msgs if m[0] == "election") == [("election", 3), ("election", 4), ("election", 5)]
    assert [m for m in nd.msgs if m[0] == "coordinator"] == [("coordinator", 1)]


def test_waits_for_coordinator_when_a_higher_node_replies():
    nd = make(2, up=(5,))

    async def go():
        nd.coordinator_event = asyncio.Event()
        task = asyncio.create_task(nd.start_election())
        await asyncio.sleep(0.05)
        assert nd.electing
        nd.leader = nd.heard = 5
        nd.coordinator_event.set()
        await task

    asyncio.run(go())
    assert nd.leader == 5
    assert not nd.electing
    assert not any(m[0] == "coordinator" for m in nd.msgs)


def test_restarts_election_when_coordinator_never_arrives(monkeypatch):
    monkeypatch.setattr(bully, "T_COORD", 0.05)
    nd = make(2)
    rounds = {"n": 0}

    async def send_election(peer):
        if peer == 5:
            rounds["n"] += 1
            return rounds["n"] == 1
        return False

    nd.send_election = send_election

    async def go():
        nd.coordinator_event = asyncio.Event()
        await asyncio.wait_for(nd.start_election(), 2)

    asyncio.run(go())
    assert rounds["n"] == 2
    assert nd.leader == 2


def test_second_start_while_electing_is_ignored():
    nd = make(2, up=(5,))

    async def go():
        nd.coordinator_event = asyncio.Event()
        first = asyncio.create_task(nd.start_election())
        await asyncio.sleep(0.01)
        await nd.start_election()
        nd.leader = nd.heard = 5
        nd.coordinator_event.set()
        await first

    asyncio.run(go())
    assert nd.msgs.count(("election", 5)) == 1

def test_failed_ping_to_old_leader_does_not_depose_new_leader(monkeypatch):
    monkeypatch.setattr(bully, "PING_S", 0.01)
    nd = make(2, up=(4,))
    nd.leader = 5
    pinged = []

    async def ping(peer):
        pinged.append(peer)
        if peer == 5:
            nd.leader = 4
            return False
        return True

    nd.ping = ping

    async def go():
        nd.coordinator_event = asyncio.Event()
        task = asyncio.create_task(nd.monitor())
        await asyncio.sleep(0.1)
        task.cancel()

    asyncio.run(go())
    assert nd.leader == 4
    assert not any(m[0] == "election" for m in nd.msgs)
    assert set(pinged) == {5, 4}



def test_coordinator_from_lower_id_does_not_end_wait_for_higher_node(monkeypatch):
    monkeypatch.setattr(bully, "T_COORD", 0.05)
    nd = make(1, up=(5,))
    rounds = {"n": 0}

    async def send_election(peer):
        if peer == 5:
            rounds["n"] += 1
            if rounds["n"] == 1:
                nd.heard = 3
                nd.coordinator_event.set()
                return True
            nd.leader = nd.heard = 5
            nd.coordinator_event.set()
            return True
        return False

    nd.send_election = send_election

    async def go():
        nd.coordinator_event = asyncio.Event()
        await asyncio.wait_for(nd.start_election(), 2)

    asyncio.run(go())
    assert rounds["n"] == 2
    assert nd.leader == 5



def test_barrier_returns_as_soon_as_all_peers_respond():
    nd = make(2, n=4)
    calls = {"n": 0}

    async def reachable(peer):
        calls["n"] += 1
        return calls["n"] > 3

    nd.reachable = reachable

    async def go():
        await asyncio.wait_for(nd.wait_peers(), 2)

    asyncio.run(go())
    assert calls["n"] >= 6


def test_barrier_gives_up_after_deadline_when_a_peer_never_answers(monkeypatch):
    monkeypatch.setattr(bully, "START_WAIT", 0.2)
    nd = make(1, n=3)

    async def reachable(peer):
        return peer == 2

    nd.reachable = reachable

    async def go():
        t = asyncio.get_running_loop().time()
        await nd.wait_peers()
        return asyncio.get_running_loop().time() - t

    waited = asyncio.run(go())
    assert 0.2 <= waited < 1.0


def test_boot_election_waits_for_peers_then_elects():
    nd = make(5)
    order = []

    async def wait_peers():
        order.append("barrier")

    nd.wait_peers = wait_peers

    async def go():
        nd.coordinator_event = asyncio.Event()
        await nd.boot_election()

    asyncio.run(go())
    assert order == ["barrier"]
    assert nd.leader == 5
