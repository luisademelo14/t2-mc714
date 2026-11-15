from detector import FailureDetector


def novo_detector():
    # nós 2 e 3 monitorados, timeout de 0.75 s, começando no tempo 0
    return FailureDetector([2, 3], timeout=0.75, now=0)


def test_ninguem_suspeito_antes_do_timeout():
    d = novo_detector()
    assert d.check(now=0.5) == []
    assert d.suspects == set()


def test_suspeita_depois_do_timeout():
    d = novo_detector()
    d.on_heartbeat(2, incarnation=1, seq=1, now=0.7)

    novos = d.check(now=1.0)

    assert [peer for peer, _ in novos] == [3]  # só o 3 ficou calado
    assert d.suspects == {3}


def test_suspeita_so_e_reportada_uma_vez():
    d = novo_detector()
    d.check(now=1.0)
    assert d.check(now=1.1) == []


def test_heartbeat_restaura_suspeito():
    d = novo_detector()
    d.check(now=1.0)

    restaurado = d.on_heartbeat(3, incarnation=1, seq=1, now=1.2)

    assert restaurado
    assert 3 not in d.suspects


def test_heartbeat_duplicado_ou_atrasado_e_ignorado():
    d = novo_detector()
    d.on_heartbeat(2, incarnation=1, seq=5, now=0.5)

    d.on_heartbeat(2, incarnation=1, seq=5, now=0.9)  # duplicado
    d.on_heartbeat(2, incarnation=1, seq=4, now=0.9)  # atrasado

    assert d.last_seen[2] == 0.5


def test_no_reiniciado_volta_a_ser_aceito():
    d = novo_detector()
    d.on_heartbeat(2, incarnation=1, seq=50, now=0.5)
    d.check(now=2.0)
    assert 2 in d.suspects

    # o nó reiniciou: seq voltou a 1, mas a incarnation é maior
    restaurado = d.on_heartbeat(2, incarnation=2, seq=1, now=2.1)

    assert restaurado
    assert 2 not in d.suspects