"""
ETAPA 1 -- Primeiro agente com tool local (15 min).

ESQUELETO: implemente as etapas na ordem. Cada uma está marcada com um comentário e um
raise NotImplementedError: troque esse raise pelo código da etapa e rode o arquivo.
  ETAPA 1.1 -- a tool consultar_servidor (SEM o salário)
  ETAPA 1.2 -- o agente AtendenteRH com a tool
  ETAPA 1.3 -- duas perguntas: uma que precisa da tool e uma que não precisa

REFERÊNCIAS NAS AULAS
  aula1/segundo_agente.py                            Agent + @function_tool + Runner.run_sync (o básico)
  exercicios_resolvidos/aula4/ex10_function_tool.py  tool que consulta uma TABELA e devolve JSON  <- o mais parecido
  aula8/exemplos/02_agente_tool/main.py              o agente decide quando chamar a tool (e quando não)

Rodar (a partir de aula10/):
    python etapa01_agente.py

Pronto quando: a tool é chamada só na primeira pergunta (o print dentro dela prova).
"""
import json

from agents import Agent, Runner, function_tool

from dados_rh import servidor_publico
from provedor import configurar

MODELO = configurar()  # LLM REAL: PROVEDOR no .env (openai ou ollama)


# ETAPA 1.1 -- a tool
#   - ponha um print("[tool] consultar_servidor", matricula) no começo, para provar quando ela roda;
#   - devolva json.dumps(servidor_publico(matricula), ensure_ascii=False). A consulta servidor_publico() (dados_rh.py)
#     já vem pronta: tira o salário (dado restrito, ver Etapas 5 e 9) e trata matrícula inexistente;
#   - capriche na DOCSTRING (com Args:): é o que o LLM lê para decidir chamar a tool. Esse é o ponto da etapa.
#   Referência: exercicios_resolvidos/aula4/ex10_function_tool.py (consultar_protocolo)
@function_tool
def consultar_servidor(matricula: str) -> str:
    """Consulta os dados públicos de um servidor do RH.

    Args:
        matricula: matrícula do servidor, por exemplo "1002".
    """
    print(f"[tool] consultar_servidor {matricula}")
    return json.dumps(servidor_publico(matricula), ensure_ascii=False)


def criar_atendente() -> Agent:
    # ETAPA 1.2 -- o agente
    #   Agent(name="AtendenteRH", instructions=..., tools=[consultar_servidor])
    #   Instruções: atende servidores, responde em português e de forma breve, usa a tool quando a pergunta
    #   for sobre os dados de UM servidor, e não inventa saldo de cabeça.
    #   Referência: aula1/segundo_agente.py
    return Agent(
        name="AtendenteRH",
        instructions=(
            "Você atende servidores do RH. Responda em português, de forma breve e objetiva. "
            "Use a ferramenta consultar_servidor apenas quando a pergunta for sobre os dados de um servidor "
            "específico (por exemplo matrícula, férias, equipe ou chefia). Se a pergunta não for sobre um "
            "servidor em particular, responda sem inventar dados e sem usar a ferramenta."
        ),
        tools=[consultar_servidor],
    )


def main() -> None:
    # ETAPA 1.3 -- rode as duas perguntas com Runner.run_sync e imprima resultado.final_output
    #   1) "Quantos dias de férias a matrícula 1002 ainda tem?"   (precisa da tool)
    #   2) "O que é abono pecuniário?"                            (não precisa)
    #   Referência: aula8/exemplos/02_agente_tool/main.py
    atendente = criar_atendente()

    perguntas = [
        "Quantos dias de férias a matrícula 1002 ainda tem?",
        "O que é abono pecuniário?",
    ]

    for pergunta in perguntas:
        resultado = Runner.run_sync(atendente, pergunta)
        print(f"\nPergunta: {pergunta}\nResposta: {resultado.final_output}")


if __name__ == "__main__":
    print(f"[modelo] {MODELO}")
    main()
