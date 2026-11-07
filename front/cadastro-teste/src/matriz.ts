/**
 * Cliente da API da matriz de obrigações (stack matriz-api). Referência para o front no Lovable.
 *
 * Mesmo login do cadastro (access token do Cognito). O CNPJ e o papel vêm da API:
 * nunca envie cnpj. Membros leem; só o dono decide propostas e muda status de tarefas (403).
 */
import { ApiError, request } from "./api";
import { config } from "./config";

export type Obrigacao = {
  cnpj: string;
  obrigacao_id: string;
  versao: number;
  titulo: string;
  fonte_ato: string | null;
  fonte_dispositivo: string | null;
  fonte_url: string | null;
  trecho_citado: string | null;
  orgao_sigla: string | null;
  tema: string | null;
  aplica_a: string[];
  recorrencia: "periodica" | "por_evento" | "continua";
  periodicidade: string | null;
  prazo_regra: string | null;
  prazo_json: string | null;
  area_responsavel: string | null;
  evidencia: string | null;
  criticidade: "baixa" | "media" | "alta" | null;
  origem: "matriz_importada" | "llm";
  status: "proposta" | "aprovada" | "rejeitada" | "revogada";
  confianca: number | null;
  incluida_em: string;
  alterada_por: string | null;
  vigente: boolean;
  mudanca: "inclusao" | "alteracao" | "revogacao";
};

export type Tarefa = {
  cnpj: string;
  tarefa_id: string;
  obrigacao_id: string;
  obrigacao_versao: number;
  unidade_id: string | null;
  outorga_id: string | null;
  descricao: string;
  vencimento: string; // AAAA-MM-DD
  area_responsavel: string | null;
  status: StatusTarefa;
  evidencia_url: string | null;
  em_risco: boolean;
  atualizada_em: string | null;
};

export type StatusTarefa = "aberta" | "em_andamento" | "concluida";

export type Historico = {
  obrigacao_id: string;
  versao: number;
  evento: "inclusao" | "alteracao" | "revogacao" | "aprovacao" | "rejeicao";
  status: string;
  origem: string | null;
  ocorrido_em: string;
  por: string | null;
  resumo: string | null;
};

const base = () => config.matrizApiUrl;

async function chamar<T>(method: string, path: string, ok: number, body?: unknown): Promise<T> {
  const { status, data } = await request(method, path, body, base());
  if (status !== ok) throw new ApiError(status, data);
  return data as T;
}

/** Versão vigente de cada obrigação + propostas aguardando decisão. `aviso` = matriz ainda não processada. */
export const getObrigacoes = () =>
  chamar<{ obrigacoes: Obrigacao[]; resumo?: { vigentes: number; propostas: number }; aviso?: string }>(
    "GET", "/obrigacoes", 200);

/** Todas as versões e o histórico de uma obrigação. */
export const getObrigacao = (id: string) =>
  chamar<{ versoes: Obrigacao[]; historico: Historico[] }>("GET", `/obrigacoes/${encodeURIComponent(id)}`, 200);

/** Aprova ou rejeita uma proposta. Devolve as versões e as tarefas recalculadas da obrigação. */
export const decidir = (id: string, versao: number, decisao: "aprovar" | "rejeitar", comentario?: string) =>
  chamar<{ versoes: Obrigacao[]; tarefas: Tarefa[] }>(
    "POST", `/obrigacoes/${encodeURIComponent(id)}/decisao`, 200, { versao, decisao, comentario });

export const getTarefas = (filtro: { em_risco?: boolean; obrigacao_id?: string } = {}) => {
  const q = new URLSearchParams();
  if (filtro.em_risco) q.set("em_risco", "true");
  if (filtro.obrigacao_id) q.set("obrigacao_id", filtro.obrigacao_id);
  const qs = q.toString();
  return chamar<{ tarefas: Tarefa[]; resumo?: { total: number; em_risco: number; concluidas: number }; aviso?: string }>(
    "GET", `/tarefas${qs ? `?${qs}` : ""}`, 200);
};

export const mudarTarefa = (id: string, status: StatusTarefa, evidencia_url?: string | null) =>
  chamar<{ tarefa: Tarefa }>("PATCH", `/tarefas/${id}`, 200,
    evidencia_url === undefined ? { status } : { status, evidencia_url });
