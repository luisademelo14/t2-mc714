import os
import subprocess
import time

import httpx
import pytest


def wait_until(cond, timeout, step=0.1):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return
        time.sleep(step)
    raise AssertionError(f"timeout after {timeout}s")


PORT_PREFIX = os.environ.get("PORT_PREFIX", "800")  # o nó i responde em localhost:<PORT_PREFIX>i


class Cluster:
    def __init__(self, n):
        self.n = n
        self.env = {**os.environ, "N": str(n), "RUN_ID": f"teste_{time.time_ns()}"}

    def compose(self, *args):
        subprocess.run(["docker", "compose", "--profile", "bully", *args], check=True, env=self.env)

    def status(self, i):
        try:
            return httpx.get(f"http://localhost:{PORT_PREFIX}{i}/status", timeout=0.5).json()
        except httpx.HTTPError:
            return None

    def up(self):
        self.compose("up", "-d", "--build", *[f"bully{i}" for i in range(1, self.n + 1)])
        wait_until(lambda: all(self.status(i) for i in range(1, self.n + 1)), 30)

    def down(self):
        self.compose("down")

    def kill(self, i):
        self.compose("kill", f"bully{i}")

    def start(self, i):
        self.compose("start", f"bully{i}")

    def trigger(self, i):
        httpx.post(f"http://localhost:{PORT_PREFIX}{i}/trigger", timeout=2)

    def leaders(self, ids):
        out = set()
        for i in ids:
            s = self.status(i)
            out.add(s["leader"] if s and not s["electing"] else "unknown")
        return out

    def wait_leader(self, leader, ids, timeout=8):
        wait_until(lambda: self.leaders(ids) == {leader}, timeout)


@pytest.fixture
def cluster5():
    c = Cluster(5)
    c.up()
    yield c
    c.down()


def test_boot_elects_highest_id(cluster5):
    cluster5.wait_leader(5, range(1, 6))


def test_leader_failure_elects_next_highest(cluster5):
    cluster5.wait_leader(5, range(1, 6))
    cluster5.kill(5)
    cluster5.wait_leader(4, range(1, 5))


def test_two_failures_in_sequence(cluster5):
    cluster5.wait_leader(5, range(1, 6))
    cluster5.kill(5)
    cluster5.wait_leader(4, range(1, 5))
    cluster5.kill(4)
    cluster5.wait_leader(3, range(1, 4))


def test_leader_killed_right_after_trigger(cluster5):
    cluster5.wait_leader(5, range(1, 6))
    cluster5.trigger(1)
    cluster5.kill(5)
    cluster5.kill(4)
    cluster5.wait_leader(3, range(1, 4), timeout=10)


def test_highest_id_returns_and_takes_over(cluster5):
    cluster5.wait_leader(5, range(1, 6))
    cluster5.kill(5)
    cluster5.wait_leader(4, range(1, 5))
    cluster5.start(5)
    cluster5.wait_leader(5, range(1, 6))


def test_concurrent_elections_converge_to_single_leader(cluster5):
    cluster5.wait_leader(5, range(1, 6))
    for i in (1, 2, 3):
        cluster5.trigger(i)
    cluster5.wait_leader(5, range(1, 6))
    assert cluster5.leaders(range(1, 6)) == {5}