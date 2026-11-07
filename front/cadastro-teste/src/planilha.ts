/**
 * Planilha da matriz de obrigações: leitura do CSV e conferência linha a linha no navegador, antes de enviar.
 *
 * As regras são as mesmas do job da matriz (pipeline/matriz/src/etl_matriz.py `_validar` e regras_matriz.py
 * `ler_prazo_json`). Linha que falha aqui também falharia lá (ficaria em quarentena na silver). Se as regras do job
 * mudarem, mude aqui também.
 *
 * O CSV pode vir com vírgula ou ponto e vírgula (Excel em português), com aspas no padrão RFC 4180 e com BOM.
 * Os nomes das colunas são lidos sem espaços e em minúsculas; os valores, não (recorrencia "Periodica" é erro).
 */

export const RECORRENCIAS = ["periodica", "por_evento", "continua"] as const;
export const PERIODICIDADES = ["mensal", "trimestral", "semestral", "anual", "bienal"] as const;
export const CRITICIDADES = ["baixa", "media", "alta"] as const;
const REFERENCIAS: Record<string, string[]> = {
  data_fixa: ["ano_corrente", "ano_seguinte_exercicio"],
  dia_do_mes: ["mes_corrente", "mes_seguinte"],
  dias_apos: ["fim_mes", "fim_trimestre", "fim_semestre"],
  dias_antes: ["validade_outorga"],
};
const ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,49}$/;

/** As colunas que o job lê, na ordem do modelo. */
export const COLUNAS: { nome: string; obrigatoria?: boolean; descricao: string }[] = [
  { nome: "obrigacao_id", obrigatoria: true, descricao: "Código único da obrigação na empresa (ex.: OBR-001)." },
  { nome: "titulo", obrigatoria: true, descricao: "O que precisa ser feito, começando por um verbo." },
  { nome: "fonte_ato", descricao: "Norma de origem (ex.: Lei 9.427/1996, IN RFB 2.005/2021)." },
  { nome: "fonte_dispositivo", descricao: "Artigo, seção ou item." },
  { nome: "fonte_url", descricao: "Link para o texto da norma." },
  { nome: "trecho_citado", descricao: "Trecho literal que sustenta a obrigação." },
  { nome: "orgao_sigla", descricao: "Órgão que fiscaliza (ex.: RFB, ANEEL, CETESB)." },
  { nome: "tema", descricao: "Tema livre, para agrupar (ex.: tributario, ambiental)." },
  { nome: "aplica_a", descricao: "IDs das unidades do perfil, separados por vírgula. Vazio = a empresa toda." },
  { nome: "recorrencia", obrigatoria: true, descricao: "periodica, por_evento ou continua." },
  { nome: "periodicidade", descricao: "Se periódica: mensal, trimestral, semestral, anual ou bienal." },
  { nome: "prazo_regra", descricao: "O prazo em texto, como está na norma (ex.: até o dia 15 do mês seguinte)." },
  { nome: "prazo_json", descricao: "O prazo em regra que o Kalman calcula (ver abaixo). Obrigatório se periódica." },
  { nome: "area_responsavel", descricao: "ID da área do perfil que responde por ela." },
  { nome: "evidencia", descricao: "O que guardar como prova de cumprimento." },
  { nome: "criticidade", descricao: "baixa, media ou alta." },
];

/** Exemplos de prazo_json para a ajuda da tela. */
export const EXEMPLOS_PRAZO: { regra: string; json: string }[] = [
  { regra: "Dia 15 do mês seguinte", json: '[{"unidade": "dia_do_mes", "referencia": "mes_seguinte", "valor": "15"}]' },
  { regra: "30/04 do ano seguinte ao exercício", json: '[{"unidade": "data_fixa", "referencia": "ano_seguinte_exercicio", "valor": "30/04"}]' },
  { regra: "60 dias após o fim do trimestre", json: '[{"unidade": "dias_apos", "referencia": "fim_trimestre", "valor": "60"}]' },
  { regra: "120 dias antes da validade da licença", json: '[{"unidade": "dias_antes", "referencia": "validade_outorga", "valor": "120"}]' },
];

const aspas = (v: string) => (/[",\n;]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);

/** Modelo para baixar: cabeçalho e duas obrigações de exemplo, sem setor específico. */
export function modeloCsv(): string {
  const linhas = [
    COLUNAS.map((c) => c.nome),
    ["OBR-001", "Entregar a DCTFWeb", "IN RFB 2.005/2021", "art. 19", "https://www.gov.br/receitafederal",
      "A DCTFWeb deverá ser apresentada até o dia 15 do mês seguinte ao da ocorrência dos fatos geradores.",
      "RFB", "tributario", "", "periodica", "mensal", "Até o dia 15 do mês seguinte",
      EXEMPLOS_PRAZO[0].json, "", "Recibo de entrega", "alta"],
    ["OBR-002", "Manter o Programa de Gerenciamento de Riscos atualizado", "NR-1", "item 1.5.4.4.6", "https://www.gov.br/trabalho-e-emprego",
      "", "MTE", "seguranca_do_trabalho", "", "continua", "", "Revisar a cada mudança relevante", "", "", "PGR assinado", "media"],
  ];
  return "﻿" + linhas.map((l) => l.map(aspas).join(",")).join("\r\n") + "\r\n";
}

/** CSV → linhas (objetos com as colunas em minúsculas). RFC 4180: aspas, aspas dobradas e quebra de linha dentro de aspas. */
export function lerCsv(texto: string): { colunas: string[]; registros: Record<string, string>[] } {
  const t = texto.replace(/^﻿/, "");
  const primeira = t.split(/\r?\n/, 1)[0];
  const sep = (primeira.match(/;/g)?.length ?? 0) > (primeira.match(/,/g)?.length ?? 0) ? ";" : ",";
  const linhas: string[][] = [];
  let campo = "", linha: string[] = [], dentro = false;
  for (let i = 0; i < t.length; i++) {
    const c = t[i];
    if (dentro) {
      if (c === '"') {
        if (t[i + 1] === '"') { campo += '"'; i++; } else dentro = false;
      } else campo += c;
    } else if (c === '"') dentro = true;
    else if (c === sep) { linha.push(campo); campo = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && t[i + 1] === "\n") i++;
      linha.push(campo); campo = "";
      if (linha.some((x) => x !== "")) linhas.push(linha);
      linha = [];
    } else campo += c;
  }
  linha.push(campo);
  if (linha.some((x) => x !== "")) linhas.push(linha);
  const [cabecalho = [], ...resto] = linhas;
  const colunas = cabecalho.map((c) => c.trim().toLowerCase());
  const registros = resto.map((l) => Object.fromEntries(colunas.map((c, i) => [c, (l[i] ?? "").trim()])));
  return { colunas, registros };
}

export type LinhaConferida = {
  /** número da linha no arquivo (o cabeçalho é a 1) */
  linha: number;
  dados: Record<string, string>;
  erros: string[];
  avisos: string[];
};

export type Conferencia = {
  colunasFaltando: string[];
  colunasDesconhecidas: string[];
  linhas: LinhaConferida[];
  validas: number;
};

const lista = (v: string) => v.split(/[;,]/).map((x) => x.trim()).filter(Boolean);

/** Erros do prazo_json, na mesma ordem e com o mesmo texto do job. */
function errosPrazo(bruto: string): { regras: { unidade: string }[]; erro?: string } {
  if (!bruto) return { regras: [] };
  let regras: unknown;
  try { regras = JSON.parse(bruto); } catch { return { regras: [], erro: "prazo_json não é um JSON válido" }; }
  if (regras && typeof regras === "object" && !Array.isArray(regras)) regras = [regras];
  if (!Array.isArray(regras)) return { regras: [], erro: "prazo_json deve ser uma lista de regras" };
  for (let i = 0; i < regras.length; i++) {
    const r = regras[i] as Record<string, unknown>;
    if (!r || typeof r !== "object") return { regras: [], erro: `prazo_json[${i}] deve ser um objeto` };
    const unidade = String(r.unidade ?? ""), ref = String(r.referencia ?? "");
    if (!(unidade in REFERENCIAS)) return { regras: [], erro: `prazo_json[${i}]: unidade desconhecida (${unidade || "vazia"})` };
    if (!REFERENCIAS[unidade].includes(ref)) return { regras: [], erro: `prazo_json[${i}]: referencia "${ref}" não combina com ${unidade}` };
    const valor = r.valor;
    if (unidade === "data_fixa") {
      const [d, m] = String(valor ?? "").split("/").map(Number);
      const data = new Date(2024, (m || 0) - 1, d || 0);
      if (!d || !m || data.getMonth() !== m - 1 || data.getDate() !== d) return { regras: [], erro: `prazo_json[${i}]: data_fixa precisa de valor DD/MM` };
    } else if (!(unidade === "dias_antes" && (valor === undefined || valor === null || valor === ""))) {
      if (!/^-?\d+$/.test(String(valor ?? "").trim())) return { regras: [], erro: `prazo_json[${i}]: valor deve ser inteiro` };
    }
  }
  return { regras: regras as { unidade: string }[] };
}

/** Confere cada linha com as regras do job. `unidades` e `areas` são os IDs do perfil da empresa. */
export function conferir(colunas: string[], registros: Record<string, string>[], unidades: Set<string>, areas: Set<string>): Conferencia {
  const conhecidas = new Set(COLUNAS.map((c) => c.nome));
  const colunasFaltando = COLUNAS.filter((c) => c.obrigatoria && !colunas.includes(c.nome)).map((c) => c.nome);
  const colunasDesconhecidas = colunas.filter((c) => c && !conhecidas.has(c));
  const vistos = new Map<string, number>();

  const linhas = registros.map((dados, i): LinhaConferida => {
    const erros: string[] = [], avisos: string[] = [];
    const id = dados.obrigacao_id ?? "";
    if (!ID.test(id)) erros.push(id ? `obrigacao_id inválido (${id}): use letras, números, - e _` : "obrigacao_id vazio");
    else if (vistos.has(id)) erros.push(`obrigacao_id repetido (já está na linha ${vistos.get(id)})`);
    else vistos.set(id, i + 2);
    if (!dados.titulo) erros.push("titulo vazio");

    const { regras, erro } = errosPrazo(dados.prazo_json ?? "");
    if (erro) erros.push(erro);
    if (!erro && dados.recorrencia === "periodica" && regras.length === 0) erros.push("prazo_json vazio em obrigação periódica");
    const soOutorga = regras.length > 0 && regras.every((r) => r.unidade === "dias_antes");
    const rec = dados.recorrencia ?? "";
    if (!(RECORRENCIAS as readonly string[]).includes(rec)) erros.push(`recorrencia inválida (${rec || "vazia"}): use ${RECORRENCIAS.join(", ")}`);
    else if (rec === "periodica" && !soOutorga && !(PERIODICIDADES as readonly string[]).includes(dados.periodicidade ?? ""))
      erros.push(`periodicidade inválida (${dados.periodicidade || "vazia"}): use ${PERIODICIDADES.join(", ")}`);
    if (dados.criticidade && !(CRITICIDADES as readonly string[]).includes(dados.criticidade))
      erros.push(`criticidade inválida (${dados.criticidade}): use ${CRITICIDADES.join(", ")}`);
    const fora = lista(dados.aplica_a ?? "").filter((u) => !unidades.has(u));
    if (fora.length) erros.push(`aplica_a cita unidade que não está no perfil: ${fora.join(", ")}`);
    if (dados.area_responsavel && !areas.has(dados.area_responsavel))
      avisos.push(`área ${dados.area_responsavel} não está no perfil: fica com a área padrão`);
    return { linha: i + 2, dados, erros, avisos };
  });

  return { colunasFaltando, colunasDesconhecidas, linhas, validas: linhas.filter((l) => !l.erros.length).length };
}
