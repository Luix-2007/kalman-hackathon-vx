/**
 * Prazos: as tarefas com data (GET /tarefas), em agenda (padrão) ou no mês. O status muda na própria linha.
 * ?risco=1 abre só as em risco (vindo da Visão geral).
 */
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { Contexto } from "./Dash";
import { LinhaTarefa, Seletor, Topo, Vazio, dataBr } from "./cartoes";
import { HOJE, areasDe, diasAte, useLoja, type TarefaDash } from "./dados";

const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];

export function Prazos({ ctx }: { ctx: Contexto }) {
  const e = useLoja();
  const [params, setParams] = useSearchParams();
  const soRisco = params.get("risco") === "1";
  const [visao, setVisao] = useState<"agenda" | "mes">("agenda");
  const [area, setArea] = useState("");

  const tarefas = e.tarefas
    .filter((t) => (!area || t.area_responsavel === area) && (!soRisco || (t.em_risco && t.status !== "concluida")))
    .sort((a, b) => a.vencimento.localeCompare(b.vencimento));
  const abertas = tarefas.filter((t) => t.status !== "concluida");
  const grupos: [string, TarefaDash[]][] = [
    ["Atrasadas", abertas.filter((t) => diasAte(t.vencimento) < 0)],
    ["Próximos 7 dias", abertas.filter((t) => diasAte(t.vencimento) >= 0 && diasAte(t.vencimento) <= 7)],
    ["Próximos 30 dias", abertas.filter((t) => diasAte(t.vencimento) > 7 && diasAte(t.vencimento) <= 30)],
    ["Depois", abertas.filter((t) => diasAte(t.vencimento) > 30)],
  ];
  const concluidas = tarefas.filter((t) => t.status === "concluida");

  return (
    <div className="d-pagina">
      <Topo titulo="Prazos">
        <span className="d-topo-data k-mono">{abertas.length} abertas</span>
      </Topo>

      <div className="d-ferramentas">
        <div className="d-segmento" role="group" aria-label="Visão">
          <button type="button" aria-pressed={visao === "agenda"} onClick={() => setVisao("agenda")}>Agenda</button>
          <button type="button" aria-pressed={visao === "mes"} onClick={() => setVisao("mes")}>Mês</button>
        </div>
        <Seletor rotulo="Área" valor={area} onChange={setArea} opcoes={[["", "Todas"], ...areasDe(e).map((a) => [a, a] as [string, string])]} />
        <label className="d-alternar">
          <input type="checkbox" checked={soRisco} onChange={() => setParams(soRisco ? {} : { risco: "1" }, { replace: true })} />
          <span className="d-chave" data-ligada={soRisco || undefined} aria-hidden="true"><i /></span>
          Só em risco
        </label>
      </div>

      {visao === "agenda" ? (
        <div className="d-caixa d-agenda">
          {abertas.length === 0 && <Vazio>{soRisco ? "Nenhuma tarefa em risco." : "Nenhuma tarefa aberta."}</Vazio>}
          {grupos.map(([nome, ts]) => ts.length > 0 && (
            <section key={nome} className="d-agenda-grupo" data-grupo={nome === "Atrasadas" ? "atrasadas" : undefined}>
              <h2>{nome}<span className="d-conta">{ts.length}</span></h2>
              <ul className="d-tarefas">{ts.map((t) => <LinhaTarefa key={t.tarefa_id} t={t} leitura={ctx.leitura} />)}</ul>
            </section>
          ))}
          {concluidas.length > 0 && !soRisco && (
            <details className="d-agenda-grupo d-concluidas">
              <summary><h2>Concluídas<span className="d-conta">{concluidas.length}</span></h2></summary>
              <ul className="d-tarefas">{concluidas.map((t) => <LinhaTarefa key={t.tarefa_id} t={t} leitura={ctx.leitura} />)}</ul>
            </details>
          )}
        </div>
      ) : <Mes tarefas={tarefas} ctx={ctx} />}
    </div>
  );
}

function Mes({ tarefas, ctx }: { tarefas: TarefaDash[]; ctx: Contexto }) {
  const hoje = new Date(`${HOJE}T12:00:00`);
  const [ref, setRef] = useState({ ano: hoje.getFullYear(), mes: hoje.getMonth() });
  const [dia, setDia] = useState<string | null>(HOJE);
  const inicio = new Date(ref.ano, ref.mes, 1).getDay(); // domingo = 0
  const nDias = new Date(ref.ano, ref.mes + 1, 0).getDate();
  const isoDe = (d: number) => `${ref.ano}-${String(ref.mes + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  const porDia = new Map<string, TarefaDash[]>();
  tarefas.forEach((t) => porDia.set(t.vencimento, [...(porDia.get(t.vencimento) ?? []), t]));
  const mover = (n: number) => { const d = new Date(ref.ano, ref.mes + n, 1); setRef({ ano: d.getFullYear(), mes: d.getMonth() }); setDia(null); };
  const doDia = dia ? porDia.get(dia) ?? [] : [];
  const celulas = Math.ceil((inicio + nDias) / 7) * 7;

  return (
    <div className="d-mes">
      <div className="d-caixa d-mes-caixa">
        <div className="d-mes-topo">
          <h2>{MESES[ref.mes]} {ref.ano}</h2>
          <div className="d-mes-nav">
            <button type="button" className="d-icone-btn" aria-label="Mês anterior" onClick={() => mover(-1)}><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M12 5l-5 5 5 5" /></svg></button>
            <button type="button" className="d-link" onClick={() => { setRef({ ano: hoje.getFullYear(), mes: hoje.getMonth() }); setDia(HOJE); }}>Hoje</button>
            <button type="button" className="d-icone-btn" aria-label="Próximo mês" onClick={() => mover(1)}><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M8 5l5 5-5 5" /></svg></button>
          </div>
        </div>
        <div className="d-mes-grade" role="grid" aria-label={`${MESES[ref.mes]} de ${ref.ano}`}>
          {["dom", "seg", "ter", "qua", "qui", "sex", "sáb"].map((d) => <span key={d} className="d-mes-semana" role="columnheader">{d}</span>)}
          {Array.from({ length: celulas }, (_, k) => {
            const n = k - inicio + 1;
            if (n < 1 || n > nDias) return <span key={`v${k}`} className="d-mes-vazio" />;
            const iso = isoDe(n);
            const ts = porDia.get(iso) ?? [];
            const fds = k % 7 === 0 || k % 7 === 6;
            return (
              <button key={iso} type="button" role="gridcell" className="d-mes-dia" aria-pressed={dia === iso} data-hoje={iso === HOJE || undefined}
                data-fds={fds || undefined} onClick={() => setDia(iso)} aria-label={`${dataBr(iso)}: ${ts.length} tarefas`}>
                <span className="d-mes-n k-mono">{n}</span>
                {ts.slice(0, 2).map((t) => (
                  <span key={t.tarefa_id} className="d-mes-chip" data-estado={t.status === "concluida" ? "feita" : t.em_risco ? "risco" : "ok"}>{t.descricao}</span>
                ))}
                {ts.length > 2 && <span className="d-mes-mais">+{ts.length - 2}</span>}
              </button>
            );
          })}
        </div>
      </div>
      {dia && (
        <section className="d-caixa">
          <header className="d-caixa-topo"><h2>{dataBr(dia)}<span className="d-conta">{doDia.length}</span></h2></header>
          {doDia.length ? <ul className="d-tarefas">{doDia.map((t) => <LinhaTarefa key={t.tarefa_id} t={t} leitura={ctx.leitura} />)}</ul>
            : <Vazio>Nenhuma tarefa neste dia.</Vazio>}
        </section>
      )}
    </div>
  );
}
