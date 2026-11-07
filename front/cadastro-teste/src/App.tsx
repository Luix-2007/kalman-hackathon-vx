import {
  confirmResetPassword,
  confirmSignUp,
  getCurrentUser,
  resendSignUpCode,
  resetPassword,
  signIn,
  signOut,
  signUp,
} from "aws-amplify/auth";
import { startTransition, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import * as apiReal from "./api";
import Landing from "./landing/Landing";
import { Privacidade, Termos } from "./landing/Legal";
import { ApiError, type Cadastro, type Convite, type Membros } from "./api";
import { CAMPOS } from "./campos";
import { mascaraCnpj, soDigitos, useConferenciaCnpj, type ConferenciaCnpj } from "./cnpj";
import { configured } from "./config";
import { DEMO_EMAIL, demoApi, demoAtivo, demoAuth, demoLogado } from "./demo";
import { Icone, Marca } from "./identidade/marca";
import { MotivoAnimado } from "./MotivoAnimado";

// ─────────────────────────── integrações (reais ou demonstração) ───────────────────────────

const api = demoAtivo ? demoApi : apiReal;

type Passo = { isSignedIn?: boolean; nextStep: { signInStep?: string; signUpStep?: string; resetPasswordStep?: string } };
const auth = {
  entrar: (email: string, senha: string): Promise<Passo> =>
    demoAtivo ? demoAuth.signIn({ username: email, password: senha }) : signIn({ username: email, password: senha }),
  criar: (email: string, senha: string): Promise<Passo> =>
    demoAtivo
      ? demoAuth.signUp({})
      : signUp({ username: email, password: senha, options: { userAttributes: { email } } }),
  confirmar: (email: string, codigo: string): Promise<unknown> =>
    demoAtivo ? demoAuth.confirmSignUp({ username: email, confirmationCode: codigo }) : confirmSignUp({ username: email, confirmationCode: codigo }),
  reenviar: (email: string): Promise<unknown> => (demoAtivo ? demoAuth.resendSignUpCode({}) : resendSignUpCode({ username: email })),
  esqueci: (email: string): Promise<Passo> => (demoAtivo ? demoAuth.resetPassword({}) : resetPassword({ username: email })),
  redefinir: (email: string, codigo: string, senha: string): Promise<unknown> =>
    demoAtivo
      ? demoAuth.confirmResetPassword({ username: email, confirmationCode: codigo, newPassword: senha })
      : confirmResetPassword({ username: email, confirmationCode: codigo, newPassword: senha }),
  sair: (): Promise<void> => (demoAtivo ? Promise.resolve() : signOut()),
};

// CNPJ informado ao criar a conta: fica guardado até o e-mail ser confirmado e a consulta sair.
const CHAVE_CNPJ = "kalman:cnpj-da-conta";
const lerCnpjPendente = () => { try { return localStorage.getItem(CHAVE_CNPJ) || ""; } catch { return ""; } };
const guardarCnpjPendente = (v: string | null) => {
  try { if (v) localStorage.setItem(CHAVE_CNPJ, v); else localStorage.removeItem(CHAVE_CNPJ); } catch { /* sem storage: segue sem */ }
};

/** Segundos de espera antes de poder pedir outro código (o Cognito limita envios). */
const ESPERA_REENVIO = 30;

// ─────────────────────────── utilidades ───────────────────────────

const MENSAGENS: Record<string, string> = {
  NotAuthorizedException: "E-mail ou senha incorretos.",
  UserNotFoundException: "E-mail ou senha incorretos.",
  UsernameExistsException: "Já existe uma conta com esse e-mail. Entre com ela.",
  InvalidPasswordException: "A senha não atende aos critérios.",
  CodeMismatchException: "Código incorreto. Confira o e-mail mais recente.",
  ExpiredCodeException: "Código expirado. Peça um novo.",
  LimitExceededException: "Muitas tentativas. Espere alguns minutos e tente de novo.",
  TooManyRequestsException: "Muitas tentativas. Espere alguns minutos e tente de novo.",
  TooManyFailedAttemptsException: "Muitas tentativas. Espere alguns minutos e tente de novo.",
  CodeDeliveryFailureException: "Não conseguimos enviar o e-mail. Tente de novo em instantes.",
  UserNotConfirmedException: "Confirme seu e-mail antes de entrar.",
  InvalidParameterException: "Não foi possível concluir. Confira os dados e tente de novo.",
};
/** Primeira letra maiúscula e ponto final: as mensagens da API vêm em minúsculas. */
const frase = (s: string) => {
  const t = s.trim();
  return t ? t[0].toUpperCase() + t.slice(1) + (/[.!?…]$/.test(t) ? "" : ".") : t;
};
function mensagemDeErro(err: unknown): string {
  if (err instanceof ApiError && err.status === 0) return "Sem conexão com o servidor. Confira a internet e tente de novo.";
  if (err instanceof ApiError) return frase(err.message);
  const e = err as { name?: string; message?: string };
  return MENSAGENS[e.name ?? ""] ?? frase(e.message ?? String(err));
}
const statusDoErro = (err: unknown) => (err as { status?: number }).status;

const emailValido = (v: string) => /^\S+@\S+\.\S+$/.test(v);
const formatCnae = (c: string) => { const d = soDigitos(c); return d.length === 7 ? `${d.slice(0, 4)}-${d.slice(4, 5)}/${d.slice(5)}` : c; };
const MINUSCULAS = new Set(["de", "da", "do", "das", "dos", "e"]);
const titulo = (s?: string | null) =>
  (s ?? "").toLowerCase().replace(/\s+/g, " ").trim().split(" ")
    .map((p, i) => {
      if (/^([a-z]\.){1,3}[a-z]?\.?$|^(ltda|me|epp|eireli|s\/a)\.?$/.test(p)) return p.toUpperCase(); // S.A., LTDA, ME
      return i > 0 && MINUSCULAS.has(p) ? p : p.charAt(0).toUpperCase() + p.slice(1);
    }).join(" ");
const dataBR = (iso?: string | null) => (iso ? iso.slice(0, 10).split("-").reverse().join("/") : "");
const dataDeEpoch = (s: number) => new Date(s * 1000).toLocaleDateString("pt-BR");

const CRITERIOS: { texto: string; ok: (s: string) => boolean }[] = [
  { texto: "8 caracteres", ok: (s) => s.length >= 8 },
  { texto: "maiúscula", ok: (s) => /[A-Z]/.test(s) },
  { texto: "minúscula", ok: (s) => /[a-z]/.test(s) },
  { texto: "número", ok: (s) => /\d/.test(s) },
];

/**
 * Regulador setorial conhecido pelo CNAE (só para mostrar no cartão da empresa). O Kalman lê normas de qualquer
 * segmento; esta lista só dá nome ao regulador quando ele é óbvio. Sem regulador, o cartão mostra a atividade.
 */
const REGULADORES: [prefixo: string, regulador: string][] = [
  ["351", "ANEEL"], ["06", "ANP"], ["192", "ANP"], ["61", "Anatel"], ["64", "Banco Central"], ["65", "SUSEP"],
  ["652", "ANS"], ["655", "ANS"], ["212", "Anvisa"], ["50", "ANTAQ"], ["51", "ANAC"], ["36", "ANA"], ["37", "ANA"],
];
const minusculaInicial = (s: string) => (/^[A-ZÀ-Ú][a-zà-ú]/.test(s) ? s[0].toLowerCase() + s.slice(1) : s);
const reguladorDoCnae = (cnae?: string) => {
  const d = soDigitos(cnae ?? "");
  return d ? REGULADORES.filter(([p]) => d.startsWith(p)).sort((a, b) => b[0].length - a[0].length)[0]?.[1] ?? null : null;
};

// ─────────────────────────── app: rotas ───────────────────────────
//
//   /                landing (pública)          /privacidade, /termos   páginas legais
//   /entrar          entrar                     /criar-conta            criar conta (aceita ?cnpj=)
//   /esqueci-senha   redefinir a senha          /painel                 área logada (sem sessão → /entrar)
//
// Confirmar o e-mail e criar a senha nova são etapas dentro de /criar-conta e /esqueci-senha (precisam do e-mail e da
// senha digitados na etapa anterior, que não vão para a URL).

export default function App() {
  const [email, setEmail] = useState<string | null | undefined>(demoLogado ? DEMO_EMAIL : demoAtivo ? null : undefined);
  const navegar = useNavigate();

  useEffect(() => {
    if (!configured || demoAtivo) return;
    getCurrentUser()
      .then((u) => setEmail(u.signInDetails?.loginId ?? u.username))
      .catch(() => setEmail(null));
  }, []);

  if (!configured && !demoAtivo) {
    return (
      <div className="centro">
        <div className="aviso-config">
          <Icone className="icone-48" />
          <h1>Configuração incompleta</h1>
          <p>Faltam o endereço da API e os dados do login. Veja <code>src/config.ts</code>.</p>
        </div>
      </div>
    );
  }
  const carregando = <div className="centro"><Carregando /></div>;
  const entrou = (e: string) => { setEmail(e); navegar("/painel", { replace: true }); };
  // O React Router 7 navega dentro de uma transição; o logout vai na mesma transição. Se fosse uma atualização urgente,
  // o /painel renderizaria antes sem usuário e mandaria para /entrar.
  const sair = () => auth.sair().then(() => startTransition(() => { navegar("/"); setEmail(null); }));
  /** Telas de acesso: quem já está logado vai direto para o painel. */
  const acesso = (modo: Modo) =>
    email === undefined ? carregando : email ? <Navigate to="/painel" replace /> : <Acesso key={modo} modoInicial={modo} onEntrar={entrou} />;

  return (
    <>
      <RolarAoTopo />
      <Routes>
        <Route path="/" element={<Inicio />} />
        <Route path="/entrar" element={acesso("entrar")} />
        <Route path="/criar-conta" element={acesso("criar")} />
        <Route path="/esqueci-senha" element={acesso("esqueci")} />
        <Route path="/painel" element={email === undefined ? carregando : email ? <Painel email={email} onSair={sair} /> : <Navigate to="/entrar" replace />} />
        <Route path="/privacidade" element={<Privacidade />} />
        <Route path="/termos" element={<Termos />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}

/** "/": a landing. Links antigos (/?criar&cnpj=...) vão para /criar-conta. */
function Inicio() {
  const [params] = useSearchParams();
  if (params.has("criar") || params.has("cnpj")) {
    const cnpj = soDigitos(params.get("cnpj") ?? "");
    return <Navigate to={cnpj ? `/criar-conta?cnpj=${cnpj}` : "/criar-conta"} replace />;
  }
  return <Landing />;
}

/** Ao trocar de rota, volta ao topo (menos quando o link aponta para uma âncora). */
function RolarAoTopo() {
  const { pathname, hash } = useLocation();
  useEffect(() => { if (!hash) window.scrollTo(0, 0); }, [pathname, hash]);
  return null;
}

// ─────────────────────────── acesso: entrar / criar conta / confirmar / redefinir senha ───────────────────────────

type Modo = "entrar" | "criar" | "confirmar" | "esqueci" | "redefinir";

const KALMAN = <span className="laranja">Kalman</span>;
const CABECA: Record<Modo, { titulo: ReactNode; aba: string; texto?: string }> = {
  entrar: { titulo: <>Entrar no {KALMAN}</>, aba: "Entrar", texto: "Veja as normas e tarefas da sua empresa." },
  criar: { titulo: <>Criar conta no {KALMAN}</>, aba: "Criar conta", texto: "Informe o CNPJ da empresa para ver as normas que valem para ela." },
  confirmar: { titulo: "Confirme seu e-mail", aba: "Confirmar e-mail" },
  esqueci: { titulo: "Redefinir a senha", aba: "Redefinir a senha", texto: "Informe o e-mail da conta. Enviamos um código para você criar uma senha nova." },
  redefinir: { titulo: "Crie uma senha nova", aba: "Senha nova" },
};
/** Modos que têm rota própria; confirmar e redefinir são etapas dentro da rota em que começaram. */
const ROTAS: Partial<Record<Modo, string>> = { entrar: "/entrar", criar: "/criar-conta", esqueci: "/esqueci-senha" };
type EstadoAcesso = { email?: string; info?: string } | null;

function Acesso({ modoInicial, onEntrar }: { modoInicial: Modo; onEntrar: (email: string) => void }) {
  const navegar = useNavigate();
  const { pathname, state } = useLocation();
  const [params] = useSearchParams();
  const vindo = state as EstadoAcesso;
  const [modo, setModo] = useState<Modo>(modoInicial);
  const [email, setEmail] = useState(vindo?.email ?? "");
  const [senha, setSenha] = useState("");
  const [senha2, setSenha2] = useState("");
  const [cnpj, setCnpj] = useState(() => mascaraCnpj(params.get("cnpj") ?? ""));
  const [codigo, setCodigo] = useState("");
  const [erro, setErro] = useState("");
  const [info, setInfo] = useState(vindo?.info ?? "");

  useEffect(() => { document.title = `${CABECA[modo].aba} · Kalman`; }, [modo]);
  const [ocupado, setOcupado] = useState(false);
  const [tocou, setTocou] = useState<Record<string, boolean>>({});
  const [espera, setEspera] = useState(0);

  useEffect(() => {
    if (espera <= 0) return;
    const t = setTimeout(() => setEspera((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [espera]);

  const senhaOk = CRITERIOS.every((c) => c.ok(senha));
  const conferencia = useConferenciaCnpj(cnpj);
  // a conta dos dígitos libera na hora; só um "não existe na Receita" segura (Receita fora do ar não segura)
  const cnpjOk = conferencia.valido && conferencia.receita?.estado !== "nao_encontrado";
  const confereOk = senha2.length > 0 && senha2 === senha;
  const podeCriar = cnpjOk && emailValido(email) && senhaOk && confereOk;
  const podeRedefinir = codigo.length === 6 && senhaOk && confereOk;

  async function executar(fn: () => Promise<void>) {
    setErro(""); setInfo(""); setOcupado(true);
    try { await fn(); } catch (err) { setErro(mensagemDeErro(err)); } finally { setOcupado(false); }
  }

  /** Troca de tela: muda de rota quando o modo tem rota própria; senão, troca a etapa aqui mesmo. */
  const irPara = (m: Modo, aviso = "") => {
    const rota = ROTAS[m];
    if (rota && rota !== pathname) {
      navegar(rota, { state: { email, info: aviso } satisfies EstadoAcesso });
      return;
    }
    setModo(m); setErro(""); setTocou({}); setCodigo(""); setInfo(aviso);
  };

  const entrar = () => executar(async () => {
    const r = await auth.entrar(email, senha);
    if (r.isSignedIn) return onEntrar(email);
    if (r.nextStep.signInStep === "CONFIRM_SIGN_UP") {
      await auth.reenviar(email);
      irPara("confirmar");
      setEspera(ESPERA_REENVIO);
      setInfo("Sua conta ainda não foi confirmada. Enviamos um novo código.");
      return;
    }
    throw new Error(`Passo de login não suportado: ${r.nextStep.signInStep}`);
  });

  function enviar(e: FormEvent) {
    e.preventDefault();
    if (modo === "entrar") return entrar();

    if (modo === "criar") {
      setTocou({ cnpj: true, email: true, senha: true, senha2: true });
      if (!podeCriar) return;
      return executar(async () => {
        // se a consulta à Receita ainda está andando, espera por ela antes de criar a conta
        if ((await conferencia.confirmar())?.estado === "nao_encontrado") throw new Error(MSG_CNPJ_NAO_ENCONTRADO);
        guardarCnpjPendente(soDigitos(cnpj));
        const r = await auth.criar(email, senha);
        if (r.nextStep.signUpStep === "CONFIRM_SIGN_UP") { irPara("confirmar"); setEspera(ESPERA_REENVIO); }
        else await entrar();
      });
    }

    if (modo === "confirmar") {
      return executar(async () => {
        await auth.confirmar(email, codigo);
        const r = await auth.entrar(email, senha);
        if (r.isSignedIn) onEntrar(email);
      });
    }

    if (modo === "esqueci") {
      setTocou({ email: true });
      if (!emailValido(email)) return;
      return executar(async () => {
        await auth.esqueci(email);
        setSenha(""); setSenha2("");
        irPara("redefinir");
        setEspera(ESPERA_REENVIO);
      });
    }

    // redefinir
    setTocou({ senha: true, senha2: true });
    if (!podeRedefinir) return;
    return executar(async () => {
      await auth.redefinir(email, codigo, senha);
      const r = await auth.entrar(email, senha);
      if (r.isSignedIn) onEntrar(email);
      else irPara("entrar", "Senha alterada. Entre com a senha nova.");
    });
  }

  const reenviar = () => executar(async () => {
    if (modo === "redefinir") await auth.esqueci(email);
    else await auth.reenviar(email);
    setEspera(ESPERA_REENVIO);
    setInfo("Código reenviado. Veja também a caixa de spam.");
  });

  const cabeca = CABECA[modo];
  const comCodigo = modo === "confirmar" || modo === "redefinir";

  return (
    <div className="acesso">
      <aside className="acesso-arte">
        <Link to="/" className="acesso-marca-link" aria-label="Kalman, voltar ao início"><Marca escuro className="acesso-marca" /></Link>
        <MotivoAnimado className="motivo" />
        <div className="acesso-frase" aria-hidden="true">
          <p className="acesso-titulo">Saiba quais normas afetam <span className="laranja">a sua empresa.</span></p>
        </div>
      </aside>

      <main className="acesso-lado">
        <div className="acesso-topo-movel">
          <Link to="/" className="acesso-marca-link" aria-label="Kalman, voltar ao início"><Marca className="acesso-marca-movel" /></Link>
        </div>
        <form className="acesso-form" onSubmit={enviar} noValidate key={modo}>
          <div className="acesso-cabeca">
            <h1>{cabeca.titulo}</h1>
            {comCodigo ? (
              <p>
                {modo === "confirmar" ? "Enviamos um código de 6 dígitos para " : "Digite o código enviado para "}
                <strong>{email}</strong>{modo === "confirmar" ? "." : " e a senha nova."}
              </p>
            ) : (
              <p>{cabeca.texto}</p>
            )}
          </div>

          {modo === "criar" && (
            <Campo id="cnpj" rotulo="CNPJ da empresa" mono ok={cnpjOk}>
              <input id="cnpj" inputMode="numeric" autoComplete="off" placeholder="00.000.000/0000-00" value={cnpj}
                onChange={(e) => setCnpj(mascaraCnpj(e.target.value))} onBlur={() => setTocou((t) => ({ ...t, cnpj: true }))}
                aria-invalid={cnpjInvalido(cnpj, conferencia, tocou.cnpj)} aria-describedby="cnpj-status" />
              <StatusCnpj id="cnpj-status" valor={cnpj} conferencia={conferencia} tocou={tocou.cnpj} />
            </Campo>
          )}

          {(modo === "entrar" || modo === "criar" || modo === "esqueci") && (
            <Campo id="email" rotulo={modo === "criar" ? "E-mail corporativo" : "E-mail"}
              erro={modo === "esqueci" && tocou.email && !emailValido(email) ? "Digite um e-mail válido." : ""}>
              <input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value.trim())}
                autoComplete="username" placeholder="voce@empresa.com.br" autoFocus={modo === "esqueci"} />
            </Campo>
          )}

          {comCodigo && (
            <div className="k-campo">
              <label htmlFor="codigo">Código</label>
              <input id="codigo" className="codigo" inputMode="numeric" maxLength={6} required value={codigo}
                onChange={(e) => setCodigo(soDigitos(e.target.value).slice(0, 6))} autoComplete="one-time-code" autoFocus placeholder="000000" />
            </div>
          )}

          {(modo === "entrar" || modo === "criar" || modo === "redefinir") && (
            <Campo id="senha" rotulo={modo === "redefinir" ? "Senha nova" : "Senha"}>
              <Senha id="senha" valor={senha} onChange={setSenha} autoComplete={modo === "entrar" ? "current-password" : "new-password"} />
              {modo !== "entrar" && <ForcaSenha senha={senha} />}
              {modo === "entrar" && (
                <button type="button" className="link link-pequeno esqueci" onClick={() => irPara("esqueci")}>Esqueci a senha</button>
              )}
            </Campo>
          )}

          {(modo === "criar" || modo === "redefinir") && (
            <Campo id="senha2" rotulo={modo === "redefinir" ? "Confirmar senha nova" : "Confirmar senha"}
              erro={tocou.senha2 && senha2 && !confereOk ? "As senhas não são iguais." : ""} ok={confereOk}>
              <Senha id="senha2" valor={senha2} onChange={setSenha2} autoComplete="new-password"
                onBlur={() => setTocou((t) => ({ ...t, senha2: true }))} invalido={tocou.senha2 && !!senha2 && !confereOk} />
            </Campo>
          )}

          <Mensagem info={info} erro={erro} />

          <button className="k-btn largo" type="submit"
            disabled={ocupado || (modo === "criar" && !podeCriar) || (modo === "confirmar" && codigo.length !== 6) || (modo === "redefinir" && !podeRedefinir)}>
            {ocupado ? "Aguarde…" : {
              entrar: "Entrar", criar: "Criar conta", confirmar: "Confirmar e entrar", esqueci: "Enviar código", redefinir: "Salvar senha e entrar",
            }[modo]}
          </button>

          {comCodigo && (
            <p className="acesso-troca">
              Não chegou?{" "}
              {espera > 0 ? (
                <span className="k-mono espera">reenviar em {espera} s</span>
              ) : (
                <button type="button" className="link" disabled={ocupado} onClick={reenviar}>Reenviar código</button>
              )}
            </p>
          )}

          <p className="acesso-troca">
            {modo === "entrar" && <>Ainda não tem conta?{" "}<button type="button" className="link" onClick={() => irPara("criar")}>Criar conta</button></>}
            {modo === "criar" && <>Já tem conta?{" "}<button type="button" className="link" onClick={() => irPara("entrar")}>Entrar</button></>}
            {modo === "confirmar" && <button type="button" className="link" onClick={() => irPara("criar")}>Usar outro e-mail</button>}
            {(modo === "esqueci" || modo === "redefinir") && <>Lembrou a senha?{" "}<button type="button" className="link" onClick={() => irPara("entrar")}>Entrar</button></>}
          </p>
        </form>
      </main>
    </div>
  );
}

// ─────────────────────────── painel: convite ou CNPJ → consulta → dados → equipe ───────────────────────────

function Painel({ email, onSair }: { email: string; onSair: () => void }) {
  const [cadastro, setCadastro] = useState<Cadastro | null | undefined>(undefined);
  const [convite, setConvite] = useState<Convite | null>(null);
  const [consultando, setConsultando] = useState(false);
  const [trocando, setTrocando] = useState(false);
  const [erro, setErro] = useState("");
  const iniciou = useRef(false);

  async function consultar(cnpj: string, consultadoAntes: string | null = cadastro?.consultado_em ?? null) {
    setErro("");
    setConsultando(true);
    try {
      await api.enviarCnpj(cnpj);
      const c = await api.aguardarConsulta(consultadoAntes);
      guardarCnpjPendente(null);
      setCadastro(c);
      setTrocando(false);
    } catch (err) {
      if (statusDoErro(err) === 409) {
        guardarCnpjPendente(null);
        setErro(/vinculado/.test((err as Error).message)
          ? "Este CNPJ já foi cadastrado por outra pessoa da empresa. Peça a ela um convite para a equipe."
          : mensagemDeErro(err));
      } else setErro(mensagemDeErro(err));
    } finally {
      setConsultando(false);
    }
  }

  /** Lê a organização do usuário; sem organização, procura convite e, se não houver, usa o CNPJ da criação da conta. */
  async function carregar() {
    const c = await api.getCadastro();
    if (c) { setConvite(null); setCadastro(c); return; }
    // o convite vem antes de decidir a tela: sem isso a tela do CNPJ pisca antes do convite aparecer
    const cv = await api.getConvite().catch(() => null);
    setConvite(cv);
    setCadastro(null);
    const pendente = lerCnpjPendente();
    if (!cv && pendente) consultar(pendente, null);
  }

  useEffect(() => {
    if (iniciou.current) return;
    iniciou.current = true;
    carregar().catch((e) => { setErro(mensagemDeErro(e)); setCadastro(null); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const nome = cadastro?.empresa?.nome_fantasia || cadastro?.empresa?.razao_social;
  useEffect(() => { document.title = nome ? `${titulo(nome)} · Kalman` : "Painel · Kalman"; }, [nome]);
  let corpo: ReactNode;
  if (cadastro === undefined) corpo = <div className="centro-area"><Carregando /></div>;
  else if (consultando) corpo = <Consultando />;
  else if (!cadastro && convite) corpo = <ConviteRecebido convite={convite} onAceito={() => carregar()} onRecusado={() => setConvite(null)} />;
  else if (!cadastro || trocando) corpo = <PedirCnpj erro={erro} onConsultar={(c) => consultar(c)} onCancelar={cadastro ? () => { setTrocando(false); setErro(""); } : undefined} />;
  else corpo = (
    <Dados cadastro={cadastro} onSalvo={setCadastro} onTrocar={() => setTrocando(true)}
      onSaiu={() => { setCadastro(null); carregar().catch(() => undefined); }} />
  );

  return (
    <div className="painel">
      <header className="barra">
        <div className="barra-linha">
          <Link to="/" aria-label="Kalman, ir para o início"><Marca className="barra-marca" /></Link>
          {nome && !consultando && <span className="barra-empresa">{titulo(nome)}</span>}
          <div className="barra-direita">
            <span className="barra-email">{email}</span>
            <button className="k-btn k-btn--contorno k-btn--sm" type="button" onClick={onSair}>Sair</button>
          </div>
        </div>
      </header>
      <main className="painel-corpo">{corpo}</main>
    </div>
  );
}

function ConviteRecebido({ convite, onAceito, onRecusado }: { convite: Convite; onAceito: () => void; onRecusado: () => void }) {
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");

  async function executar(fn: () => Promise<unknown>, depois: () => void) {
    setOcupado(true); setErro("");
    try { await fn(); depois(); } catch (err) { setErro(mensagemDeErro(err)); } finally { setOcupado(false); }
  }

  return (
    <section className="centro-area">
      <div className="convite">
        <Icone className="icone-48" />
        <h1>Você foi convidado</h1>
        <p className="apoio">
          {convite.convidado_por ? <strong>{convite.convidado_por}</strong> : "O responsável da empresa"} chamou você para acompanhar as normas desta empresa.
        </p>
        <div className="convite-empresa k-pontos">
          <span className="k-rotulo">Empresa</span>
          <strong className="convite-nome">{convite.razao_social ? titulo(convite.razao_social) : "Empresa sem nome na Receita"}</strong>
          <span className="k-mono convite-cnpj">{mascaraCnpj(convite.cnpj)}</span>
        </div>
        <p className="convite-nota">Como membro, você vê os dados e os alertas da empresa. Só o dono edita. Convite válido até <span className="k-mono">{dataDeEpoch(convite.expira_em)}</span>.</p>
        <Mensagem erro={erro} />
        <div className="convite-acoes">
          <button className="k-btn" type="button" disabled={ocupado} onClick={() => executar(api.aceitarConvite, onAceito)}>
            {ocupado ? "Aguarde…" : "Aceitar convite"}
          </button>
          <button className="k-btn k-btn--contorno" type="button" disabled={ocupado} onClick={() => executar(api.recusarConvite, onRecusado)}>
            Recusar
          </button>
        </div>
      </div>
    </section>
  );
}

function PedirCnpj({ erro, onConsultar, onCancelar }: { erro: string; onConsultar: (cnpj: string) => void; onCancelar?: () => void }) {
  const [cnpj, setCnpj] = useState(() => mascaraCnpj(lerCnpjPendente()));
  const [tocou, setTocou] = useState(false);
  const conferencia = useConferenciaCnpj(cnpj);
  const ok = conferencia.valido && conferencia.receita?.estado !== "nao_encontrado";

  async function enviar(e: FormEvent) {
    e.preventDefault();
    setTocou(true);
    if (!ok) return;
    if ((await conferencia.confirmar())?.estado === "nao_encontrado") return; // o status já mostra o motivo
    onConsultar(soDigitos(cnpj));
  }

  return (
    <section className="centro-area">
      <form className="pedir" onSubmit={enviar} noValidate>
        <Icone className="icone-48" />
        <h1>{onCancelar ? "Trocar o CNPJ" : "Qual é o CNPJ da empresa?"}</h1>
        <p className="apoio">O perfil sai da Receita Federal. Você só confere.</p>
        <div className="pedir-linha">
          <label htmlFor="cnpj-painel" className="sr">CNPJ</label>
          <input id="cnpj-painel" className="cnpj-grande" inputMode="numeric" autoComplete="off" autoFocus placeholder="00.000.000/0000-00"
            value={cnpj} onChange={(e) => setCnpj(mascaraCnpj(e.target.value))}
            aria-invalid={cnpjInvalido(cnpj, conferencia, tocou)} aria-describedby="cnpj-painel-status" />
          <button className="k-btn" type="submit" disabled={!ok}>Consultar</button>
        </div>
        {erro ? (
          <p className="campo-msg" data-erro="" role="alert">{erro}</p>
        ) : (
          <StatusCnpj id="cnpj-painel-status" valor={cnpj} conferencia={conferencia} tocou={tocou} centro />
        )}
        {onCancelar && <button type="button" className="link" onClick={onCancelar}>Voltar aos dados</button>}
      </form>
    </section>
  );
}

function Consultando() {
  const [s, setS] = useState(0);
  useEffect(() => { const t = setInterval(() => setS((v) => v + 1), 1000); return () => clearInterval(t); }, []);
  return (
    <section className="centro-area" aria-live="polite">
      <div className="consultando">
        <svg className="consultando-arte" viewBox="0 0 220 80" aria-hidden="true">
          {[10, 25, 40, 55, 70].map((y) => (
            <path key={y} d={`M0 ${y} C 50 ${y}, 70 40, 120 40`} fill="none" stroke="#BFD9EA" strokeWidth="1.4" strokeLinecap="round" />
          ))}
          <path className="consultando-reta" d="M120 40 L196 40" stroke="#0E1A24" strokeWidth="2.4" strokeLinecap="round" />
          <circle cx="202" cy="40" r="6" fill="#FF5A1F" className="consultando-ponto" />
        </svg>
        <h1>Lendo o CNPJ na Receita</h1>
        <p className="apoio k-mono">{s} s</p>
      </div>
    </section>
  );
}

// grupos do formulário (as chaves vêm de campos.ts)
const SECOES: { id: string; nome: string; texto: string; chaves: string[] }[] = [
  { id: "responsavel", nome: "Responsável", texto: "Quem recebe os alertas.", chaves: ["responsavel_nome", "responsavel_cargo"] },
  { id: "contato", nome: "Contato", texto: "Para avisos da conta.", chaves: ["email_contato", "telefone", "site"] },
  { id: "empresa", nome: "Empresa", texto: "Como chamamos a empresa.", chaves: ["nome_fantasia", "funcionarios"] },
];
const ENDERECO = ["cep", "logradouro", "numero", "complemento", "bairro", "municipio", "uf"];
const TITULO_CASE = new Set(["nome_fantasia", "logradouro", "complemento", "bairro", "municipio"]);

function Dados({ cadastro, onSalvo, onTrocar, onSaiu }: {
  cadastro: Cadastro; onSalvo: (c: Cadastro) => void; onTrocar: () => void; onSaiu: () => void;
}) {
  const e = cadastro.empresa;
  const leitura = cadastro.papel === "membro";
  const inicial = useMemo(() => Object.fromEntries(CAMPOS.map((c) => {
    if (c.key in cadastro.dados) return [c.key, String(cadastro.dados[c.key])];
    const daReceita = c.daReceita?.(e);
    return [c.key, daReceita ? (TITULO_CASE.has(c.key) ? titulo(daReceita) : daReceita) : ""];
  })), [cadastro, e]);
  const [valores, setValores] = useState<Record<string, string>>(inicial);
  const [editarEndereco, setEditarEndereco] = useState(false);
  const [salvando, setSalvando] = useState(false);
  const [msg, setMsg] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const alterado = CAMPOS.some((c) => (valores[c.key] ?? "") !== (inicial[c.key] ?? "")) || Object.keys(cadastro.dados).length === 0;

  const campo = (key: string) => CAMPOS.find((c) => c.key === key);
  const input = (key: string) => {
    const c = campo(key);
    if (!c) return null;
    const mono = ["cep", "numero", "uf", "telefone", "funcionarios"].includes(key);
    return (
      <div key={key} className={`k-campo${mono ? " k-campo--mono" : ""} c-${key}`}>
        <label htmlFor={`f-${key}`}>{c.label}</label>
        <input id={`f-${key}`} type={c.type ?? "text"} value={valores[key] ?? ""} readOnly={leitura}
          placeholder={leitura ? "—" : undefined}
          onChange={(ev) => { setValores((v) => ({ ...v, [key]: ev.target.value })); setMsg(null); }} />
      </div>
    );
  };

  async function salvar(ev: FormEvent) {
    ev.preventDefault();
    if (leitura) return;
    setSalvando(true); setMsg(null);
    try {
      const dados = Object.fromEntries(CAMPOS.map((c) => {
        const v = (valores[c.key] ?? "").trim();
        return [c.key, v === "" ? null : c.type === "number" ? Number(v) : v];
      }));
      onSalvo(await api.salvarDados(dados));
      setMsg({ tipo: "ok", texto: `Salvo às ${new Date().toLocaleTimeString("pt-BR", { timeStyle: "short" })}` });
    } catch (err) {
      setMsg({ tipo: "erro", texto: mensagemDeErro(err) });
    } finally {
      setSalvando(false);
    }
  }

  const cnae = e.cnaes?.find((c) => c.is_principal);
  const regulador = reguladorDoCnae(cnae?.codigo ?? (e.cnae_principal as string | undefined));
  const v = valores;
  const enderecoResumo = [
    [v.logradouro, v.numero?.replace(/^0+(?=\d)/, "")].filter(Boolean).join(", "),
    v.complemento, v.bairro, [v.municipio, v.uf].filter(Boolean).join("/"),
    v.cep ? `CEP ${soDigitos(v.cep).replace(/(\d{5})(\d{3})/, "$1-$2")}` : "",
  ].filter(Boolean).join(" · ");

  return (
    <div className="dados">
      <section className="empresa k-pontos" aria-label="Empresa">
        <div className="empresa-topo">
          <span className="k-rotulo">Receita Federal · {cadastro.status === "ativa" ? "ativa" : cadastro.status.replace("_", " ")}</span>
          {!leitura && <button type="button" className="link link-claro" onClick={onTrocar}>Trocar CNPJ</button>}
        </div>
        <h1 className="empresa-nome">{titulo(e.razao_social)}</h1>
        <div className="empresa-fichas">
          <span className="ficha k-mono">{mascaraCnpj(cadastro.cnpj ?? "")}</span>
          {cnae && <span className="ficha"><span className="k-mono">{formatCnae(cnae.codigo)}</span> {cnae.descricao}</span>}
          {e.municipio && <span className="ficha">{titulo(e.municipio)}/{e.uf}</span>}
          {e.data_inicio_atividade && <span className="ficha">desde <span className="k-mono">{dataBR(e.data_inicio_atividade).slice(-4)}</span></span>}
        </div>
        <div className="empresa-setor">
          <span className="setor-ponto" aria-hidden="true" />
          <span>
            O Kalman vai ler as normas de <strong>{cnae?.descricao ? minusculaInicial(cnae.descricao) : "sua atividade"}</strong>
            {regulador ? <> · Diário Oficial e {regulador}</> : <> · Diário Oficial</>}
          </span>
        </div>
      </section>

      {leitura && (
        <p className="nota-leitura"><span className="k-ponto" aria-hidden="true" /> Você é membro desta empresa: vê os dados, mas só o dono edita.</p>
      )}

      <form className="blocos" onSubmit={salvar}>
        {SECOES.map((s) => (
          <fieldset key={s.id} className="bloco">
            <legend className="sr">{s.nome}</legend>
            <div className="bloco-titulo"><h2>{s.nome}</h2><p>{s.texto}</p></div>
            <div className="bloco-campos">{s.chaves.map(input)}</div>
          </fieldset>
        ))}
        <fieldset className="bloco">
          <legend className="sr">Endereço</legend>
          <div className="bloco-titulo"><h2>Endereço</h2><p>Veio da Receita.</p></div>
          <div className="bloco-campos">
            {editarEndereco ? (
              <div className="grade-endereco">{ENDERECO.map(input)}</div>
            ) : (
              <div className="resumo-endereco">
                <span>{enderecoResumo || "Sem endereço na Receita"}</span>
                {!leitura && <button type="button" className="link" onClick={() => setEditarEndereco(true)}>Corrigir</button>}
              </div>
            )}
          </div>
        </fieldset>

        {!leitura && (
          <div className="salvar">
            {msg && <span className={`salvar-msg ${msg.tipo}`} role="status">{msg.texto}</span>}
            {!msg && alterado && <span className="salvar-msg">Confira e salve</span>}
            <button className="k-btn" type="submit" disabled={salvando}>{salvando ? "Salvando…" : "Salvar"}</button>
          </div>
        )}
      </form>

      <Equipe key={cadastro.cnpj} cadastro={cadastro} onSaiu={onSaiu} />
    </div>
  );
}

// ─────────────────────────── equipe: dono, membros e convites ───────────────────────────

function Equipe({ cadastro, onSaiu }: { cadastro: Cadastro; onSaiu: () => void }) {
  const [org, setOrg] = useState<Membros | null>(null);
  const [email, setEmail] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [msg, setMsg] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const souDono = cadastro.papel === "dono";

  const carregar = () => api.getMembros().then(setOrg).catch((e) => setMsg({ tipo: "erro", texto: mensagemDeErro(e) }));
  useEffect(() => { carregar(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function executar(fn: () => Promise<unknown>, ok: string, depois: () => unknown = carregar) {
    setOcupado(true); setMsg(null);
    try {
      await fn();
      setMsg({ tipo: "ok", texto: ok });
      await depois();
    } catch (err) {
      setMsg({ tipo: "erro", texto: mensagemDeErro(err) });
    } finally {
      setOcupado(false);
    }
  }

  function convidar(e: FormEvent) {
    e.preventDefault();
    const alvo = email.trim().toLowerCase();
    if (!emailValido(alvo)) { setMsg({ tipo: "erro", texto: "Digite um e-mail válido." }); return; }
    executar(() => api.convidar(alvo), `Convite criado. Avise ${alvo} para criar a conta com esse e-mail.`,
      () => { setEmail(""); return carregar(); });
  }

  return (
    <section className="bloco equipe" aria-labelledby="t-equipe">
      <div className="bloco-titulo">
        <h2 id="t-equipe">Equipe</h2>
        <p>{souDono ? "Quem vê os dados e os alertas desta empresa." : "Quem acompanha esta empresa."}</p>
      </div>
      <div className="equipe-corpo">
        {!org && !msg && <Carregando />}
        {org && (
          <ul className="equipe-lista">
            <li className="pessoa">
              <span className="pessoa-email">{org.dono.email ?? "Dono"}</span>
              <span className="papel papel--dono">dono</span>
              <span className="pessoa-acao" />
            </li>
            {org.membros.map((m) => (
              <li className="pessoa" key={m.user_id}>
                <span className="pessoa-email">{m.email}</span>
                <span className="papel">membro</span>
                <span className="pessoa-acao">
                  {souDono && (
                    <button type="button" className="link link-pequeno" disabled={ocupado}
                      onClick={() => executar(() => api.removerMembro(m.user_id), `${m.email} saiu da equipe.`)}>Remover</button>
                  )}
                  {m.user_id === cadastro.user_id && (
                    <button type="button" className="link link-pequeno" disabled={ocupado}
                      onClick={() => executar(() => api.removerMembro(m.user_id), "Você saiu da empresa.", onSaiu)}>Sair da empresa</button>
                  )}
                </span>
              </li>
            ))}
            {org.convites?.map((c) => (
              <li className="pessoa pessoa--pendente" key={c.email}>
                <span className="pessoa-email">{c.email}</span>
                <span className="papel papel--pendente">convite até <span className="k-mono">{dataDeEpoch(c.expira_em)}</span></span>
                <span className="pessoa-acao">
                  <button type="button" className="link link-pequeno" disabled={ocupado}
                    onClick={() => executar(() => api.removerMembro(c.email), "Convite cancelado.")}>Cancelar</button>
                </span>
              </li>
            ))}
          </ul>
        )}

        {souDono && (
          <form className="convidar" onSubmit={convidar} noValidate>
            <div className="k-campo">
              <label htmlFor="convidar-email">Convidar pelo e-mail</label>
              <div className="convidar-linha">
                <input id="convidar-email" type="email" placeholder="pessoa@empresa.com.br" value={email}
                  onChange={(e) => { setEmail(e.target.value); setMsg(null); }} disabled={ocupado} autoComplete="off" />
                <button className="k-btn k-btn--grafite" type="submit" disabled={ocupado || !email.trim()}>Convidar</button>
              </div>
            </div>
            <p className="convidar-nota">Não enviamos e-mail de convite: avise a pessoa para criar a conta com esse endereço. O convite aparece quando ela entrar e vale por 7 dias.</p>
          </form>
        )}

        {msg && <p className={`msg ${msg.tipo === "erro" ? "msg-erro" : "msg-info"}`} role={msg.tipo === "erro" ? "alert" : "status"}>{msg.texto}</p>}
      </div>
    </section>
  );
}

// ─────────────────────────── peças ───────────────────────────

const MSG_CNPJ_NAO_ENCONTRADO = "Este CNPJ não aparece na Receita Federal. Confira o número.";

/** Campo em vermelho: conta dos dígitos errada, CNPJ inexistente, ou incompleto depois de sair do campo. */
const cnpjInvalido = (valor: string, c: ConferenciaCnpj, tocou?: boolean) => {
  const n = soDigitos(valor).length;
  return (c.completo && !c.valido) || c.receita?.estado === "nao_encontrado" || (!!tocou && n > 0 && n < 14);
};

/**
 * Linha embaixo do campo de CNPJ. A conta dos dígitos é instantânea; com a conta certa, mostra a consulta na Receita:
 * a razão social e a cidade (achou), "não aparece na Receita" (bloqueia) ou "não deu para conferir" (não bloqueia).
 */
function StatusCnpj({ id, valor, conferencia: c, tocou, centro }: {
  id: string; valor: string; conferencia: ConferenciaCnpj; tocou?: boolean; centro?: boolean;
}) {
  const n = soDigitos(valor).length;
  let tipo: "erro" | "ok" | "aviso" | "neutro" = "neutro";
  let texto: ReactNode = null;
  const r = c.receita;
  const girando = c.valido && (c.consultando || !r);

  if (c.completo && !c.valido) { tipo = "erro"; texto = "CNPJ inválido. Confira os dígitos."; }
  else if (!c.completo) { if (tocou && n > 0) { tipo = "erro"; texto = `Faltam ${14 - n} ${14 - n === 1 ? "dígito" : "dígitos"}.`; } }
  else if (c.consultando || !r) { texto = "Conferindo na Receita Federal…"; }
  else if (r.estado === "nao_encontrado") { tipo = "erro"; texto = MSG_CNPJ_NAO_ENCONTRADO; }
  else if (r.estado === "indisponivel") { texto = "Não deu para conferir na Receita agora. Você pode seguir."; }
  else {
    const ativa = !r.situacao || r.situacao.toLowerCase() === "ativa";
    tipo = ativa ? "ok" : "aviso";
    texto = (
      <>
        <strong>{titulo(r.razaoSocial) || "Empresa encontrada"}</strong>
        {r.municipio && <> · {titulo(r.municipio)}/{r.uf}</>}
        {!ativa && <> · situação na Receita: {r.situacao?.toLowerCase()}</>}
      </>
    );
  }

  return (
    <p id={id} className={`cnpj-status cnpj-status--${tipo}${centro ? " cnpj-status--centro" : ""}`}
      role={tipo === "erro" ? "alert" : "status"} aria-live="polite">
      {girando && <span className="cnpj-girando" aria-hidden="true" />}
      {texto && <span>{texto}</span>}
    </p>
  );
}

function Campo({ id, rotulo, erro, ok, mono, children }: { id: string; rotulo: string; erro?: string; ok?: boolean; mono?: boolean; children: ReactNode }) {
  return (
    <div className={`k-campo${mono ? " k-campo--mono" : ""}`} data-ok={ok || undefined}>
      <label htmlFor={id}>{rotulo}</label>
      {children}
      {erro && <span className="k-campo-msg" data-erro="" role="alert">{erro}</span>}
    </div>
  );
}

/** Campo de senha com o botão de mostrar/ocultar. */
function Senha({ id, valor, onChange, autoComplete, onBlur, invalido }: {
  id: string; valor: string; onChange: (v: string) => void; autoComplete: string; onBlur?: () => void; invalido?: boolean;
}) {
  const [ver, setVer] = useState(false);
  return (
    <div className="senha">
      <input id={id} type={ver ? "text" : "password"} required value={valor} onChange={(e) => onChange(e.target.value)}
        onBlur={onBlur} autoComplete={autoComplete} aria-invalid={invalido || undefined} spellCheck={false} />
      <button type="button" className="olho" onClick={() => setVer((v) => !v)} aria-label={ver ? "Ocultar senha" : "Mostrar senha"}
        aria-pressed={ver} aria-controls={id}>
        {ver ? (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M3 3l18 18" /><path d="M10.6 5.1A9.9 9.9 0 0 1 12 5c5 0 9 4.5 10 7-.4 1-1.2 2.3-2.4 3.6M6.4 6.4C4.3 7.8 2.8 9.9 2 12c1 2.5 5 7 10 7 1.9 0 3.6-.6 5-1.5" /><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M2 12c1-2.5 5-7 10-7s9 4.5 10 7c-1 2.5-5 7-10 7S3 14.5 2 12Z" /><circle cx="12" cy="12" r="3" />
          </svg>
        )}
      </button>
    </div>
  );
}

/** Força da senha enquanto digita. "Fraca" diz o que falta para passar na regra do Cognito. */
function ForcaSenha({ senha }: { senha: string }) {
  if (!senha) return null;
  const faltam = CRITERIOS.filter((c) => !c.ok(senha)).map((c) => c.texto);
  const extra = (senha.length >= 12 ? 1 : 0) + (/[^A-Za-z0-9]/.test(senha) ? 1 : 0);
  const nivel = faltam.length ? 1 : extra === 0 ? 2 : 3;
  const nome = ["", "Fraca", "Boa", "Forte"][nivel];
  return (
    <div className="forca" data-nivel={nivel} aria-live="polite">
      <div className="forca-barra" aria-hidden="true"><i /><i /><i /></div>
      <span className="forca-texto">
        <strong>{nome}</strong>
        {faltam.length > 0 && <> · falta {faltam.join(", ")}</>}
      </span>
    </div>
  );
}

function Mensagem({ info, erro }: { info?: string; erro?: string }) {
  if (!info && !erro) return null;
  return <p className={`msg ${erro ? "msg-erro" : "msg-info"}`} role={erro ? "alert" : "status"}>{erro || info}</p>;
}

function Carregando() {
  return <span className="carregando" role="status" aria-label="Carregando" />;
}
