"""Resumo e gráficos dos experimentos do heartbeat.

Lê execucoes.csv e deteccoes.csv (gerados por experimento.py) e escreve, na mesma pasta:
  resumo.csv                       uma linha por configuração: média, desvio e percentis
  deteccao.png                     tempo de detecção da morte do nó
  falsos_positivos.png             suspeitas de nós vivos
  mensagens.png                    mensagens por segundo, medidas e teóricas

Uso, a partir da pasta heartbeat/:  python3 analise.py [pasta_com_os_csvs]
Precisa de pandas e matplotlib.
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # só grava arquivos, não abre janela
import matplotlib.pyplot as plt
import pandas as pd

from experimento import K, N, NIVEIS_PERDA, NIVEIS_T, T_BASE

PASTA = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "resultados"

# Cada gráfico compara a variação de T e a variação da perda.
PAINEIS = [
    ("Variando T (sem perda)", [(f"{t} ms", t, 0.0) for t in NIVEIS_T]),
    (f"Variando a perda (T = {T_BASE} ms)", [(f"{p:.0%}", T_BASE, p) for p in NIVEIS_PERDA]),
]


def selecionar(df, t_ms, loss):
    return df[(df.t_ms == t_ms) & (df.loss == loss)]


def resumir(exe, det):
    linhas = []
    for (t_ms, loss), g in exe.groupby(["t_ms", "loss"]):
        d = selecionar(det, t_ms, loss)
        tempos = d.deteccao_ms.dropna()
        linhas.append({
            "t_ms": t_ms, "loss": loss, "repeticoes": len(g),
            "det_amostras": len(tempos),
            "det_media_ms": tempos.mean(), "det_desvio_ms": tempos.std(),
            "det_p50_ms": tempos.quantile(0.50),
            "det_p95_ms": tempos.quantile(0.95),
            "det_p99_ms": tempos.quantile(0.99),
            "ja_suspeito": int(d.ja_suspeito.sum()),  # já suspeitava da vítima quando ela morreu
            "nao_detectou": int((d.deteccao_ms.isna() & (d.ja_suspeito == 0)).sum()),
            "fp_por_min_media": g.falsos_por_min.mean(), "fp_por_min_desvio": g.falsos_por_min.std(),
            "msgs_por_s_media": g.msgs_por_s.mean(), "msgs_por_s_desvio": g.msgs_por_s.std(),
            "perda_obs_media": g.perda_obs.mean(),
        })
    resumo = pd.DataFrame(linhas)
    perda_observada = resumo.perda_obs_media.round(4)
    resumo = resumo.round(2)
    resumo["perda_obs_media"] = perda_observada
    return resumo


def grafico_deteccao(det):
    fig, eixos = plt.subplots(1, 2, figsize=(10, 4), sharey=True)
    for ax, (titulo, niveis) in zip(eixos, PAINEIS):
        tempos, timeouts, rotulos = [], [], []
        for rotulo, t_ms, loss in niveis:
            tempos.append(selecionar(det, t_ms, loss).deteccao_ms.dropna())
            timeouts.append(K * t_ms)
            rotulos.append(rotulo)

        posicoes = range(1, len(niveis) + 1)
        ax.boxplot(tempos)
        # Com perda, o silêncio pode começar antes da morte do nó.
        ax.plot(posicoes, timeouts, "x--", label="Timeout K*T")
        ax.set_xticks(posicoes, rotulos)
        ax.set_title(titulo)
        ax.set_ylabel("Tempo de detecção (ms)")
        ax.legend()
        ax.grid(axis="y")
    fig.tight_layout()
    fig.savefig(PASTA / "deteccao.png", dpi=200)
    plt.close(fig)


def grafico_falsos_positivos(exe):
    fig, eixos = plt.subplots(1, 2, figsize=(10, 4), sharey=True)
    for ax, (titulo, niveis) in zip(eixos, PAINEIS):
        medias, desvios, rotulos = [], [], []
        for rotulo, t_ms, loss in niveis:
            valores = selecionar(exe, t_ms, loss).falsos_por_min
            medias.append(valores.mean())
            desvios.append(valores.std() if len(valores) > 1 else 0)
            rotulos.append(rotulo)

        ax.bar(rotulos, medias, yerr=desvios, capsize=4, label="Média ± desvio padrão")
        ax.set_title(titulo)
        ax.set_ylabel("Falsos positivos por minuto (cluster)")
        ax.legend()
        ax.grid(axis="y")
    eixos[0].set_ylim(bottom=0)
    fig.tight_layout()
    fig.savefig(PASTA / "falsos_positivos.png", dpi=200)
    plt.close(fig)


def grafico_mensagens(exe):
    fig, ax = plt.subplots(figsize=(6, 4))
    intervalos = range(min(NIVEIS_T), max(NIVEIS_T) + 1)
    teorico = [N * (N - 1) * 1000 / t for t in intervalos]
    ax.plot(intervalos, teorico, "--", label="Teórico: N(N-1)/T")
    medias, desvios = [], []
    for t_ms in NIVEIS_T:
        valores = selecionar(exe, t_ms, 0.0).msgs_por_s
        medias.append(valores.mean())
        desvios.append(valores.std() if len(valores) > 1 else 0)
    ax.errorbar(NIVEIS_T, medias, yerr=desvios, fmt="o", capsize=4,
                label="Medido: média ± desvio padrão")
    ax.set_title("Mensagens sem perda")
    ax.set_xlabel("T (ms)")
    ax.set_ylabel("Tentativas de envio por segundo")
    ax.set_xticks(NIVEIS_T)
    ax.legend()
    ax.grid()
    fig.tight_layout()
    fig.savefig(PASTA / "mensagens.png", dpi=200)
    plt.close(fig)


def main():
    exe = pd.read_csv(PASTA / "execucoes.csv")
    det = pd.read_csv(PASTA / "deteccoes.csv")
    resumo = resumir(exe, det)
    resumo.to_csv(PASTA / "resumo.csv", index=False)
    print(resumo.to_string(index=False))
    grafico_deteccao(det)
    grafico_falsos_positivos(exe)
    grafico_mensagens(exe)
    print(f"\nArquivos gravados em {PASTA}")


if __name__ == "__main__":
    main()
