/**
 * Dados do dash, por enquanto sem backend: uma loja em memória com os MESMOS tipos das APIs
 * (Obrigacao, Tarefa e Historico de src/matriz.ts; Resposta e Bloco de src/chatbot.ts).
 * Integrar = trocar o miolo das funções de `acoes` por getObrigacoes/getTarefas/getLinhaDoTempo/decidir/
 * mudarTarefa (matriz.ts) e enviarMensagem (chatbot.ts), mantendo a loja como cache da tela.
 *
 * O que é real e o que é exemplo:
 *  - REAL: a leitura da semana (dados/semana-2026-11.json): 1.931 atos da seção 1 do DOU de 03 a 06/11/2026, a
 *    triagem, os 13 alertas e os descartes com motivo, saídos do pipeline do benchmark (torre-regulatoria).
 *    As propostas abaixo usam o texto desses alertas (ato, página, trecho, prazo).
 *  - EXEMPLO: a matriz da Light (obrigações vigentes), as tarefas, as pessoas e as conversas da IA.
 *
 * Ainda não existe na API (precisa de rota nova): a leitura do DOU por empresa (funil e descartes) e o resumo do dia.
 */
import { useSyncExternalStore } from "react";
import { ApiError } from "../api";
import { enviarMensagem, novaConversa as novaSessao, type Ato, type Bloco, type EventoDaLinhaDoTempo, type Resposta, type Tarefa as TarefaChat } from "../chatbot";
import { demoAtivo } from "../demo";
import * as apiMatriz from "../matriz";
import type { Processamento } from "../matriz";
import type { Historico, Obrigacao, StatusTarefa, Tarefa } from "../matriz";
import semanaJson from "./dados/semana-2026-11.json";

// ─────────────────────────── tipos que a API ainda não tem ───────────────────────────

export type Dia = { data: string; atos: number; triagem: number; obrigacao: number; acompanhar: number };
export type Alerta = {
  id: string; data: string; orgao: string; tipo: string | null; identifica: string; ementa: string; pagina: string | null;
  url: string | null; decisao: "obrigacao" | "acompanhar"; destinatario: string; o_que_determina: string; motivo: string;
  trecho: string; prazo: string | null; unidade: string | null; altera_norma: string | null; confianca: number | null;
};
export type Descarte = { id: string; data: string; orgao: string; identifica: string; categoria: string; motivo: string };
export type Semana = {
  dias: Dia[]; alertas: Alerta[];
  descartes: { total: number; categorias: [string, number][]; amostra: Descarte[] };
};
export const semana = semanaJson as unknown as Semana;

/** Tarefa da tela: a da API + uma nota quando o prazo foi recalculado por uma nova versão. */
export type TarefaDash = Tarefa & { nota?: string };

/** `ms`: tempo da pergunta até a resposta, medido no navegador (inclui a rede, a Lambda e o agente). */
export type Mensagem = { id: string; de: "pessoa" | "ia"; texto: string; blocos?: Bloco[]; em: string; erro?: boolean; ms?: number };
export type Conversa = { id: string; titulo: string; criada_em: string; mensagens: Mensagem[] };

export const AREAS = ["Comercial", "Regulação", "Medição e faturamento", "Operação", "Financeiro"] as const;
export const EMPRESA = { nome: "Light SESA", cnpj: "60444437000146" };
export const PESSOA = { nome: "Ana Ribeiro", email: "regulacao@empresa-exemplo.com.br" };

// ─────────────────────────── datas ───────────────────────────

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export const HOJE = iso(new Date());
export const daqui = (dias: number) => { const d = new Date(); d.setDate(d.getDate() + dias); return iso(d); };
/** Soma dias úteis (seg a sex) a uma data ISO. */
export function diasUteis(inicio: string, n: number) {
  const d = new Date(`${inicio}T12:00:00`);
  while (n > 0) { d.setDate(d.getDate() + 1); if (d.getDay() % 6 !== 0) n--; }
  return iso(d);
}
export const diasAte = (data: string) =>
  Math.round((new Date(`${data}T12:00:00`).getTime() - new Date(`${HOJE}T12:00:00`).getTime()) / 86_400_000);

// ─────────────────────────── a matriz da Light (exemplo) ───────────────────────────

const CNPJ = EMPRESA.cnpj;
const base = (o: Partial<Obrigacao> & Pick<Obrigacao, "obrigacao_id" | "titulo">): Obrigacao => ({
  cnpj: CNPJ, versao: 1, fonte_ato: null, fonte_dispositivo: null, fonte_url: null, trecho_citado: null,
  orgao_sigla: "ANEEL", tema: null, aplica_a: [], recorrencia: "periodica", periodicidade: "mensal", prazo_regra: null,
  prazo_json: null, area_responsavel: null, evidencia: null, criticidade: "media", origem: "matriz_importada",
  status: "aprovada", confianca: null, incluida_em: "2026-11-07", alterada_por: PESSOA.email, vigente: true,
  mudanca: "inclusao", data_ato: null, vigente_de: "2022-01-01", vigente_ate: null, ...o,
});

const alerta = (id: string) => semana.alertas.find((a) => a.id === id)!;
const A1174 = alerta("52024096"), A1174b = alerta("52024099"), A1175 = alerta("52019671"), ASTF = alerta("52012519");

const VIGENTES: Obrigacao[] = [
  base({ obrigacao_id: "OBR-001", titulo: "Enviar à ANEEL os indicadores de continuidade DEC e FEC", tema: "qualidade do serviço",
    prazo_regra: "Até o último dia útil do mês seguinte", fonte_ato: "PRODIST", fonte_dispositivo: "Módulo 8",
    area_responsavel: "Operação", evidencia: "Protocolo de envio à ANEEL", criticidade: "alta" }),
  base({ obrigacao_id: "OBR-002", titulo: "Aplicar a bandeira tarifária do mês nas faturas", tema: "tarifas",
    prazo_regra: "Todo mês, conforme o despacho da ANEEL", fonte_ato: "PRORET", fonte_dispositivo: "Submódulo 6.1",
    area_responsavel: "Medição e faturamento", evidencia: "Fatura de amostra com a bandeira do mês", criticidade: "alta" }),
  base({ obrigacao_id: "OBR-003", titulo: "Recolher a Taxa de Fiscalização (TFSEE)", tema: "encargos",
    prazo_regra: "Até o dia 15 de cada mês", fonte_ato: "Lei nº 9.427/1996", fonte_dispositivo: "art. 12",
    area_responsavel: "Financeiro", evidencia: "Comprovante de pagamento" }),
  base({ obrigacao_id: "OBR-004", titulo: "Pagar a quota mensal da CDE", tema: "encargos",
    prazo_regra: "Até o dia 10 de cada mês", fonte_ato: "Lei nº 10.438/2002", fonte_dispositivo: "art. 13",
    area_responsavel: "Financeiro", evidencia: "Comprovante de pagamento", criticidade: "alta" }),
  base({ obrigacao_id: "OBR-005", titulo: "Recolher as quotas do PROINFA", tema: "encargos",
    prazo_regra: "Até o dia 20 de cada mês", fonte_ato: "Lei nº 10.438/2002", fonte_dispositivo: "art. 3º",
    area_responsavel: "Financeiro", evidencia: "Comprovante de pagamento" }),
  base({ obrigacao_id: "OBR-006", titulo: "Responder o pedido de migração ao mercado livre", tema: "mercado livre",
    recorrencia: "por_evento", periodicidade: null, prazo_regra: "Até 10 dias úteis do recebimento da comunicação",
    fonte_ato: "REN ANEEL nº 1.000/2021", fonte_dispositivo: "art. 166", area_responsavel: "Comercial",
    evidencia: "Protocolo da resposta ao consumidor", criticidade: "alta", vigente_de: "2023-12-20" }),
  base({ obrigacao_id: "OBR-007", titulo: "Manter a vigência do CUSD em 12 meses, com prorrogação automática", tema: "contratos",
    recorrencia: "continua", periodicidade: null, prazo_regra: "Denúncia com antecedência de pelo menos 180 dias",
    fonte_ato: "REN ANEEL nº 1.000/2021", fonte_dispositivo: "art. 133 (redação da REN 1.081/2023)",
    trecho_citado: "12 meses para a vigência do CUSD, com prorrogação automática por igual período, desde que o consumidor e demais usuários não se manifestem em contrário com antecedência de pelo menos 180 dias em relação ao término de cada vigência",
    area_responsavel: "Comercial", evidencia: "Contrato assinado", vigente_de: "2023-12-20" }),
  base({ obrigacao_id: "OBR-008", titulo: "Liquidar a Conta Bandeiras na CCEE", tema: "tarifas",
    prazo_regra: "Conforme o calendário de liquidação da CCEE", fonte_ato: "PRORET", fonte_dispositivo: "Submódulo 6.8",
    area_responsavel: "Financeiro", evidencia: "Relatório de liquidação da CCEE" }),
  base({ obrigacao_id: "OBR-009", titulo: "Entregar as Demonstrações Contábeis Regulatórias auditadas", tema: "contabilidade",
    periodicidade: "anual", prazo_regra: "Até 30 de abril do ano seguinte", fonte_ato: "Manual de Contabilidade do Setor Elétrico",
    area_responsavel: "Financeiro", evidencia: "Protocolo de entrega e parecer do auditor", criticidade: "alta" }),
  base({ obrigacao_id: "OBR-010", titulo: "Enviar os dados do reajuste tarifário anual", tema: "tarifas",
    periodicidade: "anual", prazo_regra: "Antes do aniversário tarifário (15 de março)", fonte_ato: "PRORET",
    area_responsavel: "Regulação", evidencia: "Ofício de envio", criticidade: "alta" }),
  base({ obrigacao_id: "OBR-011", titulo: "Responder às reclamações dos consumidores no prazo", tema: "atendimento",
    recorrencia: "por_evento", periodicidade: null, prazo_regra: "Conforme o tipo de pedido na REN 1.000/2021",
    fonte_ato: "REN ANEEL nº 1.000/2021", area_responsavel: "Comercial", evidencia: "Registro da resposta no sistema comercial" }),
];

const proposta = (o: Partial<Obrigacao> & Pick<Obrigacao, "obrigacao_id" | "titulo">, a: Alerta): Obrigacao => base({
  origem: "llm", status: "proposta", vigente: false, alterada_por: null, incluida_em: a.data, data_ato: a.data,
  vigente_de: null, fonte_url: a.url, trecho_citado: a.trecho, ...o,
});

const PROPOSTAS: Obrigacao[] = [
  proposta({ obrigacao_id: "OBR-006", versao: 2, mudanca: "alteracao", titulo: "Responder o pedido de migração ao mercado livre",
    tema: "mercado livre", recorrencia: "por_evento", periodicidade: null, prazo_regra: "Até 5 dias úteis do recebimento da comunicação",
    fonte_ato: "REN ANEEL nº 1.174/2026", fonte_dispositivo: "art. 166-A da REN 1.000/2021", area_responsavel: "Comercial",
    evidencia: "Protocolo da resposta ao consumidor", criticidade: "alta", confianca: 0.97,
    trecho_citado: "A distribuidora tem o prazo de até 5 dias úteis, contados a partir do recebimento da comunicação da migração prevista no art. 166, para verificar os requisitos técnicos e a existência de motivos que impeçam a migração" }, A1174),
  proposta({ obrigacao_id: "OBR-012", titulo: "Dar ao consumidor acesso aos próprios dados por interface padronizada",
    tema: "open energy", recorrencia: "continua", periodicidade: null, prazo_regra: "Até 12 meses da publicação (04/11/2027)",
    fonte_ato: "REN ANEEL nº 1.175/2026", fonte_dispositivo: "art. 22, I", area_responsavel: "Medição e faturamento",
    evidencia: "Interface publicada e registro de testes", criticidade: "alta", confianca: 0.91,
    trecho_citado: A1175.o_que_determina }, A1175),
  proposta({ obrigacao_id: "OBR-013", titulo: "Não fazer co-branding com comercializadora e identificar a distribuição nas comunicações",
    tema: "mercado livre", recorrencia: "continua", periodicidade: null, prazo_regra: "Em até 180 dias da publicação",
    fonte_ato: "REN ANEEL nº 1.174/2026", fonte_dispositivo: "art. 172-B da REN 1.000/2021", area_responsavel: "Comercial",
    evidencia: "Peças de comunicação revisadas", confianca: 0.88 }, A1174b),
  proposta({ obrigacao_id: "OBR-014", titulo: "Destinar aos consumidores os créditos de PIS/Cofins restituídos",
    orgao_sigla: "STF", tema: "tributos", recorrencia: "por_evento", periodicidade: null,
    prazo_regra: "10 anos da restituição do indébito ou da homologação da compensação", fonte_ato: "STF · embargos na ADI 7324",
    area_responsavel: "Financeiro", evidencia: "Plano de destinação aprovado", criticidade: "alta", confianca: 0.84 }, ASTF),
];

// ─────────────────────────── tarefas (exemplo, datas relativas a hoje) ───────────────────────────

let seq = 0;
const tarefa = (obrigacao_id: string, descricao: string, vencimento: string, area: string, status: StatusTarefa = "aberta", versao = 1): TarefaDash => ({
  cnpj: CNPJ, tarefa_id: `T-${String(++seq).padStart(3, "0")}`, obrigacao_id, obrigacao_versao: versao, unidade_id: null,
  outorga_id: null, descricao, vencimento, area_responsavel: area, status, evidencia_url: null, em_risco: false, atualizada_em: null,
});
/** Pedido de migração recebido ontem (Grupo A): o prazo da versão vigente conta dele. */
const MIGRACAO_RECEBIDA = daqui(-1);

function emRisco(t: TarefaDash): TarefaDash {
  return { ...t, em_risco: t.status !== "concluida" && diasAte(t.vencimento) <= 3 };
}

const TAREFAS: TarefaDash[] = [
  tarefa("OBR-005", "Recolher o PROINFA de outubro", daqui(-1), "Financeiro"),
  tarefa("OBR-002", "Aplicar a bandeira verde de novembro nas faturas", daqui(0), "Medição e faturamento", "em_andamento"),
  tarefa("OBR-004", "Pagar a quota da CDE de novembro", daqui(2), "Financeiro"),
  tarefa("OBR-006", "Responder o pedido de migração · UC 4471-2 (Grupo A)", diasUteis(MIGRACAO_RECEBIDA, 10), "Comercial", "em_andamento"),
  tarefa("OBR-008", "Liquidar a Conta Bandeiras de setembro na CCEE", daqui(4), "Financeiro"),
  tarefa("OBR-003", "Recolher a TFSEE de novembro", daqui(7), "Financeiro"),
  tarefa("OBR-005", "Recolher o PROINFA de novembro", daqui(12), "Financeiro"),
  tarefa("OBR-001", "Enviar DEC e FEC de outubro", daqui(17), "Operação"),
  tarefa("OBR-011", "Responder reclamação · protocolo 2026-118734", daqui(5), "Comercial"),
  tarefa("OBR-010", "Enviar os dados do reajuste de 2027", daqui(60), "Regulação"),
  tarefa("OBR-009", "Entregar as DCR auditadas de 2026", "2027-04-30", "Financeiro"),
  tarefa("OBR-001", "Enviar DEC e FEC de setembro", daqui(-12), "Operação", "concluida"),
  tarefa("OBR-004", "Pagar a quota da CDE de outubro", daqui(-20), "Financeiro", "concluida"),
  tarefa("OBR-003", "Recolher a TFSEE de outubro", daqui(-16), "Financeiro", "concluida"),
].map(emRisco);

// ─────────────────────────── linha do tempo ───────────────────────────

const evento = (o: Obrigacao, e: Partial<Historico>): Historico => ({
  obrigacao_id: o.obrigacao_id, versao: o.versao, evento: o.mudanca, status: o.status, origem: o.origem,
  ocorrido_em: o.incluida_em, por: o.origem === "llm" ? null : PESSOA.email, resumo: null, ato_id: null, ato_url: o.fonte_url,
  data_ato: o.data_ato, trecho_citado: o.trecho_citado, alteracoes: [], titulo: o.titulo, orgao_sigla: o.orgao_sigla, ...e,
});
const atoId = (a: Alerta) => `dou-${a.data}-${a.id}`;
const v1006 = VIGENTES.find((o) => o.obrigacao_id === "OBR-006")!;

const HISTORICO: Historico[] = [
  evento(PROPOSTAS[0], { ato_id: atoId(A1174), resumo: "Prazo de resposta à migração cai de 10 para 5 dias úteis",
    alteracoes: [
      { campo: "prazo_regra", antes: v1006.prazo_regra, depois: PROPOSTAS[0].prazo_regra },
      { campo: "fonte_ato", antes: v1006.fonte_ato, depois: PROPOSTAS[0].fonte_ato },
      { campo: "fonte_dispositivo", antes: v1006.fonte_dispositivo, depois: PROPOSTAS[0].fonte_dispositivo },
    ] }),
  evento(PROPOSTAS[1], { ato_id: atoId(A1175), resumo: "Nova obrigação: Open Energy, acesso do consumidor aos próprios dados" }),
  evento(PROPOSTAS[2], { ato_id: atoId(A1174b), resumo: "Nova obrigação: vedação de co-branding e identificação da distribuição" }),
  evento(PROPOSTAS[3], { ato_id: atoId(ASTF), resumo: "Nova obrigação: destinação dos créditos de PIS/Cofins (decisão do STF)" }),
  ...VIGENTES.map((o) => evento(o, { ocorrido_em: "2026-11-07", resumo: "Incluída pela planilha da matriz", ato_url: null })),
];

// ─────────────────────────── conversas da IA (exemplo) ───────────────────────────

const CONVERSAS: Conversa[] = [
  { id: "c-bandeira", titulo: "Bandeira de novembro", criada_em: daqui(-1), mensagens: [
    { id: "m1", de: "pessoa", texto: "Qual a bandeira de novembro?", em: daqui(-1) },
    { id: "m2", de: "ia", texto: "Verde, para os consumidores do SIN. Saiu no Despacho ANEEL nº 4.158, publicado em 04/11/2026.",
      blocos: [{ tipo: "atos", parametros: {}, itens: [atoDoAlerta(alerta("52021318"))] }], em: daqui(-1) },
  ] },
];

function atoDoAlerta(a: Alerta): Ato {
  return { data_publicacao: a.data, tipo: a.tipo, orgao: a.orgao, identifica: a.identifica, ementa: a.ementa, url_pdf: a.url };
}

// ─────────────────────────── a loja ───────────────────────────
//
// Dois modos:
//  - EXEMPLO (só em dev, ?demo=dash): os dados acima, em memória, para desenhar e apresentar sem AWS;
//  - REAL (com login): matriz-api (obrigações, tarefas, linha do tempo, decisões) e chatbot-api (IA do Kalman).

/** true com login de verdade; false no modo demonstração (src/demo.ts, só em npm run dev). */
export const MODO_REAL = !demoAtivo;
/** A leitura do DOU por empresa (funil e descartes) ainda não tem rota na API: só aparece no modo exemplo. */
export const TEM_LEITURA_DOU = !MODO_REAL;

export type Estado = {
  obrigacoes: Obrigacao[]; // vigentes + propostas (como GET /obrigacoes)
  versoesAntigas: Obrigacao[]; // versões que saíram de vigor (modo exemplo)
  versoesPorId: Record<string, Obrigacao[]>; // GET /obrigacoes/{id} (modo real, carregado ao abrir a obrigação)
  tarefas: TarefaDash[];
  historico: Historico[];
  conversas: Conversa[];
  carregando: boolean;
  erro: string | null;
  /** a matriz da empresa ainda não foi processada (aviso da API) */
  semMatriz: boolean;
  /** último processamento da matriz (GET /importacoes); RUNNING = análise em andamento */
  processamento: Processamento;
  /** quando começou o carregamento em andamento (para o tempo e a estimativa na tela) */
  carregandoDesde: number | null;
};

let proximaAtualizacao: number | undefined;

let estado: Estado = MODO_REAL
  ? { obrigacoes: [], versoesAntigas: [], versoesPorId: {}, tarefas: [], historico: [], conversas: [], carregando: true, erro: null, semMatriz: false, processamento: null, carregandoDesde: Date.now() }
  : { obrigacoes: [...VIGENTES, ...PROPOSTAS], versoesAntigas: [], versoesPorId: {}, tarefas: TAREFAS, historico: HISTORICO, conversas: CONVERSAS,
      carregando: false, erro: null, semMatriz: false, processamento: null, carregandoDesde: null };
const ouvintes = new Set<() => void>();
const mudar = (f: (e: Estado) => Estado) => { estado = f(estado); ouvintes.forEach((o) => o()); };

export function useLoja(): Estado {
  return useSyncExternalStore((o) => { ouvintes.add(o); return () => { ouvintes.delete(o); }; }, () => estado);
}

const espera = (ms: number) => new Promise((r) => setTimeout(r, ms));
/** Mensagem de erro para a tela: a API já manda `erro` em português. */
export const mensagemDeErro = (e: unknown) =>
  e instanceof ApiError ? (e.status === 403 ? "Só quem criou a conta pode fazer isso." : e.message) : "Não foi possível falar com o servidor. Tente de novo.";

export const propostasDe = (e: Estado) => e.obrigacoes.filter((o) => o.status === "proposta");
export const vigentesDe = (e: Estado) => e.obrigacoes.filter((o) => o.vigente);
export const todasVersoes = (e: Estado, id: string) =>
  (e.versoesPorId[id] ?? [...e.versoesAntigas, ...e.obrigacoes].filter((o) => o.obrigacao_id === id)).slice().sort((a, b) => a.versao - b.versao);
/** As áreas que aparecem na matriz e nas tarefas da empresa (os filtros usam estas, não uma lista fixa). */
export const areasDe = (e: Estado): string[] => {
  const s = new Set<string>();
  e.obrigacoes.forEach((o) => { if (o.area_responsavel) s.add(o.area_responsavel); });
  e.tarefas.forEach((t) => { if (t.area_responsavel) s.add(t.area_responsavel); });
  const ordem = AREAS as readonly string[];
  return [...s].sort((a, b) => (ordem.indexOf(a) + 1 || 99) - (ordem.indexOf(b) + 1 || 99) || a.localeCompare(b));
};

/** A matriz como estava num dia, no modo exemplo (no modo real: acoes.matrizEm, GET /obrigacoes?em=). */
export const matrizEm = (e: Estado, dia: string) =>
  [...e.versoesAntigas, ...e.obrigacoes].filter((o) =>
    (o.status === "aprovada" || o.status === "revogada") && o.vigente_de && o.vigente_de <= dia && (!o.vigente_ate || o.vigente_ate > dia));

/** Tarefas que nascem quando uma proposta de inclusão é aprovada (modo exemplo). */
const TAREFAS_NOVAS: Record<string, () => TarefaDash[]> = {
  "OBR-012": () => [tarefa("OBR-012", "Disponibilizar a interface de acesso aos dados do consumidor", "2027-11-04", "Medição e faturamento")],
  "OBR-013": () => [tarefa("OBR-013", "Revisar as comunicações e retirar co-branding de comercializadoras", diasUteis("2026-11-04", 125), "Comercial")],
  "OBR-014": () => [tarefa("OBR-014", "Mapear os créditos de PIS/Cofins restituídos e propor o plano de destinação", daqui(30), "Financeiro")],
};

/** Decisão no modo exemplo: aplica na memória o que a API faria. */
function decidirExemplo(id: string, versao: number, decisao: "aprovar" | "rejeitar", comentario?: string) {
  mudar((e) => {
    const alvo = e.obrigacoes.find((o) => o.obrigacao_id === id && o.versao === versao && o.status === "proposta");
    if (!alvo) return e;
    const agora = HOJE;
    let obrigacoes = e.obrigacoes, versoesAntigas = e.versoesAntigas, tarefas = e.tarefas;
    if (decisao === "aprovar") {
      const anterior = e.obrigacoes.find((o) => o.obrigacao_id === id && o.vigente);
      if (anterior) versoesAntigas = [...versoesAntigas, { ...anterior, vigente: false, vigente_ate: agora }];
      obrigacoes = e.obrigacoes
        .filter((o) => !(o.obrigacao_id === id && o.vigente))
        .map((o) => (o === alvo ? { ...o, status: "aprovada" as const, vigente: true, vigente_de: agora, alterada_por: PESSOA.email } : o));
      if (id === "OBR-006") {
        // a nova versão recalcula o prazo das tarefas abertas: 5 dias úteis em vez de 10
        tarefas = tarefas.map((t) => t.obrigacao_id === id && t.status !== "concluida"
          ? emRisco({ ...t, obrigacao_versao: versao, vencimento: diasUteis(MIGRACAO_RECEBIDA, 5), nota: "Prazo recalculado pela versão 2: 5 dias úteis em vez de 10" })
          : t);
      } else tarefas = [...tarefas, ...(TAREFAS_NOVAS[id]?.() ?? []).map(emRisco)];
    } else {
      obrigacoes = e.obrigacoes.map((o) => (o === alvo ? { ...o, status: "rejeitada" as const, alterada_por: PESSOA.email } : o));
    }
    const historico: Historico[] = [evento(alvo, {
      evento: decisao === "aprovar" ? "aprovacao" : "rejeicao", status: decisao === "aprovar" ? "aprovada" : "rejeitada",
      ocorrido_em: agora, por: PESSOA.email, origem: "decisao", resumo: comentario || (decisao === "aprovar" ? "Aprovada" : "Rejeitada"),
      ato_id: e.historico.find((h) => h.obrigacao_id === id && h.versao === versao)?.ato_id ?? null,
    }), ...e.historico];
    return { ...e, obrigacoes, versoesAntigas, tarefas, historico };
  });
}

const juntarMensagem = (conversaId: string, m: Mensagem) =>
  mudar((e) => ({ ...e, conversas: e.conversas.map((c) => (c.id !== conversaId ? c : {
    ...c, titulo: c.mensagens.length ? c.titulo : m.texto.slice(0, 48), mensagens: [...c.mensagens, m] })) }));

export const acoes = {
  /** Carrega a matriz, as tarefas e a linha do tempo da empresa (modo real). Sem efeito no modo exemplo. */
  async carregar(silencioso = false) {
    if (!MODO_REAL) return;
    window.clearTimeout(proximaAtualizacao);
    if (!silencioso) mudar((e) => ({ ...e, carregando: true, erro: null, carregandoDesde: Date.now() }));
    try {
      const [o, t, l, imp] = await Promise.all([apiMatriz.getObrigacoes(), apiMatriz.getTarefas(), apiMatriz.getLinhaDoTempo(),
        apiMatriz.getImportacoes().catch(() => null)]);
      const processamento = imp?.processamento ?? null;
      mudar((e) => ({ ...e, carregando: false, obrigacoes: o.obrigacoes, tarefas: t.tarefas, historico: l.eventos, versoesPorId: {},
        semMatriz: !!o.aviso && o.obrigacoes.length === 0, processamento }));
      // análise em andamento (7 a 15 min): confere de novo a cada 30 s, sem prender a tela
      if (processamento?.estado === "RUNNING") proximaAtualizacao = window.setTimeout(() => acoes.carregar(true), 30_000);
    } catch (err) {
      mudar((e) => ({ ...e, carregando: false, erro: mensagemDeErro(err) }));
    }
  },
  /** GET /obrigacoes/{id}: todas as versões (modo real; no exemplo já estão na memória). */
  async carregarObrigacao(id: string) {
    if (!MODO_REAL) return;
    try {
      const r = await apiMatriz.getObrigacao(id);
      mudar((e) => ({ ...e, versoesPorId: { ...e.versoesPorId, [id]: r.versoes } }));
    } catch { /* fica com o que veio na lista */ }
  },
  /** GET /obrigacoes?em=AAAA-MM-DD */
  async matrizEm(dia: string): Promise<Obrigacao[]> {
    if (!MODO_REAL) return matrizEm(estado, dia);
    return (await apiMatriz.getObrigacoesEm(dia)).obrigacoes;
  },
  /** POST /obrigacoes/{id}/decisao. Erro (403 para membro, 409 se já decidida) vai para a faixa de erro. */
  async decidir(id: string, versao: number, decisao: "aprovar" | "rejeitar", comentario?: string): Promise<boolean> {
    if (!MODO_REAL) { await espera(450); decidirExemplo(id, versao, decisao, comentario); return true; }
    try {
      await apiMatriz.decidir(id, versao, decisao, comentario);
    } catch (err) {
      mudar((e) => ({ ...e, erro: mensagemDeErro(err) }));
      if (err instanceof ApiError && err.status === 409) await acoes.carregar(); // alguém já decidiu: atualiza a tela
      return false;
    }
    await acoes.carregar();
    return true;
  },
  /** PATCH /tarefas/{id} */
  async mudarTarefa(id: string, status: StatusTarefa) {
    if (!MODO_REAL) {
      await espera(200);
      mudar((e) => ({ ...e, tarefas: e.tarefas.map((t) => (t.tarefa_id === id ? emRisco({ ...t, status, atualizada_em: new Date().toISOString() }) : t)) }));
      return;
    }
    const antes = estado.tarefas;
    mudar((e) => ({ ...e, tarefas: e.tarefas.map((t) => (t.tarefa_id === id ? { ...t, status } : t)) })); // otimista
    try {
      const { tarefa: nova } = await apiMatriz.mudarTarefa(id, status);
      mudar((e) => ({ ...e, tarefas: e.tarefas.map((t) => (t.tarefa_id === id ? nova : t)) }));
    } catch (err) {
      mudar((e) => ({ ...e, tarefas: antes, erro: mensagemDeErro(err) }));
    }
  },
  limparErro() { mudar((e) => ({ ...e, erro: null })); },
  /** Uma conversa = um session_id da API do chatbot (UUID). */
  novaConversa(): string {
    const id = MODO_REAL ? novaSessao() : `c-${Date.now()}`;
    mudar((e) => ({ ...e, conversas: [{ id, titulo: "Nova conversa", criada_em: HOJE, mensagens: [] }, ...e.conversas] }));
    return id;
  },
  /** POST /chatbot/mensagens (no exemplo: respostas montadas da loja). Erros viram mensagem da IA. */
  async perguntar(conversaId: string, prompt: string): Promise<Resposta> {
    juntarMensagem(conversaId, { id: `m-${Date.now()}`, de: "pessoa", texto: prompt, em: HOJE });
    let r: Resposta;
    let erro = false;
    const inicio = performance.now();
    if (MODO_REAL) {
      try { r = await enviarMensagem(prompt, conversaId); }
      catch (err) { r = { resposta: err instanceof ApiError ? err.message : mensagemDeErro(err), blocos: [] }; erro = true; }
    } else {
      await espera(1400 + Math.random() * 700);
      r = responder(prompt, estado);
    }
    juntarMensagem(conversaId, { id: `m-${Date.now()}`, de: "ia", texto: r.resposta, blocos: r.blocos, em: HOJE, erro,
      ms: Math.round(performance.now() - inicio) });
    return r;
  },
};

// ─────────────────────────── respostas da IA (exemplo) ───────────────────────────

export const PERGUNTAS_SUGERIDAS = MODO_REAL
  ? ["O que vence esta semana?", "Quais tarefas estão em risco?", "Quais são as minhas obrigações?", "Quais atos do DOU saíram sobre a minha empresa?"]
  : ["O que vence esta semana?", "O que mudou no prazo de migração?", "Quais tarefas estão em risco?", "Quais atos do DOU desta semana valem para nós?"];

/** A pergunta do botão "Perguntar à IA" de uma obrigação. */
export const perguntaSobre = (id: string, alteracao: boolean) =>
  !MODO_REAL && id === "OBR-006" ? "O que mudou no prazo de migração?" : alteracao ? `O que mudou na obrigação ${id}?` : `Explique a obrigação ${id}`;

const sem = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const tarefaChat = (t: TarefaDash): TarefaChat => ({
  descricao: t.descricao, vencimento: t.vencimento, status: t.status, em_risco: t.em_risco,
  area_responsavel: t.area_responsavel, obrigacao_id: t.obrigacao_id, obrigacao_versao: t.obrigacao_versao,
});
const dataBr = (d: string) => d.split("-").reverse().join("/");

function responder(prompt: string, e: Estado): Resposta {
  const p = sem(prompt);
  const abertas = e.tarefas.filter((t) => t.status !== "concluida").sort((a, b) => a.vencimento.localeCompare(b.vencimento));
  if (/explique|obr-\d/.test(p)) {
    const id = prompt.match(/OBR-\d{3}/i)?.[0].toUpperCase();
    const atuais = e.obrigacoes.filter((x) => x.vigente || x.status === "proposta");
    const o = id ? atuais.find((x) => x.obrigacao_id === id) : atuais.find((x) => p.includes(sem(x.titulo)));
    if (o) {
      const versoes = todasVersoes(e, o.obrigacao_id);
      return {
        resposta: `${o.titulo}. ${o.prazo_regra ? `Prazo: ${o.prazo_regra.toLowerCase()}. ` : ""}Fonte: ${[o.fonte_ato, o.fonte_dispositivo].filter(Boolean).join(", ") || "planilha da matriz"}. Responsável: ${o.area_responsavel ?? "sem área"}.${versoes.some((v) => v.status === "proposta") ? " Há uma versão proposta pela IA esperando a sua decisão." : ""}`,
        blocos: [{ tipo: "versoes", parametros: { obrigacao_id: o.obrigacao_id }, itens: versoes.map((v) => ({
          obrigacao_id: v.obrigacao_id, versao: v.versao, titulo: v.titulo, status: v.status, vigente: v.vigente, vigente_de: v.vigente_de,
          vigente_ate: v.vigente_ate, orgao_sigla: v.orgao_sigla, fonte_ato: v.fonte_ato, fonte_dispositivo: v.fonte_dispositivo, data_ato: v.data_ato,
          trecho_citado: v.trecho_citado, prazo_regra: v.prazo_regra, area_responsavel: v.area_responsavel, evidencia: v.evidencia,
          criticidade: v.criticidade, aplica_a: v.aplica_a })) }],
      };
    }
  }
  if (/risco|atras|urgente/.test(p)) {
    const r = abertas.filter((t) => t.em_risco);
    return { resposta: r.length
      ? `Há ${r.length} tarefas em risco. A mais urgente é "${r[0].descricao}", que vence em ${dataBr(r[0].vencimento)}.`
      : "Nenhuma tarefa está em risco agora.", blocos: r.length ? [{ tipo: "tarefas", parametros: { em_risco: true }, itens: r.map(tarefaChat) }] : [] };
  }
  if (/migra|mudou|mudanca|alter|1\.?174/.test(p)) {
    const ev: EventoDaLinhaDoTempo[] = e.historico.filter((h) => h.obrigacao_id === "OBR-006" && !(h.versao === 1 && h.evento === "inclusao"))
      .map((h) => ({ ocorrido_em: h.ocorrido_em, obrigacao_id: h.obrigacao_id, titulo: h.titulo ?? null, versao: h.versao, evento: h.evento,
        resumo: h.resumo, ato_id: h.ato_id, data_ato: h.data_ato, trecho_citado: h.trecho_citado,
        alteracoes: h.alteracoes.map((a) => ({ campo: a.campo, antes: a.antes == null ? null : String(a.antes), depois: a.depois == null ? null : String(a.depois) })) }));
    const aprovada = e.obrigacoes.some((o) => o.obrigacao_id === "OBR-006" && o.versao === 2 && o.status === "aprovada");
    return { resposta: `A REN ANEEL nº 1.174/2026, publicada em 04/11/2026, reduziu o prazo para responder ao pedido de migração de 10 para 5 dias úteis (art. 166-A da REN 1.000/2021). ${aprovada ? "A mudança já foi aprovada e as tarefas abertas foram recalculadas." : "A mudança ainda aguarda a sua decisão."}`,
      blocos: [{ tipo: "linha_do_tempo", parametros: { obrigacao_id: "OBR-006" }, itens: ev }] };
  }
  if (/venc|semana|prazo|agenda/.test(p)) {
    const r = abertas.filter((t) => diasAte(t.vencimento) >= 0 && diasAte(t.vencimento) <= 7);
    const atrasadas = abertas.filter((t) => diasAte(t.vencimento) < 0).length;
    return { resposta: `Vencem ${r.length} tarefas nos próximos 7 dias${r.length ? `, a primeira em ${dataBr(r[0].vencimento)}: ${r[0].descricao}.` : "."}${atrasadas ? ` E ${atrasadas} já ${atrasadas > 1 ? "estão atrasadas" : "está atrasada"}.` : ""}`,
      blocos: [{ tipo: "tarefas", parametros: {}, itens: r.map(tarefaChat) }] };
  }
  if (/dou|ato|norma|publica|diario|valem/.test(p)) {
    const r = semana.alertas.filter((a) => ["52024096", "52024099", "52019671", "52021318", "52021303", "52012519"].includes(a.id));
    return { resposta: `Na semana de 03 a 06/11/2026 li 1.931 atos do DOU. ${r.length} mudam o que vocês precisam fazer; os outros têm o motivo do descarte registrado.`,
      blocos: [{ tipo: "atos", parametros: {}, itens: r.map(atoDoAlerta) }] };
  }
  return { resposta: "Não encontrei isso nos atos do DOU nem na sua matriz. Posso ajudar com obrigações, prazos, tarefas em risco e o que cada norma mudou.", blocos: [] };
}
