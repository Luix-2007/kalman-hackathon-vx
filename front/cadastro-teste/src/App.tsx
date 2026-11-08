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
  aceitarConvite,
  aguardarConsulta,
  ApiError,
  convidar,
  enviarCnpj,
  getCadastro,
  getConvite,
  getMembros,
  onRequestLog,
  recusarConvite,
  removerMembro,
  salvarDados,
  type Cadastro,
  type Convite,
  type LogEntry,
  type Membros,
} from "./api";
import { CAMPOS, GRUPOS, paraEnvio, valorInicial, type Campo, type Linha, type Valor } from "./campos";
import { config, configured } from "./config";
import { Chatbot } from "./Chatbot";
import { Matriz } from "./Matriz";

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
  processando: { texto: "Consultando…", cor: "aviso" },
  ativa: { texto: "Ativa", cor: "ok" },
  inativa: { texto: "Inativa na Receita", cor: "aviso" },
  nao_encontrado: { texto: "CNPJ não encontrado", cor: "erro" },
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
          <p className="sub">Login no Cognito → CNPJ → consulta em segundo plano → formulário → membros</p>
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
        {config.matrizApiUrl && <> · Matriz: <code>{config.matrizApiUrl}</code></>}
        {config.chatbotApiUrl && <> · Assistente: <code>{config.chatbotApiUrl}</code></>}
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

// ---------- 2. CNPJ + 3. formulário + 4. organização ----------

function Cadastrar() {
  const [cadastro, setCadastro] = useState<Cadastro | null | undefined>(undefined);
  const [cnpj, setCnpj] = useState("");
  const [fase, setFase] = useState<"parado" | "enviando" | "aguardando">("parado");
  const [segundos, setSegundos] = useState(0);
  const [erro, setErro] = useState("");
  const souMembro = cadastro?.papel === "membro";

  const recarregar = () =>
    getCadastro().then(setCadastro).catch((e) => {
      setErro(mensagemDeErro(e));
      setCadastro(null);
    });

  useEffect(() => {
    recarregar();
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
      {cadastro === null && <ConvitePendente onAceito={recarregar} />}

      <section className="card">
        <h2>2. CNPJ</h2>
        {souMembro ? (
          <p className="sub">Você é membro desta organização. Só o dono pode trocar o CNPJ e editar o cadastro.</p>
        ) : (
        <form onSubmit={consultar} className="linha">
          <input placeholder="00.000.000/0001-91" value={cnpj} onChange={(e) => setCnpj(e.target.value)} required
            disabled={fase !== "parado"} />
          <button type="submit" disabled={fase !== "parado"}>
            {fase === "enviando" ? "Enviando…" : fase === "aguardando" ? `Consultando… ${segundos}s` : cadastro ? "Trocar CNPJ" : "Consultar"}
          </button>
        </form>
        )}
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
          somenteLeitura={souMembro}
        />
      )}

      {cadastro && <Organizacao key={cadastro.cnpj} cadastro={cadastro} onSaiu={() => setCadastro(null)} />}

      {cadastro && config.matrizApiUrl && <Matriz key={`matriz-${cadastro.cnpj}`} souMembro={souMembro} />}

      {cadastro && config.chatbotApiUrl && <Chatbot key={`chatbot-${cadastro.cnpj}`} />}
    </>
  );
}

function ConvitePendente({ onAceito }: { onAceito: () => void }) {
  const [convite, setConvite] = useState<Convite | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");

  useEffect(() => {
    getConvite().then(setConvite).catch((e) => setErro(mensagemDeErro(e)));
  }, []);

  async function executar(fn: () => Promise<unknown>, depois: () => void) {
    setOcupado(true);
    setErro("");
    try {
      await fn();
      depois();
    } catch (err) {
      setErro(mensagemDeErro(err));
    } finally {
      setOcupado(false);
    }
  }

  if (!convite && !erro) return null;
  return (
    <section className="card destaque">
      <h2>Convite pendente</h2>
      {convite && (
        <>
          <p>
            <strong>{convite.convidado_por ?? "O dono"}</strong> convidou você para a organização{" "}
            <strong>{convite.razao_social ?? formatCnpj(convite.cnpj)}</strong> ({formatCnpj(convite.cnpj)}).
            Como membro, você vê os dados da empresa, mas não edita.
          </p>
          <p className="sub">Válido até {new Date(convite.expira_em * 1000).toLocaleString("pt-BR")}.</p>
          <div className="acoes">
            <button disabled={ocupado} onClick={() => executar(aceitarConvite, onAceito)}>Aceitar</button>
            <button className="link" disabled={ocupado} onClick={() => executar(recusarConvite, () => setConvite(null))}>
              Recusar
            </button>
          </div>
        </>
      )}
      {erro && <p className="msg erro">{erro}</p>}
    </section>
  );
}

function Organizacao({ cadastro, onSaiu }: { cadastro: Cadastro; onSaiu: () => void }) {
  const [org, setOrg] = useState<Membros | null>(null);
  const [email, setEmail] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [msg, setMsg] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const souDono = cadastro.papel === "dono";

  const carregar = () => getMembros().then(setOrg).catch((e) => setMsg({ tipo: "erro", texto: mensagemDeErro(e) }));
  useEffect(() => {
    carregar();
  }, []);

  async function executar(fn: () => Promise<unknown>, ok: string, depois: () => unknown = carregar) {
    setOcupado(true);
    setMsg(null);
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

  function enviarConvite(e: FormEvent) {
    e.preventDefault();
    executar(() => convidar(email.trim()), `Convite criado. Avise ${email.trim()} para criar a conta com esse e-mail.`,
      () => { setEmail(""); return carregar(); });
  }

  return (
    <section className="card">
      <h2>4. Organização</h2>
      <p className="sub">
        {souDono
          ? "Você é o dono. Convide pessoas pelo e-mail: elas veem os dados da empresa, mas não editam."
          : "Você é membro: vê os dados da empresa, mas não edita."}
      </p>
      {org && (
        <table>
          <tbody>
            <tr>
              <td>{org.dono.email ?? org.dono.user_id}</td>
              <td><span className="badge ok">dono</span></td>
              <td></td>
            </tr>
            {org.membros.map((m) => (
              <tr key={m.user_id}>
                <td>{m.email}</td>
                <td><span className="badge">membro</span></td>
                <td>
                  {souDono && (
                    <button className="link" disabled={ocupado}
                      onClick={() => executar(() => removerMembro(m.user_id), `${m.email} removido.`)}>
                      Remover
                    </button>
                  )}
                  {m.user_id === cadastro.user_id && (
                    <button className="link" disabled={ocupado}
                      onClick={() => executar(() => removerMembro(m.user_id), "Você saiu da organização.", onSaiu)}>
                      Sair da organização
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {org.convites?.map((c) => (
              <tr key={c.email}>
                <td>{c.email}</td>
                <td><span className="badge aviso">convite pendente</span></td>
                <td>
                  <button className="link" disabled={ocupado}
                    onClick={() => executar(() => removerMembro(c.email), "Convite cancelado.")}>
                    Cancelar
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {souDono && (
        <form onSubmit={enviarConvite} className="linha" style={{ marginTop: 16 }}>
          <input type="email" required placeholder="pessoa@empresa.com" value={email}
            onChange={(e) => setEmail(e.target.value)} disabled={ocupado} />
          <button type="submit" disabled={ocupado}>Convidar</button>
        </form>
      )}
      {msg && <p className={`msg ${msg.tipo}`} style={{ marginTop: 12 }}>{msg.texto}</p>}
    </section>
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

function Formulario({ cadastro, onSalvo, somenteLeitura }: {
  cadastro: Cadastro;
  onSalvo: (c: Cadastro) => void;
  somenteLeitura: boolean;
}) {
  const inicial = () =>
    Object.fromEntries(CAMPOS.map((c) => [c.key, valorInicial(c, cadastro.dados, cadastro.empresa)])) as Record<string, Valor>;
  const [valores, setValores] = useState<Record<string, Valor>>(inicial);
  const [salvando, setSalvando] = useState(false);
  const [msg, setMsg] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const muda = (key: string) => (v: Valor) => setValores((atual) => ({ ...atual, [key]: v }));

  async function salvar(e: FormEvent) {
    e.preventDefault();
    setSalvando(true);
    setMsg(null);
    try {
      const dados = Object.fromEntries(CAMPOS.map((c) => [c.key, paraEnvio(c, valores[c.key])]));
      onSalvo(await salvarDados(dados));
      setMsg({ tipo: "ok", texto: "Salvo." });
    } catch (err) {
      const campos = err instanceof ApiError ? (err.body as { campos?: unknown })?.campos : undefined;
      const detalhe = campos && !Array.isArray(campos)
        ? Object.entries(campos as Record<string, string>).map(([k, v]) => `${k}: ${v}`).join("; ")
        : "";
      setMsg({ tipo: "erro", texto: [mensagemDeErro(err), detalhe].filter(Boolean).join(" — ") });
    } finally {
      setSalvando(false);
    }
  }

  const campo = (c: Campo) => {
    const valor = valores[c.key];
    const daReceita = !(c.key in cadastro.dados) && "daReceita" in c && c.daReceita?.(cadastro.empresa) !== undefined;
    const titulo = (
      <span>
        {c.label} {daReceita && <small className="tag">da Receita</small>}
        {c.ajuda && <small className="ajuda">{c.ajuda}</small>}
      </span>
    );
    if (c.tipo === "objetos") {
      return (
        <div key={c.key} className="campo-largo">
          {titulo}
          <Linhas campo={c} linhas={valor as Linha[]} onChange={muda(c.key)} somenteLeitura={somenteLeitura} />
        </div>
      );
    }
    if (c.tipo === "chips") {
      return (
        <div key={c.key} className="campo-chips">
          {titulo}
          <Chips valores={valor as string[]} onChange={muda(c.key)} somenteLeitura={somenteLeitura}
            sugestoes={c.sugestoes} maiusculas={c.maiusculas} id={c.key} />
        </div>
      );
    }
    if (c.tipo === "opcoes") {
      return (
        <label key={c.key}>
          {titulo}
          <select value={valor as string} disabled={somenteLeitura} onChange={(e) => muda(c.key)(e.target.value)}>
            <option value="">—</option>
            {c.opcoes.map((o) => <option key={o.valor} value={o.valor}>{o.rotulo}</option>)}
          </select>
        </label>
      );
    }
    return (
      <label key={c.key}>
        {titulo}
        <input type={c.input ?? "text"} value={valor as string} readOnly={somenteLeitura}
          onChange={(e) => muda(c.key)(e.target.value)} />
      </label>
    );
  };

  return (
    <section className="card">
      <h2>3. Perfil regulatório</h2>
      <form onSubmit={salvar}>
        {GRUPOS.map(({ grupo, titulo }) => (
          <div key={grupo}>
            <h3>{titulo}</h3>
            <div className="grid duas">{CAMPOS.filter((c) => c.grupo === grupo).map(campo)}</div>
          </div>
        ))}
        {!somenteLeitura && (
          <div className="acoes">
            <button type="submit" disabled={salvando}>{salvando ? "Salvando…" : "Salvar"}</button>
            {msg && <span className={`msg ${msg.tipo}`}>{msg.texto}</span>}
          </div>
        )}
      </form>
      <details>
        <summary>Resposta do GET /cadastro/me</summary>
        <pre>{JSON.stringify(cadastro, null, 2)}</pre>
      </details>
    </section>
  );
}

/** Lista de textos como chips. Enter ou vírgula adiciona; × remove. */
function Chips({ id, valores, onChange, somenteLeitura, sugestoes, maiusculas }: {
  id: string;
  valores: string[];
  onChange: (v: string[]) => void;
  somenteLeitura: boolean;
  sugestoes?: string[];
  maiusculas?: boolean;
}) {
  const [texto, setTexto] = useState("");
  const adiciona = () => {
    const novos = texto.split(",").map((t) => (maiusculas ? t.trim().toUpperCase() : t.trim())).filter(Boolean);
    if (novos.length) onChange([...valores, ...novos.filter((n) => !valores.includes(n))]);
    setTexto("");
  };
  return (
    <div className="chips">
      {valores.map((v) => (
        <span key={v} className="chip">
          {v}
          {!somenteLeitura && (
            <button type="button" aria-label={`remover ${v}`} onClick={() => onChange(valores.filter((x) => x !== v))}>×</button>
          )}
        </span>
      ))}
      {!somenteLeitura && (
        <>
          <input value={texto} list={sugestoes ? `${id}-sugestoes` : undefined} placeholder="adicionar…"
            onChange={(e) => setTexto(e.target.value)} onBlur={adiciona}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === ",") { e.preventDefault(); adiciona(); }
              if (e.key === "Backspace" && !texto && valores.length) onChange(valores.slice(0, -1));
            }} />
          {sugestoes && (
            <datalist id={`${id}-sugestoes`}>
              {sugestoes.filter((s) => !valores.includes(s)).map((s) => <option key={s} value={s} />)}
            </datalist>
          )}
        </>
      )}
    </div>
  );
}

/** Linhas repetíveis (unidades, outorgas, áreas): um bloco por item, com os campos das colunas. */
function Linhas({ campo, linhas, onChange, somenteLeitura }: {
  campo: Extract<Campo, { tipo: "objetos" }>;
  linhas: Linha[];
  onChange: (v: Linha[]) => void;
  somenteLeitura: boolean;
}) {
  const altera = (i: number, key: string, v: string) =>
    onChange(linhas.map((l, j) => (j === i ? { ...l, [key]: v } : l)));
  const novoId = () => {
    let n = linhas.length + 1;
    const ids = new Set(linhas.map((l) => String(l.id ?? "")));
    while (ids.has(`${campo.prefixoId}-${String(n).padStart(2, "0")}`)) n++;
    return `${campo.prefixoId}-${String(n).padStart(2, "0")}`;
  };
  return (
    <div className="linhas">
      {linhas.length === 0 && <p className="sub">Nenhum item.</p>}
      {linhas.map((linha, i) => (
        <fieldset key={i} className="linha-item">
          <div className="grid duas">
            {campo.colunas.map((col) => {
              const v = linha[col.key];
              return (
                <label key={col.key}>
                  <span>{col.label}{col.obrigatoria && " *"}</span>
                  <input type={col.type === "lista" ? "text" : col.type ?? "text"} readOnly={somenteLeitura}
                    placeholder={col.placeholder} required={col.obrigatoria}
                    value={Array.isArray(v) ? v.join(", ") : String(v ?? "")}
                    onChange={(e) => altera(i, col.key, e.target.value)} />
                </label>
              );
            })}
          </div>
          {!somenteLeitura && (
            <button type="button" className="link" onClick={() => onChange(linhas.filter((_, j) => j !== i))}>Remover</button>
          )}
        </fieldset>
      ))}
      {!somenteLeitura && (
        <button type="button" className="link" onClick={() => onChange([...linhas, { id: novoId() }])}>
          + Adicionar {campo.label.toLowerCase()}
        </button>
      )}
    </div>
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
