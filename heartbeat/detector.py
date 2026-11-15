class FailureDetector:
    """Detector de falhas por heartbeat.

    Um par é suspeito se ficar mais de `timeout` segundos sem enviar heartbeat.
    O tempo atual (`now`) é sempre passado de fora, assim dá para testar
    sem rede e sem esperar.
    """

    def __init__(self, peers, timeout, now):
        self.timeout = timeout
        self.last_seen = {p: now for p in peers}   # quando chegou o último heartbeat
        self.last_msg = {p: (0, 0) for p in peers}  # (incarnation, seq) mais recente
        self.suspects = set()

    def on_heartbeat(self, peer, incarnation, seq, now):
        """Registra um heartbeat. Retorna True se o par estava suspeito e foi restaurado."""
        # Duplicado ou atrasado: ignora. Um nó reiniciado tem incarnation maior,
        # então seus heartbeats voltam a ser aceitos mesmo com seq reiniciando.
        if (incarnation, seq) <= self.last_msg[peer]:
            return False

        self.last_msg[peer] = (incarnation, seq)
        self.last_seen[peer] = now

        if peer in self.suspects:
            self.suspects.remove(peer)
            return True
        return False

    def check(self, now):
        """Marca como suspeitos os pares que estouraram o timeout.

        Retorna a lista de (par, silêncio em segundos) dos novos suspeitos.
        """
        novos = []
        for peer, seen in self.last_seen.items():
            silencio = now - seen
            if silencio > self.timeout and peer not in self.suspects:
                self.suspects.add(peer)
                novos.append((peer, silencio))
        return novos