"""
Teste de integração cnpj-cadastro -> lakehouse -> chatbot (agent.py), contra a AWS.

    make ia-chatbot-integracao
    make ia-chatbot-integracao ARGS="--com-llm"     # também chama o modelo (precisa de MODEL_ID)
    make ia-chatbot-integracao ARGS="--cnpj 33000167000101 --timeout-pipeline 3600"

O contrato entre as duas partes é o CNPJ: o da organização que a API grava no DynamoDB
precisa chegar nas views do gold, onde o agente filtra (`WHERE cnpj = ?`). Quem leva o dado
de um lado para o outro é o pipeline do stack lakehouse-pipeline (export do DynamoDB ->
landing -> bronze -> silver -> gold). Em produção quem descobre o CNPJ do usuário é a Lambda
api/chatbot; aqui o teste usa o CNPJ que o GET /cadastro/me devolveu.

  1. pela API: A cadastra o CNPJ (dono), B aceita o convite (membro), C não tem organização
  2. roda o pipeline do lakehouse e espera terminar (~15 min, por causa do export)
  3. ferramentas do agente com o CNPJ da organização:
       A e B (mesma organização) veem a empresa (mesmo CNPJ e razão social do GET /cadastro/me);
       um CNPJ sem dados não devolve nada
  4. invoke() recusa cnpj e user_id fora do formato (o filtro do Athena é montado com eles)
  5. (--com-llm) o agente responde com a razão social da empresa

Limpeza: usuários do Cognito e itens do DynamoDB (como os smoke tests) e as linhas
deles no silver e no gold, porque o pipeline só faz upsert e nunca apaga.
Se o pipeline falhar, o tópico de alerta dele recebe o aviso, como numa falha real.
Sai com 0 se tudo passar, 1 se falhar.
"""

import argparse
import os
import re
import sys
import time
import uuid
from pathlib import Path

import boto3

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parents[2] / "api" / "cnpj-cadastro" / "tests"))  # smoke_lib
sys.path.insert(0, str(AQUI.parent))                                   # agent.py

from smoke_lib import Smoke, http  # noqa: E402

REGION = "us-east-1"
TABELAS_DO_LAKE = ("silver_db.usuarios_cnpj", "silver_db.socios", "gold_db.empresas_clientes")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stack", default="cnpj-cadastro")
    p.add_argument("--lakehouse-stack", default="lakehouse-pipeline")
    p.add_argument("--cnpj", default="00000000000191", help="um CNPJ real e ativo, sem dono no cadastro")
    p.add_argument("--timeout", type=int, default=60, help="segundos esperando a consulta do CNPJ")
    p.add_argument("--timeout-pipeline", type=int, default=2400, help="segundos esperando o pipeline")
    p.add_argument("--com-llm", action="store_true", help="também chama o agente com o modelo (MODEL_ID)")
    args = p.parse_args()

    if args.com_llm and not os.environ.get("MODEL_ID"):
        sys.exit("--com-llm precisa de MODEL_ID no ambiente (o mesmo do runtime do agente)")

    lake = Lakehouse(args.lakehouse_stack)
    s = Smoke(args.stack)
    rodou_pipeline = False
    try:
        rodou_pipeline = run(s, lake, args)
    finally:
        s.cleanup()
        if rodou_pipeline:
            lake.apagar_linhas_de_teste(s)
    s.finish()


class Lakehouse:
    """Pipeline (Step Functions) e consultas no Athena do stack lakehouse-pipeline."""

    def __init__(self, stack: str):
        cfn = boto3.client("cloudformation", region_name=REGION)

        def recurso(logical_id: str) -> str:
            return cfn.describe_stack_resource(
                StackName=stack, LogicalResourceId=logical_id)["StackResourceDetail"]["PhysicalResourceId"]

        self.state_machine = recurso("PipelineStateMachine")
        # O agente usa o workgroup do lakehouse (já tem local de saída); ATHENA_OUTPUT só vale
        # para um workgroup sem local de saída, como o "primary".
        self.athena_output = os.environ.get("ATHENA_OUTPUT") or f"s3://{recurso('LakeBucket')}/athena-results/"
        self.sfn = boto3.client("stepfunctions", region_name=REGION)
        self.athena = boto3.client("athena", region_name=REGION)
        print(f"Lakehouse {stack}\n  Pipeline:  {self.state_machine.rsplit(':', 1)[-1]}\n"
              f"  Athena:    {self.athena_output}\n")

    def rodar_pipeline(self, timeout: int) -> tuple[str, str]:
        """Dispara o pipeline e espera. Devolve (status, motivo da falha)."""
        arn = self.sfn.start_execution(
            stateMachineArn=self.state_machine, name=f"integracao-{uuid.uuid4().hex[:8]}", input="{}",
        )["executionArn"]
        inicio = time.time()
        while time.time() - inicio < timeout:
            ex = self.sfn.describe_execution(executionArn=arn)
            if ex["status"] != "RUNNING":
                return ex["status"], self._motivo_da_falha(arn) if ex["status"] != "SUCCEEDED" else ""
            print(f"    ... {time.time() - inicio:.0f}s", end="\r", flush=True)
            time.sleep(20)
        return "TIMEOUT", f"não terminou em {timeout}s ({arn})"

    def _motivo_da_falha(self, arn: str) -> str:
        """O pipeline captura o erro em $.erro e segue para AvisarFalha: o motivo está lá."""
        eventos = self.sfn.get_execution_history(executionArn=arn, reverseOrder=True, maxResults=100)["events"]
        for e in eventos:
            for chave in ("taskFailedEventDetails", "executionFailedEventDetails"):
                if chave in e:
                    d = e[chave]
                    return f"{d.get('error', '')}: {d.get('cause', '')}"[:600]
        return arn

    def _sql(self, sql: str) -> None:
        qid = self.athena.start_query_execution(
            QueryString=sql, WorkGroup="primary", ResultConfiguration={"OutputLocation": self.athena_output},
        )["QueryExecutionId"]
        while True:
            st = self.athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
            if st["State"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
                break
            time.sleep(1)
        if st["State"] != "SUCCEEDED":
            raise RuntimeError(st.get("StateChangeReason", st["State"]))

    def apagar_linhas_de_teste(self, s: Smoke) -> None:
        """Tira do lake tudo que veio dos itens de teste: o sub de cada usuário e as
        chaves da organização e dos convites (o ETL usa a chave do item como user_id)."""
        chaves = set()
        for user in s._users:
            chaves |= {user.sub, f"CONVITE#{user.email}"}
        chaves |= {f"CNPJ#{c}" for c in getattr(s, "cnpjs_de_teste", ())}
        lista = ", ".join("'" + c.replace("'", "''") + "'" for c in sorted(chaves))
        for tabela in TABELAS_DO_LAKE:
            try:
                self._sql(f"DELETE FROM {tabela} WHERE user_id IN ({lista})")
            except Exception as exc:  # não esconde o resultado dos testes por causa da limpeza
                print(f"  ⚠️  falha ao limpar {tabela}: {exc}")
        print(f"  linhas de teste apagadas de {', '.join(TABELAS_DO_LAKE)}")


def so_digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def run(s: Smoke, lake: Lakehouse, args) -> bool:
    """Devolve True se chegou a rodar o pipeline (aí é preciso limpar o lake)."""
    a, b, c = s.new_user(), s.new_user(), s.new_user()
    for user in (a, b, c):
        user.login()
    print(f"  usuário A (dono):   {a.email}  {a.sub}\n"
          f"  usuário B (membro): {b.email}  {b.sub}\n"
          f"  usuário C (sem organização): {c.email}  {c.sub}\n")

    print("  1. cadastro pela API")
    code, body = http("POST", s.api_url, a.access_token, {"cnpj": args.cnpj})
    if not s.check("A: POST /cadastro -> 202", code == 202, f"{code} {body}"):
        return False
    s.cnpjs_de_teste = [so_digitos(args.cnpj)]

    inicio, cad = time.time(), None
    while time.time() - inicio < args.timeout:
        code, body = http("GET", f"{s.api_url}/me", a.access_token)
        if code == 200 and body.get("status") != "processando":
            cad = body
            break
        time.sleep(2)
    if not s.check("consulta do CNPJ terminou", cad is not None, "veja sam logs -n CnpjLookupFunction"):
        return False
    if not s.check("status é 'ativa'", cad.get("status") == "ativa", f"status={cad.get('status')}"):
        return False
    razao = (cad.get("empresa") or {}).get("razao_social")
    print(f"    {cad.get('cnpj')} {razao}")

    code, body = http("POST", f"{s.api_url}/membros", a.access_token, {"email": b.email})
    s.check("A convida B -> 201", code == 201, f"{code} {body}")
    code, body = http("POST", f"{s.api_url}/convite", b.access_token)
    s.check("B aceita o convite -> 200", code == 200, f"{code} {body}")

    print(f"\n  2. pipeline do lakehouse (até {args.timeout_pipeline}s)")
    inicio = time.time()
    status, motivo = lake.rodar_pipeline(args.timeout_pipeline)
    print(f"    terminou em {time.time() - inicio:.0f}s")
    if not s.check("pipeline -> SUCCEEDED", status == "SUCCEEDED", f"{status} {motivo}"):
        return True

    # Só agora: agent.py lê as variáveis de ambiente na importação.
    os.environ.setdefault("MODEL_ID", "nao-usado-sem-llm")
    os.environ["ATHENA_OUTPUT"] = lake.athena_output
    import agent

    def ferramentas(cnpj):
        return {t.tool_name: t for t in agent.make_tools(cnpj)}

    print("\n  3. ferramentas do agente")
    for nome, user in (("A (dono)", a), ("B (membro)", b)):
        painel = ferramentas(cad["cnpj"])["painel_da_empresa"]()
        linha = painel[0] if painel else {}
        if not s.check(f"{nome}: painel_da_empresa encontra a empresa", linha and "erro" not in linha,
                       f"resposta={painel}  (o CNPJ {cad['cnpj']} não está nas views do gold)"):
            continue
        s.check(f"{nome}: mesmo CNPJ do cadastro", so_digitos(linha.get("cnpj")) == so_digitos(cad.get("cnpj")),
                f"{linha.get('cnpj')} != {cad.get('cnpj')}")
        s.check(f"{nome}: mesma razão social do cadastro", linha.get("razao_social") == razao,
                f"{linha.get('razao_social')!r} != {razao!r}")

    painel_outro = ferramentas("99999999000199")["painel_da_empresa"]()
    s.check("CNPJ sem dados: painel vazio", painel_outro == [], f"resposta={painel_outro}")

    atos = ferramentas(cad["cnpj"])["atos_no_dou"](limite=5)
    s.check("A: atos_no_dou roda sem erro", not any("erro" in r for r in atos), f"resposta={atos}")

    frescor = ferramentas(cad["cnpj"])["atualizacao_dos_dados"]()
    origens = {r.get("origem") for r in frescor}
    s.check("atualizacao_dos_dados lista o cadastro (DynamoDB)", "cadastro (DynamoDB)" in origens, f"resposta={frescor}")

    print("\n  4. cnpj e user_id inválidos")
    for campo, invalido in (("cnpj", f"CNPJ#{so_digitos(args.cnpj)}"), ("cnpj", "x' OR '1'='1"), ("cnpj", ""),
                            ("user_id", "x' OR '1'='1"), ("user_id", "")):
        payload = {"cnpj": cad["cnpj"], "user_id": a.sub, "prompt": "qual minha empresa?", campo: invalido}
        resp = agent.invoke(payload)
        s.check(f"invoke recusa {campo} {invalido!r}", "erro" in resp and "resposta" not in resp, f"resposta={resp}")

    if args.com_llm:
        print("\n  5. agente com o modelo")
        resp = agent.invoke({"cnpj": cad["cnpj"], "user_id": a.sub,
                             "prompt": "Qual é a razão social e o CNPJ da minha empresa?"})
        resposta = resp.get("resposta", "")
        print(f"    {resposta[:300]}")
        primeira_palavra = (razao or "").split()[0].lower() if razao else "\0"
        s.check("resposta cita a empresa", primeira_palavra in resposta.lower()
                or so_digitos(args.cnpj) in so_digitos(resposta), f"resposta={resp}")
    return True


if __name__ == "__main__":
    main()
