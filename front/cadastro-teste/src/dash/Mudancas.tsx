/**
 * Mudanças: o "replay". O que cada ato mudou na matriz, campo a campo (GET /linha-do-tempo).
 * Agrupado por ato; a inclusão pela planilha fica recolhida.
 */
import { useState } from "react";
import { useObrigacao } from "./DetalheObrigacao";
import type { Historico } from "../matriz";
import { BotaoIa, Citacao, Diff, Selo, Topo, Vazio, alertaDaUrl, dataBr, linkSeguro } from "./cartoes";
import { perguntaSobre, useLoja } from "./dados";
import { ROTULO_EVENTO } from "./Hoje";

type Filtro = "todas" | "propostas" | "decididas" | "planilha";

export function Mudancas() {
  const e = useLoja();
  const { abrir } = useObrigacao();
  const [filtro, setFiltro] = useState<Filtro>("todas");
  const doLlm = (h: Historico) => h.origem === "llm" || h.origem === "decisao";
  const eventos = e.historico.filter((h) =>
    filtro === "propostas" ? h.status === "proposta" && propostaAberta(h)
    : filtro === "decididas" ? h.evento === "aprovacao" || h.evento === "rejeicao"
    : filtro === "planilha" ? !doLlm(h) : true);

  // agrupa por ato (os da planilha num grupo só), do mais recente ao mais antigo
  const grupos = new Map<string, Historico[]>();
  for (const h of eventos) {
    const k = h.ato_id ?? "planilha";
    grupos.set(k, [...(grupos.get(k) ?? []), h]);
  }
  const ordenados = [...grupos.entries()].sort((a, b) => (b[1][0].ocorrido_em).localeCompare(a[1][0].ocorrido_em));

  function propostaAberta(h: Historico) {
    return e.obrigacoes.some((o) => o.obrigacao_id === h.obrigacao_id && o.versao === h.versao && o.status === "proposta");
  }

  return (
    <div className="d-pagina d-mudancas">
      <Topo titulo="Mudanças" />

      <div className="d-filtros" role="group" aria-label="Filtrar mudanças">
        {([["todas", "Todas"], ["propostas", "Aguardando decisão"], ["decididas", "Decididas"], ["planilha", "Planilha da matriz"]] as [Filtro, string][]).map(([f, r]) => (
          <button key={f} type="button" className="d-filtro" aria-pressed={filtro === f} onClick={() => setFiltro(f)}>{r}</button>
        ))}
      </div>

      {ordenados.length === 0 && <Vazio>Nenhuma mudança com esse filtro.</Vazio>}
      <ol className="d-linha">
        {ordenados.map(([chave, hs]) => chave === "planilha" ? (
          <li key={chave} className="d-linha-item">
            <span className="d-linha-data k-mono">{dataBr(hs[0].ocorrido_em)}</span>
            <details className="d-cartao d-linha-ato">
              <summary>
                <p className="d-rotulo">Planilha da matriz enviada</p>
                <h2>{hs.length} obrigações incluídas</h2>
              </summary>
              <ul className="d-linha-lista">
                {hs.map((h) => <li key={h.obrigacao_id}><span className="k-mono">{h.obrigacao_id}</span> <button type="button" className="d-link" onClick={() => abrir(h.obrigacao_id)}>{h.titulo}</button></li>)}
              </ul>
            </details>
          </li>
        ) : <GrupoAto key={chave} hs={hs} aberta={propostaAberta} />)}
      </ol>
    </div>
  );
}

function GrupoAto({ hs, aberta }: { hs: Historico[]; aberta: (h: Historico) => boolean }) {
  const e = useLoja();
  const { abrir } = useObrigacao();
  const primeiro = hs[hs.length - 1];
  const o = e.obrigacoes.find((x) => x.obrigacao_id === primeiro.obrigacao_id && x.versao === primeiro.versao);
  const a = alertaDaUrl(primeiro.ato_url);
  const link = linkSeguro(primeiro.ato_url);
  return (
    <li className="d-linha-item">
      <span className="d-linha-data k-mono">{dataBr(hs[0].ocorrido_em)}</span>
      <article className="d-cartao d-linha-ato">
        <header>
          <p className="d-rotulo">{[a?.orgao, primeiro.data_ato && `DOU ${dataBr(primeiro.data_ato)}`, a?.pagina && `p. ${a.pagina}`].filter(Boolean).join(" · ")}</p>
          <h2>{o?.fonte_ato ?? a?.identifica ?? "Ato do DOU"}{link && <a className="d-link d-linha-dou" href={link} target="_blank" rel="noreferrer">ver no DOU ↗</a>}</h2>
        </header>
        {hs.map((h, i) => (
          <section key={i} className="d-linha-evento" data-evento={h.evento}>
            <p className="d-linha-evento-topo">
              <Selo tipo={h.evento === "aprovacao" ? "aprovada" : h.evento === "rejeicao" ? "rejeitada" : aberta(h) ? "proposta" : "neutro"}>
                {ROTULO_EVENTO[h.evento]}{h.evento === "inclusao" || h.evento === "alteracao" ? (aberta(h) ? " proposta" : "") : ""}
              </Selo>
              <span className="k-mono d-nota">{h.obrigacao_id} · v{h.versao}</span>
              {h.por && <span className="d-nota">por {h.por.split("@")[0]}</span>}
            </p>
            <button type="button" className="d-linha-evento-titulo" onClick={() => abrir(h.obrigacao_id)}>{h.titulo} <span aria-hidden="true">→</span></button>
            <Diff alteracoes={h.alteracoes.filter((a) => a.campo === "prazo_regra")} />
            {h.trecho_citado && (h.evento === "inclusao" || h.evento === "alteracao") && (
              <details className="d-trecho"><summary>Trecho do ato</summary><Citacao texto={h.trecho_citado} /></details>
            )}
          </section>
        ))}
        <footer><BotaoIa pergunta={perguntaSobre(primeiro.obrigacao_id, primeiro.evento === "alteracao")} /></footer>
      </article>
    </li>
  );
}
