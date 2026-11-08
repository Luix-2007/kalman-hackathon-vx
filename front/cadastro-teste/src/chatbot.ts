/**
 * Cliente da API do chatbot (stack chatbot-api). Referência para o front no Lovable.
 *
 * Mesmo login do cadastro (access token do Cognito). O CNPJ vem da organização do usuário,
 * decidida pela API: nunca envie cnpj nem user_id.
 *
 * A resposta tem duas partes:
 *   resposta  resumo curto, escrito pelo modelo. É TEXTO: mostre como texto, nunca como HTML.
 *   blocos    os dados que a tela desenha (tarefas, linha do tempo...). Montados em código a
 *             partir das consultas, com tipos e campos fixos, então dá para desenhar cada tipo
 *             sempre do mesmo jeito. Pode vir vazio (recusa, pergunta sem dado).
 *
 * O contrato está em ia/chatbot/contrato/: schema.json (JSON Schema) e exemplos.json (respostas de
 * exemplo da Aurora, que servem de mock). Os tipos abaixo seguem o schema campo a campo; todos os
 * campos de um item sempre existem, com null quando não há valor.
 *
 * Erros: 429 (limite de mensagens por hora ou dia; header Retry-After), 504 (o assistente
 * demorou), 502 (falha; tente de novo), 404 (usuário sem organização), 400 (mensagem inválida).
 * A mensagem para o usuário já vem em `erro`.
 */
import { ApiError, request } from "./api";
import { config } from "./config";

export const PROMPT_MAX = 2000; // o mesmo limite da API

// ---------- blocos de dados (contrato: ia/chatbot/contrato/schema.json) ----------

export type Empresa = {
  cnpj: string | null;
  razao_social: string | null;
  situacao_cadastral: string | null;
  status_cadastro: string | null;
  capital_social: string | null;
  qtd_socios: number | null;
  atos_no_dou: number | null;
  tipos_de_ato: number | null;
  ato_mais_recente: string | null; // AAAA-MM-DD
};

export type Ato = {
  data_publicacao: string | null; // AAAA-MM-DD
  tipo: string | null;
  orgao: string | null;
  identifica: string | null;
  ementa: string | null;
  url_pdf: string | null; // sempre http(s) ou null
};

export type Obrigacao = {
  obrigacao_id: string | null;
  versao: number | null;
  titulo: string | null;
  orgao_sigla: string | null;
  tema: string | null;
  recorrencia: string | null;
  periodicidade: string | null;
  prazo_regra: string | null;
  area_responsavel: string | null;
  criticidade: string | null;
  status: "proposta" | "aprovada" | "rejeitada" | "revogada" | string | null;
  vigente: boolean | null;
  data_ato: string | null;
  vigente_de: string | null;
  vigente_ate: string | null;
};

export type Tarefa = {
  descricao: string | null;
  vencimento: string | null; // AAAA-MM-DD
  status: "aberta" | "em_andamento" | "concluida" | string | null;
  em_risco: boolean | null;
  area_responsavel: string | null;
  obrigacao_id: string | null;
  obrigacao_versao: number | null;
};

export type Alteracao = { campo: string; antes: string | null; depois: string | null };

export type EventoDaLinhaDoTempo = {
  ocorrido_em: string | null; // AAAA-MM-DD
  obrigacao_id: string | null;
  titulo: string | null;
  versao: number | null;
  evento: "inclusao" | "alteracao" | "revogacao" | "aprovacao" | "rejeicao" | string | null;
  resumo: string | null;
  ato_id: string | null;
  data_ato: string | null; // publicação do ato
  trecho_citado: string | null;
  alteracoes: Alteracao[] | null; // o antes e o depois de cada campo
};

export type Versao = {
  obrigacao_id: string | null;
  versao: number | null;
  titulo: string | null;
  status: string | null;
  vigente: boolean | null;
  vigente_de: string | null;
  vigente_ate: string | null;
  orgao_sigla: string | null;
  fonte_ato: string | null;
  fonte_dispositivo: string | null;
  data_ato: string | null;
  trecho_citado: string | null;
  prazo_regra: string | null;
  area_responsavel: string | null;
  evidencia: string | null;
  criticidade: string | null;
  aplica_a: string[] | null;
};

type Parametros = { em_risco?: boolean; obrigacao_id?: string };

/** Um bloco de dados. `tipo` diz o formato dos `itens`; `parametros` ajuda a rotular (ex.: "só em risco"). */
export type Bloco =
  | { tipo: "empresa"; parametros: Parametros; itens: Empresa[] }
  | { tipo: "atos"; parametros: Parametros; itens: Ato[] }
  | { tipo: "obrigacoes"; parametros: Parametros; itens: Obrigacao[] }
  | { tipo: "tarefas"; parametros: Parametros; itens: Tarefa[] }
  | { tipo: "linha_do_tempo"; parametros: Parametros; itens: EventoDaLinhaDoTempo[] }
  | { tipo: "versoes"; parametros: Parametros; itens: Versao[] };

export type Resposta = { resposta: string; blocos: Bloco[] };

/** Uma conversa = um session_id. A API deriva a sessão do usuário: não dá para entrar na de outro. */
export const novaConversa = () => crypto.randomUUID();

/** Envia uma mensagem e devolve o resumo e os blocos de dados. */
export async function enviarMensagem(prompt: string, sessionId: string): Promise<Resposta> {
  // sem esta guarda, o request cairia na URL do cadastro (valor padrão) e chamaria a API errada
  if (!config.chatbotApiUrl) throw new Error("VITE_CHATBOT_API_URL não está configurada (make front-env)");
  const { status, data } = await request(
    "POST", "/chatbot/mensagens", { prompt, session_id: sessionId }, config.chatbotApiUrl);
  if (status !== 200) throw new ApiError(status, data);
  const r = data as Partial<Resposta>;
  return { resposta: r.resposta ?? "", blocos: Array.isArray(r.blocos) ? r.blocos : [] };
}
