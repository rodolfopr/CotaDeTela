"""
Cota de Tela 2019 — Sem obrigação legal
Não houve decreto presidencial regulamentando a obrigação para 2019.

Fundamento:
- ANCINE registra oficialmente que "2019 - Não houve decreto".
- A Secretaria Especial da Cultura (jan/2019) sustentou que o Decreto
  9.256/2017 seguiria vigente, mas a interpretação é juridicamente
  controvertida (o texto menciona expressamente "ano de 2018").
- Não há parâmetro normativo inequívoco para aferição de 2019.
"""

import streamlit as st


def main():
    st.set_page_config(
        page_title="Cota de Tela 2019 — Sem obrigação",
        page_icon="🎬",
        layout="wide",
    )

    st.title("🎬 Cota de Tela 2019 — Sem obrigação legal")
    st.error(
        "**2019 não teve decreto de Cota de Tela.**\n\n"
        "O Decreto que fixaria a obrigação para 2019 não foi publicado a tempo. "
        "A ANCINE registra oficialmente que **\"2019 - Não houve decreto\"**. "
        "Não há parâmetro normativo para aferição neste ano."
    )

    st.markdown("---")

    st.subheader("O que aconteceu")
    st.markdown(
        """
        - Em **dezembro de 2018**, a Câmara Técnica da ANCINE aprovou um novo modelo
          de aferição (por sessão, com bônus para sessões após as 17h).
        - O decreto seria publicado até o fim de 2018, mas **a mudança de governo
          impediu a publicação a tempo**.
        - Em **9 de janeiro de 2019**, a Secretaria Especial da Cultura emitiu nota
          sustentando que o **Decreto 9.256/2017** (que fixou a cota para 2018)
          "segue vigente até que nova legislação o substitua", com base no
          Art. 2º da Lei de Introdução às Normas do Direito Brasileiro.
        - **Ressalva:** advogados consultados à época consideraram a interpretação
          "pouco sustentável", pois o decreto menciona expressamente o ano de 2018.
        - A obrigação só foi restabelecida com o **Decreto 10.190/2019**, que fixou
          a cota para **2020**.
        """
    )

    st.subheader("Fontes")
    st.markdown(
        """
        - ANCINE — Histórico de Decretos de Cota de Tela: registra 2018 (Decreto
          9.256/2017) e 2020 (Decreto 10.190/2019), **sem entrada para 2019**.
        - ANCINE — Despacho 24-E/2023/SRG: "2019 - Não houve obrigação por ausência
          de decreto presidencial regulamentando a norma".
        - Nota oficial da Secretaria Especial da Cultura (jan/2019), reproduzida
          em análise acadêmica da Spcine, com a ressalva sobre a fragilidade
          jurídica da interpretação.
        """
    )

    st.info(
        "Para os anos com decreto vigente, selecione o ano correspondente no menu "
        "lateral (2015–2018, 2020, 2024–2025)."
    )


if __name__ == "__main__":
    main()