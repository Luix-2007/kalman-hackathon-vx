import {
  confirmSignUp,
  getCurrentUser,
  resendSignUpCode,
  signIn,
  signOut,
  signUp,
} from "aws-amplify/auth";
import { useEffect, useState, type FormEvent } from "react";
import {
  aguardarConsulta,
  ApiError,
  enviarCnpj,
  getCadastro,
  onRequestLog,
  salvarDados,
  type Cadastro,
  type LogEntry,
} from "./api";
import { CAMPOS } from "./campos";
import { config, configured } from "./config";

// ---------- utilidades ----------

const MENSAGENS: Record<string, string> = {
  NotAuthorizedException: "E-mail ou senha incorretos.",
  UserNotFoundException: "E-mail ou senha incorretos.",
  UsernameExistsException: "Já existe uma conta com esse e-mail. Use \"Entrar\".",
  InvalidPasswordException: "Senha fraca: mínimo de 8 caracteres, com maiúscula, minúscula e número.",
  CodeMismatchException: "Código incorreto.",
  ExpiredCodeException: "Código expirado. Peça um novo.",
  LimitExceededException: "Muitas tentativas. Espere alguns minutos.",
};

function mensagemDeErro(err: unknown): string {
  if (err instanceof ApiError) return err.status ? `${err.message} (HTTP ${err.status})` : err.message;
  const e = err as { name?: string; message?: string };
  return MENSAGENS[e.name ?? ""] ?? e.message ?? String(err);
}

function formatCnpj(cnpj: string | null) {
  if (!cnpj || !/^[0-9A-Z]{12}\d{2}$/.test(cnpj)) return cnpj ?? "";
  return `${cnpj.slice(0, 2)}.${cnpj.slice(2, 5)}.${cnpj.slice(5, 8)}/${cnpj.slice(8, 12)}-${cnpj.slice(12)}`;
}

const STATUS: Record<Cadastro["status"], { texto: string; cor: string }> = {
  ativa: { texto: "Ativa", cor: "ok" },
  inativa: { texto: "Inativa na Receita", cor: "aviso" },
  nao_encontrado: { texto: "CNPJ não encontrado", cor: "erro" },
  cnpj_invalido: { texto: "CNPJ inválido", cor: "erro" },
};

// ---------- app ----------

export default function App() {
  const [email, setEmail] = useState<string | null | undefined>(undefined); // undefined = carregando
  const [logs, setLogs] = useState<LogEntry[]>([]);

  useEffect(() => {
    onRequestLog((entry) => setLogs((l) => [entry, ...l].slice(0, 30)));
    if (!configured) return;
    getCurrentUser()
      .then((u) => setEmail(u.signInDetails?.loginId ?? u.username))
      .catch(() => setEmail(null));
  }, []);

  if (!configured) {
    return (
      <main>
        <h1>Cadastro (teste)</h1>
        <div className="card erro">
          Falta o arquivo <code>.env</code>. Na raiz do repositório, rode <code>make front-env</code> e reinicie o
          <code> make front-dev</code>.
        </div>
      </main>
    );
  }

  return (
    <main>
      <header>
        <div>
          <h1>Cadastro (teste)</h1>
          <p className="sub">Login no Cognito → CNPJ → consulta em segundo plano → formulário</p>
        </div>
        {email && (
          <div className="usuario">
            <span>{email}</span>
            <button className="link" onClick={() => signOut().then(() => setEmail(null))}>
              Sair
            </button>
          </div>
        )}
      </header>

      {email === undefined && <p className="sub">Carregando…</p>}
      {email === null && <Login onLogin={setEmail} />}
      {email && <Cadastrar />}

      <RequestLog logs={logs} />
      <footer className="sub">
        API: <code>{config.apiUrl}</code> · User Pool: <code>{config.userPoolId}</code>
      </footer>
    </main>
  );
}

// ---------- 1. login ----------

function Login({ onLogin }: { onLogin: (email: string) => void }) {
  const [modo, setModo] = useState<"entrar" | "criar" | "confirmar">("entrar");
  const [emailInput, setEmailInput] = useState("");
  const [senha, setSenha] = useState("");
  const [codigo, setCodigo] = useState("");
  const [erro, setErro] = useState("");
  const [info, setInfo] = useState("");
  const [ocupado, setOcupado] = useState(false);

  async function executar(fn: () => Promise<void>) {
    setErro("");
    setInfo("");
    setOcupado(true);
    try {
      await fn();
    } catch (err) {
      setErro(mensagemDeErro(err));
    } finally {
      setOcupado(false);
    }
  }

  const entrar = () =>
    executar(async () => {
      const r = await signIn({ username: emailInput, password: senha });
      if (r.isSignedIn) return onLogin(emailInput);
      if (r.nextStep.signInStep === "CONFIRM_SIGN_UP") {
        await resendSignUpCode({ username: emailInput });
        setModo("confirmar");
        setInfo("Sua conta ainda não foi confirmada. Enviamos um novo código para o seu e-mail.");
        return;
      }
      throw new Error(`Passo de login não suportado neste teste: ${r.nextStep.signInStep}`);
    });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (modo === "entrar") return entrar();
    if (modo === "criar")
      return executar(async () => {
        const r = await signUp({ username: emailInput, password: senha, options: { userAttributes: { email: emailInput } } });
        if (r.nextStep.signUpStep === "CONFIRM_SIGN_UP") {
          setModo("confirmar");
          setInfo("Enviamos um código para o seu e-mail (veja também o spam).");
        } else {
          await entrar();
        }
      });
    return executar(async () => {
      await confirmSignUp({ username: emailInput, confirmationCode: codigo.trim() });
      const r = await signIn({ username: emailInput, password: senha });
      if (r.isSignedIn) onLogin(emailInput);
    });
  }

  return (
    <section className="card">
      <h2>1. Conta</h2>
      {modo !== "confirmar" && (
        <div className="abas">
          <button className={modo === "entrar" ? "ativa" : ""} onClick={() => setModo("entrar")} type="button">
            Entrar
          </button>
          <button className={modo === "criar" ? "ativa" : ""} onClick={() => setModo("criar")} type="button">
            Criar conta
          </button>
        </div>
      )}
      <form onSubmit={submit} className="grid">
        <label>
          E-mail
          <input type="email" required value={emailInput} disabled={modo === "confirmar"}
            onChange={(e) => setEmailInput(e.target.value)} autoComplete="username" />
        </label>
        <label>
          Senha
          <input type="password" required minLength={8} value={senha} disabled={modo === "confirmar"}
            onChange={(e) => setSenha(e.target.value)}
            autoComplete={modo === "criar" ? "new-password" : "current-password"} />
          {modo === "criar" && <small>Mínimo de 8 caracteres, com maiúscula, minúscula e número.</small>}
        </label>
        {modo === "confirmar" && (
          <label>
            Código recebido por e-mail
            <input inputMode="numeric" required value={codigo} onChange={(e) => setCodigo(e.target.value)}
              autoComplete="one-time-code" autoFocus />
          </label>
        )}
        {info && <p className="msg info">{info}</p>}
        {erro && <p className="msg erro">{erro}</p>}
        <div className="acoes">
          <button type="submit" disabled={ocupado}>
            {ocupado ? "Aguarde…" : modo === "entrar" ? "Entrar" : modo === "criar" ? "Criar conta" : "Confirmar e entrar"}
          </button>
          {modo === "confirmar" && (
            <button type="button" className="link" disabled={ocupado}
              onClick={() => executar(async () => {
                await resendSignUpCode({ username: emailInput });
                setInfo("Código reenviado.");
              })}>
              Reenviar código
            </button>
          )}
        </div>
      </form>
    </section>
  );
}

// ---------- 2. CNPJ + 3. formulário ----------

function Cadastrar() {
  const [cadastro, setCadastro] = useState<Cadastro | null | undefined>(undefined);
  const [cnpj, setCnpj] = useState("");
  const [fase, setFase] = useState<"parado" | "enviando" | "aguardando">("parado");
  const [segundos, setSegundos] = useState(0);
  const [erro, setErro] = useState("");

  useEffect(() => {
    getCadastro().then(setCadastro).catch((e) => {
      setErro(mensagemDeErro(e));
      setCadastro(null);
    });
  }, []);

  useEffect(() => {
    if (fase !== "aguardando") return;
    setSegundos(0);
    const t = setInterval(() => setSegundos((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [fase]);

  async function consultar(e: FormEvent) {
    e.preventDefault();
    setErro("");
    try {
      setFase("enviando");
      await enviarCnpj(cnpj);
      setFase("aguardando");
      setCadastro(await aguardarConsulta(cadastro?.consultado_em ?? null));
    } catch (err) {
      setErro(mensagemDeErro(err));
    } finally {
      setFase("parado");
    }
  }

  if (cadastro === undefined) return <p className="sub">Carregando cadastro…</p>;

  return (
    <>
      <section className="card">
        <h2>2. CNPJ</h2>
        <form onSubmit={consultar} className="linha">
          <input placeholder="00.000.000/0001-91" value={cnpj} onChange={(e) => setCnpj(e.target.value)} required
            disabled={fase !== "parado"} />
          <button type="submit" disabled={fase !== "parado"}>
            {fase === "enviando" ? "Enviando…" : fase === "aguardando" ? `Consultando… ${segundos}s` : cadastro ? "Consultar outro" : "Consultar"}
          </button>
        </form>
        {fase === "aguardando" && (
          <p className="sub">POST respondeu 202. Agora o EventBridge chama a Lambda que consulta o OpenCNPJ; o front repete o GET a cada 2s.</p>
        )}
        {erro && <p className="msg erro">{erro}</p>}
        {cadastro && <ResumoEmpresa cadastro={cadastro} />}
      </section>

      {cadastro && (
        <Formulario
          key={cadastro.consultado_em ?? ""} // recarrega o pré-preenchimento após nova consulta
          cadastro={cadastro}
          onSalvo={setCadastro}
        />
      )}
    </>
  );
}

function ResumoEmpresa({ cadastro }: { cadastro: Cadastro }) {
  const e = cadastro.empresa;
  const s = STATUS[cadastro.status];
  const cnae = e.cnaes?.find((c) => c.is_principal);
  return (
    <div className="resumo">
      <div className="resumo-topo">
        <strong>{e.razao_social ?? formatCnpj(cadastro.cnpj)}</strong>
        <span className={`badge ${s.cor}`}>{s.texto}</span>
      </div>
      <dl>
        <dt>CNPJ</dt><dd>{formatCnpj(cadastro.cnpj)}</dd>
        {e.natureza_juridica && (<><dt>Natureza jurídica</dt><dd>{e.natureza_juridica}</dd></>)}
        {cnae && (<><dt>Atividade principal</dt><dd>{cnae.descricao}</dd></>)}
        {e.porte_empresa && (<><dt>Porte</dt><dd>{e.porte_empresa}</dd></>)}
        {e.data_inicio_atividade && (<><dt>Início</dt><dd>{e.data_inicio_atividade.split("-").reverse().join("/")}</dd></>)}
        {e.opcao_simples && (<><dt>Simples / MEI</dt><dd>{e.opcao_simples === "S" ? "Sim" : "Não"} / {e.opcao_mei === "S" ? "Sim" : "Não"}</dd></>)}
        <dt>Consultado em</dt><dd>{cadastro.consultado_em ? new Date(cadastro.consultado_em).toLocaleString("pt-BR") : "—"}</dd>
      </dl>
    </div>
  );
}

function Formulario({ cadastro, onSalvo }: { cadastro: Cadastro; onSalvo: (c: Cadastro) => void }) {
  const inicial = () =>
    Object.fromEntries(
      CAMPOS.map((c) => [c.key, String(cadastro.dados[c.key] ?? c.daReceita?.(cadastro.empresa) ?? "")]),
    );
  const [valores, setValores] = useState<Record<string, string>>(inicial);
  const [salvando, setSalvando] = useState(false);
  const [msg, setMsg] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);

  async function salvar(e: FormEvent) {
    e.preventDefault();
    setSalvando(true);
    setMsg(null);
    try {
      const dados = Object.fromEntries(
        CAMPOS.map((c) => {
          const v = valores[c.key].trim();
          return [c.key, v === "" ? null : c.type === "number" ? Number(v) : v]; // vazio apaga o campo
        }),
      );
      onSalvo(await salvarDados(dados));
      setMsg({ tipo: "ok", texto: "Salvo." });
    } catch (err) {
      setMsg({ tipo: "erro", texto: mensagemDeErro(err) });
    } finally {
      setSalvando(false);
    }
  }

  const grupo = (g: "empresa" | "adicional") =>
    CAMPOS.filter((c) => c.grupo === g).map((c) => {
      const salvo = c.key in cadastro.dados;
      const daReceita = !salvo && c.daReceita?.(cadastro.empresa) !== undefined;
      return (
        <label key={c.key}>
          <span>
            {c.label} {daReceita && <small className="tag">da Receita</small>}
          </span>
          <input type={c.type ?? "text"} value={valores[c.key]}
            onChange={(e) => setValores((v) => ({ ...v, [c.key]: e.target.value }))} />
        </label>
      );
    });

  return (
    <section className="card">
      <h2>3. Formulário</h2>
      <form onSubmit={salvar}>
        <h3>Dados da empresa</h3>
        <div className="grid duas">{grupo("empresa")}</div>
        <h3>Informações adicionais</h3>
        <div className="grid duas">{grupo("adicional")}</div>
        <div className="acoes">
          <button type="submit" disabled={salvando}>{salvando ? "Salvando…" : "Salvar"}</button>
          {msg && <span className={`msg ${msg.tipo}`}>{msg.texto}</span>}
        </div>
      </form>
      <details>
        <summary>Resposta do GET /cadastro/me</summary>
        <pre>{JSON.stringify(cadastro, null, 2)}</pre>
      </details>
    </section>
  );
}

// ---------- log ----------

function RequestLog({ logs }: { logs: LogEntry[] }) {
  if (!logs.length) return null;
  return (
    <section className="card">
      <h2>Chamadas à API</h2>
      <table>
        <tbody>
          {logs.map((l) => (
            <tr key={l.id}>
              <td className="sub">{l.at}</td>
              <td><code>{l.method}</code></td>
              <td><code>/cadastro{l.path === "/" ? "" : l.path}</code></td>
              <td className={typeof l.status === "number" && l.status < 400 ? "ok" : "erro"}>{l.status}</td>
              <td className="sub">{l.ms} ms</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
