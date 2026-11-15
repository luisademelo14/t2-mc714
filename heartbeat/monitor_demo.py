"""Mostra o estado dos nós a partir dos logs reais, durante cada etapa do demo.sh."""
import json
import sys
import time
from pathlib import Path


def ler_estado(pasta):
    estados = {}
    mudancas = []
    inicios = []
    for no in range(1, 6):
        estado = {"recebidos": 0, "ultimo_envio": None, "suspeitos": set()}
        arquivo = pasta / f"node{no}.jsonl"
        if arquivo.exists():
            # A última linha pode ainda estar sendo escrita; só lemos as completas.
            for linha in arquivo.read_text().split("\n")[:-1]:
                evento = json.loads(linha)
                tipo = evento["event"]
                if tipo == "start":
                    estado = {"recebidos": 0, "ultimo_envio": None, "suspeitos": set()}
                    inicios.append(evento["ts_wall"])
                elif tipo == "hb_recv":
                    estado["recebidos"] += 1
                elif tipo == "hb_sent":
                    estado["ultimo_envio"] = evento["ts_wall"]
                elif tipo == "suspect":
                    estado["suspeitos"].add(evento["peer"])
                    mudancas.append(evento)
                elif tipo == "restore":
                    estado["suspeitos"].discard(evento["peer"])
                    mudancas.append(evento)
        estados[no] = estado
    mudancas.sort(key=lambda e: e["ts_wall"])
    return estados, mudancas, min(inicios) if inicios else time.time()


def mostrar(pasta, titulo, parado):
    estados, mudancas, inicio = ler_estado(pasta)
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="")
    print("DEMONSTRAÇÃO HEARTBEAT")
    print(titulo)
    print("N = 5 | T = 500 ms | K = 3 | timeout = 1500 ms | perda = 0%\n")
    print(f"{'Nó':<8} {'Envio de heartbeat':<23} {'HBs recebidos':<17} Suspeitos")
    print("-" * 70)
    for no, estado in estados.items():
        if no == parado:
            situacao = "PARADO (docker kill)"
            suspeitos = "-"
        else:
            envio = estado["ultimo_envio"]
            if envio is None:
                situacao = "aguardando início"
            elif time.time() - envio > 1.5:
                situacao = "sem envio recente"
            else:
                situacao = "enviando"
            suspeitos = ", ".join(f"nó {p}" for p in sorted(estado["suspeitos"])) or "nenhum"
        print(f"nó {no:<5} {situacao:<23} {estado['recebidos']:<17} {suspeitos}")

    print("\nEventos recentes (registrados pelos próprios nós):")
    if not mudancas:
        print("  Nenhuma suspeita registrada.")
    for evento in mudancas[-8:]:
        acao = "passou a suspeitar do" if evento["event"] == "suspect" else "voltou a confiar no"
        depois = evento["ts_wall"] - inicio
        print(f"  +{depois:5.1f}s: nó {evento['node']} {acao} nó {evento['peer']}")
    print("\nA tabela usa os logs; o contador de recebimentos zera quando o nó reinicia.", flush=True)


def main():
    pasta = Path(sys.argv[1])
    titulo = sys.argv[2]
    parado = int(sys.argv[3])
    fim = time.monotonic() + 5
    while time.monotonic() < fim:
        if sys.stdout.isatty():
            mostrar(pasta, titulo, parado)
        time.sleep(0.25)
    mostrar(pasta, titulo, parado)


if __name__ == "__main__":
    main()
