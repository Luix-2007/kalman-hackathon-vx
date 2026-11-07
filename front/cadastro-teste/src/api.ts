/**
 * Cliente da API de cadastro. É a parte para levar para o front de verdade (Lovable).
 *
 * Toda chamada leva o access token do Cognito no header Authorization.
 * O user_id nunca é enviado: a API pega do token.
 */
import { fetchAuthSession } from "aws-amplify/auth";
import { config } from "./config";

export type Status = "ativa" | "inativa" | "nao_encontrado" | "cnpj_invalido";

export type Empresa = {
  razao_social?: string;
  nome_fantasia?: string;
  situacao_cadastral?: string;
  natureza_juridica?: string;
  porte_empresa?: string;
  data_inicio_atividade?: string;
  cnaes?: { codigo: string; descricao: string; is_principal: boolean }[];
  opcao_simples?: string;
  opcao_mei?: string;
  email?: string;
  telefones?: { ddd: string; numero: string; is_fax: boolean }[];
  tipo_logradouro?: string;
  logradouro?: string;
  numero?: string;
  complemento?: string;
  bairro?: string;
  cep?: string;
  municipio?: string;
  uf?: string;
  [campo: string]: unknown;
};

export type Cadastro = {
  user_id: string;
  cnpj: string | null;
  status: Status;
  consultado_em: string | null;
  empresa: Empresa;
  dados: Record<string, string | number | boolean>;
};

export type LogEntry = { id: number; at: string; method: string; path: string; status: number | "falhou"; ms: number };

export class ApiError extends Error {
  constructor(public status: number, public body: unknown) {
    const b = body as { erro?: string; message?: string } | null;
    super(b?.erro ?? b?.message ?? `HTTP ${status}`);
  }
}

let logListener: ((entry: LogEntry) => void) | null = null;
let seq = 0;
export function onRequestLog(fn: (entry: LogEntry) => void) {
  logListener = fn;
}

async function request(method: string, path: string, body?: unknown): Promise<{ status: number; data: unknown }> {
  // fetchAuthSession renova o access token sozinho quando ele expira (refresh token)
  const token = (await fetchAuthSession()).tokens?.accessToken?.toString();
  if (!token) throw new ApiError(401, { erro: "sessão expirada, entre de novo" });

  const started = performance.now();
  let status: number | "falhou" = "falhou";
  try {
    const resp = await fetch(config.apiUrl + path, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body !== undefined && { "Content-Type": "application/json" }),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    status = resp.status;
    return { status: resp.status, data: await resp.json().catch(() => ({})) };
  } catch (err) {
    // fetch só lança erro em falha de rede ou CORS (a API não respondeu ou o navegador bloqueou)
    throw new ApiError(0, { erro: `falha de rede ou CORS: ${(err as Error).message}. Veja o console do navegador.` });
  } finally {
    logListener?.({
      id: ++seq,
      at: new Date().toLocaleTimeString("pt-BR"),
      method,
      path: path || "/",
      status,
      ms: Math.round(performance.now() - started),
    });
  }
}

/** GET /cadastro/me. Devolve null enquanto o cadastro não existe (404). */
export async function getCadastro(): Promise<Cadastro | null> {
  const { status, data } = await request("GET", "/me");
  if (status === 404) return null;
  if (status !== 200) throw new ApiError(status, data);
  return data as Cadastro;
}

/** POST /cadastro. A consulta do CNPJ roda em segundo plano: use aguardarConsulta depois. */
export async function enviarCnpj(cnpj: string): Promise<void> {
  const { status, data } = await request("POST", "", { cnpj });
  if (status !== 202) throw new ApiError(status, data);
}

/** PATCH /cadastro/me. Merge campo a campo; null apaga o campo. */
export async function salvarDados(dados: Record<string, string | number | boolean | null>): Promise<Cadastro> {
  const { status, data } = await request("PATCH", "/me", { dados });
  if (status !== 200) throw new ApiError(status, data);
  return data as Cadastro;
}

/**
 * Espera a consulta em segundo plano terminar: chama GET /me a cada 2s até aparecer
 * um resultado mais novo que `consultadoAntes` (null se ainda não havia cadastro).
 */
export async function aguardarConsulta(
  consultadoAntes: string | null,
  { timeoutMs = 60_000, intervaloMs = 2_000 } = {},
): Promise<Cadastro> {
  const fim = Date.now() + timeoutMs;
  while (Date.now() < fim) {
    const cadastro = await getCadastro();
    if (cadastro && cadastro.consultado_em !== consultadoAntes) return cadastro;
    await new Promise((r) => setTimeout(r, intervaloMs));
  }
  throw new ApiError(408, { erro: "a consulta do CNPJ demorou demais. Tente de novo em instantes." });
}
