/**
 * Campos do formulário de TESTE. Os campos reais ainda não estão definidos:
 * quando estiverem, troque esta lista (e preencha CAMPOS_PERMITIDOS em api/cnpj-cadastro/src/usuario.py).
 *
 * `daReceita` pré-preenche o campo com os dados do CNPJ enquanto o usuário não salvou nada.
 */
import type { Empresa } from "./api";

export type Campo = {
  key: string; // nome salvo em `dados` (snake_case)
  label: string;
  type?: "text" | "email" | "tel" | "url" | "number";
  grupo: "empresa" | "adicional";
  daReceita?: (e: Empresa) => string | undefined;
};

const limpa = (v?: string) => (v ?? "").replace(/\s+/g, " ").trim() || undefined;

export const CAMPOS: Campo[] = [
  { key: "nome_fantasia", label: "Nome fantasia", grupo: "empresa", daReceita: (e) => limpa(e.nome_fantasia) },
  { key: "email_contato", label: "E-mail de contato", type: "email", grupo: "empresa", daReceita: (e) => limpa(e.email)?.toLowerCase() },
  {
    key: "telefone", label: "Telefone", type: "tel", grupo: "empresa",
    daReceita: (e) => {
      const t = e.telefones?.find((t) => !t.is_fax) ?? e.telefones?.[0];
      return t ? `(${t.ddd}) ${t.numero}` : undefined;
    },
  },
  { key: "cep", label: "CEP", grupo: "empresa", daReceita: (e) => limpa(e.cep) },
  { key: "logradouro", label: "Logradouro", grupo: "empresa", daReceita: (e) => limpa(`${e.tipo_logradouro ?? ""} ${e.logradouro ?? ""}`) },
  { key: "numero", label: "Número", grupo: "empresa", daReceita: (e) => limpa(e.numero) },
  { key: "complemento", label: "Complemento", grupo: "empresa", daReceita: (e) => limpa(e.complemento) },
  { key: "bairro", label: "Bairro", grupo: "empresa", daReceita: (e) => limpa(e.bairro) },
  { key: "municipio", label: "Município", grupo: "empresa", daReceita: (e) => limpa(e.municipio) },
  { key: "uf", label: "UF", grupo: "empresa", daReceita: (e) => limpa(e.uf) },
  { key: "responsavel_nome", label: "Nome do responsável", grupo: "adicional" },
  { key: "responsavel_cargo", label: "Cargo do responsável", grupo: "adicional" },
  { key: "site", label: "Site", type: "url", grupo: "adicional" },
  { key: "funcionarios", label: "Número de funcionários", type: "number", grupo: "adicional" },
];
