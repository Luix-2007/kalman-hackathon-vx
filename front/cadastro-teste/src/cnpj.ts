/**
 * CNPJ: máscara, conferência matemática (instantânea) e consulta na Receita pela OpenCNPJ (api.opencnpj.org).
 *
 * A OpenCNPJ é pública, sem chave, libera CORS para qualquer origem e respondeu em 50 a 450 ms nos testes
 * (07/11/2026). CNPJ inexistente → 404. A consulta aqui é só para avisar o usuário enquanto ele digita; o cadastro
 * oficial continua sendo a consulta da API do Kalman (Lambda) depois do POST /cadastro.
 *
 * Se a OpenCNPJ cair ou demorar, o resultado é "indisponivel" e nada é bloqueado.
 */
import { useEffect, useRef, useState } from "react";
import { CNPJ_DEMO, demoAtivo, receitaDemo } from "./demo";

export const soDigitos = (v: string) => v.replace(/\D/g, "");

export function mascaraCnpj(v: string) {
  const d = soDigitos(v).slice(0, 14);
  if (d.length <= 2) return d;
  if (d.length <= 5) return `${d.slice(0, 2)}.${d.slice(2)}`;
  if (d.length <= 8) return `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5)}`;
  if (d.length <= 12) return `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5, 8)}/${d.slice(8)}`;
  return `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5, 8)}/${d.slice(8, 12)}-${d.slice(12)}`;
}

/** Dígitos verificadores do CNPJ numérico. */
export function cnpjValido(v: string) {
  const d = soDigitos(v);
  if (d.length !== 14 || /^(\d)\1+$/.test(d)) return false;
  const dv = (base: string) => {
    let soma = 0, peso = base.length - 7;
    for (const c of base) { soma += +c * peso--; if (peso < 2) peso = 9; }
    const r = soma % 11;
    return r < 2 ? 0 : 11 - r;
  };
  return dv(d.slice(0, 12)) === +d[12] && dv(d.slice(0, 13)) === +d[13];
}

export type Receita =
  | { estado: "encontrado"; razaoSocial: string; municipio?: string; uf?: string; situacao?: string }
  | { estado: "nao_encontrado" }
  | { estado: "indisponivel" };

const URL_OPENCNPJ = "https://api.opencnpj.org/";
const LIMITE_MS = 4000;
const cache = new Map<string, Promise<Receita>>();

/** Consulta um CNPJ (14 dígitos, já conferido). Guarda o resultado: digitar de novo o mesmo número não repete a chamada. */
export function consultarReceita(cnpj: string): Promise<Receita> {
  const d = soDigitos(cnpj);
  const pronto = cache.get(d);
  if (pronto) return pronto;
  const p = (async (): Promise<Receita> => {
    // demonstração gravada: o CNPJ fixo responde na hora, sem depender da internet
    if (demoAtivo && d === CNPJ_DEMO) {
      await new Promise((r) => setTimeout(r, 350));
      return { estado: "encontrado", ...receitaDemo };
    }
    const controle = new AbortController();
    const relogio = setTimeout(() => controle.abort(), LIMITE_MS);
    try {
      const r = await fetch(URL_OPENCNPJ + d, { signal: controle.signal });
      if (r.status === 404) return { estado: "nao_encontrado" };
      if (!r.ok) return { estado: "indisponivel" };
      const j = (await r.json()) as { razao_social?: string; municipio?: string; uf?: string; situacao_cadastral?: string };
      return { estado: "encontrado", razaoSocial: j.razao_social ?? "", municipio: j.municipio, uf: j.uf, situacao: j.situacao_cadastral };
    } catch {
      return { estado: "indisponivel" };
    } finally {
      clearTimeout(relogio);
    }
  })();
  cache.set(d, p);
  p.then((r) => { if (r.estado === "indisponivel") cache.delete(d); }); // falha não fica guardada
  return p;
}

export type ConferenciaCnpj = {
  /** 14 dígitos digitados */
  completo: boolean;
  /** passou na conta dos dígitos verificadores */
  valido: boolean;
  /** resultado da Receita; undefined enquanto não há consulta ou ela está em andamento */
  receita?: Receita;
  consultando: boolean;
  /** Espera a consulta do número atual (a que estiver em andamento ou uma nova). */
  confirmar: () => Promise<Receita | undefined>;
};

/** Confere o CNPJ enquanto a pessoa digita: a conta é imediata; a Receita é consultada logo depois (250 ms parado). */
export function useConferenciaCnpj(valor: string): ConferenciaCnpj {
  const d = soDigitos(valor);
  const completo = d.length === 14;
  const valido = cnpjValido(d);
  const [resultado, setResultado] = useState<{ cnpj: string; receita: Receita } | null>(null);
  const atual = useRef(d);
  atual.current = d;

  useEffect(() => {
    if (!valido) return;
    const t = setTimeout(() => {
      consultarReceita(d).then((receita) => { if (atual.current === d) setResultado({ cnpj: d, receita }); });
    }, 250);
    return () => clearTimeout(t);
  }, [d, valido]);

  const receita = valido && resultado?.cnpj === d ? resultado.receita : undefined;
  return {
    completo,
    valido,
    receita,
    consultando: valido && !receita,
    confirmar: async () => (valido ? consultarReceita(d) : undefined),
  };
}
