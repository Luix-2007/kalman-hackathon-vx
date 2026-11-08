/**
 * Painel · Matriz de obrigações (rota /painel/matriz).
 *
 * 1. Enviar a planilha que a empresa já tem (CSV ou XLSX). O CSV é conferido aqui, linha a linha, com as mesmas regras
 *    do job (src/planilha.ts); o XLSX só é conferido depois de enviado.
 * 2. Acompanhar o processamento (o job da matriz leva de 7 a 15 minutos).
 * 3. Ver as obrigações vigentes que saíram dele (GET /obrigacoes). É a base do dashboard.
 *
 * Só quem criou a conta envia; membros veem o estado e as obrigações.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type ReactNode } from "react";
import { ApiError, type Cadastro } from "./api";
import { demoAtivo, demoMatriz } from "./demo";
import * as matrizReal from "./matriz";
import type { Importacao, Obrigacao, Processamento } from "./matriz";
import { COLUNAS, EXEMPLOS_PRAZO, conferir, lerCsv, modeloCsv, type Conferencia } from "./planilha";

const api = demoAtivo ? demoMatriz : matrizReal;

const erroDe = (e: unknown) => {
  if (e instanceof ApiError && e.status === 0) return "Sem conexão com o servidor. Confira a internet e tente de novo.";
  const m = (e as Error)?.message ?? String(e);
  return m ? m[0].toUpperCase() + m.slice(1) + (/[.!?]$/.test(m) ? "" : ".") : "Erro desconhecido.";
};
const dataHora = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }).replace(",", " às") : "";
const tamanho = (b: number) => (b < 1024 ? `${b} B` : b < 1024 * 1024 ? `${Math.round(b / 1024)} KB` : `${(b / 1024 / 1024).toFixed(1)} MB`);
/** "20261107-215413-matriz.csv" → "matriz.csv" (o prefixo é a data do envio, que já aparece ao lado). */
const nomeOriginal = (arquivo: string) => arquivo.replace(/^\d{8}-\d{6}-/, "");

const MAX_BYTES = 2 * 1024 * 1024;
const RECORRENCIA: Record<string, string> = { periodica: "periódica", por_evento: "por evento", continua: "contínua" };
const recorrencia = (v: string) => RECORRENCIA[v] ?? v;

type Escolhido =
  | { tipo: "csv"; nome: string; texto: string; conferencia: Conferencia }
  | { tipo: "xlsx"; nome: string; base64: string; tamanho: number };

export function TelaMatriz({ cadastro, onEnvio, onPular }: {
  cadastro: Cadastro;
  /** enviada = já existe planilha desta empresa; porAcao = acabou de ser enviada agora (o fluxo segue para a equipe) */
  onEnvio?: (enviada: boolean, porAcao: boolean) => void;
  /** "Pular esta etapa": quem ainda não tem a planilha segue para a equipe */
  onPular?: () => void;
}) {
  const dono = cadastro.papel === "dono";
  const [importacoes, setImportacoes] = useState<Importacao[] | null>(null);
  const [processamento, setProcessamento] = useState<Processamento>(null);
  const [obrigacoes, setObrigacoes] = useState<Obrigacao[] | null>(null);
  const [aviso, setAviso] = useState("");
  const [erro, setErro] = useState("");
  const [novaVersao, setNovaVersao] = useState(false);
  const avisou = useRef(false);

  const carregarEstado = useCallback(async () => {
    try {
      const r = await api.getImportacoes();
      setImportacoes(r.importacoes);
      setProcessamento(r.processamento);
      if (!avisou.current) { avisou.current = true; onEnvio?.(r.importacoes.length > 0, false); }
      return r.processamento;
    } catch (e) {
      setErro(erroDe(e));
      setImportacoes([]);
      if (!avisou.current) { avisou.current = true; onEnvio?.(false, false); }
      return null;
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const carregarObrigacoes = useCallback(async () => {
    try {
      const r = await api.getObrigacoes();
      setObrigacoes(r.obrigacoes);
      setAviso(r.aviso ?? "");
    } catch {
      setObrigacoes([]); // sem matriz processada ainda: a seção só aparece quando houver
    }
  }, []);

  useEffect(() => { carregarEstado(); carregarObrigacoes(); }, [carregarEstado, carregarObrigacoes]);

  // a análise roda em segundo plano; enquanto roda, a tela confere de vez em quando, sem prender ninguém
  const analisando = processamento?.estado === "RUNNING";
  useEffect(() => {
    if (!analisando) return;
    const t = setInterval(async () => {
      const p = await carregarEstado();
      if (p && p.estado !== "RUNNING") carregarObrigacoes();
    }, demoAtivo ? 3000 : 30000);
    return () => clearInterval(t);
  }, [analisando, carregarEstado, carregarObrigacoes]);

  const unidades = useMemo(() => idsDoPerfil(cadastro.dados.unidades), [cadastro.dados.unidades]);
  const areas = useMemo(() => idsDoPerfil(cadastro.dados.areas), [cadastro.dados.areas]);
  const enviada = (importacoes?.length ?? 0) > 0;
  const pronta = enviada && !analisando && (obrigacoes?.length ?? 0) > 0;

  if (importacoes === null) return <div className="matriz"><span className="carregando" role="status" aria-label="Carregando" /></div>;

  return (
    <div className="matriz">
      {!enviada && (
        <p className="etapa-apoio">
          Envie a planilha de obrigações que a empresa já acompanha. Cada linha vira uma obrigação com prazo calculado e
          tarefas com data, e o Kalman passa a avisar quando uma norma nova mudar alguma delas.
        </p>
      )}

      {erro && <p className="msg msg-erro" role="alert">{erro}</p>}

      {enviada && <Recebida importacoes={importacoes!} processamento={processamento}
        onNova={dono && !novaVersao ? () => setNovaVersao(true) : undefined} />}

      {dono && (!enviada || novaVersao) && (
        <Envio unidades={unidades} areas={areas} temUnidades={unidades.size > 0}
          onCancelar={enviada ? () => setNovaVersao(false) : undefined}
          onEnviado={(p) => { setProcessamento(p); setNovaVersao(false); carregarEstado(); onEnvio?.(true, true); }} />
      )}

      {!dono && !enviada && (
        <p className="nota-leitura"><span className="k-ponto" aria-hidden="true" /> Quem envia a planilha é quem criou a conta. O resultado aparece aqui.</p>
      )}

      {onPular && !enviada && (
        <p className="pular">Ainda não tem a planilha? <button type="button" className="link" onClick={onPular}>Pular esta etapa</button></p>
      )}

      {pronta && <Obrigacoes obrigacoes={obrigacoes!} aviso={aviso} />}
    </div>
  );
}

function idsDoPerfil(lista: unknown): Set<string> {
  return new Set(Array.isArray(lista) ? lista.map((x) => String((x as { id?: unknown })?.id ?? "")).filter(Boolean) : []);
}

// ─────────────────────────── 1. envio ───────────────────────────

function Envio({ unidades, areas, temUnidades, onEnviado, onCancelar }: {
  unidades: Set<string>; areas: Set<string>; temUnidades: boolean; onEnviado: (p: Processamento) => void; onCancelar?: () => void;
}) {
  const [escolhido, setEscolhido] = useState<Escolhido | null>(null);
  const [arrastando, setArrastando] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [msg, setMsg] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const entrada = useRef<HTMLInputElement>(null);

  async function abrir(arquivo: File) {
    setMsg(null);
    const ext = arquivo.name.split(".").pop()?.toLowerCase();
    if (ext !== "csv" && ext !== "xlsx") { setMsg({ tipo: "erro", texto: "Envie um arquivo .csv ou .xlsx." }); return; }
    if (arquivo.size > MAX_BYTES) { setMsg({ tipo: "erro", texto: "Arquivo maior que 2 MB." }); return; }
    if (ext === "csv") {
      const texto = await arquivo.text();
      const { colunas, registros } = lerCsv(texto);
      setEscolhido({ tipo: "csv", nome: arquivo.name, texto, conferencia: conferir(colunas, registros, unidades, areas) });
    } else {
      const bytes = new Uint8Array(await arquivo.arrayBuffer());
      let bin = "";
      for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
      setEscolhido({ tipo: "xlsx", nome: arquivo.name, base64: btoa(bin), tamanho: arquivo.size });
    }
  }

  function soltar(e: DragEvent) {
    e.preventDefault();
    setArrastando(false);
    const f = e.dataTransfer.files?.[0];
    if (f) abrir(f);
  }

  async function enviar() {
    if (!escolhido) return;
    setEnviando(true); setMsg(null);
    try {
      const r = await api.importarMatriz(escolhido.nome,
        escolhido.tipo === "csv" ? { texto: escolhido.texto } : { base64: escolhido.base64 });
      setEscolhido(null);
      onEnviado(r.processamento);
    } catch (e) {
      setMsg({ tipo: "erro", texto: erroDe(e) });
    } finally {
      setEnviando(false);
    }
  }

  const c = escolhido?.tipo === "csv" ? escolhido.conferencia : null;
  const bloqueado = !!c && (c.colunasFaltando.length > 0 || c.validas === 0);
  const comErro = c ? c.linhas.length - c.validas : 0;

  return (
    <section className="bloco bloco--largo" aria-labelledby="t-envio">
      <div className="bloco-titulo">
        <h3 id="t-envio">{onCancelar ? "Enviar nova versão" : "Enviar a planilha"}</h3>
        <p>CSV ou Excel, até 2 MB. Uma linha por obrigação.</p>
        {onCancelar && <button type="button" className="link link-pequeno" onClick={onCancelar}>Cancelar</button>}
        <button type="button" className="link link-pequeno baixar-modelo" onClick={baixarModelo}>Baixar modelo (.csv)</button>
      </div>

      <div className="envio">
        {!escolhido ? (
          <label className="soltar" data-arrastando={arrastando || undefined}
            onDragOver={(e) => { e.preventDefault(); setArrastando(true); }} onDragLeave={() => setArrastando(false)} onDrop={soltar}>
            <input ref={entrada} type="file" accept=".csv,.xlsx,text/csv" className="sr"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) abrir(f); e.target.value = ""; }} />
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M12 15V4" /><path d="m7.5 8.5 4.5-4.5 4.5 4.5" /><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
            </svg>
            <span className="soltar-titulo">Solte a planilha aqui ou <span className="soltar-link">escolha o arquivo</span></span>
            <span className="soltar-apoio">O CSV é conferido aqui mesmo, antes de enviar.</span>
          </label>
        ) : (
          <div className="escolhido">
            <div className="escolhido-topo">
              <div>
                <strong className="escolhido-nome">{escolhido.nome}</strong>
                <span className="escolhido-resumo">
                  {c
                    ? <>{c.linhas.length} {c.linhas.length === 1 ? "obrigação" : "obrigações"} · <b className="ok">{c.validas} {c.validas === 1 ? "pronta" : "prontas"}</b>{comErro > 0 && <> · <b className="erro">{comErro} com erro</b></>}</>
                    : <>Planilha do Excel · {escolhido.tipo === "xlsx" ? tamanho(escolhido.tamanho) : ""} · conferida depois do envio</>}
                </span>
              </div>
              <button type="button" className="link link-pequeno" onClick={() => { setEscolhido(null); setMsg(null); }}>Trocar arquivo</button>
            </div>

            {c && c.colunasFaltando.length > 0 && (
              <p className="msg msg-erro" role="alert">Faltam colunas obrigatórias: {c.colunasFaltando.join(", ")}. Use o modelo.</p>
            )}
            {c && c.colunasDesconhecidas.length > 0 && (
              <p className="msg msg-info">Colunas ignoradas: {c.colunasDesconhecidas.join(", ")}.</p>
            )}
            {c && !temUnidades && c.linhas.some((l) => l.dados.aplica_a) && (
              <p className="msg msg-info">O perfil da empresa ainda não tem unidades: deixe a coluna aplica_a vazia para a obrigação valer para a empresa toda.</p>
            )}

            {c && c.linhas.length > 0 && <Previa conferencia={c} />}

            <div className="envio-acoes">
              {comErro > 0 && !bloqueado && <span className="envio-nota">As linhas com erro ficam de fora até serem corrigidas.</span>}
              <button className="k-btn" type="button" disabled={enviando || bloqueado} onClick={enviar}>
                {enviando ? "Enviando…" : c ? `Enviar ${c.validas} ${c.validas === 1 ? "obrigação" : "obrigações"}` : "Enviar planilha"}
              </button>
            </div>
          </div>
        )}

        {msg && <p className={`msg ${msg.tipo === "erro" ? "msg-erro" : "msg-info"}`} role={msg.tipo === "erro" ? "alert" : "status"}>{msg.texto}</p>}

        <details className="colunas-ajuda">
          <summary>Colunas da planilha</summary>
          <dl>
            {COLUNAS.map((col) => (
              <div key={col.nome}>
                <dt className="k-mono">{col.nome}{col.obrigatoria && <span className="obrigatoria"> obrigatória</span>}</dt>
                <dd>{col.descricao}</dd>
              </div>
            ))}
          </dl>
          <p className="colunas-sub">Exemplos de <span className="k-mono">prazo_json</span>:</p>
          <ul className="exemplos-prazo">
            {EXEMPLOS_PRAZO.map((x) => (
              <li key={x.regra}><span>{x.regra}</span><code>{x.json}</code></li>
            ))}
          </ul>
        </details>
      </div>
    </section>
  );
}

function baixarModelo() {
  const url = URL.createObjectURL(new Blob([modeloCsv()], { type: "text/csv;charset=utf-8" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: "kalman-matriz-modelo.csv" });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Prévia linha a linha. Mostra primeiro as linhas com erro. */
function Previa({ conferencia: c }: { conferencia: Conferencia }) {
  const [todas, setTodas] = useState(false);
  const ordenadas = [...c.linhas].sort((a, b) => Number(b.erros.length > 0) - Number(a.erros.length > 0) || a.linha - b.linha);
  const visiveis = todas ? ordenadas : ordenadas.slice(0, 8);
  return (
    <div className="previa">
      <div className="previa-rolagem">
        <table className="tabela">
          <thead>
            <tr><th>Linha</th><th>ID</th><th>Obrigação</th><th>Órgão</th><th>Prazo</th><th>Criticidade</th></tr>
          </thead>
          <tbody>
            {visiveis.map((l) => (
              <LinhaPrevia key={l.linha} cols={[
                <span className="k-mono">{l.linha}</span>,
                <span className="k-mono">{l.dados.obrigacao_id || "—"}</span>,
                l.dados.titulo || "—",
                l.dados.orgao_sigla || "—",
                l.dados.prazo_regra || (l.dados.recorrencia ? recorrencia(l.dados.recorrencia) : "—"),
                l.dados.criticidade ? <Criticidade valor={l.dados.criticidade} /> : "—",
              ]} erros={l.erros} avisos={l.avisos} />
            ))}
          </tbody>
        </table>
      </div>
      {c.linhas.length > 8 && (
        <button type="button" className="link link-pequeno" onClick={() => setTodas((v) => !v)}>
          {todas ? "Mostrar menos" : `Mostrar as ${c.linhas.length} linhas`}
        </button>
      )}
    </div>
  );
}

function LinhaPrevia({ cols, erros, avisos }: { cols: ReactNode[]; erros: string[]; avisos: string[] }) {
  return (
    <>
      <tr data-erro={erros.length > 0 || undefined}>
        {cols.map((c, i) => <td key={i}>{c}</td>)}
      </tr>
      {(erros.length > 0 || avisos.length > 0) && (
        <tr className="linha-problemas" data-erro={erros.length > 0 || undefined}>
          <td />
          <td colSpan={cols.length - 1}>
            {erros.map((e) => <span key={e} className="problema problema--erro">{e}</span>)}
            {avisos.map((a) => <span key={a} className="problema">{a}</span>)}
          </td>
        </tr>
      )}
    </>
  );
}

function Criticidade({ valor }: { valor: string }) {
  return <span className="criticidade" data-nivel={valor}>{valor === "media" ? "média" : valor}</span>;
}

// ─────────────────────────── 2. planilha recebida + análise em segundo plano ───────────────────────────

function Recebida({ importacoes, processamento: p, onNova }: { importacoes: Importacao[]; processamento: Processamento; onNova?: () => void }) {
  const ultima = importacoes[0];
  let status: ReactNode = null;
  if (p?.estado === "RUNNING") {
    status = <><span className="cnpj-girando" aria-hidden="true" /><span>
      Analisando o perfil da empresa e cruzando a matriz com as normas. Roda em segundo plano: você pode seguir.
      O resultado aparece aqui quando ficar pronto.</span></>;
  } else if (p?.estado === "SUCCEEDED") {
    status = <span>Análise concluída em {dataHora(p.fim)}.</span>;
  } else if (p) {
    status = <span>A análise não terminou desta vez. Ela roda de novo sozinha em até 1 hora; não precisa enviar outra vez.</span>;
  }
  return (
    <div className="recebida" data-estado={p?.estado}>
      <div className="recebida-topo">
        <div className="recebida-titulo">
          <span className="etapa-ok" aria-hidden="true">✓</span>
          <strong>Planilha recebida</strong>
          <span className="envio-meta k-mono">{nomeOriginal(ultima.arquivo)} · {dataHora(ultima.enviado_em)}</span>
        </div>
        {onNova && <button type="button" className="link link-pequeno" onClick={onNova}>Enviar nova versão</button>}
      </div>
      {status && <p className="recebida-status" aria-live="polite">{status}</p>}
      {importacoes.length > 1 && (
        <p className="recebida-historico">Versões anteriores: {importacoes.slice(1, 4).map((i) => `${nomeOriginal(i.arquivo)} (${dataHora(i.enviado_em)})`).join(" · ")}</p>
      )}
    </div>
  );
}

// ─────────────────────────── 3. obrigações vigentes ───────────────────────────

function Obrigacoes({ obrigacoes, aviso }: { obrigacoes: Obrigacao[] | null; aviso: string }) {
  const [aberta, setAberta] = useState<string | null>(null);
  if (obrigacoes === null) return null;
  const vigentes = obrigacoes.filter((o) => o.vigente !== false && o.status !== "proposta");
  const propostas = obrigacoes.filter((o) => o.status === "proposta");

  return (
    <section className="bloco bloco--largo" aria-labelledby="t-obrigacoes">
      <div className="bloco-titulo">
        <h2 id="t-obrigacoes">Obrigações</h2>
        <p>{vigentes.length ? `${vigentes.length} vigentes${propostas.length ? ` · ${propostas.length} mudanças propostas` : ""}.` : "O que saiu da planilha."}</p>
      </div>
      <div className="obrigacoes">
        {vigentes.length === 0 ? (
          <p className="vazio">{aviso ? "A matriz ainda não foi processada. Envie a planilha acima." : "Nenhuma obrigação vigente."}</p>
        ) : (
          <ul className="obrigacoes-lista">
            {vigentes.map((o) => (
              <li key={`${o.obrigacao_id}-${o.versao}`} className="obrigacao" data-aberta={aberta === o.obrigacao_id || undefined}>
                <button type="button" className="obrigacao-linha" aria-expanded={aberta === o.obrigacao_id}
                  onClick={() => setAberta((a) => (a === o.obrigacao_id ? null : o.obrigacao_id))}>
                  <span className="k-mono obrigacao-id">{o.obrigacao_id}</span>
                  <span className="obrigacao-titulo">{o.titulo}</span>
                  <span className="obrigacao-orgao">{o.orgao_sigla ?? ""}</span>
                  {o.criticidade ? <Criticidade valor={o.criticidade} /> : <span />}
                </button>
                {aberta === o.obrigacao_id && (
                  <dl className="obrigacao-detalhe">
                    {o.prazo_regra && <div><dt>Prazo</dt><dd className="k-prazo">{o.prazo_regra}</dd></div>}
                    <div><dt>Recorrência</dt><dd>{[recorrencia(o.recorrencia), o.periodicidade].filter(Boolean).join(" · ")}</dd></div>
                    {(o.fonte_ato || o.fonte_dispositivo) && (
                      <div><dt>Fonte</dt><dd>
                        {o.fonte_url ? <a href={o.fonte_url} target="_blank" rel="noopener">{[o.fonte_ato, o.fonte_dispositivo].filter(Boolean).join(", ")}</a>
                          : [o.fonte_ato, o.fonte_dispositivo].filter(Boolean).join(", ")}
                      </dd></div>
                    )}
                    {o.trecho_citado && <div><dt>Trecho</dt><dd><q>{o.trecho_citado}</q></dd></div>}
                    {o.area_responsavel && <div><dt>Área</dt><dd className="k-mono">{o.area_responsavel}</dd></div>}
                    {o.evidencia && <div><dt>Evidência</dt><dd>{o.evidencia}</dd></div>}
                    <div><dt>Versão</dt><dd className="k-mono">v{o.versao} · desde {o.incluida_em?.slice(0, 10).split("-").reverse().join("/")}</dd></div>
                  </dl>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

// ─────────────────────────── resumo para a etapa de revisão do painel ───────────────────────────

/** Uma linha sobre a matriz: planilha recebida e estado da análise (que roda em segundo plano). */
export function ResumoMatriz({ pulou, versao, onAbrir }: { pulou: boolean; versao: number; onAbrir: () => void }) {
  const [importacoes, setImportacoes] = useState<Importacao[] | null>(null);
  const [processamento, setProcessamento] = useState<Processamento>(null);
  const [vigentes, setVigentes] = useState<number | null>(null);

  useEffect(() => {
    let vivo = true;
    const ler = async () => {
      const r = await api.getImportacoes().catch(() => ({ importacoes: [] as Importacao[], processamento: null as Processamento }));
      if (!vivo) return r.processamento;
      setImportacoes(r.importacoes);
      setProcessamento(r.processamento);
      if (r.importacoes.length && r.processamento?.estado !== "RUNNING") {
        const o = await api.getObrigacoes().catch(() => ({ obrigacoes: [] as Obrigacao[] }));
        if (vivo) setVigentes(o.obrigacoes.filter((x) => x.vigente !== false && x.status !== "proposta").length);
      }
      return r.processamento;
    };
    ler();
    const t = setInterval(async () => { const p = await ler(); if (p?.estado !== "RUNNING") clearInterval(t); }, demoAtivo ? 3000 : 30000);
    return () => { vivo = false; clearInterval(t); };
  }, [versao]);

  if (importacoes === null) return <span className="carregando" role="status" aria-label="Carregando" />;
  const ultima = importacoes[0];
  let estado: ReactNode;
  if (!ultima) estado = pulou ? "Etapa pulada: envie a planilha quando tiver." : "Nenhuma planilha enviada.";
  else if (processamento?.estado === "RUNNING") estado = <><span className="cnpj-girando" aria-hidden="true" /> Análise em andamento, em segundo plano.</>;
  else if (processamento?.estado === "SUCCEEDED") estado = vigentes ? `Análise concluída: ${vigentes} obrigações vigentes.` : "Análise concluída.";
  else estado = "A análise roda de novo sozinha em até 1 hora.";

  return (
    <div className="revisao-item" data-feito={!!ultima || undefined}>
      <div className="revisao-item-topo">
        <h3>Matriz de obrigações</h3>
        <button type="button" className="link link-pequeno" onClick={onAbrir}>{ultima ? "Ver a matriz" : "Enviar a planilha"}</button>
      </div>
      {ultima && <p className="revisao-linha"><span className="etapa-ok" aria-hidden="true">✓</span> {nomeOriginal(ultima.arquivo)} · enviada em {dataHora(ultima.enviado_em)}</p>}
      <p className="revisao-linha revisao-estado">{estado}</p>
    </div>
  );
}
