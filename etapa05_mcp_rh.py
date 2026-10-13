"""
ETAPA 5 -- MCP Server do RH (30 min). Volta aqui na ETAPA 9 (token, regra N8 e auditoria).

Os dados saem de dentro do agente e passam a morar num PROCESSO SEPARADO, que fala MCP. O agente (Etapa 5.3) e os
nós do grafo (Etapa 7, via cliente_mcp.chamar_mcp) só enxergam as tools abaixo: nunca os CSVs.

ESQUELETO: implemente as etapas na ordem (troque cada raise NotImplementedError pelo código da etapa).
  ETAPA 5.1 -- as 5 tools de LEITURA: declare cada uma com @mcp.tool(), escreva a DOCSTRING (é o "schema" que o LLM
               lê) e devolva o resultado da consulta pronta de dados_rh.py. Toda tool devolve UM dict.
  ETAPA 5.2 -- a tool de ESCRITA registrar_decisao, IDEMPOTENTE (protocolo repetido não duplica)
  ETAPA 9.2 -- autorização NO SERVER: token + regra N8 (chefia certa, nunca o próprio servidor) + decisão num enum
  ETAPA 9.3 -- auditoria: toda tentativa de escrita (ALLOW ou DENY) vira uma linha em saidas/auditoria.jsonl

REFERÊNCIAS NAS AULAS
  aula6/desafio2/mcp_unidades.py               MCP Server que lê um CSV                          <- o mais parecido (5.1)
  aula5/exemplos/03_mcp_parametros/server.py   tool com parâmetros opcionais
  aula5/exemplos/05_multiplas_tools/server.py  várias tools no mesmo server, tool de "descoberta"
  aula3/agente_retry3.py                       idempotência (5.2)
  aula5/exemplos/10_seguranca/server_seguro.py token, enum fechado e auditoria NO SERVER        <- o mais parecido (9.2/9.3)

Testar sem agente (MCP Inspector, precisa de Node.js):
    npx @modelcontextprotocol/inspector python etapa05_mcp_rh.py

Pronto quando: o Inspector lista as 6 tools; registrar C1 duas vezes gera um único registro.
"""
import json
import os
from datetime import datetime

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

from dados_rh import PASTA, SAIDAS, carregar_servidores, diaria, escala_da_equipe, normas, remuneracao, servidor_publico

# O server roda como SUBPROCESSO: ele não herda o ambiente de quem o chamou. Por isso carrega o .env sozinho
# (mesmo cuidado de aula5/exemplos/02_mcp_basico/database.py).
load_dotenv(PASTA / ".env")

mcp = MCPServer("rh-mcp")

ARQUIVO_REGISTROS = SAIDAS / "registros.json"
ARQUIVO_AUDITORIA = SAIDAS / "auditoria.jsonl"
TOKEN_REGISTRO = os.getenv("TOKEN_REGISTRO", "")
DECISOES_VALIDAS = {"deferido", "indeferido", "indeferido_pela_chefia"}
TIPOS_COM_CHEFIA = {"ferias", "diaria"}  # regra N8


def _ler_registros() -> dict:
    """(PRONTO) {protocolo: registro} gravados até agora."""
    if ARQUIVO_REGISTROS.exists():
        return json.loads(ARQUIVO_REGISTROS.read_text(encoding="utf-8"))
    return {}


def _gravar_registros(registros: dict) -> None:
    """(PRONTO)"""
    ARQUIVO_REGISTROS.write_text(json.dumps(registros, ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------------------------------------------------ ETAPA 5.1: leitura
@mcp.tool()
def consultar_servidor(matricula: str) -> dict:
    """Consulta o cadastro público de um servidor, sem o salário-base.

    Args:
        matricula: matrícula do servidor (ex.: "1002").
    """
    # Devolva servidor_publico(matricula) (dados_rh.py): já tira o salário e trata matrícula inexistente.
    return servidor_publico(matricula)


@mcp.tool()
def consultar_escala(equipe: str, inicio: str, fim: str) -> dict:
    """Consulta a escala da equipe no período e calcula o limite da regra N5.

    Args:
        equipe: nome da equipe (ex.: "Cartório").
        inicio: data inicial no formato AAAA-MM-DD.
        fim: data final no formato AAAA-MM-DD.
    """
    # Devolva escala_da_equipe(equipe, inicio, fim) (dados_rh.py). Na docstring, diga o formato das datas (AAAA-MM-DD)
    # e o que volta (tamanho da equipe, limite de afastados e os afastamentos que se sobrepõem ao período).
    return escala_da_equipe(equipe, inicio, fim)


@mcp.tool()
def consultar_normas(tema: str) -> dict:
    """Lista as normas do tema informado.

    Args:
        tema: tema das normas (ex.: férias, prazos, escala, abono, diária, aprovação, saúde, dados).
    """
    # Devolva {"tema": tema, "regras": normas(tema)} (normas() está em dados_rh.py).
    # Por que um dict e não a lista direto? Uma tool MCP que devolve LISTA manda cada item como um conteúdo separado:
    # quem chama não distingue "lista com 1 regra" de "1 dict". Neste server, TODA tool devolve UM dict.
    return {"tema": tema, "regras": normas(tema)}


@mcp.tool()
def tabela_diarias(tipo_destino: str) -> dict:
    """Consulta a tabela de diárias por tipo de destino.

    Args:
        tipo_destino: tipo de destino (capital, interior ou exterior).
    """
    # Devolva diaria(tipo_destino) (dados_rh.py).
    return diaria(tipo_destino)


@mcp.tool()
def consultar_remuneracao(matricula: str) -> dict:
    """[RESTRITA] Consulta salário-base de um servidor.

    Args:
        matricula: matrícula do servidor (ex.: "1002").
    """
    # Devolva remuneracao(matricula) (dados_rh.py).
    return remuneracao(matricula)


# ------------------------------------------------------------------ ETAPA 5.2 / 9.2 / 9.3: escrita
def _auditar(protocolo: str, decisao_acesso: str, motivo: str, parametros: dict) -> None:
    # ETAPA 9.3 -- acrescente UMA linha JSON em ARQUIVO_AUDITORIA com: quando (datetime.now().isoformat()),
    #   thread_id, quem pediu (aprovador), tool ("registrar_decisao"), protocolo, decisao_acesso ("ALLOW"/"DENY"),
    #   motivo e os parâmetros (SEM o token e SEM o despacho inteiro).
    #   Referência: aula5/exemplos/10_seguranca/server_seguro.py (_registrar_auditoria), aqui em JSON Lines.
    #   Até fazer a 9.3, este pass deixa a escrita funcionar sem auditoria.
    registro = {
        "quando": datetime.now().isoformat(),
        "thread_id": parametros.get("thread_id", ""),
        "quem": parametros.get("aprovador", ""),
        "tool": "registrar_decisao",
        "protocolo": protocolo,
        "decisao_acesso": decisao_acesso,
        "motivo": motivo,
        "parametros": dict(parametros),
    }
    with open(ARQUIVO_AUDITORIA, "a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")


@mcp.tool()
def registrar_decisao(protocolo: str, matricula: str, tipo: str, inicio: str, fim: str, decisao: str,
                      aprovador: str, despacho: str, token: str, thread_id: str = "") -> dict:
    """[ESCRITA -- requer autorização] TODO ETAPA 5.2: docstring.

    Args:
        protocolo: protocolo idempotente do pedido (ferramentas.gerar_protocolo).
        ...: TODO descreva os demais.
        token: token de registro. Sem ele, a gravação é negada.
    """
    parametros = {"matricula": matricula, "tipo": tipo, "inicio": inicio, "fim": fim, "decisao": decisao,
                  "aprovador": aprovador, "thread_id": thread_id}

    # ETAPA 9.2 -- ANTES de gravar, negue (e audite com DENY) quando:
    #   - token != TOKEN_REGISTRO (ou TOKEN_REGISTRO vazio);
    #   - decisao não está em DECISOES_VALIDAS;
    #   - aprovador == matricula (ninguém aprova o próprio pedido, N8);
    #   - decisao == "deferido" e tipo in TIPOS_COM_CHEFIA e aprovador != chefia do servidor no cadastro.
    #   Devolva {"sucesso": False, "erro": "..."} -- quem nega é o SERVER, não o agente.
    #   Referência: aula5/exemplos/10_seguranca/server_seguro.py (alterar_status_ocorrencia)
    if not TOKEN_REGISTRO or token != TOKEN_REGISTRO:
        _auditar(protocolo, "DENY", "token inválido", parametros)
        return {"sucesso": False, "erro": "token inválido"}

    if decisao not in DECISOES_VALIDAS:
        _auditar(protocolo, "DENY", f"decisão inválida ({decisao})", parametros)
        return {"sucesso": False, "erro": f"decisão inválida: use {sorted(DECISOES_VALIDAS)}"}

    if aprovador == matricula:
        _auditar(protocolo, "DENY", "autoaprovação (N8)", parametros)
        return {"sucesso": False, "erro": "autoaprovação (N8)"}

    if decisao == "deferido" and tipo in TIPOS_COM_CHEFIA:
        servidor = carregar_servidores().get(matricula)
        if not servidor:
            _auditar(protocolo, "DENY", "matrícula não encontrada", parametros)
            return {"sucesso": False, "erro": "matrícula não encontrada"}
        chefia = servidor.get("chefia")
        if aprovador != chefia:
            _auditar(protocolo, "DENY", f"aprovador não é a chefia {chefia} (N8)", parametros)
            return {"sucesso": False, "erro": f"aprovador não é a chefia {chefia} (N8)"}

    # ETAPA 5.2 -- grave em ARQUIVO_REGISTROS (use _ler_registros/_gravar_registros).
    #   Protocolo já existe -> NÃO grave de novo; devolva {"sucesso": True, "duplicado": True, ...}.
    #   Senão grave {**parametros, "despacho": despacho, "registrado_em": ...} e devolva {"sucesso": True, ...}.
    #   Audite com ALLOW (9.3).
    registros = _ler_registros()
    if protocolo in registros:
        _auditar(protocolo, "ALLOW", "duplicado", parametros)
        return {"sucesso": True, "duplicado": True, "protocolo": protocolo}

    registros[protocolo] = {
        **parametros,
        "despacho": despacho,
        "registrado_em": datetime.now().isoformat(),
    }
    _gravar_registros(registros)
    _auditar(protocolo, "ALLOW", "gravado", parametros)
    return {"sucesso": True, "protocolo": protocolo}


if __name__ == "__main__":
    mcp.run(transport="stdio")
