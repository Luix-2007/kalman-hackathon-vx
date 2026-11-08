/**
 * Obrigações: a matriz numa tabela limpa (uma linha por obrigação). O clique abre a obrigação em tela quase cheia
 * (DetalheObrigacao, ?obrigacao=). "Em [data]" mostra a matriz como estava naquele dia (GET /obrigacoes?em=).
 */
import { useEffect, useState } from "react";
import type { Obrigacao } from "../matriz";
import type { Contexto } from "./Dash";
import { useObrigacao } from "./DetalheObrigacao";
import { Criticidade, RECORRENCIA, Seletor, Topo, Vazio, dataBr, prazoCurto } from "./cartoes";
import { HOJE, acoes, areasDe, propostasDe, useLoja, vigentesDe } from "./dados";

type Filtro = "todas" | "vigentes" | "propostas";

export function Obrigacoes(_props: { ctx: Contexto }) {
  const e = useLoja();
  const { abrir } = useObrigacao();
  const [busca, setBusca] = useState("");
  const [area, setArea] = useState("");
  const [filtro, setFiltro] = useState<Filtro>("todas");
  const [dia, setDia] = useState(HOJE);
  const passado = dia < HOJE;
  // "Em [data]": a matriz como estava naquele dia (GET /obrigacoes?em=)
  const [doDia, setDoDia] = useState<Obrigacao[] | null>(null);
  useEffect(() => {
    if (!passado) { setDoDia(null); return; }
    let vivo = true;
    acoes.matrizEm(dia).then((l) => { if (vivo) setDoDia(l); }).catch(() => { if (vivo) setDoDia([]); });
    return () => { vivo = false; };
  }, [dia, passado]);

  const vigentes = vigentesDe(e);
  const comProposta = new Map(propostasDe(e).map((p) => [p.obrigacao_id, p]));
  const novas = propostasDe(e).filter((p) => !vigentes.some((v) => v.obrigacao_id === p.obrigacao_id));
  const base: Obrigacao[] = passado ? doDia ?? []
    : filtro === "vigentes" ? vigentes : filtro === "propostas" ? propostasDe(e) : [...novas, ...vigentes];
  const lista = base
    .filter((o) => (!area || o.area_responsavel === area) && (!busca || `${o.obrigacao_id} ${o.titulo} ${o.fonte_ato ?? ""}`.toLowerCase().includes(busca.toLowerCase())))
    .sort((a, b) => Number(comProposta.has(b.obrigacao_id)) - Number(comProposta.has(a.obrigacao_id)) || a.obrigacao_id.localeCompare(b.obrigacao_id));

  return (
    <div className="d-pagina">
      <Topo titulo="Obrigações">
        <span className="d-topo-data k-mono">{vigentes.length} vigentes · {propostasDe(e).length} propostas</span>
      </Topo>

      <div className="d-ferramentas">
        <label className="d-busca">
          <span className="sr">Buscar</span>
          <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="9" cy="9" r="5.5" /><path d="M13 13l4 4" /></svg>
          <input type="search" placeholder="Buscar" value={busca} onChange={(ev) => setBusca(ev.target.value)} />
        </label>
        <div className="d-segmento" role="group" aria-label="Situação">
          {(["todas", "vigentes", "propostas"] as Filtro[]).map((f) => (
            <button key={f} type="button" aria-pressed={!passado && filtro === f} disabled={passado} onClick={() => setFiltro(f)}>
              {f === "todas" ? "Todas" : f === "vigentes" ? "Vigentes" : "Propostas"}
            </button>
          ))}
        </div>
        <Seletor rotulo="Área" valor={area} onChange={setArea} opcoes={[["", "Todas"], ...areasDe(e).map((a) => [a, a] as [string, string])]} />
        <label className="d-select d-data">
          <span>Em</span>
          <input type="date" value={dia} max={HOJE} onChange={(ev) => setDia(ev.target.value || HOJE)} />
        </label>
      </div>

      {passado && (
        <p className="d-faixa" role="status">
          Matriz em <b className="k-mono">{dataBr(dia)}</b> · {lista.length} em vigor
          <button type="button" className="d-link" onClick={() => setDia(HOJE)}>Voltar para hoje</button>
        </p>
      )}

      <div className="d-caixa d-tabela-caixa">
        {lista.length === 0 ? <Vazio>Nenhuma obrigação com esses filtros.</Vazio> : (
          <table className="d-tabela">
            <thead>
              <tr><th>Obrigação</th><th>Área</th><th>Prazo</th><th>Criticidade</th><th><span className="sr">Situação</span></th></tr>
            </thead>
            <tbody>
              {lista.map((o) => {
                const p = o.status === "proposta" ? o : passado ? undefined : comProposta.get(o.obrigacao_id);
                return (
                  <tr key={`${o.obrigacao_id}-${o.versao}`} data-proposta={!!p || undefined} onClick={() => abrir(o.obrigacao_id)}>
                    <td>
                      <button type="button" className="d-tabela-abrir" onClick={(ev) => { ev.stopPropagation(); abrir(o.obrigacao_id); }}>
                        <span className="k-mono">{o.obrigacao_id}</span>{o.titulo}
                      </button>
                    </td>
                    <td className="d-tabela-area">{o.area_responsavel ?? "—"}</td>
                    <td className="k-mono d-tabela-prazo">{o.prazo_regra ? prazoCurto(o.prazo_regra) : RECORRENCIA[o.recorrencia]}</td>
                    <td><Criticidade valor={o.criticidade} /></td>
                    <td className="d-tabela-sit">{p && <span className="d-pendente">{p.mudanca === "alteracao" ? `v${p.versao} a decidir` : "nova · a decidir"}</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
