/**
 * A obrigação em tela quase cheia: abre de qualquer lugar do dash com ?obrigacao=OBR-XXX (sem trocar de página).
 * Ordem de leitura: o que pede decisão → os fatos (prazo, área, fonte…) → o texto da norma → versões e tarefas.
 */
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { Contexto } from "./Dash";
import { BotaoIa, Citacao, Criticidade, Diff, LinhaTarefa, RECORRENCIA, Vazio, alertaDaUrl, dataBr, linkSeguro } from "./cartoes";
import { acoes, perguntaSobre, todasVersoes, useLoja } from "./dados";

/** Abrir e fechar a janela da obrigação mexendo só no parâmetro ?obrigacao= da página atual. */
export function useObrigacao() {
  const [params, setParams] = useSearchParams();
  return {
    id: params.get("obrigacao"),
    abrir: (id: string) => { const n = new URLSearchParams(params); n.set("obrigacao", id); setParams(n); },
    fechar: () => { const n = new URLSearchParams(params); n.delete("obrigacao"); setParams(n, { replace: true }); },
  };
}

export function DetalheObrigacao({ ctx }: { ctx: Contexto }) {
  const { id, fechar } = useObrigacao();
  const ref = useRef<HTMLDialogElement>(null);
  const e = useLoja();
  const versoes = id ? todasVersoes(e, id) : [];
  const aberta = versoes.length > 0;

  // modo real: busca todas as versões (GET /obrigacoes/{id}) ao abrir
  useEffect(() => { if (id) acoes.carregarObrigacao(id); }, [id]);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (aberta && !d.open) d.showModal();
    if (!aberta && d.open) d.close();
  }, [aberta]);

  return (
    <dialog ref={ref} className="d-modal" aria-label={versoes[0]?.titulo ?? "Obrigação"} onClose={fechar}
      onClick={(ev) => { if (ev.target === ref.current) fechar(); }}>
      {aberta && <Conteudo id={id!} ctx={ctx} onFechar={fechar} />}
    </dialog>
  );
}

function Conteudo({ id, ctx, onFechar }: { id: string; ctx: Contexto; onFechar: () => void }) {
  const e = useLoja();
  const versoes = todasVersoes(e, id);
  const vigente = versoes.find((v) => v.vigente);
  const proposta = versoes.find((v) => v.status === "proposta");
  const o = vigente ?? proposta ?? versoes[versoes.length - 1];
  const h = proposta && e.historico.find((x) => x.obrigacao_id === id && x.versao === proposta.versao);
  const tarefas = e.tarefas.filter((t) => t.obrigacao_id === id).sort((a, b) => a.vencimento.localeCompare(b.vencimento));
  const alerta = alertaDaUrl((proposta ?? o).fonte_url);
  const [enviando, setEnviando] = useState<string | null>(null);
  const decidir = async (d: "aprovar" | "rejeitar") => { if (!proposta) return; setEnviando(d); await acoes.decidir(id, proposta.versao, d); setEnviando(null); };
  // os fatos e o texto são da versão em vigor; a proposta tem o próprio quadro (antes → depois)
  const fonte = o.trecho_citado || !proposta ? o : proposta;
  const texto = fonte.trecho_citado;

  return (
    <div className="d-modal-corpo">
      <header className="d-modal-topo">
        <div>
          <p className="d-rotulo">{id} · {o.orgao_sigla} · {o.status === "proposta" ? "proposta" : `v${o.versao} em vigor`}</p>
          <h2>{o.titulo}</h2>
        </div>
        <button type="button" className="d-icone-btn" aria-label="Fechar" onClick={onFechar}>
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 5l10 10M15 5L5 15" /></svg>
        </button>
      </header>

      {proposta && (
        <section className="d-decisao" aria-label="Decisão pendente">
          <div className="d-decisao-txt">
            <p className="d-decisao-titulo">{proposta.mudanca === "alteracao" ? `Nova versão (v${proposta.versao}) proposta pela IA` : "Nova obrigação proposta pela IA"}</p>
            <p className="d-rotulo">{[proposta.fonte_ato, proposta.data_ato && `DOU ${dataBr(proposta.data_ato)}`, alerta?.pagina && `p. ${alerta.pagina}`].filter(Boolean).join(" · ")}</p>
            {h && h.alteracoes.length > 0 && <Diff alteracoes={h.alteracoes.filter((a) => a.campo === "prazo_regra")} />}
          </div>
          {!ctx.leitura && (
            <div className="d-decisao-acoes">
              <button className="k-btn k-btn--sm" type="button" disabled={!!enviando} onClick={() => decidir("aprovar")}>{enviando === "aprovar" ? "Aprovando…" : "Aprovar"}</button>
              <button className="k-btn k-btn--contorno k-btn--sm" type="button" disabled={!!enviando} onClick={() => decidir("rejeitar")}>Rejeitar</button>
            </div>
          )}
        </section>
      )}

      <dl className="d-fatos">
        <div><dt>Prazo</dt><dd className="k-mono">{o.prazo_regra ?? "—"}</dd></div>
        <div><dt>Área</dt><dd>{o.area_responsavel ?? "—"}</dd></div>
        <div><dt>Recorrência</dt><dd>{RECORRENCIA[o.recorrencia]}{o.periodicidade ? ` · ${o.periodicidade}` : ""}</dd></div>
        <div><dt>Criticidade</dt><dd><Criticidade valor={o.criticidade} /></dd></div>
        <div><dt>Fonte</dt><dd>{[o.fonte_ato, o.fonte_dispositivo].filter(Boolean).join(", ") || "Planilha da matriz"}</dd></div>
        <div><dt>Evidência</dt><dd>{o.evidencia ?? "—"}</dd></div>
      </dl>

      <div className="d-modal-colunas">
        <section className="d-modal-bloco">
          <h3>Texto da norma{fonte === proposta && vigente ? " (proposta)" : ""}</h3>
          {texto ? <Citacao texto={texto} fonte={fonte.fonte_dispositivo ?? undefined} url={fonte.fonte_url} />
            : <Vazio>Sem trecho: obrigação vinda da planilha da matriz.</Vazio>}
          {!texto && linkSeguro(fonte.fonte_url) && <a className="d-link" href={linkSeguro(fonte.fonte_url)!} target="_blank" rel="noreferrer">ver no DOU ↗</a>}
          <BotaoIa pergunta={perguntaSobre(id, !!proposta && proposta.mudanca === "alteracao")} />
        </section>
        <div className="d-modal-lado">
          <section className="d-modal-bloco">
            <h3>Versões</h3>
            <ol className="d-versoes">
              {versoes.map((v) => (
                <li key={v.versao} data-status={v.status}>
                  <b className="k-mono">v{v.versao}</b>
                  <span>{v.prazo_regra}<small>{v.status === "proposta" ? "aguardando decisão" : v.status === "rejeitada" ? "rejeitada"
                    : `${v.vigente_de ? `desde ${dataBr(v.vigente_de)}` : ""}${v.vigente_ate ? ` até ${dataBr(v.vigente_ate)}` : ""}`}</small></span>
                </li>
              ))}
            </ol>
          </section>
          <section className="d-modal-bloco">
            <h3>Tarefas</h3>
            {tarefas.length ? <ul className="d-tarefas d-tarefas--compacto">{tarefas.map((t) => <LinhaTarefa key={t.tarefa_id} t={t} leitura mostrarArea={false} />)}</ul>
              : <Vazio>Nascem quando a obrigação é aprovada.</Vazio>}
          </section>
        </div>
      </div>
    </div>
  );
}
