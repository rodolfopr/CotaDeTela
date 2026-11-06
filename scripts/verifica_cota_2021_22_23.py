"""
Cota de Tela 2021–2023 — Sem obrigação legal
A obrigação prevista no art. 55 da MP 2.228-1/2001 perdeu vigência
em 5 de setembro de 2021 (prazo original de 20 anos).

Fundamento:
- ANCINE registra oficialmente: "2021 a 2023 - Não houve decreto
  (Obrigação da cota de tela não estava vigente no período)".
- A Lei 14.814/2024 restabeleceu a obrigação, mas apenas a partir
  de 2024 (com regulamentação pelo Decreto 12.067/2024).
- Não há parâmetro normativo para aferição neste triênio.
"""

import streamlit as st


def main():
    st.set_page_config(
        page_title="Cota de Tela 2021–2023 — Sem obrigação",
        page_icon="🎬",
        layout="wide",
    )

    st.title("🎬 Cota de Tela 2021–2023 — Sem obrigação legal")
    st.error(
        "**2021, 2022 e 2023 não tiveram Cota de Tela.**\n\n"
        "A obrigação prevista no art. 55 da MP 2.228-1/2001 tinha prazo de "
        "**20 anos**, expirando em **5 de setembro de 2021**. Não houve decreto "
        "para nenhum dos três anos, porque **a própria obrigação não estava vigente**. "
        "Não há parâmetro normativo para aferição neste período."
    )

    st.markdown("---")

    st.subheader("O que aconteceu")
    st.markdown(
        """
        - A **MP 2.228-1/2001** criou a Cota de Tela com prazo de **20 anos**
          (art. 55), ou seja, até **5 de setembro de 2021**.
        - Em **2021**, a obrigação **perdeu vigência automaticamente**.
        - De **2021 a 2023**, não houve decreto nem obrigação legal. A ANCINE
          registra oficialmente que "não houve decreto" nesse período, porque
          "a obrigação da cota de tela não estava vigente".
        - A situação só foi revertida com a **Lei 14.814/2024**, sancionada em
          **15 de janeiro de 2024**, que restabeleceu a Cota de Tela até
          **31 de dezembro de 2033**.
        - A nova obrigação só passou a valer efetivamente com o
          **Decreto 12.067/2024**, que fixou os parâmetros para **2024**.
        """
    )

    st.subheader("Impacto no mercado")
    st.markdown(
        """
        A ausência da obrigação teve efeito mensurável na participação de
        filmes brasileiros nas bilheterias:
        - Em **2021**, a participação caiu de 13% para **1,8%**.
        - Em **2022**, ficou em cerca de **4,2%**.
        """
    )

    st.subheader("Fontes")
    st.markdown(
        """
        - **ANCINE — Histórico de Decretos de Cota de Tela**: registra
          explicitamente "2021 a 2023 - Não houve decreto (Obrigação da cota
          de tela não estava vigente no período)".
        - **ANCINE — Apresentação "Renovação da política de Cota de Tela"
          (fev/2023)**: confirma que o art. 55 da MP 2.228-1/01
          "perdeu a validade em setembro de 2021".
        - **Lei 14.814/2024**: restabelece a obrigação até 2033.
        - **Decreto 12.067/2024**: regulamenta a Cota de Tela para 2024.
        """
    )

    st.info(
        "Para os anos com decreto vigente, selecione o ano correspondente no menu "
        "lateral: **2015–2018** (dias por complexo), **2020** (dias por sala × grupo), "
        "**2024–2025** (percentual de sessões)."
    )


if __name__ == "__main__":
    main()