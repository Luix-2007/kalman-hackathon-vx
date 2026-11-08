/**
 * Visão geral, para o executivo: as métricas, uma frase sobre a leitura do DOU e, em seguida, o que fazer
 * (decidir propostas e destravar prazos em risco). Filtros de área e período no topo.
 */
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import type { Contexto } from "./Dash";
import { useObrigacao } from "./DetalheObrigacao";
import { Gaveta, LinhaProposta, Seletor, Topo, Vazio, dataCurta, relativo, usePerguntar } from "./cartoes";
import { TEM_LEITURA_DOU, acoes, areasDe, diasAte, propostasDe, semana, todasVersoes, useLoja, vigentesDe, type TarefaDash } from "./dados";
import { Robo } from "./Robo";

const fmtN = (n: number) => n.toLocaleString("pt-BR");
const PERIODOS: [string, string][] = [["7", "7 dias"], ["30", "30 dias"], ["90", "90 dias"]];

export function Hoje({ ctx }: { ctx: Contexto }) {
  const e = useLoja();
  const { abrir } = useObrigacao();
  const [area, setArea] = useState("");
  const [periodo, setPeriodo] = useState("30");
  const [descartes, setDescartes] = useState(false);
  const dias = Number(periodo);
  const areas = areasDe(e);
  const daArea = (a: string | null) => !area || a === area;

  const propostas = propostasDe(e).filter((o) => daArea(o.area_responsavel));
  const tarefas = e.tarefas.filter((t) => daArea(t.area_responsavel));
  const abertas = tarefas.filter((t) => t.status !== "concluida").sort((a, b) => a.vencimento.localeCompare(b.vencimento));
  const atrasadas = abertas.filter((t) => diasAte(t.vencimento) < 0);
  const risco = abertas.filter((t) => t.em_risco);
  const proximas = abertas.filter((t) => !t.em_risco && diasAte(t.vencimento) >= 0 && diasAte(t.vencimento) <= dias);
  const noPeriodo = abertas.filter((t) => diasAte(t.vencimento) >= 0 && diasAte(t.vencimento) <= dias);
  const pct = Math.round(((tarefas.length - atrasadas.length) / Math.max(1, tarefas.length)) * 100);
  const total = semana.dias.reduce((s, d) => s + d.atos, 0);

  return (
    <div className="d-pagina">
      <Topo titulo="Visão geral">
        <Seletor rotulo="Área" valor={area} onChange={setArea} opcoes={[["", "Todas"], ...areas.map((a) => [a, a] as [string, string])]} />
        <Seletor rotulo="Período" valor={periodo} onChange={setPeriodo} opcoes={PERIODOS} />
        <PerguntaRapida />
      </Topo>

      <section className="d-metricas" aria-label="Métricas">
        <Metrica rotulo="Para decidir" valor={propostas.length} nota="propostas da IA" destaque={propostas.length > 0} />
        <Metrica rotulo="Em risco" valor={risco.length} nota={`${atrasadas.length} atrasada${atrasadas.length === 1 ? "" : "s"}`} destaque={risco.length > 0} para="/painel/prazos?risco=1" />
        <Metrica rotulo={`Vencem em ${dias} dias`} valor={noPeriodo.length} nota="tarefas abertas" para="/painel/prazos" />
        <Metrica rotulo="Em dia" valor={pct} sufixo="%" nota={`${tarefas.length - atrasadas.length} de ${tarefas.length} tarefas`} barra={pct} positivo={pct > 60} />
        <Metrica rotulo="Obrigações vigentes" valor={vigentesDe(e).filter((o) => daArea(o.area_responsavel)).length} nota={area || `${areas.length} áreas`} para="/painel/obrigacoes" />
      </section>

      {TEM_LEITURA_DOU ? (
        <p className="d-resumo-dou">
          <Robo tamanho={26} />
          <span>
            DOU de 03 a 06/11: <b className="k-mono">{fmtN(total)}</b> atos lidos, <b className="k-mono">{semana.alertas.length}</b> relevantes
            {propostas.length > 0 && <>, <b className="k-mono d-laranja-txt">{propostas.length}</b> esperam a sua decisão</>}.
          </span>
          <button type="button" className="d-link" onClick={() => setDescartes(true)}>Descartes</button>
        </p>
      ) : propostas.length > 0 && (
        <p className="d-resumo-dou">
          <Robo tamanho={26} />
          <span>A IA leu o DOU e propôs <b className="k-mono d-laranja-txt">{propostas.length}</b> {propostas.length === 1 ? "mudança" : "mudanças"} na sua matriz.</span>
        </p>
      )}

      <div className="d-painel-hoje">
        <section className="d-caixa d-fazer" aria-labelledby="t-fazer">
          <header className="d-caixa-topo"><h2 id="t-fazer">O que fazer</h2></header>

          <div className="d-fazer-grupo">
            <h3>Decidir<span className="d-conta">{propostas.length}</span></h3>
            {propostas.length === 0 ? <Vazio>Nada para decidir.</Vazio> : (
              <ul className="d-props">
                {propostas.map((o) => (
                  <LinhaProposta key={`${o.obrigacao_id}-${o.versao}`} o={o} leitura={ctx.leitura}
                    anterior={todasVersoes(e, o.obrigacao_id).find((v) => v.vigente)} onAbrir={() => abrir(o.obrigacao_id)} />
                ))}
              </ul>
            )}
          </div>

          <div className="d-fazer-grupo">
            <h3>Destravar prazos<span className="d-conta">{risco.length}</span></h3>
            {risco.length === 0 ? <Vazio>Nenhum prazo em risco.</Vazio> : (
              <ul className="d-riscos">{risco.map((t) => <LinhaRisco key={t.tarefa_id} t={t} leitura={ctx.leitura} onAbrir={() => abrir(t.obrigacao_id)} />)}</ul>
            )}
          </div>
        </section>

        <aside className="d-caixa d-agenda-lado" aria-labelledby="t-agenda">
          <header className="d-caixa-topo"><h2 id="t-agenda">Agenda · {dias} dias</h2><Link className="d-link" to="/painel/prazos">Prazos</Link></header>
          {proximas.length === 0 ? <Vazio>Sem outros prazos no período.</Vazio> : (
            <ol className="d-agenda-lista">
              {proximas.slice(0, 6).map((t) => (
                <li key={t.tarefa_id}>
                  <b className="k-mono">{dataCurta(t.vencimento)}</b>
                  <span>{t.descricao}<small>{t.area_responsavel} · {relativo(t.vencimento)}</small></span>
                </li>
              ))}
            </ol>
          )}
          <div className="d-agenda-areas">
            <p className="d-rotulo">Abertas por área</p>
            <PorArea tarefas={e.tarefas} areas={areas} destacar={area} />
          </div>
        </aside>
      </div>

      <Gaveta aberta={descartes} titulo="Descartes da semana" rotulo={`${fmtN(semana.descartes.total)} atos · amostra de ${semana.descartes.amostra.length}`} onFechar={() => setDescartes(false)}>
        <ListaDescartes />
      </Gaveta>
    </div>
  );
}

// ─────────────────────────── peças ───────────────────────────

function Metrica({ rotulo, valor, sufixo, nota, destaque, positivo, barra, para }: {
  rotulo: string; valor: number; sufixo?: string; nota: string; destaque?: boolean; positivo?: boolean; barra?: number; para?: string;
}) {
  const corpo = (
    <>
      <span className="d-metrica-rotulo">{rotulo}</span>
      <b className="d-metrica-valor k-mono">{valor}{sufixo && <small>{sufixo}</small>}</b>
      {barra !== undefined && <span className="d-metrica-barra" aria-hidden="true"><i style={{ width: `${barra}%` }} /></span>}
      <span className="d-metrica-nota">{nota}</span>
    </>
  );
  return para
    ? <Link to={para} className="d-metrica" data-destaque={destaque || undefined} data-positivo={positivo || undefined}>{corpo}</Link>
    : <div className="d-metrica" data-destaque={destaque || undefined} data-positivo={positivo || undefined}>{corpo}</div>;
}

function LinhaRisco({ t, leitura, onAbrir }: { t: TarefaDash; leitura?: boolean; onAbrir: () => void }) {
  const atrasada = diasAte(t.vencimento) < 0;
  return (
    <li className="d-risco">
      <button type="button" className="d-risco-abrir" onClick={onAbrir}>
        <span className="d-risco-data k-mono" data-atrasada={atrasada || undefined}>{dataCurta(t.vencimento)}<small>{relativo(t.vencimento)}</small></span>
        <span className="d-prop-titulo">{t.descricao}<small>{t.obrigacao_id} · {t.area_responsavel}{t.nota ? ` · ${t.nota}` : ""}</small></span>
      </button>
      {!leitura && (
        <button type="button" className="d-btn-concluir" onClick={() => acoes.mudarTarefa(t.tarefa_id, "concluida")} aria-label={`Concluir: ${t.descricao}`}>
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4.5 10.5l3.5 3.5 7.5-8" /></svg>Concluir
        </button>
      )}
    </li>
  );
}

function PorArea({ tarefas, areas, destacar }: { tarefas: TarefaDash[]; areas: string[]; destacar: string }) {
  const linhas = areas.map((a) => {
    const ts = tarefas.filter((t) => t.area_responsavel === a && t.status !== "concluida");
    return { area: a, total: ts.length, risco: ts.filter((t) => t.em_risco).length };
  });
  const max = Math.max(1, ...linhas.map((l) => l.total));
  return (
    <ul className="d-areas">
      {linhas.map((l) => (
        <li key={l.area} data-apagada={(destacar && destacar !== l.area) || undefined}>
          <span className="d-areas-nome">{l.area}</span>
          <span className="d-areas-barra" title={`${l.risco} em risco, ${l.total - l.risco} no prazo`}>
            {l.risco > 0 && <i data-cor="risco" style={{ width: `${(l.risco / max) * 100}%` }} />}
            {l.total - l.risco > 0 && <i data-cor="ok" style={{ width: `${((l.total - l.risco) / max) * 100}%` }} />}
          </span>
          <b className="k-mono">{l.total}</b>
        </li>
      ))}
    </ul>
  );
}

function PerguntaRapida() {
  const perguntar = usePerguntar();
  const [texto, setTexto] = useState("");
  const enviar = (ev: FormEvent) => { ev.preventDefault(); if (texto.trim()) perguntar(texto.trim()); };
  return (
    <form className="d-pergunta" onSubmit={enviar} role="search">
      <Robo tamanho={22} estado={texto ? "ouvindo" : "repouso"} />
      <label className="sr" htmlFor="pergunta-rapida">Pergunte à IA do Kalman</label>
      <input id="pergunta-rapida" value={texto} onChange={(ev) => setTexto(ev.target.value)} placeholder="Pergunte à IA" autoComplete="off" />
    </form>
  );
}

function ListaDescartes() {
  const [cat, setCat] = useState<string | null>(null);
  const { categorias, amostra } = semana.descartes;
  const lista = cat ? amostra.filter((d) => d.categoria === cat) : amostra;
  const max = categorias[0][1];
  return (
    <>
      <ul className="d-barras">
        {categorias.map(([nome, n]) => (
          <li key={nome}>
            <button type="button" aria-pressed={cat === nome} onClick={() => setCat(cat === nome ? null : nome)}>
              <span>{nome}</span><span className="d-barras-barra"><i style={{ width: `${Math.max(1.5, (n / max) * 100)}%` }} /></span><b className="k-mono">{fmtN(n)}</b>
            </button>
          </li>
        ))}
      </ul>
      <ul className="d-descartes">
        {lista.map((d) => (
          <li key={d.id}>
            <p className="d-rotulo">{dataCurta(d.data)} · {d.orgao}</p>
            <p className="d-descartes-ato">{d.identifica}</p>
            <p className="d-descartes-motivo">{d.motivo}</p>
          </li>
        ))}
        {lista.length === 0 && <Vazio>Sem exemplos desta categoria na amostra.</Vazio>}
      </ul>
    </>
  );
}

export const ROTULO_EVENTO: Record<string, string> = { inclusao: "inclusão", alteracao: "alteração", revogacao: "revogação", aprovacao: "aprovada", rejeicao: "rejeitada" };
