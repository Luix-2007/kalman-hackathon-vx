/**
 * Modo demonstração, só em desenvolvimento (npm run dev): dá para percorrer as telas sem Cognito e sem API.
 *
 *   http://localhost:5173/entrar?demo         entrar / criar conta (qualquer e-mail e senha; código: qualquer 6 dígitos)
 *   http://localhost:5173/painel?demo=vazio   já logado, antes do CNPJ (a consulta simulada leva 3 s)
 *   http://localhost:5173/painel?demo=dados   já logado como dono, com o CNPJ consultado, 1 membro e 1 convite
 *   http://localhost:5173/painel?demo=membro  já logado como membro (só leitura)
 *   http://localhost:5173/painel?demo=convite já logado, sem empresa, com um convite pendente
 *
 * O modo vale para a aba inteira a partir do primeiro carregamento com ?demo (navegar entre rotas não o desliga).
 *
 * O cadastro de exemplo é o da Ampla (Enel Distribuição Rio) que está no DynamoDB, com dados públicos da Receita.
 * No build de produção o modo não existe. Para tirá-lo do projeto: apague este arquivo e as referências a
 * demoApi, demoAuth, demoAtivo, demoLogado e DEMO_EMAIL no App.tsx.
 */
import type { Cadastro, Convite, Membros } from "./api";

const params = new URLSearchParams(location.search);
export const demoAtivo = import.meta.env.DEV && params.has("demo");
const modo = params.get("demo");
export const demoLogado = demoAtivo && ["vazio", "dados", "membro", "convite"].includes(modo ?? "");

export const DEMO_EMAIL = modo === "membro" || modo === "convite" ? "medicao@distribuidora-exemplo.com.br" : "regulacao@distribuidora-exemplo.com.br";
const DONO_EMAIL = "regulacao@distribuidora-exemplo.com.br";

const EXEMPLO: Cadastro = {
  user_id: "demo",
  papel: "dono",
  cnpj: "33050071000158",
  status: "ativa",
  consultado_em: "2026-11-07T17:58:07+00:00",
  empresa: {
    razao_social: "AMPLA ENERGIA E SERVICOS S.A.",
    nome_fantasia: "ENEL DISTRIBUICAO RIO",
    situacao_cadastral: "Ativa",
    natureza_juridica: "Sociedade Anônima Aberta",
    porte_empresa: "Demais",
    data_inicio_atividade: "1966-08-01",
    cnae_principal: "3514000",
    cnaes: [{ codigo: "3514000", descricao: "Distribuição de energia elétrica", is_principal: true }],
    opcao_simples: "",
    opcao_mei: "",
    email: "FISCPRO@ENEL.COM",
    telefones: [{ ddd: "21", numero: "27161101", is_fax: false }],
    tipo_logradouro: "AVENIDA",
    logradouro: "OSCAR NIEMEYER",
    numero: "02000",
    complemento: "      BLOCO 1 SALA 701          PARTE",
    bairro: "SANTO CRISTO",
    cep: "20220297",
    municipio: "RIO DE JANEIRO",
    uf: "RJ",
  },
  dados: {},
};

const daqui = (dias: number) => Math.floor(Date.now() / 1000) + dias * 86400;

let atual: Cadastro | null =
  modo === "dados" ? structuredClone(EXEMPLO)
  : modo === "membro" ? { ...structuredClone(EXEMPLO), user_id: "demo-membro", papel: "membro", dados: { responsavel_nome: "Ana Ribeiro", responsavel_cargo: "Gerente de Regulação" } }
  : null;

let equipe: Membros = {
  cnpj: EXEMPLO.cnpj!,
  dono: { user_id: "demo", email: DONO_EMAIL },
  membros: [{ user_id: "demo-membro", email: "medicao@distribuidora-exemplo.com.br", desde: "2026-11-07T18:10:00+00:00" }],
  convites: [{ email: "comercial@distribuidora-exemplo.com.br", criado_em: "2026-11-07T18:20:00+00:00", expira_em: daqui(7) }],
};

let convite: Convite | null = modo === "convite"
  ? { cnpj: EXEMPLO.cnpj!, razao_social: EXEMPLO.empresa.razao_social ?? null, convidado_por: DONO_EMAIL, expira_em: daqui(6) }
  : null;

const espera = (ms: number) => new Promise((r) => setTimeout(r, ms));
const erroApi = (status: number, erro: string) => Object.assign(new Error(erro), { status });

export const demoApi = {
  async getCadastro(): Promise<Cadastro | null> {
    await espera(250);
    return atual && structuredClone(atual);
  },
  async enviarCnpj(_cnpj: string): Promise<void> {
    await espera(400);
  },
  async aguardarConsulta(_antes: string | null): Promise<Cadastro> {
    await espera(3000);
    atual = { ...structuredClone(EXEMPLO), dados: atual?.dados ?? {}, consultado_em: new Date().toISOString() };
    return structuredClone(atual);
  },
  async salvarDados(dados: Record<string, string | number | boolean | null>): Promise<Cadastro> {
    await espera(500);
    if (!atual) throw new Error("cadastro não encontrado");
    for (const [k, v] of Object.entries(dados)) {
      if (v === null) delete atual.dados[k];
      else atual.dados[k] = v;
    }
    return structuredClone(atual);
  },
  async getMembros(): Promise<Membros> {
    await espera(300);
    if (atual?.papel === "membro") return { ...structuredClone(equipe), convites: undefined };
    return structuredClone(equipe);
  },
  async convidar(email: string): Promise<unknown> {
    await espera(500);
    if (equipe.convites?.some((c) => c.email === email) || equipe.membros.some((m) => m.email === email))
      throw erroApi(409, "essa pessoa já faz parte da organização ou já tem convite");
    equipe = { ...equipe, convites: [...(equipe.convites ?? []), { email, criado_em: new Date().toISOString(), expira_em: daqui(7) }] };
    return {};
  },
  async removerMembro(id: string): Promise<unknown> {
    await espera(400);
    if (atual?.papel === "membro" && id === atual.user_id) { atual = null; return {}; }
    equipe = { ...equipe, membros: equipe.membros.filter((m) => m.user_id !== id), convites: equipe.convites?.filter((c) => c.email !== id) };
    return {};
  },
  async getConvite(): Promise<Convite | null> {
    await espera(250);
    return convite && structuredClone(convite);
  },
  async aceitarConvite(): Promise<unknown> {
    await espera(500);
    convite = null;
    atual = { ...structuredClone(EXEMPLO), user_id: "demo-membro", papel: "membro" };
    return {};
  },
  async recusarConvite(): Promise<unknown> {
    await espera(400);
    convite = null;
    return {};
  },
};

/** Mesmas assinaturas usadas do aws-amplify/auth, sem rede. */
export const demoAuth = {
  async signIn(_: { username: string; password: string }) {
    await espera(600);
    return { isSignedIn: true, nextStep: { signInStep: "DONE" } };
  },
  async signUp(_: unknown) {
    await espera(700);
    return { nextStep: { signUpStep: "CONFIRM_SIGN_UP" } };
  },
  async confirmSignUp({ confirmationCode }: { username: string; confirmationCode: string }) {
    await espera(600);
    if (!/^\d{6}$/.test(confirmationCode)) throw Object.assign(new Error("Código incorreto."), { name: "CodeMismatchException" });
  },
  async resendSignUpCode(_: unknown) {
    await espera(400);
  },
  async resetPassword(_: unknown) {
    await espera(600);
    return { nextStep: { resetPasswordStep: "CONFIRM_RESET_PASSWORD_WITH_CODE" } };
  },
  async confirmResetPassword({ confirmationCode }: { username: string; confirmationCode: string; newPassword: string }) {
    await espera(600);
    if (!/^\d{6}$/.test(confirmationCode)) throw Object.assign(new Error("Código incorreto."), { name: "CodeMismatchException" });
  },
};
