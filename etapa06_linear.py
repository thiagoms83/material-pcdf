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
import re
import sys

from agents import RunHooks

import etapa06_agentes as agentes
from etapa05_cliente_mcp import chamar_mcp
from dados.casos import CASOS
from etapa02_extracao import extrair
from etapa04_ferramentas import LoopExcedido, TempoEsgotado, gerar_protocolo, rodar_com_limites_sync
from etapa10_governanca import Governanca, LimiteExcedido
from etapa03_guardrails import encontrar_dado_sensivel, nota_escopo, LIMIAR, MENSAGENS
from provedor import configurar
from etapa06_regras import precisa_chefia, resumo_periodo, violacoes_objetivas

MODELO = configurar()


def _br_para_iso(data_br: str) -> str | None:
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", data_br.strip())
    if not m:
        return None
    dd, mm, aaaa = m.groups()
    return f"{aaaa}-{mm}-{dd}"


def _normalizar_pedido(texto: str, pedido: dict) -> dict:
    normalizado = dict(pedido)
    for campo in ("matricula", "data_inicio", "data_fim", "destino", "tipo_destino"):
        valor = normalizado.get(campo)
        if isinstance(valor, str) and valor.strip().lower() in {"", "null", "none"}:
            normalizado[campo] = None

    m = re.search(r"matr[ií]cula\s*(\d{4})", texto, flags=re.IGNORECASE)
    if not normalizado.get("matricula") and m:
        normalizado["matricula"] = m.group(1)

    datas_br = re.findall(r"\b\d{2}/\d{2}/\d{4}\b", texto)
    datas_iso = [_br_para_iso(d) for d in datas_br]
    datas_iso = [d for d in datas_iso if d]
    if datas_iso:
        if not normalizado.get("data_inicio"):
            normalizado["data_inicio"] = datas_iso[0]
        if not normalizado.get("data_fim"):
            normalizado["data_fim"] = datas_iso[1] if len(datas_iso) > 1 else datas_iso[0]

    if normalizado.get("tipo") == "abono":
        normalizado["dias_vendidos"] = 0
        if normalizado.get("data_inicio") and not normalizado.get("data_fim"):
            normalizado["data_fim"] = normalizado["data_inicio"]
        normalizado["destino"] = None
        normalizado["tipo_destino"] = None

    if normalizado.get("tipo") != "ferias":
        normalizado["dias_vendidos"] = 0

    if normalizado.get("tipo") == "diaria":
        if not normalizado.get("destino"):
            m_destino = re.search(r"\ba serviço a ([^.,]+?) de \d{2}/\d{2}/\d{4}", texto, flags=re.IGNORECASE)
            if m_destino:
                normalizado["destino"] = m_destino.group(1).strip()
        destino = (normalizado.get("destino") or "").lower()
        if "buenos aires" in destino:
            normalizado["tipo_destino"] = "exterior"
        elif normalizado.get("tipo_destino") not in {"capital", "interior", "exterior"}:
            normalizado["tipo_destino"] = None
    return normalizado


def _despacho_fallback(pedido: dict, violacoes: list[str], decisao: str) -> str:
    periodo = f"{pedido.get('data_inicio')} a {pedido.get('data_fim')}"
    if decisao == "deferido":
        return f"Defiro o pedido da matrícula {pedido.get('matricula')} para o período de {periodo}."
    return (
        f"Indefiro o pedido da matrícula {pedido.get('matricula')} para o período de {periodo}, "
        f"pelos motivos: {'; '.join(violacoes)}."
    )


def _despacho_coerente(despacho: str, decisao: str) -> bool:
    texto = despacho.lower()
    if decisao == "deferido":
        return "indefer" not in texto
    return "indefer" in texto


def analisar(pedido: dict, servidor: dict, periodo: dict, violacoes: list[str], hooks: RunHooks | None = None) -> str:
    # ETAPA 6.3 -- monte um texto com o pedido, o servidor (matrícula e equipe), o período e as violações objetivas,
    #   e rode criar_coordenador(hooks) com rodar_com_limites_sync(..., hooks=hooks). Devolva final_output.
    periodo_reduzido = {
        "inicio": periodo.get("inicio"),
        "fim": periodo.get("fim"),
        "dias_corridos": periodo.get("dias_corridos"),
        "dias_uteis": periodo.get("dias_uteis"),
        "retorno": periodo.get("retorno"),
        "inicio_permitido_n3": periodo.get("inicio_permitido_n3"),
        "fonte_feriados": periodo.get("fonte_feriados"),
    }
    entrada = (
        "Pedido:\n"
        f"{json.dumps(pedido, ensure_ascii=False, indent=2)}\n\n"
        "Servidor:\n"
        f"{json.dumps({'matricula': servidor.get('matricula'), 'equipe': servidor.get('equipe')}, ensure_ascii=False, indent=2)}\n\n"
        "Período:\n"
        f"{json.dumps(periodo_reduzido, ensure_ascii=False, indent=2)}\n\n"
        "Violações objetivas:\n"
        f"{json.dumps(violacoes, ensure_ascii=False, indent=2)}"
    )
    resultado = rodar_com_limites_sync(
        agentes.criar_coordenador(hooks),
        entrada,
        hooks=hooks,
        timeout_s=180,
        max_turns=6,
    )
    return resultado.final_output


def processar(texto: str, hooks: RunHooks | None = None) -> dict:
    # ETAPA 6.4 -- encadeie, imprimindo cada passo ("[1/9] guardrails", ...):
    #   1. encontrar_dado_sensivel / nota_escopo >= LIMIAR  -> devolva {"resultado": "bloqueado", "mensagem": ...}
    #   2. pedido = extrair(texto).model_dump(mode="json")  -> sem matrícula ou datas: {"resultado": "pedir_dados"}
    #   3. servidor = chamar_mcp("consultar_servidor", ...) -> não encontrado: {"resultado": "pedir_dados"}
    #   4. periodo = resumo_periodo(...)                     (API de feriados, Etapa 4)
    #   5. escala = chamar_mcp("consultar_escala", ...); violacoes = violacoes_objetivas(...)
    #   6. parecer = analisar(...)
    #   7. despacho = rodar_com_limites_sync(agentes.criar_redator(), <fatos + parecer + violações>).final_output
    #   8. protocolo = gerar_protocolo(...)
    #   9. chamar_mcp("registrar_decisao", {..., "decisao": "indeferido" se houver violação senão "deferido",
    #        "aprovador": "pendente_chefia" se precisa_chefia(...) senão "sistema", "token": os.getenv("TOKEN_REGISTRO")})
    #      (a aprovação de verdade da chefia entra na Etapa 8; aqui só marcamos que ela será necessária)
    #   Devolva {"resultado": ..., "protocolo": ..., "despacho": ..., "parecer": ...}.
    print("[1/9] guardrails")
    sensivel = encontrar_dado_sensivel(texto)
    if sensivel:
        return {"resultado": "bloqueado", "mensagem": MENSAGENS[sensivel]}
    nota, _ = nota_escopo(texto)
    if nota >= LIMIAR:
        return {"resultado": "bloqueado", "mensagem": MENSAGENS["fora_do_escopo"]}

    pedido = _normalizar_pedido(texto, extrair(texto).model_dump(mode="json"))
    print(f"[2/9] extração: {pedido.get('tipo')} {pedido.get('matricula')} {pedido.get('data_inicio')}..{pedido.get('data_fim')}")
    if not pedido.get("matricula") or not pedido.get("data_inicio") or not pedido.get("data_fim"):
        return {
            "resultado": "pedir_dados",
            "mensagem": "Informe matrícula e datas exatas (início e fim) no formato AAAA-MM-DD.",
            "pedido": pedido,
        }

    servidor = chamar_mcp("consultar_servidor", {"matricula": pedido["matricula"]})
    if servidor.get("erro"):
        return {
            "resultado": "pedir_dados",
            "mensagem": "Matrícula não encontrada. Confira o número informado.",
            "pedido": pedido,
        }
    print(f"[3/9] servidor: {servidor.get('nome')} ({servidor.get('equipe')})")

    periodo = resumo_periodo(pedido["data_inicio"], pedido["data_fim"])
    print(
        f"[4/9] período: {periodo.get('dias_uteis')} dia(s) útil(is), "
        f"retorno {periodo.get('retorno')} (fonte: {periodo.get('fonte_feriados')})"
    )

    escala = chamar_mcp(
        "consultar_escala",
        {"equipe": servidor["equipe"], "inicio": pedido["data_inicio"], "fim": pedido["data_fim"]},
    )
    violacoes = violacoes_objetivas(pedido, servidor, periodo, escala)
    print(f"[5/9] violações: {violacoes or 'nenhuma'}")

    print("[6/9] coordenador")
    try:
        parecer = analisar(pedido, servidor, periodo, violacoes, hooks=hooks)
        especialistas = ["parecer_normas", "parecer_escala"]
        if pedido["tipo"] == "diaria" or (pedido["tipo"] == "ferias" and pedido.get("dias_vendidos", 0) > 0):
            especialistas.append("parecer_financeiro")
        print(f"        consultou {', '.join(especialistas)}")
    except (TempoEsgotado, LoopExcedido) as erro:
        parecer = (
            "Parecer de contingência (timeout do coordenador): "
            f"decisão {'indeferida' if violacoes else 'deferida'} com base nas regras objetivas."
        )
        print(f"        contingência por limite de tempo ({erro})")

    print("[7/9] redator")
    decisao = "indeferido" if violacoes else "deferido"
    fatos = (
        "Você vai redigir o despacho com base nos fatos abaixo.\n"
        f"Pedido: {json.dumps(pedido, ensure_ascii=False)}\n"
        f"Servidor: {json.dumps({'matricula': servidor.get('matricula'), 'nome': servidor.get('nome'), 'equipe': servidor.get('equipe')}, ensure_ascii=False)}\n"
        f"Período: {json.dumps(periodo, ensure_ascii=False)}\n"
        f"Violações: {json.dumps(violacoes, ensure_ascii=False)}\n"
        f"Parecer consolidado: {parecer}\n"
        f"Decisão pretendida: {decisao}"
    )
    try:
        despacho = rodar_com_limites_sync(
            agentes.criar_redator(),
            fatos,
            hooks=hooks,
            timeout_s=120,
            max_turns=4,
        ).final_output
    except (TempoEsgotado, LoopExcedido) as erro:
        despacho = _despacho_fallback(pedido, violacoes, decisao)
        print(f"        contingência por limite de tempo ({erro})")

    if not _despacho_coerente(despacho, decisao):
        despacho = _despacho_fallback(pedido, violacoes, decisao)

    protocolo = gerar_protocolo(pedido["matricula"], pedido["tipo"], pedido["data_inicio"], pedido["data_fim"])
    print(f"[8/9] protocolo {protocolo}")

    registro = chamar_mcp(
        "registrar_decisao",
        {
            "protocolo": protocolo,
            "matricula": pedido["matricula"],
            "tipo": pedido["tipo"],
            "inicio": pedido["data_inicio"],
            "fim": pedido["data_fim"],
            "decisao": decisao,
            "aprovador": "pendente_chefia" if precisa_chefia(pedido, violacoes) else "sistema",
            "despacho": despacho,
            "token": os.getenv("TOKEN_REGISTRO", ""),
        },
    )
    print(f"[9/9] registrar: {registro}")

    resultado = "registrado" if registro.get("sucesso") else f"negado_pelo_server: {registro.get('erro', 'erro desconhecido')}"
    return {"resultado": resultado, "protocolo": protocolo, "despacho": despacho, "parecer": parecer}


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
