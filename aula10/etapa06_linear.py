"""
ETAPA 6 -- O sistema inteiro como um FLUXO LINEAR em Python puro (sem LangGraph) ⇒ Marco mínimo.

ESQUELETO:
  ETAPA 6.3 -- analisar(): o Coordenador junta os pareceres (com os limites da Etapa 4.7)
  ETAPA 6.4 -- processar(): guardrails -> extração -> MCP -> feriados -> regras -> coordenador -> redator
               -> protocolo -> MCP (registrar)
  🆕 B.4    -- (OPCIONAL, bônus) testar_governanca(): os dois testes de bloqueio do --governanca

REFERÊNCIAS NAS AULAS
  aula6/exemplos/01_fluxo_linear/main.py     o fluxo linear: funciona, mas sem decisão nem volta (por isso a Etapa 7)
  aula4/ex03_agente_as_tool.py               o Coordenador com especialistas como tools
  aula7/exemplos/02_agentes_especializados/main.py   cada especialista imprime o que fez: dá para saber quem fez o quê

Rodar:
    python etapa06_linear.py                 # C1, C2, C6 e C11
    python etapa06_linear.py --governanca    # 🆕 B (opcional): os dois testes de bloqueio

Pronto quando: C1, C2 e C11 são gravados com protocolo, C6 vira indeferimento com sugestão de datas, e você sabe dizer
qual agente escreveu cada parte. (Opcional) no --governanca: a tool restrita NÃO executa e o C2 para no orçamento.
"""
import json
import os
import sys

from agents import RunHooks

import etapa06_agentes as agentes
from etapa05_cliente_mcp import chamar_mcp
from dados.casos import CASOS
from etapa02_extracao import extrair
from etapa04_ferramentas import gerar_protocolo, rodar_com_limites_sync
from etapa10_governanca import Governanca, LimiteExcedido
from etapa03_guardrails import encontrar_dado_sensivel, nota_escopo, LIMIAR, MENSAGENS
from provedor import configurar
from etapa06_regras import precisa_chefia, resumo_periodo, violacoes_objetivas

MODELO = configurar()


def _ferramentas_consultadas(resultado) -> list[str]:
    """Nomes das ferramentas/especialistas que o coordenador chamou, na ordem, sem repetir."""
    nomes: list[str] = []
    for item in resultado.new_items:
        if getattr(item, "type", "") != "tool_call_item":
            continue
        raw = item.raw_item
        nome = raw.get("name") if isinstance(raw, dict) else getattr(raw, "name", None)
        if nome and nome not in nomes:
            nomes.append(nome)
    return nomes


def analisar(
    pedido: dict,
    servidor: dict,
    periodo: dict,
    violacoes: list[str],
    hooks: RunHooks | None = None,
) -> tuple[str, list[str]]:
    # ETAPA 6.3 -- monte um texto com o pedido, o servidor (matrícula e equipe), o período e as violações objetivas,
    #   e rode criar_coordenador(hooks) com rodar_com_limites_sync(..., hooks=hooks).
    #   Devolve (final_output, nomes das ferramentas consultadas).
    servidor_resumido = {
        "matricula": servidor.get("matricula"),
        "nome": servidor.get("nome"),
        "cargo": servidor.get("cargo"),
        "equipe": servidor.get("equipe"),
    }

    entrada = (
        "Analise a solicitação de RH usando os especialistas disponíveis.\n\n"
        f"PEDIDO:\n{json.dumps(pedido, ensure_ascii=False, indent=2)}\n\n"
        "SERVIDOR:\n"
        f"{json.dumps(servidor_resumido, ensure_ascii=False, indent=2)}\n\n"
        f"PERÍODO E FERIADOS:\n{json.dumps(periodo, ensure_ascii=False, indent=2)}\n\n"
        "VIOLAÇÕES OBJETIVAS IDENTIFICADAS:\n"
        f"{json.dumps(violacoes, ensure_ascii=False, indent=2)}\n\n"
        "Consulte os especialistas necessários. Explique as regras aplicáveis, "
        "considere os conflitos de escala e os valores financeiros quando "
        "pertinentes. Não invente dados nem desconsidere as violações objetivas. "
        "Se houver violação, deixe claro o impedimento e considere as alternativas "
        "sugeridas pelos especialistas."
    )

    resultado = rodar_com_limites_sync(
        agentes.criar_coordenador(hooks=hooks),
        entrada,
        hooks=hooks,
    )

    return resultado.final_output, _ferramentas_consultadas(resultado)


def processar(texto: str, hooks: RunHooks | None = None) -> dict:
    # [1/9] Guardrails
    print("[1/9] guardrails")

    tipo_sensivel = encontrar_dado_sensivel(texto)
    if tipo_sensivel:
        return {
            "resultado": "bloqueado",
            "mensagem": f"Dado sensível identificado: {tipo_sensivel}",
        }

    nota, motivo = nota_escopo(texto)
    if nota >= LIMIAR:
        return {
            "resultado": "bloqueado",
            "mensagem": motivo or MENSAGENS.get(
                "fora_do_escopo",
                "Solicitação fora do escopo do atendimento de RH.",
            ),
        }

    # [2/9] Extração
    pedido = extrair(texto).model_dump(mode="json")

    matricula = str(pedido.get("matricula") or "").strip()
    inicio = pedido.get("data_inicio")
    fim = pedido.get("data_fim")

    print(
        f"[2/9] extração: {pedido.get('tipo')} "
        f"{matricula} {inicio}..{fim}"
    )

    if not matricula or not inicio or not fim:
        return {
            "resultado": "pedir_dados",
            "mensagem": (
                "Informe a matrícula do servidor e as datas de início "
                "e fim do período solicitado."
            ),
            "pedido": pedido,
        }

    # [3/9] Consulta ao servidor
    servidor = chamar_mcp(
        "consultar_servidor",
        {"matricula": matricula},
    )

    if (
        not servidor
        or servidor.get("erro")
        or not servidor.get("matricula")
    ):
        return {
            "resultado": "pedir_dados",
            "mensagem": (
                f"Não foi possível localizar o servidor de matrícula "
                f"{matricula}. Verifique a matrícula."
            ),
            "pedido": pedido,
        }

    print(
        f"[3/9] servidor: {servidor.get('nome')} "
        f"({servidor.get('equipe')})"
    )

    # [4/9] Cálculo do período e feriados
    periodo = resumo_periodo(inicio, fim)

    dias = periodo["dias_uteis"]
    unidade = "dia útil" if dias == 1 else "dias úteis"

    print(
        f"[4/9] período: {dias} {unidade}, "
        f"retorno {periodo['retorno']} "
        f"(fonte: {periodo['fonte_feriados']})"
    )

    # [5/9] Consulta à escala e regras objetivas
    escala = chamar_mcp(
        "consultar_escala",
        {
            "equipe": servidor.get("equipe", ""),
            "inicio": inicio,
            "fim": fim,
        },
    )

    if not escala or escala.get("erro"):
        return {
            "resultado": "erro_consulta",
            "mensagem": "Não foi possível consultar a escala da equipe.",
            "pedido": pedido,
        }

    violacoes = violacoes_objetivas(
        pedido,
        servidor,
        periodo,
        escala,
    )

    print(
        f"[5/9] violações: "
        f"{'; '.join(violacoes) if violacoes else 'nenhuma'}"
    )

    # [6/9] Análise pelos especialistas
    parecer, consultados = analisar(
        pedido,
        servidor,
        periodo,
        violacoes,
        hooks=hooks,
    )

    print(f"[6/9] coordenador: consultou {', '.join(consultados) if consultados else 'nenhum especialista'}")

    # [7/9] Redação do despacho
    fatos = {
        "pedido": pedido,
        "servidor": {
            "matricula": servidor.get("matricula"),
            "nome": servidor.get("nome"),
            "cargo": servidor.get("cargo"),
            "equipe": servidor.get("equipe"),
        },
        "periodo": periodo,
        "escala": escala,
        "violacoes_objetivas": violacoes,
        "parecer_especialistas": parecer,
    }

    entrada_redator = (
        "Redija o despacho administrativo com base exclusivamente "
        "nos fatos e pareceres a seguir. Não invente informações. "
        "A decisão deve respeitar as violações objetivas: se houver "
        "violações, redija o indeferimento; caso contrário, redija "
        "o deferimento, sem criar pendências não indicadas nos dados. "
        "Se houver indeferimento, inclua as alternativas de datas "
        "sugeridas pelos especialistas, se existirem. "
        "Não inclua CPF nem dados de saúde.\n\n"
        f"{json.dumps(fatos, ensure_ascii=False, indent=2)}"
    )

    despacho = rodar_com_limites_sync(
        agentes.criar_redator(),
        entrada_redator,
        hooks=hooks,
    ).final_output

    print("[7/9] redator: despacho concluído")

    # [8/9] Geração do protocolo
    protocolo = gerar_protocolo(
        matricula,
        pedido["tipo"],
        inicio,
        fim,
    )

    print(f"[8/9] protocolo {protocolo}")

    # [9/9] Registro da decisão
    decisao = "indeferido" if violacoes else "deferido"
    requer_chefia = precisa_chefia(pedido, servidor)

    registro = chamar_mcp(
        "registrar_decisao",
        {
            "protocolo": protocolo,
            "matricula": matricula,
            "tipo": pedido["tipo"],
            "inicio": inicio,
            "fim": fim,
            "decisao": decisao,
            "aprovador": (
                "pendente_chefia" if requer_chefia else "sistema"
            ),
            "despacho": despacho,
            "token": os.getenv("TOKEN_REGISTRO", ""),
        },
    )

    print(f"[9/9] registrar: {registro}")

    if not registro or registro.get("sucesso") is not True:
        return {
            "resultado": "erro_registro",
            "protocolo": protocolo,
            "despacho": despacho,
            "parecer": parecer,
        }

    return {
        "resultado": "registrado",
        "protocolo": protocolo,
        "despacho": despacho,
        "parecer": parecer,
    }


def testar_governanca() -> None:
    # 🆕 B.4 (opcional) -- dois testes, cada um tratando LimiteExcedido e imprimindo o motivo:
    #   a) coordenador = agentes.criar_coordenador(hooks=Governanca(), tools_extras=[agentes.consultar_remuneracao])
    #      pergunte "Qual o salário da matrícula 1002?" -> deve ser BARRADO e o print da tool NÃO pode aparecer.
    #   b) processar(CASOS["C2_ferias_com_venda"]["pedido"], hooks=Governanca(max_tools=1))
    #      -> deve parar ANTES do segundo especialista.
    raise NotImplementedError("🆕 B.4: testar_governanca")


if __name__ == "__main__":
    print(f"[modelo] {MODELO}")
    if "--governanca" in sys.argv:
        testar_governanca()
    else:
        for nome in ("C1_abono_simples", "C2_ferias_com_venda", "C6_conflito_de_escala", "C11_diaria_exterior"):
            print(f"\n=============== {nome}")
            print(json.dumps(processar(CASOS[nome]["pedido"]), ensure_ascii=False, indent=2))
