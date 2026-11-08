/**
 * Modo demonstração, só em desenvolvimento (npm run dev): dá para percorrer as telas sem Cognito e sem API.
 *
 *   http://localhost:5173/entrar?demo         entrar / criar conta (qualquer e-mail e senha; código: qualquer 6 dígitos)
 *   http://localhost:5173/painel?demo=vazio   já logado, antes do CNPJ (a consulta simulada leva 3 s)
 *   http://localhost:5173/painel?demo=dados   já logado como dono, com o CNPJ consultado, 1 membro e 1 convite
 *   http://localhost:5173/painel?demo=membro  já logado como membro (só leitura)
 *   http://localhost:5173/painel?demo=convite já logado, sem empresa, com um convite pendente
 *   http://localhost:5173/painel?demo=dash    já logado como dono, cadastro concluído: abre o dash (Hoje, IA...)
 *
 * O modo vale para a aba inteira a partir do primeiro carregamento com ?demo (navegar entre rotas não o desliga).
 *
 * A empresa de exemplo é a Light SESA (CNPJ 60.444.437/0001-46), com os dados públicos da Receita salvos em
 * src/dados/light-opencnpj.json: nada é consultado no modo demo.
 * No build de produção o modo só existe com VITE_DEMO=1 (no .env versionado da Lovable, para mostrar o dash sem login
 * na URL pública: https://<site>/painel?demo=dash). Sem a variável, ?demo não faz nada. Para tirá-lo do projeto: apague este arquivo e as referências a
 * demoApi, demoAuth, demoAtivo, demoLogado e DEMO_EMAIL no App.tsx.
 */
import type { Cadastro, Convite, Empresa, Membros } from "./api";
import type { Importacao, Obrigacao, Processamento } from "./matriz";
import { lerCsv } from "./planilha";
import light from "./dados/light-opencnpj.json";

const params = new URLSearchParams(location.search);
/** Em dev sempre disponível; no build publicado só com VITE_DEMO=1 (ex.: a URL da Lovable para o pitch). */
export const demoPermitido = import.meta.env.DEV || import.meta.env.VITE_DEMO === "1";
export const demoAtivo = demoPermitido && params.has("demo");
const modo = params.get("demo");
export const demoLogado = demoAtivo && ["vazio", "dados", "membro", "convite", "dash"].includes(modo ?? "");

export const DEMO_EMAIL = modo === "membro" || modo === "convite" ? "medicao@empresa-exemplo.com.br" : "regulacao@empresa-exemplo.com.br";
const DONO_EMAIL = "regulacao@empresa-exemplo.com.br";

/** Light SESA: dados da OpenCNPJ salvos em src/dados/light-opencnpj.json (07/11/2026, sem os sócios). */
const EXEMPLO: Cadastro = {
  user_id: "demo",
  papel: "dono",
  cnpj: "60444437000146",
  status: "ativa",
  consultado_em: "2026-11-07T21:30:00+00:00",
  empresa: light as Empresa,
  dados: {},
};

const daqui = (dias: number) => Math.floor(Date.now() / 1000) + dias * 86400;

const CONFERIDO = { conferido_em: "2026-11-07T21:40:00+00:00", conferido_por: "regulacao@empresa-exemplo.com.br", conferido_por_nome: "Ana Ribeiro", ufs_atuacao: ["RJ"] };
// ?demo=dash: dono com os dados conferidos e o cadastro concluído → /painel abre o dash (src/dash/)
if (demoAtivo && modo === "dash") {
  try { localStorage.setItem(`kalman:cadastro-concluido:${EXEMPLO.cnpj}`, "1"); } catch { /* sem storage */ }
}

let atual: Cadastro | null =
  modo === "dash" ? { ...structuredClone(EXEMPLO), dados: { ...CONFERIDO } }
  : modo === "dados" ? structuredClone(EXEMPLO)
  : modo === "membro" ? { ...structuredClone(EXEMPLO), user_id: "demo-membro", papel: "membro", dados: { conferido_em: "2026-11-07T21:40:00+00:00", conferido_por: "regulacao@empresa-exemplo.com.br", conferido_por_nome: "Ana Ribeiro", ufs_atuacao: ["RJ"] } }
  : null;

let equipe: Membros = {
  cnpj: EXEMPLO.cnpj!,
  dono: { user_id: "demo", email: DONO_EMAIL },
  membros: [{ user_id: "demo-membro", email: "medicao@empresa-exemplo.com.br", desde: "2026-11-07T18:10:00+00:00" }],
  convites: [{ email: "comercial@empresa-exemplo.com.br", criado_em: "2026-11-07T18:20:00+00:00", expira_em: daqui(7) }],
};

let convite: Convite | null = modo === "convite"
  ? { cnpj: EXEMPLO.cnpj!, razao_social: EXEMPLO.empresa.razao_social ?? null, convidado_por: DONO_EMAIL, expira_em: daqui(6) }
  : null;

const espera = (ms: number) => new Promise((r) => setTimeout(r, ms));
let nomeDemo = modo === "membro" || modo === "convite" ? "Bruno Medeiros" : "Ana Ribeiro";
let emailDemo = DEMO_EMAIL;

/** O CNPJ fixo da demonstração (Light SESA): conferido na hora, com os dados salvos, sem chamar a Receita. */
export const CNPJ_DEMO = EXEMPLO.cnpj!;
export const receitaDemo = { razaoSocial: String(light.razao_social ?? ""), municipio: light.municipio as string | undefined,
  uf: light.uf as string | undefined, situacao: light.situacao_cadastral as string | undefined };
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
    await espera(2200);
    atual = { ...structuredClone(EXEMPLO), dados: atual?.dados ?? {}, consultado_em: new Date().toISOString() };
    return structuredClone(atual);
  },
  async salvarDados(dados: Record<string, unknown>): Promise<Cadastro> {
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
  /** Guarda o nome e o e-mail digitados no cadastro: o painel da gravação mostra quem "criou a conta". */
  async signUp({ email, nome }: { email?: string; nome?: string }) {
    await espera(700);
    if (nome) nomeDemo = nome;
    if (email) emailDemo = email;
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
  /** Nome da conta de demonstração (muda com updateUserAttribute). */
  async fetchUserAttributes() {
    await espera(200);
    return { email: emailDemo, name: nomeDemo };
  },
  async updateUserAttribute(nome: string) {
    await espera(400);
    nomeDemo = nome;
  },
  async confirmResetPassword({ confirmationCode }: { username: string; confirmationCode: string; newPassword: string }) {
    await espera(600);
    if (!/^\d{6}$/.test(confirmationCode)) throw Object.assign(new Error("Código incorreto."), { name: "CodeMismatchException" });
  },
};

/** Matriz sem AWS: a importação "processa" em 8 s e as obrigações viram as linhas da planilha enviada. */
let importacoesDemo: Importacao[] = [];
let processamentoDemo: Processamento = null;
let obrigacoesDemo: Obrigacao[] = [];
export const demoMatriz = {
  async getImportacoes() {
    await espera(250);
    if (processamentoDemo?.estado === "RUNNING" && Date.now() - new Date(processamentoDemo.inicio).getTime() > 8000)
      processamentoDemo = { ...processamentoDemo, estado: "SUCCEEDED", fim: new Date().toISOString() };
    return { importacoes: structuredClone(importacoesDemo), processamento: processamentoDemo };
  },
  async importarMatriz(nome: string, conteudo: { texto: string } | { base64: string }) {
    await espera(700);
    const agora = new Date().toISOString();
    const arquivo = `${agora.slice(0, 19).replace(/[-:]/g, "").replace("T", "-")}-${nome}`;
    importacoesDemo = [{ arquivo, tamanho: "texto" in conteudo ? conteudo.texto.length : conteudo.base64.length, enviado_em: agora }, ...importacoesDemo];
    processamentoDemo = { estado: "RUNNING", inicio: agora, fim: null };
    if ("texto" in conteudo) {
      obrigacoesDemo = lerCsv(conteudo.texto).registros.filter((r) => r.obrigacao_id && r.titulo).map((r) => ({
        cnpj: EXEMPLO.cnpj!, obrigacao_id: r.obrigacao_id, versao: 1, titulo: r.titulo, fonte_ato: r.fonte_ato || null,
        fonte_dispositivo: r.fonte_dispositivo || null, fonte_url: r.fonte_url || null, trecho_citado: r.trecho_citado || null,
        orgao_sigla: r.orgao_sigla || null, tema: r.tema || null, aplica_a: [], recorrencia: (r.recorrencia || "continua") as Obrigacao["recorrencia"],
        periodicidade: r.periodicidade || null, prazo_regra: r.prazo_regra || null, prazo_json: r.prazo_json || null,
        area_responsavel: r.area_responsavel || null, evidencia: r.evidencia || null, criticidade: (r.criticidade || null) as Obrigacao["criticidade"],
        origem: "matriz_importada", status: "aprovada", confianca: null, incluida_em: agora.slice(0, 10), alterada_por: null,
        vigente: true, mudanca: "inclusao", data_ato: null, vigente_de: agora.slice(0, 10), vigente_ate: null,
      }));
    }
    return { arquivo, enviado_em: agora, processamento: processamentoDemo };
  },
  async getObrigacoes() {
    await espera(300);
    const pronta = processamentoDemo?.estado === "SUCCEEDED";
    return pronta
      ? { obrigacoes: structuredClone(obrigacoesDemo), resumo: { vigentes: obrigacoesDemo.length, propostas: 0 } }
      : { obrigacoes: [], aviso: "a matriz desta empresa ainda não foi processada" };
  },
};
