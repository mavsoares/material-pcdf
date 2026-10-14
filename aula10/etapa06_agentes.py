"""
ETAPA 6 -- Os especialistas, cada um com UMA responsabilidade e SÓ as tools de que precisa.

ESQUELETO:
  ETAPA 6.1 -- criar_normas(), criar_escala(), criar_financeiro(), criar_redator()
  ETAPA 6.2 -- criar_coordenador(): usa Normas, Escala e Financeiro como TOOLS (as_tool)

As tools abaixo (PRONTAS) só repassam a chamada ao MCP Server do RH (cliente_mcp.chamar_mcp_async). Dar a cada agente
só as tools dele é o PRIVILÉGIO MÍNIMO (Etapa 9.1); o hook do 🆕 B (etapa10_governanca.py) confere isso em tempo de execução.

REFERÊNCIAS NAS AULAS
  aula4/ex03_agente_as_tool.py                         Coordenador que chama especialistas como tools    <- o mais parecido
  aula2/agente_handoff2.py                             as_tool com tool_name e tool_description
  aula4/ex02_handoff_roteamento.py                     handoff: compare (quem responde no fim?)
  aula7/exemplos/02_agentes_especializados/main.py     uma responsabilidade por agente
  aula7/agentes.py                                     ModelSettings(temperature=0) para respostas mais estáveis
  aula8/exemplos/06_excessive_agency/1_codigo_pronto/main.py   o problema de dar tools DEMAIS a um agente
"""
import json

from agents import Agent, ModelSettings, RunHooks, function_tool

from etapa05_cliente_mcp import chamar_mcp_async
from etapa04_ferramentas import cotacao_usd_brl

CONFIG = ModelSettings(temperature=0)


# ------------------------------------------------------------------ tools (PRONTAS)
@function_tool
async def consultar_normas(tema: str) -> str:
    """Regras da norma interna sobre um tema: férias, prazos, escala, abono, diária, aprovação, saúde ou dados."""
    return json.dumps(await chamar_mcp_async("consultar_normas", {"tema": tema}), ensure_ascii=False)


@function_tool
async def consultar_escala(equipe: str, inicio: str, fim: str) -> str:
    """Afastamentos da equipe que se sobrepõem ao período (AAAA-MM-DD) e o limite de afastados da regra N5."""
    return json.dumps(await chamar_mcp_async("consultar_escala", {"equipe": equipe, "inicio": inicio, "fim": fim}),
                      ensure_ascii=False)


@function_tool
async def tabela_diarias(tipo_destino: str) -> str:
    """Moeda e valor da diária para o tipo de destino: capital, interior ou exterior."""
    return json.dumps(await chamar_mcp_async("tabela_diarias", {"tipo_destino": tipo_destino}), ensure_ascii=False)


@function_tool
async def consultar_remuneracao(matricula: str) -> str:
    """[RESTRITA] Salário-base de um servidor. Só para calcular a venda de férias (N2)."""
    print(f"[tool] consultar_remuneracao({matricula}) EXECUTOU")  # o 🆕 B prova que, barrada, ela NÃO executa
    return json.dumps(await chamar_mcp_async("consultar_remuneracao", {"matricula": matricula}), ensure_ascii=False)


@function_tool
def cotacao_dolar() -> str:
    """Cotação atual do dólar em reais (USD->BRL). Devolve 'indisponível' se a API falhar: nunca invente o câmbio."""
    cotacao = cotacao_usd_brl()
    return f"{cotacao:.4f}" if cotacao else "indisponível"


# ------------------------------------------------------------------ ETAPA 6.1: especialistas
def criar_normas() -> Agent:
    return Agent(
        name="Normas",
        instructions=(
            "Você é especialista nas normas administrativas de RH. "
            "Consulte as normas aplicáveis ao tema do pedido e explique-as "
            "em linguagem simples, relacionando-as aos fatos e às violações "
            "objetivas recebidas. Não calcule valores financeiros e não "
            "consulte a escala da equipe. Não invente regras."
        ),
        tools=[consultar_normas],
        model_settings=CONFIG,
    )


def criar_escala() -> Agent:
    return Agent(
        name="Escala",
        instructions=(
            "Você é especialista em escalas e afastamentos de equipes. "
            "Consulte os afastamentos que se sobrepõem ao período solicitado "
            "e verifique o limite permitido pela regra N5. Se houver conflito, "
            "sugira um período alternativo com a mesma quantidade de dias, "
            "respeitando as regras aplicáveis e começando em uma data permitida. "
            "Explique os conflitos encontrados. Não invente dados de escala."
        ),
        tools=[consultar_escala],
        model_settings=CONFIG,
    )


def criar_financeiro() -> Agent:
    return Agent(
        name="Financeiro",
        instructions=(
            "Você é o especialista financeiro de RH. Calcule valores somente "
            "com dados obtidos pelas ferramentas disponíveis e mostre a conta.\n\n"
            "Venda de férias (N2): valor = dias vendidos x salário-base / 30. "
            "Consulte a remuneração somente quando necessário para esse cálculo.\n\n"
            "Diárias (N7): calcule uma diária por pernoite e meia diária no "
            "retorno. Para destinos no exterior, use o valor em USD e converta "
            "para reais com a cotação obtida pela ferramenta cotacao_dolar. "
            "Se o câmbio estiver indisponível, informe o valor convertido como "
            "'a calcular', sem inventar uma cotação.\n\n"
            "Diferencie valores informados de valores calculados. Não invente "
            "salários, tarifas, cotações ou quantidades de pernoites."
        ),
        tools=[tabela_diarias, consultar_remuneracao, cotacao_dolar],
        model_settings=CONFIG,
    )


def criar_redator() -> Agent:
    return Agent(
        name="Redator",
        instructions=(
            "Você redige despachos administrativos de RH, com linguagem formal, "
            "clara, objetiva e impessoal. Produza o despacho de deferimento ou "
            "indeferimento usando somente os fatos recebidos: matrícula, período, "
            "decisão, regras citadas, valores e, em caso de indeferimento, a "
            "sugestão de datas apresentada pelo especialista responsável.\n\n"
            "Não invente informações nem altere os pareceres recebidos. "
            "Nunca inclua CPF ou dados de saúde, conforme a regra N10. "
            "Se receber feedback de validação ou da chefia, revise o despacho "
            "para corrigir os pontos indicados."
        ),
        tools=[],
        model_settings=CONFIG,
    )


# ------------------------------------------------------------------ ETAPA 6.2: coordenador
def criar_coordenador(hooks: RunHooks | None = None, tools_extras: list | None = None) -> Agent:
    # ETAPA 6.2 -- Agent(name="Coordenador", instructions=..., tools=[
    #       criar_normas().as_tool(tool_name="parecer_normas", tool_description=..., hooks=hooks,
    #                              failure_error_function=None),
    #       criar_escala().as_tool(tool_name="parecer_escala", ..., hooks=hooks, failure_error_function=None),
    #       criar_financeiro().as_tool(tool_name="parecer_financeiro", ..., hooks=hooks, failure_error_function=None),
    #       *(tools_extras or [])])
    #   O Coordenador decide QUAIS especialistas consultar (abono não precisa do Financeiro) e junta os pareceres.
    #   hooks=hooks nas as_tool faz o hook do 🆕 B enxergar também as tools DENTRO de cada especialista.
    #   failure_error_function=None: sem isso, um erro dentro do especialista (inclusive o bloqueio do 🆕 B) vira só
    #   um texto de erro para o Coordenador, que segue em frente. Com None, o erro interrompe a execução.
    #   tools_extras serve só para o teste do 🆕 B (dar de propósito consultar_remuneracao ao Coordenador).
    #   Referência: aula4/ex03_agente_as_tool.py
    # ------------------------------------------------------------------ ETAPA 6.2: coordenador
    return Agent(
        name="Coordenador",
        instructions=(
            "Você coordena a análise de solicitações administrativas de RH. "
            "Analise o pedido e consulte os especialistas necessários para produzir "
            "uma resposta fundamentada.\n\n"

            "Especialistas disponíveis:\n"
            "- Normas: identifica e explica as regras administrativas aplicáveis.\n"
            "- Escala: verifica afastamentos, limites da equipe e sugere datas "
            "alternativas quando necessário.\n"
            "- Financeiro: calcula valores de férias vendidas e diárias.\n\n"

            "Escolha os especialistas conforme a necessidade do pedido. "
            "Consulte Normas quando precisar verificar regras administrativas. "
            "Consulte Escala para pedidos de afastamento que possam afetar a equipe. "
            "Consulte Financeiro somente quando houver necessidade de calcular "
            "valores financeiros, como venda de férias ou diárias. "
            "Pedidos de abono, por exemplo, normalmente não exigem consulta ao "
            "Financeiro.\n\n"

            "Combine os pareceres recebidos em uma resposta clara, coerente e "
            "fundamentada. Não invente dados, regras ou valores. Se os pareceres "
            "indicarem impedimentos, explique-os e apresente as alternativas "
            "sugeridas pelos especialistas. Diferencie fatos confirmados de "
            "informações que ainda precisam ser verificadas."
        ),
        tools=[
            criar_normas().as_tool(
                tool_name="parecer_normas",
                tool_description=(
                    "Consulta o especialista em normas para identificar e explicar "
                    "as regras administrativas aplicáveis ao pedido."
                ),
                hooks=hooks,
                failure_error_function=None,
            ),
            criar_escala().as_tool(
                tool_name="parecer_escala",
                tool_description=(
                    "Consulta o especialista em escala para verificar afastamentos, "
                    "limites da equipe e possíveis períodos alternativos."
                ),
                hooks=hooks,
                failure_error_function=None,
            ),
            criar_financeiro().as_tool(
                tool_name="parecer_financeiro",
                tool_description=(
                    "Consulta o especialista financeiro para calcular valores de "
                    "venda de férias ou diárias, quando necessário."
                ),
                hooks=hooks,
                failure_error_function=None,
            ),
            *(tools_extras or []),
        ],
        model_settings=CONFIG,
    )
