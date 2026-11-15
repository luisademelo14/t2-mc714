"""gráficos dos experimentos do bully.

  resumo.csv       uma linha por (cenário, N): média, desvio e percentis
  eleicao.png      latência da eleição em função de N
  mensagens.png    mensagens por eleição, medidas (média ± desvio) e teóricas (tracejado)
  recuperacao.png  tempo de detecção da queda e de recuperação total (monitor ligado)

"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # só grava arquivos, não abre janela
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from experimento import NIVEIS_N, PING_MS, teorico_total

PASTA = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "resultados"

AZUL, LARANJA = "#2a78d6", "#d9730d"
TINTA, TINTA2, MUDO = "#0b0b0b", "#52514e", "#898781"
GRADE, EIXO = "#e1e0d9", "#c3c2b7"

SERIES = {
    "pior": ("pior caso (inicia o nó 1)", AZUL, "o", lambda n: 1),
    "melhor": ("melhor caso (inicia o nó N−1)", LARANJA, "s", lambda n: n - 1),
}
DESLOC = {"pior": -0.15, "melhor": 0.15}  


def estilo(ax):
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color(EIXO)
    ax.grid(axis="y", color=GRADE, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=TINTA2, length=3)
    ax.set_xticks(NIVEIS_N)
    ax.set_xlim(min(NIVEIS_N) - 0.7, max(NIVEIS_N) + 0.7)
    ax.set_xlabel("número de nós N", color=TINTA2)
    ax.set_ylim(bottom=0)


def legenda_embaixo(fig, ax, linhas):
    handles, rotulos = ax.get_legend_handles_labels()
    fig.legend(handles, rotulos, loc="lower center", ncol=1, frameon=False, fontsize=8,
               labelcolor=TINTA2)
    fig.tight_layout(rect=(0, 0.045 * linhas + 0.02, 1, 1))


def selecionar(df, cenario, n):
    return df[(df.cenario == cenario) & (df.n == n) & (df.convergiu == 1)]


def resumir(df):
    linhas = []
    for (cenario, n), g in df.groupby(["cenario", "n"]):
        ok = g[g.convergiu == 1]
        linhas.append({
            "cenario": cenario, "n": n, "repeticoes": len(g), "convergiram": len(ok),
            "eleicao_media_ms": ok.eleicao_ms.mean(), "eleicao_desvio_ms": ok.eleicao_ms.std(),
            "eleicao_p50_ms": ok.eleicao_ms.quantile(0.50),
            "eleicao_p95_ms": ok.eleicao_ms.quantile(0.95),
            "eleicao_p99_ms": ok.eleicao_ms.quantile(0.99),
            "msgs_media": ok.msgs_total.mean(), "msgs_desvio": ok.msgs_total.std(),
            "msgs_teorico": ok.msgs_teorico.mean(),
            "deteccao_p50_ms": ok.deteccao_ms.quantile(0.50),
            "recuperacao_p50_ms": ok.recuperacao_ms.quantile(0.50),
            "recuperacao_p95_ms": ok.recuperacao_ms.quantile(0.95),
        })
    return pd.DataFrame(linhas).round(2)


def jitter(x, n):
    return x + np.random.default_rng(0).uniform(-0.06, 0.06, n)


def grafico_eleicao(df):
    fig, ax = plt.subplots(figsize=(4.4, 3.8))
    for cenario, (rotulo, cor, marcador, _) in SERIES.items():
        medianas = []
        for n in NIVEIS_N:
            v = selecionar(df, cenario, n).eleicao_ms
            ax.scatter(jitter(n + DESLOC[cenario], len(v)), v, s=14, color=cor, alpha=0.45,
                       linewidths=0)
            medianas.append(v.median())
        ax.plot(np.array(NIVEIS_N) + DESLOC[cenario], medianas, marker=marcador, color=cor,
                markersize=6, linewidth=1.5, label=rotulo)
    ax.plot([], [], marker="o", linestyle="", color=MUDO, alpha=0.45, markersize=4,
            label="uma execução (a linha liga as medianas)")
    ax.set_ylabel("latência da eleição (ms)", color=TINTA2)
    estilo(ax)
    legenda_embaixo(fig, ax, 3)
    fig.savefig(PASTA / "eleicao.png", dpi=200)


def grafico_mensagens(df):
    fig, ax = plt.subplots(figsize=(4.4, 4.0))
    grade = range(min(NIVEIS_N), max(NIVEIS_N) + 1)
    for cenario, (rotulo, cor, marcador, iniciador) in SERIES.items():
        ax.plot(grade, [teorico_total(n, iniciador(n)) for n in grade], color=cor, linestyle="--",
                linewidth=1, alpha=0.8)
        medias = [selecionar(df, cenario, n).msgs_total.mean() for n in NIVEIS_N]
        desvios = [selecionar(df, cenario, n).msgs_total.std() for n in NIVEIS_N]
        ax.errorbar(np.array(NIVEIS_N) + DESLOC[cenario], medias, yerr=np.nan_to_num(desvios),
                    fmt=marcador, color=cor, markersize=6, capsize=3, linewidth=1.2,
                    label=f"{rotulo}: medido (média ± desvio)")
    ax.set_ylabel("mensagens por eleição", color=TINTA2)
    estilo(ax)
    legenda_embaixo(fig, ax, 2)
    fig.savefig(PASTA / "mensagens.png", dpi=200)


def grafico_recuperacao(df):
    fig, ax = plt.subplots(figsize=(4.4, 3.8))
    series = [("deteccao_ms", "detecção da queda", AZUL, "D"),
              ("recuperacao_ms", "recuperação total", TINTA, "o")]
    for coluna, rotulo, cor, marcador in series:
        medianas = []
        for n in NIVEIS_N:
            v = selecionar(df, "recuperacao", n)[coluna]
            ax.scatter(jitter(n, len(v)), v, s=14, color=cor, alpha=0.35, linewidths=0)
            medianas.append(v.median())
        ax.plot(NIVEIS_N, medianas, marker=marcador, color=cor, markersize=6, linewidth=1.5,
                label=f"{rotulo} (mediana)")
    ax.axhline(PING_MS, color=MUDO, linestyle="--", linewidth=1, label=f"PING_MS = {PING_MS} ms")
    ax.set_ylabel("tempo desde a queda do líder (ms)", color=TINTA2)
    estilo(ax)
    legenda_embaixo(fig, ax, 3)
    fig.savefig(PASTA / "recuperacao.png", dpi=200)


def main():
    df = pd.read_csv(PASTA / "execucoes.csv")
    resumo = resumir(df)
    resumo.to_csv(PASTA / "resumo.csv", index=False)
    with pd.option_context("display.width", 250, "display.max_columns", None):
        print(resumo.to_string(index=False))
    grafico_eleicao(df)
    grafico_mensagens(df)
    grafico_recuperacao(df)
    print(f"\nArquivos gravados em {PASTA}")


if __name__ == "__main__":
    main()
