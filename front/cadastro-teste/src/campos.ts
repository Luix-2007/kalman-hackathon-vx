/**
 * Campos do perfil regulatório (o mesmo conjunto de CAMPOS em api/cnpj-cadastro/src/perfil.py).
 *
 * Tipos:
 *   texto    input simples; `daReceita` pré-preenche com os dados do CNPJ enquanto nada foi salvo
 *   opcoes   select com valores fixos
 *   chips    lista de textos (Enter ou vírgula adiciona)
 *   objetos  linhas repetíveis (unidades, outorgas, áreas), cada uma com `id` único
 */
import type { Empresa } from "./api";

export type Linha = Record<string, string | number | string[]>;
export type Valor = string | string[] | Linha[];

export type Coluna = {
  key: string;
  label: string;
  type?: "text" | "email" | "date" | "number" | "lista"; // lista = textos separados por vírgula
  obrigatoria?: boolean;
  placeholder?: string;
};

type Base = { key: string; label: string; grupo: Grupo; ajuda?: string };

export type Campo =
  | (Base & { tipo: "texto"; input?: "text" | "email"; daReceita?: (e: Empresa) => string | undefined })
  | (Base & { tipo: "opcoes"; opcoes: { valor: string; rotulo: string }[] })
  | (Base & { tipo: "chips"; sugestoes?: string[]; maiusculas?: boolean; daReceita?: (e: Empresa) => string[] | undefined })
  | (Base & { tipo: "objetos"; colunas: Coluna[]; prefixoId: string });

export type Grupo = "empresa" | "atuacao" | "estrutura" | "temas";

export const GRUPOS: { grupo: Grupo; titulo: string }[] = [
  { grupo: "empresa", titulo: "Empresa" },
  { grupo: "atuacao", titulo: "Onde atua e quem fiscaliza" },
  { grupo: "estrutura", titulo: "Unidades, outorgas e áreas" },
  { grupo: "temas", titulo: "Temas e certificações" },
];

const limpa = (v?: string) => (v ?? "").replace(/\s+/g, " ").trim() || undefined;

/** Setor sugerido pela divisão do CNAE principal (2 primeiros dígitos). O usuário pode trocar. */
const SETOR_POR_DIVISAO: [number, number, string][] = [
  [1, 3, "agropecuaria"], [5, 9, "mineracao_petroleo_gas"], [10, 33, "industria"],
  [35, 35, "energia_eletrica"], [36, 39, "saneamento"], [41, 43, "construcao"],
  [45, 47, "comercio"], [49, 53, "transporte_logistica"], [61, 61, "telecomunicacoes"],
  [64, 66, "financeiro"], [86, 88, "saude"],
];

export function setorDoCnae(e: Empresa): string | undefined {
  const cnae = e.cnaes?.find((c) => c.is_principal)?.codigo ?? (e.cnae_principal as string | undefined);
  if (!cnae) return undefined;
  const div = Number(cnae.slice(0, 2));
  return SETOR_POR_DIVISAO.find(([de, ate]) => div >= de && div <= ate)?.[2] ?? "outros";
}

export const UFS = ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
  "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"];

export const CAMPOS: Campo[] = [
  { key: "nome_fantasia", label: "Nome fantasia", grupo: "empresa", tipo: "texto", daReceita: (e) => limpa(e.nome_fantasia) },
  {
    key: "email_alertas", label: "E-mail que recebe os alertas", grupo: "empresa", tipo: "texto", input: "email",
    ajuda: "Não usamos o e-mail da Receita: muitas vezes é o do contador.",
  },
  {
    key: "faixa_funcionarios", label: "Número de funcionários", grupo: "empresa", tipo: "opcoes",
    ajuda: "CIPA e SESMT (NRs 4 e 5) dependem dessa faixa.",
    opcoes: ["1-19", "20-49", "50-100", "101-500", "501-1000", "1001+"].map((v) => ({ valor: v, rotulo: v })),
  },
  {
    key: "setor", label: "Setor", grupo: "empresa", tipo: "texto", daReceita: setorDoCnae,
    ajuda: "Sugerido a partir do CNAE principal.",
  },
  {
    key: "ufs_atuacao", label: "UFs onde atua", grupo: "atuacao", tipo: "chips", sugestoes: UFS, maiusculas: true,
    daReceita: (e) => (e.uf ? [e.uf] : undefined),
  },
  {
    key: "municipios_atuacao", label: "Municípios onde atua", grupo: "atuacao", tipo: "chips",
    ajuda: "Código IBGE de 7 dígitos (ex.: 3509502 para Campinas).",
  },
  {
    key: "orgaos_fiscalizadores", label: "Órgãos fiscalizadores", grupo: "atuacao", tipo: "chips",
    sugestoes: ["ANEEL", "ONS", "CCEE", "ANA", "IBAMA", "CETESB", "SP Águas", "MTE", "RFB", "CVM", "ANVISA", "ANP", "ANATEL"],
  },
  {
    key: "unidades", label: "Unidades", grupo: "estrutura", tipo: "objetos", prefixoId: "UN",
    colunas: [
      { key: "id", label: "ID", obrigatoria: true, placeholder: "UN-01" },
      { key: "nome", label: "Nome", obrigatoria: true },
      { key: "tipo", label: "Tipo", placeholder: "subestacao, usina, escritorio…" },
      { key: "tags", label: "Tags", type: "lista", placeholder: "separadas por vírgula" },
    ],
  },
  {
    key: "outorgas", label: "Outorgas e licenças", grupo: "estrutura", tipo: "objetos", prefixoId: "OUT",
    ajuda: "A renovação vira tarefa: validade menos a antecedência.",
    colunas: [
      { key: "id", label: "ID", obrigatoria: true, placeholder: "OUT-01" },
      { key: "tipo", label: "Tipo", obrigatoria: true, placeholder: "licenca_operacao" },
      { key: "numero", label: "Número" },
      { key: "orgao", label: "Órgão", obrigatoria: true, placeholder: "CETESB" },
      { key: "objeto", label: "Objeto" },
      { key: "unidade_id", label: "Unidade (ID)", placeholder: "UN-01" },
      { key: "validade", label: "Validade", type: "date" },
      { key: "antecedencia_renovacao_dias", label: "Renovar com quantos dias", type: "number" },
    ],
  },
  {
    key: "areas", label: "Áreas responsáveis", grupo: "estrutura", tipo: "objetos", prefixoId: "AREA",
    ajuda: "Cada obrigação tem uma área dona; a de compliance é a padrão.",
    colunas: [
      { key: "id", label: "ID", obrigatoria: true, placeholder: "COMP" },
      { key: "nome", label: "Nome", obrigatoria: true },
      { key: "responsavel", label: "Responsável" },
      { key: "email", label: "E-mail", type: "email" },
    ],
  },
  { key: "temas_interesse", label: "Temas de interesse", grupo: "temas", tipo: "chips" },
  { key: "temas_fora_escopo", label: "Temas fora do escopo", grupo: "temas", tipo: "chips" },
  { key: "certificacoes", label: "Certificações", grupo: "temas", tipo: "chips", sugestoes: ["ISO 9001", "ISO 14001", "ISO 45001", "ISO 37001"] },
];

/** Valor inicial do campo: o salvo, ou a sugestão da Receita, ou vazio. */
export function valorInicial(c: Campo, dados: Record<string, unknown>, empresa: Empresa): Valor {
  const salvo = dados[c.key];
  if (salvo !== undefined && salvo !== null) return salvo as Valor;
  if (c.tipo === "texto") return c.daReceita?.(empresa) ?? "";
  if (c.tipo === "chips") return c.daReceita?.(empresa) ?? [];
  if (c.tipo === "objetos") return [];
  return "";
}

/** Converte o estado do formulário no corpo do PATCH. Vazio vira null (apaga o campo). */
export function paraEnvio(c: Campo, valor: Valor): unknown {
  if (c.tipo === "texto" || c.tipo === "opcoes") {
    const v = String(valor ?? "").trim();
    return v === "" ? null : v;
  }
  if (c.tipo === "chips") {
    const lista = (valor as string[]).map((x) => x.trim()).filter(Boolean);
    return lista.length ? lista : null;
  }
  const linhas = (valor as Linha[])
    .map((linha) => {
      const obj: Linha = {};
      for (const col of c.colunas) {
        const bruto = linha[col.key];
        if (bruto === undefined || bruto === "") continue;
        if (col.type === "number") obj[col.key] = Number(bruto);
        else if (col.type === "lista") {
          const itens = Array.isArray(bruto) ? bruto : String(bruto).split(",").map((s) => s.trim()).filter(Boolean);
          if (itens.length) obj[col.key] = itens;
        } else obj[col.key] = String(bruto).trim();
      }
      return obj;
    })
    .filter((obj) => Object.keys(obj).length > 0);
  return linhas.length ? linhas : null;
}
