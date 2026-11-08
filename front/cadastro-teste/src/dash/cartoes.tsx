/**
 * Peças comuns do dash: as mesmas na Hoje, nas listas e nas respostas da IA.
 * O cartão da proposta é o "cartão da tarefa" da landing, agora com decisão.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import type { Alteracao, Obrigacao, StatusTarefa } from "../matriz";
import { acoes, diasAte, perguntaSobre, semana, type Alerta, type TarefaDash } from "./dados";
import { Robo } from "./Robo";

// ─────────────────────────── formatos ───────────────────────────

const MINUSCULAS = new Set(["de", "da", "do", "das", "dos", "e"]);
/** "LIGHT SERVICOS DE ELETRICIDADE S.A." → "Light Servicos de Eletricidade S.A." */
export const nomeProprio = (s: string) => s.toLowerCase().split(/\s+/).map((p, i) =>
  /^s\.?a\.?$|^ltda\.?$/.test(p) ? p.toUpperCase() : i > 0 && MINUSCULAS.has(p) ? p : p.charAt(0).toUpperCase() + p.slice(1))
  .join(" ").replace(/ S A$/, " S.A.");

export const dataBr =(iso: string | null | undefined) => (iso ? iso.slice(0, 10).split("-").reverse().join("/") : "—");
export const dataCurta = (iso: string) => dataBr(iso).slice(0, 5);
const SEMANA = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];
export const diaSemana = (iso: string) => SEMANA[new Date(`${iso}T12:00:00`).getDay()];

export function relativo(iso: string) {
  const d = diasAte(iso);
  if (d === 0) return "hoje";
  if (d === 1) return "amanhã";
  if (d === -1) return "venceu ontem";
  if (d < 0) return `venceu há ${-d} dias`;
  if (d < 60) return `em ${d} dias`;
  return dataBr(iso);
}

export const CAMPO: Record<string, string> = {
  prazo_regra: "Prazo", prazo_json: "Regra de prazo", titulo: "Título", periodicidade: "Periodicidade", recorrencia: "Recorrência",
  area_responsavel: "Área", aplica_a: "Aplica a", criticidade: "Criticidade", evidencia: "Evidência", trecho_citado: "Trecho",
  fonte_ato: "Ato", fonte_dispositivo: "Dispositivo", fonte_url: "Link do ato", orgao_sigla: "Órgão", tema: "Tema",
};
export const STATUS_TAREFA: Record<StatusTarefa, string> = { aberta: "Aberta", em_andamento: "Em andamento", concluida: "Concluída" };
export const RECORRENCIA: Record<string, string> = { periodica: "Periódica", por_evento: "Por evento", continua: "Contínua" };

export const alertaDaUrl = (url: string | null) => (url ? semana.alertas.find((a) => a.url === url) : undefined);
export const linkSeguro = (url: string | null | undefined) => (url && /^https?:\/\//i.test(url) ? url : null);

/** "REN ANEEL Nº 1.174/2026 · DOU 04/11/2026 · P. 68" */
export function linhaDoAto(o: Pick<Obrigacao, "fonte_ato" | "fonte_dispositivo" | "data_ato" | "fonte_url">, a?: Alerta) {
  return [o.fonte_ato, o.fonte_dispositivo, o.data_ato && `DOU ${dataBr(o.data_ato)}`, a?.pagina && `p. ${a.pagina}`].filter(Boolean).join(" · ");
}

// ─────────────────────────── peças pequenas ───────────────────────────

export function Criticidade({ valor }: { valor: string | null | undefined }) {
  if (!valor) return null;
  return <span className="d-crit" data-nivel={valor}>{valor === "media" ? "média" : valor}</span>;
}

export function Selo({ tipo, children }: { tipo: "proposta" | "aprovada" | "rejeitada" | "risco" | "neutro"; children: ReactNode }) {
  return <span className="d-selo" data-tipo={tipo}>{children}</span>;
}

/** Citação literal, com o prazo grifado (a primeira ocorrência de "N dias/meses/anos"). */
export function Citacao({ texto, fonte, url }: { texto: string; fonte?: string; url?: string | null }) {
  const m = texto.match(/(até )?\d+ (\(.*?\) )?(dias úteis|dias|meses|anos)/i);
  const partes = m && m.index !== undefined ? [texto.slice(0, m.index), m[0], texto.slice(m.index + m[0].length)] : [texto];
  const link = linkSeguro(url);
  return (
    <blockquote className="d-citacao">
      <p>“{partes[0]}{partes[1] && <mark className="k-grifo">{partes[1]}</mark>}{partes[2]}”</p>
      {(fonte || link) && (
        <cite>{fonte}{fonte && link && " · "}{link && <a href={link} target="_blank" rel="noreferrer">ver no DOU ↗</a>}</cite>
      )}
    </blockquote>
  );
}

const fmt = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : Array.isArray(v) ? v.join(", ") : String(v));

/** O antes e o depois de cada campo alterado. */
export function Diff({ alteracoes }: { alteracoes: Pick<Alteracao, "campo" | "antes" | "depois">[] }) {
  if (!alteracoes.length) return null;
  return (
    <dl className="d-diff">
      {alteracoes.map((a) => (
        <div key={a.campo} className="d-diff-linha">
          <dt>{CAMPO[a.campo] ?? a.campo}</dt>
          <dd><s>{fmt(a.antes)}</s><span className="d-diff-seta" aria-label="passa a ser">→</span><b>{fmt(a.depois)}</b></dd>
        </div>
      ))}
    </dl>
  );
}

export function usePerguntar() {
  const ir = useNavigate();
  return (texto: string) => ir(`/painel/ia?p=${encodeURIComponent(texto)}`);
}

export function BotaoIa({ pergunta, children = "Perguntar à IA" }: { pergunta: string; children?: ReactNode }) {
  const perguntar = usePerguntar();
  return (
    <button type="button" className="d-btn-ia" onClick={() => perguntar(pergunta)}>
      <Robo tamanho={20} />
      {children}
    </button>
  );
}

/** Filtro compacto (select nativo): "Área: Todas ▾". */
export function Seletor({ rotulo, valor, opcoes, onChange }: {
  rotulo: string; valor: string; opcoes: [string, string][]; onChange: (v: string) => void;
}) {
  return (
    <label className="d-select">
      <span>{rotulo}</span>
      <select value={valor} onChange={(ev) => onChange(ev.target.value)}>
        {opcoes.map(([v, r]) => <option key={v} value={v}>{r}</option>)}
      </select>
    </label>
  );
}

/** Cabeçalho de página: título curto e, à direita, o que a página precisar (filtro, contagem). */
export function Topo({ titulo, children }: { titulo: string; children?: ReactNode }) {
  return (
    <header className="d-topo">
      <h1>{titulo}</h1>
      {children && <div className="d-topo-lado">{children}</div>}
    </header>
  );
}

/** Gaveta à direita (dialog nativo): detalhe sem sair da tela. */
export function Gaveta({ aberta, titulo, rotulo, onFechar, children }: {
  aberta: boolean; titulo: string; rotulo?: string; onFechar: () => void; children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (aberta && !d.open) d.showModal();
    if (!aberta && d.open) d.close();
  }, [aberta]);
  return (
    <dialog ref={ref} className="d-gaveta" aria-label={titulo} onClose={onFechar}
      onClick={(ev) => { if (ev.target === ref.current) onFechar(); }}>
      {aberta && (
        <div className="d-gaveta-corpo">
          <header className="d-gaveta-topo">
            <div>{rotulo && <p className="d-rotulo">{rotulo}</p>}<h2>{titulo}</h2></div>
            <button type="button" className="d-icone-btn" aria-label="Fechar" onClick={onFechar}>
              <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 5l10 10M15 5L5 15" /></svg>
            </button>
          </header>
          {children}
        </div>
      )}
    </dialog>
  );
}

/** "Até 10 dias úteis do recebimento…" → "10 dias úteis" */
export const prazoCurto = (regra: string | null | undefined) =>
  regra?.match(/\d+ (\(.*?\) )?(dias úteis|dias|meses|anos)/i)?.[0].replace(/ \(.*?\)/, "") ?? (regra ? regra.split(/[,(]/)[0] : "—");

/** Linha compacta de proposta (Visão geral): tipo, título, ato, prazo e a decisão. O resto abre na gaveta. */
export function LinhaProposta({ o, anterior, leitura, onAbrir }: { o: Obrigacao; anterior?: Obrigacao; leitura?: boolean; onAbrir: () => void }) {
  const [enviando, setEnviando] = useState<"aprovar" | "rejeitar" | null>(null);
  const alteracao = o.mudanca === "alteracao";
  const decidir = async (d: "aprovar" | "rejeitar") => { setEnviando(d); if (!(await acoes.decidir(o.obrigacao_id, o.versao, d))) setEnviando(null); };
  return (
    <li className="d-prop" aria-busy={!!enviando || undefined}>
      <button type="button" className="d-prop-abrir" onClick={onAbrir}>
        <span className="d-prop-tipo" data-tipo={alteracao ? "alteracao" : "nova"}>{alteracao ? "Alteração" : "Nova"}</span>
        <span className="d-prop-titulo">{o.titulo}<small>{[o.fonte_ato, o.area_responsavel].filter(Boolean).join(" · ")}</small></span>
        <span className="d-prop-prazo k-mono">
          {alteracao && anterior ? <><s>{prazoCurto(anterior.prazo_regra)}</s> → <b>{prazoCurto(o.prazo_regra)}</b></> : prazoCurto(o.prazo_regra)}
        </span>
      </button>
      {!leitura && (
        <span className="d-prop-acoes">
          <button type="button" className="d-prop-sim" disabled={!!enviando} onClick={() => decidir("aprovar")} aria-label={`Aprovar: ${o.titulo}`} title="Aprovar">
            <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4.5 10.5l3.5 3.5 7.5-8" /></svg>
          </button>
          <button type="button" className="d-prop-nao" disabled={!!enviando} onClick={() => decidir("rejeitar")} aria-label={`Rejeitar: ${o.titulo}`} title="Rejeitar">
            <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5.5 5.5l9 9M14.5 5.5l-9 9" /></svg>
          </button>
        </span>
      )}
    </li>
  );
}

// ─────────────────────────── cartão da proposta ───────────────────────────

export function CartaoProposta({ o, anterior, alteracoes, leitura }: {
  o: Obrigacao; anterior?: Obrigacao; alteracoes?: Alteracao[]; leitura?: boolean;
}) {
  const [enviando, setEnviando] = useState<"aprovar" | "rejeitar" | null>(null);
  const a = alertaDaUrl(o.fonte_url);
  const decidir = async (d: "aprovar" | "rejeitar") => { setEnviando(d); if (!(await acoes.decidir(o.obrigacao_id, o.versao, d))) setEnviando(null); };
  const alteracao = o.mudanca === "alteracao";
  return (
    <article className="d-cartao d-proposta" aria-busy={!!enviando || undefined}>
      <header className="d-proposta-topo">
        <span className="d-rotulo">{linhaDoAto(o, a)}</span>
        <Selo tipo="proposta">{alteracao ? `Alteração · v${anterior?.versao ?? o.versao - 1} → v${o.versao}` : "Nova obrigação"}</Selo>
      </header>
      <h3 className="d-proposta-titulo">{o.titulo}</h3>
      {alteracao && alteracoes && <Diff alteracoes={alteracoes.filter((x) => x.campo === "prazo_regra")} />}
      <dl className="d-dados">
        {!alteracao && <div><dt>Prazo</dt><dd className="d-prazo">{o.prazo_regra ?? "—"}</dd></div>}
        <div><dt>Área</dt><dd>{o.area_responsavel ?? "—"}</dd></div>
        <div><dt>Evidência</dt><dd>{o.evidencia ?? "—"}</dd></div>
        <div><dt>Criticidade</dt><dd><Criticidade valor={o.criticidade} /></dd></div>
      </dl>
      {o.trecho_citado && <Citacao texto={o.trecho_citado} fonte={o.fonte_dispositivo ?? undefined} url={o.fonte_url} />}
      <footer className="d-proposta-acoes">
        {leitura ? <span className="d-nota">Quem decide é quem criou a conta.</span> : (
          <>
            <button className="k-btn k-btn--sm" type="button" disabled={!!enviando} onClick={() => decidir("aprovar")}>
              {enviando === "aprovar" ? "Aprovando…" : "Aprovar"}
            </button>
            <button className="k-btn k-btn--contorno k-btn--sm" type="button" disabled={!!enviando} onClick={() => decidir("rejeitar")}>
              {enviando === "rejeitar" ? "Rejeitando…" : "Rejeitar"}
            </button>
          </>
        )}
        <BotaoIa pergunta={perguntaSobre(o.obrigacao_id, alteracao)} />
      </footer>
    </article>
  );
}

// ─────────────────────────── linha da tarefa ───────────────────────────

export function LinhaTarefa({ t, leitura, mostrarArea = true }: { t: TarefaDash; leitura?: boolean; mostrarArea?: boolean }) {
  const d = diasAte(t.vencimento);
  const estado = t.status === "concluida" ? "feita" : d < 0 ? "atrasada" : t.em_risco ? "risco" : "ok";
  return (
    <li className="d-tarefa" data-estado={estado}>
      <div className="d-tarefa-data">
        <b className="k-mono">{dataCurta(t.vencimento)}</b>
        <span>{t.status === "concluida" ? "feita" : relativo(t.vencimento)}</span>
      </div>
      <div className="d-tarefa-corpo">
        <p className="d-tarefa-desc">{t.descricao}</p>
        <p className="d-tarefa-meta">
          <span className="k-mono">{t.obrigacao_id}{t.obrigacao_versao > 1 && ` · v${t.obrigacao_versao}`}</span>
          {mostrarArea && t.area_responsavel && <span>{t.area_responsavel}</span>}
          {t.nota && <span className="d-tarefa-nota">{t.nota}</span>}
        </p>
      </div>
      {leitura ? <span className="d-tarefa-status">{STATUS_TAREFA[t.status]}</span> : (
        <label className="d-tarefa-status">
          <span className="sr">Status de {t.descricao}</span>
          <select value={t.status} onChange={(e) => acoes.mudarTarefa(t.tarefa_id, e.target.value as StatusTarefa)}>
            {Object.entries(STATUS_TAREFA).map(([v, r]) => <option key={v} value={v}>{r}</option>)}
          </select>
        </label>
      )}
    </li>
  );
}

export function Vazio({ children }: { children: ReactNode }) {
  return <p className="d-vazio">{children}</p>;
}
