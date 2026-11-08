/**
 * A IA do Kalman: o chat ocupa a tela. Histórico e "Nova conversa" ficam no cabeçalho; as fontes aparecem dentro de
 * cada resposta, depois que ela chega.
 * O contrato é o da API do chatbot (src/chatbot.ts): `resposta` (texto curto) + `blocos` (dados com formato fixo).
 * Integrar = acoes.perguntar → enviarMensagem(prompt, sessionId).
 *
 * O robô acompanha a conversa: ouvindo (digitando) → pensando (esperando a API) → respondendo → concluído,
 * ou "não sei" quando a resposta não traz dado.
 */
import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { PROMPT_MAX, type Bloco } from "../chatbot";
import type { Contexto } from "./Dash";
import { useObrigacao } from "./DetalheObrigacao";
import { Citacao, Criticidade, Diff, STATUS_TAREFA, dataBr, dataCurta, linkSeguro, relativo } from "./cartoes";
import { PERGUNTAS_SUGERIDAS, acoes, useLoja, type Mensagem } from "./dados";
import { ROTULO_EVENTO } from "./Hoje";
import { NOME_IA, Robo, type EstadoRobo } from "./Robo";

export function Ia(_props: { ctx: Contexto }) {
  const e = useLoja();
  const [params, setParams] = useSearchParams();
  const [atual, setAtual] = useState<string | null>(null);
  const [texto, setTexto] = useState("");
  const [esperando, setEsperando] = useState(false);
  const [robo, setRobo] = useState<EstadoRobo>("repouso");
  const [historico, setHistorico] = useState(false);
  const campo = useRef<HTMLTextAreaElement>(null);
  const fim = useRef<HTMLDivElement>(null);
  const timers = useRef<number[]>([]);
  const caixaHist = useRef<HTMLDivElement>(null);

  const conversa = e.conversas.find((c) => c.id === atual);
  const mensagens = conversa?.mensagens ?? [];
  const antigas = e.conversas.filter((c) => c.mensagens.length);

  async function enviar(prompt: string, conversaId?: string) {
    const p = prompt.trim().slice(0, PROMPT_MAX);
    if (!p || esperando) return;
    const id = conversaId ?? atual ?? acoes.novaConversa();
    if (id !== atual) setAtual(id);
    setTexto("");
    setEsperando(true);
    setRobo("pensando");
    timers.current.forEach(clearTimeout);
    const r = await acoes.perguntar(id, p);
    setEsperando(false);
    setRobo("respondendo");
    timers.current = [
      window.setTimeout(() => setRobo(r.blocos.length ? "concluido" : "nao-sei"), 1100),
      window.setTimeout(() => setRobo("repouso"), 5200),
    ];
  }

  // ?p=pergunta (vindo de "Perguntar à IA" em outra tela): abre uma conversa nova e já pergunta
  const iniciou = useRef(false);
  useEffect(() => {
    const p = params.get("p");
    if (iniciou.current || !p) return;
    iniciou.current = true;
    const id = acoes.novaConversa();
    setAtual(id);
    setParams({}, { replace: true });
    setTimeout(() => enviar(p, id), 0);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => timers.current.forEach(clearTimeout), []);
  useEffect(() => { fim.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [mensagens.length, esperando]);
  useEffect(() => {
    if (!historico) return;
    const fora = (ev: MouseEvent) => { if (!caixaHist.current?.contains(ev.target as Node)) setHistorico(false); };
    addEventListener("mousedown", fora);
    return () => removeEventListener("mousedown", fora);
  }, [historico]);

  function submeter(ev: FormEvent) { ev.preventDefault(); enviar(texto); }
  function tecla(ev: KeyboardEvent<HTMLTextAreaElement>) {
    if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); enviar(texto); }
  }
  function digitar(v: string) { setTexto(v); if (!esperando) setRobo(v ? "ouvindo" : "repouso"); }
  function nova() { setAtual(null); setRobo("repouso"); campo.current?.focus(); }

  return (
    <div className="d-ia">
      <header className="d-ia-topo">
        <div className="d-ia-nome"><Robo estado={robo} tamanho={30} /><h1>{NOME_IA}</h1></div>
        <div className="d-ia-topo-acoes">
          <div className="d-hist" ref={caixaHist}>
            <button type="button" className="k-btn k-btn--contorno k-btn--sm" aria-haspopup="menu" aria-expanded={historico} onClick={() => setHistorico(!historico)} disabled={!antigas.length}>
              Histórico{antigas.length > 0 && <span className="d-conta">{antigas.length}</span>}
            </button>
            {historico && (
              <ul className="d-hist-lista" role="menu">
                {antigas.map((c) => (
                  <li key={c.id}>
                    <button type="button" role="menuitem" aria-current={c.id === atual || undefined} onClick={() => { setAtual(c.id); setHistorico(false); }}>
                      <span>{c.titulo}</span><small className="k-mono">{dataCurta(c.criada_em)}</small>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <button type="button" className="k-btn k-btn--sm" onClick={nova} disabled={!mensagens.length}>Nova conversa</button>
        </div>
      </header>

      <div className="d-ia-rolagem">
        <div className="d-ia-coluna">
          {mensagens.length === 0 ? (
            <div className="d-ia-vazio">
              <Robo estado={robo} tamanho={104} rotulo={NOME_IA} />
              <h2>Pergunte sobre as suas normas<span className="d-ponto-final">.</span></h2>
              <p className="d-apoio">Toda resposta mostra a fonte.</p>
              <div className="d-sugestoes">
                {PERGUNTAS_SUGERIDAS.map((p) => <button key={p} type="button" className="d-sugestao" onClick={() => enviar(p)}>{p}</button>)}
              </div>
            </div>
          ) : (
            <ol className="d-mensagens">
              {mensagens.map((m) => <MensagemChat key={m.id} m={m} />)}
              {esperando && (
                <li className="d-msg d-msg--ia">
                  <Robo estado="pensando" tamanho={28} />
                  <div className="d-msg-corpo"><p className="d-msg-pensando">Lendo os atos e a matriz<span>.</span><span>.</span><span>.</span></p></div>
                </li>
              )}
            </ol>
          )}
          <div ref={fim} />
        </div>
      </div>

      <form className="d-ia-entrada" onSubmit={submeter}>
        <div className="d-ia-campo">
          <label className="sr" htmlFor="pergunta">Sua pergunta</label>
          <textarea id="pergunta" ref={campo} rows={1} value={texto} maxLength={PROMPT_MAX} placeholder="Pergunte sobre prazos, obrigações ou um ato do DOU…"
            onChange={(ev) => digitar(ev.target.value)} onKeyDown={tecla} onBlur={() => !texto && !esperando && setRobo("repouso")} autoFocus />
          <button className="d-ia-enviar" type="submit" disabled={!texto.trim() || esperando} aria-label="Enviar pergunta">
            <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 15.5v-11M5.5 9 10 4.5 14.5 9" /></svg>
          </button>
        </div>
      </form>
    </div>
  );
}

function MensagemChat({ m }: { m: Mensagem }) {
  if (m.de === "pessoa") return <li className="d-msg d-msg--pessoa"><p>{m.texto}</p></li>;
  const blocos = m.blocos ?? [];
  return (
    <li className="d-msg d-msg--ia" data-erro={m.erro || undefined}>
      <Robo estado={blocos.length ? "repouso" : "nao-sei"} tamanho={28} />
      <div className="d-msg-corpo">
        <p className="d-msg-texto">{m.texto}</p>
        {blocos.map((b, i) => <BlocoChat key={i} b={b} />)}
        <div className="d-msg-rodape">
          {!m.erro && <Fontes blocos={blocos} />}
          {m.ms !== undefined && <span className="d-msg-tempo k-mono" title="Da pergunta até a resposta: rede, Lambda e agente">{(m.ms / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1, minimumFractionDigits: 1 })} s</span>}
        </div>
      </div>
    </li>
  );
}

// ─────────────────────────── blocos (contrato do chatbot) ───────────────────────────

function BlocoChat({ b }: { b: Bloco }) {
  const { abrir } = useObrigacao();
  switch (b.tipo) {
    case "tarefas":
      return (
        <ul className="d-bloco d-bloco-tarefas">
          {b.itens.map((t, i) => (
            <li key={i} data-risco={t.em_risco || undefined}>
              <b className="k-mono">{t.vencimento ? dataCurta(t.vencimento) : "—"}</b>
              <span>{t.descricao}<small>{[t.area_responsavel, t.vencimento && relativo(t.vencimento), t.status && STATUS_TAREFA[t.status as keyof typeof STATUS_TAREFA]].filter(Boolean).join(" · ")}</small></span>
            </li>
          ))}
        </ul>
      );
    case "linha_do_tempo":
      return (
        <div className="d-bloco d-bloco-eventos">
          {b.itens.map((ev, i) => (
            <article key={i} className="d-evento-mini">
              <p className="d-rotulo">{ev.obrigacao_id} · v{ev.versao} · {ROTULO_EVENTO[ev.evento ?? ""] ?? ev.evento} · {dataBr(ev.ocorrido_em)}</p>
              {ev.alteracoes && ev.alteracoes.some((a) => a.campo === "prazo_regra")
                ? <Diff alteracoes={ev.alteracoes.filter((a) => a.campo === "prazo_regra")} />
                : <p className="d-evento-mini-titulo">{ev.titulo}</p>}
            </article>
          ))}
        </div>
      );
    case "atos":
      return (
        <ul className="d-bloco d-bloco-atos">
          {b.itens.map((a, i) => {
            const link = linkSeguro(a.url_pdf);
            return (
              <li key={i}>
                <p className="d-rotulo">{dataBr(a.data_publicacao)} · {a.orgao}</p>
                <p>{link ? <a href={link} target="_blank" rel="noreferrer">{a.identifica} ↗</a> : a.identifica}</p>
              </li>
            );
          })}
        </ul>
      );
    case "obrigacoes":
    case "versoes":
      return (
        <ul className="d-bloco d-bloco-atos">
          {b.itens.map((o, i) => (
            <li key={i}>
              <button type="button" className="d-bloco-abrir" onClick={() => o.obrigacao_id && abrir(o.obrigacao_id)}>
                <span className="d-rotulo">{o.obrigacao_id} · v{o.versao} · {o.status}</span>
                <span>{o.prazo_regra ?? o.titulo} <Criticidade valor={o.criticidade} /></span>
              </button>
            </li>
          ))}
        </ul>
      );
    case "empresa":
      return (
        <ul className="d-bloco d-bloco-atos">
          {b.itens.map((x, i) => <li key={i}><p>{x.razao_social}</p><p className="d-rotulo">{x.situacao_cadastral} · {x.atos_no_dou ?? 0} atos no DOU</p></li>)}
        </ul>
      );
    default:
      return null;
  }
}

/** As fontes da resposta, recolhidas: aparecem só depois que a IA respondeu e só quando ela citou algo. */
function Fontes({ blocos }: { blocos: Bloco[] }) {
  const e = useLoja();
  const itens = useMemo(() => {
    const out: { titulo: string; meta: string; trecho?: string | null; url?: string | null }[] = [];
    for (const b of blocos) {
      if (b.tipo === "atos") b.itens.forEach((a) => out.push({ titulo: a.identifica ?? "Ato", meta: `${a.orgao} · DOU ${dataBr(a.data_publicacao)}`, url: a.url_pdf }));
      if (b.tipo === "linha_do_tempo") b.itens.forEach((ev) => {
        const o = e.obrigacoes.find((x) => x.obrigacao_id === ev.obrigacao_id && x.versao === ev.versao);
        out.push({ titulo: o?.fonte_ato ?? ev.ato_id ?? "Ato", meta: [o?.fonte_dispositivo, ev.data_ato && `DOU ${dataBr(ev.data_ato)}`].filter(Boolean).join(" · "), trecho: ev.trecho_citado, url: o?.fonte_url });
      });
      if (b.tipo === "versoes") b.itens.filter((v) => v.fonte_ato).forEach((v) => {
        const o = e.obrigacoes.find((x) => x.obrigacao_id === v.obrigacao_id && x.versao === v.versao) ?? e.versoesAntigas.find((x) => x.obrigacao_id === v.obrigacao_id && x.versao === v.versao);
        out.push({ titulo: `${v.fonte_ato}`, meta: [v.fonte_dispositivo, v.data_ato && `DOU ${dataBr(v.data_ato)}`].filter(Boolean).join(" · "), trecho: v.trecho_citado, url: o?.fonte_url });
      });
      if (b.tipo === "tarefas") [...new Set(b.itens.map((t) => t.obrigacao_id))].forEach((id) => {
        const o = e.obrigacoes.find((x) => x.obrigacao_id === id && x.vigente);
        if (o) out.push({ titulo: `${id} · ${o.titulo}`, meta: [o.fonte_ato, o.fonte_dispositivo].filter(Boolean).join(" · "), trecho: o.trecho_citado, url: o.fonte_url });
      });
    }
    const vistos = new Set<string>();
    return out.filter((f) => { const k = `${f.titulo}|${f.trecho ?? ""}`; if (vistos.has(k)) return false; vistos.add(k); return true; });
  }, [blocos, e]);
  if (!blocos.length) return <p className="d-msg-semfonte">Sem fonte para esta resposta.</p>;
  if (!itens.length) return null;
  return (
    <details className="d-fontes">
      <summary>{itens.length} {itens.length === 1 ? "fonte" : "fontes"}</summary>
      <ul>
        {itens.map((f) => (
          <li key={`${f.titulo}|${f.trecho ?? ""}`}>
            <p className="d-fontes-titulo">{f.titulo}</p>
            {f.meta && <p className="d-rotulo">{f.meta}</p>}
            {f.trecho ? <Citacao texto={f.trecho} url={f.url} /> : linkSeguro(f.url) && <a className="d-link" href={linkSeguro(f.url)!} target="_blank" rel="noreferrer">ver no DOU ↗</a>}
          </li>
        ))}
      </ul>
    </details>
  );
}
