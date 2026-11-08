"""
Lambdas do passo de propostas (stack matriz-propostas). A máquina de estados
(statemachine/propostas.asl.json) chama, em ordem:

    indexar    {evento do EventBridge ou {"dias": 7}}         -> {run_id, dia, desde, indexacao}
    recuperar  {run_id, dia, desde}                           -> {run_id, dia, itens: [{run_id, dia, cnpj, ato_id}]}
    processar  {run_id, dia, cnpj, ato_id}  (um por item, Map) -> {cnpj, ato_id, resultado}
    resumir    {run_id, dia, resultados}                      -> contagem por resultado

Disparo: o fim com sucesso da execução do ETL do DOU (regra do EventBridge no template).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3
from botocore.config import Config as BotoConfig

from propostas import dados, fluxo, perfil
from propostas.armazem import ArmazemS3, gravar_json
from propostas.athena import Athena
from propostas.config import de_ambiente
from propostas.eventos import Registro
from propostas.modelo import Modelo
from propostas.vetores import IndiceS3Vectors, TitanEmbedder

log = logging.getLogger()
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

BRASILIA = timezone(timedelta(hours=-3))
CFG = de_ambiente()
_RETRIES = BotoConfig(retries={"mode": "adaptive", "max_attempts": 10}, read_timeout=120)
_clientes: dict = {}
_contextos: dict = {}


def _cliente(nome: str):
    if nome not in _clientes:
        _clientes[nome] = boto3.client(nome, region_name=CFG.regiao, config=_RETRIES)
    return _clientes[nome]


def _armazem() -> ArmazemS3:
    return ArmazemS3(_cliente("s3"), CFG.lake_bucket)


def _athena() -> Athena:
    return Athena(_cliente("athena"), CFG.athena_workgroup)


def _indice() -> IndiceS3Vectors:
    return IndiceS3Vectors(_cliente("s3vectors"), CFG.vector_bucket, CFG.indice_atos)


def _hoje() -> str:
    return datetime.now(BRASILIA).date().isoformat()


def indexar(event, context=None):
    event = event or {}
    dia = event.get("dia") or _hoje()
    # o id do evento do EventBridge identifica a execução; sem ele (disparo manual), o horário
    run_id = event.get("run_id") or event.get("id") or datetime.now(timezone.utc).strftime("manual-%Y%m%dT%H%M%S")
    dias = int(event.get("dias") or CFG.dias_indexar)
    desde = (datetime.fromisoformat(dia).date() - timedelta(days=dias)).isoformat()
    registro = Registro(_armazem(), run_id, dia)
    try:
        resumo = fluxo.indexar(dados.atos_desde(_athena(), desde), TitanEmbedder(_cliente("bedrock-runtime")),
                               _indice(), CFG, registro)
    finally:
        registro.descarregar("indexar")
    log.info(json.dumps({"etapa": "indexar", "run_id": run_id, **resumo}))
    return {"run_id": run_id, "dia": dia, "desde": desde, "indexacao": resumo}


def recuperar(event, context=None):
    run_id, dia, desde = event["run_id"], event["dia"], event["desde"]
    armazem = _armazem()
    registro = Registro(armazem, run_id, dia)
    try:
        empresas = dados.carregar_empresas(_athena())
        try:
            taxonomia = perfil.carregar_taxonomia(ArmazemS3(_cliente("s3"), CFG.taxonomia_uri.split("/")[2])
                                                  .ler(CFG.taxonomia_uri.split("/", 3)[3]))
        except Exception:
            log.warning("taxonomia indisponível em %s: segue sem as consultas por tipo", CFG.taxonomia_uri)
            taxonomia = None
        processados = {}
        for e in empresas:
            prefixo = fluxo.caminho_processado(e["cnpj"], "x").rsplit("/", 1)[0] + "/"
            processados[e["cnpj"]] = {k.rsplit("/", 1)[1][:-5] for k in armazem.listar(prefixo)}
        contexto, pares = fluxo.preparar(empresas, taxonomia, TitanEmbedder(_cliente("bedrock-runtime")), _indice(),
                                         CFG, desde, processados, registro)
        gravar_json(armazem, fluxo.caminho_contexto(run_id), contexto)
    finally:
        registro.descarregar("recuperar")
    itens = [{"run_id": run_id, "dia": dia, "cnpj": cnpj, "ato_id": c["ato_id"]} for cnpj, c in pares]
    log.info(json.dumps({"etapa": "recuperar", "run_id": run_id, "empresas": len(empresas), "pares": len(itens)}))
    return {"run_id": run_id, "dia": dia, "itens": itens}


def processar(event, context=None):
    run_id, dia, cnpj, ato_id = event["run_id"], event["dia"], event["cnpj"], event["ato_id"]
    armazem = _armazem()
    if run_id not in _contextos:
        _contextos.clear()
        _contextos[run_id] = fluxo.ler_contexto(armazem, run_id)
    ctx = _contextos[run_id]
    registro = Registro(armazem, run_id, dia)
    try:
        resultado = fluxo.processar(
            ctx["empresas"][cnpj], ctx["candidatos"][f"{cnpj}|{ato_id}"], dados.ato(_athena(), ato_id),
            Modelo(_cliente("bedrock-runtime"), CFG.modelo_triagem, 800),
            Modelo(_cliente("bedrock-runtime"), CFG.modelo_extracao, 8000), CFG, armazem, registro, dia)
    except Exception as exc:
        registro.evento("processar", cnpj=cnpj, ato_id=ato_id, resultado="erro", motivo=type(exc).__name__)
        raise
    finally:
        registro.descarregar(f"processar-{cnpj}")
    return resultado


def resumir(event, context=None):
    resumo = fluxo.resumir(event.get("resultados") or [])
    registro = Registro(_armazem(), event["run_id"], event["dia"])
    registro.evento("resumo", resultado="ok", detalhes=resumo)
    registro.descarregar("resumo")
    log.info(json.dumps({"etapa": "resumo", "run_id": event["run_id"], **resumo}))
    return {"run_id": event["run_id"], **resumo}
