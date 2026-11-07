/**
 * Tela da matriz de obrigações: propostas do LLM para decidir, tarefas com vencimento e as
 * obrigações vigentes. Lê da API da matriz (src/matriz.ts).
 */
import { useEffect, useState } from "react";
import { ApiError } from "./api";
import {
  decidir,
  getObrigacao,
  getObrigacoes,
  getTarefas,
  mudarTarefa,
  type Historico,
  type Obrigacao,
  type StatusTarefa,
  type Tarefa,
} from "./matriz";

const dataBr = (iso: string | null) => (iso ? iso.slice(0, 10).split("-").reverse().join("/") : "—");
const diasAte = (iso: string) =>
  Math.round((new Date(`${iso}T00:00:00`).getTime() - new Date(new Date().toDateString()).getTime()) / 86_400_000);
const erroDe = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message : String(e));

const STATUS_TAREFA: Record<StatusTarefa, string> = {
  aberta: "Aberta",
  em_andamento: "Em andamento",
  concluida: "Concluída",
};

export function Matriz({ souMembro }: { souMembro: boolean }) {
  const [obrigacoes, setObrigacoes] = useState<Obrigacao[] | null>(null);
  const [tarefas, setTarefas] = useState<Tarefa[] | null>(null);
  const [aviso, setAviso] = useState("");
  const [msg, setMsg] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const [soRisco, setSoRisco] = useState(false);
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [aberta, setAberta] = useState<string | null>(null);

  const carregar = async () => {
    try {
      const [o, t] = await Promise.all([getObrigacoes(), getTarefas()]);
      setObrigacoes(o.obrigacoes);
      setTarefas(t.tarefas);
      setAviso(o.aviso ?? t.aviso ?? "");
    } catch (e) {
      setMsg({ tipo: "erro", texto: erroDe(e) });
    }
  };

  useEffect(() => {
    carregar();
  }, []);

  async function executar(chave: string, fn: () => Promise<unknown>, ok: string) {
    setOcupado(chave);
    setMsg(null);
    try {
      await fn();
      setMsg({ tipo: "ok", texto: ok });
      await carregar();
    } catch (e) {
      setMsg({ tipo: "erro", texto: erroDe(e) });
    } finally {
      setOcupado(null);
    }
  }

  if (obrigacoes === null || tarefas === null) {
    return (
      <section className="card">
        <h2>5. Matriz de obrigações</h2>
        {msg ? <p className={`msg ${msg.tipo}`}>{msg.texto}</p> : <p className="sub">Carregando a matriz…</p>}
      </section>
    );
  }

  const vigentes = obrigacoes.filter((o) => o.vigente);
  const propostas = obrigacoes.filter((o) => o.status === "proposta");
  const vigentePor = new Map(vigentes.map((o) => [o.obrigacao_id, o]));
  const emRisco = tarefas.filter((t) => t.em_risco);
  const lista = soRisco ? emRisco : tarefas;

  return (
    <section className="card">
      <div className="resumo-topo">
        <h2>5. Matriz de obrigações</h2>
        <button className="link" onClick={carregar}>Atualizar</button>
      </div>
      <p className="sub">
        {vigentes.length} obrigações vigentes · {propostas.length} proposta(s) para decidir · {tarefas.length} tarefas,{" "}
        <strong className={emRisco.length ? "texto-erro" : ""}>{emRisco.length} em risco</strong>
      </p>
      {aviso && <p className="msg info">{aviso}. O job roda a cada hora (ou <code>make pipeline-matriz-run</code>).</p>}
      {msg && <p className={`msg ${msg.tipo}`}>{msg.texto}</p>}

      {propostas.length > 0 && (
        <>
          <h3>Propostas do DOU para decidir</h3>
          {propostas.map((p) => {
            const atual = vigentePor.get(p.obrigacao_id);
            const chave = `${p.obrigacao_id}-${p.versao}`;
            return (
              <div key={chave} className="proposta">
                <div className="resumo-topo">
                  <strong>{p.obrigacao_id} · {p.titulo}</strong>
                  <span className="badge aviso">
                    {p.mudanca === "alteracao" ? "Alteração" : p.mudanca === "revogacao" ? "Revogação" : "Nova"} · v{p.versao}
                  </span>
                </div>
                <dl>
                  <dt>Ato</dt><dd>{p.alterada_por ?? p.fonte_ato}{p.fonte_dispositivo ? `, ${p.fonte_dispositivo}` : ""}</dd>
                  {atual && atual.prazo_regra !== p.prazo_regra && (
                    <><dt>Prazo</dt><dd><s>{atual.prazo_regra}</s> → <strong>{p.prazo_regra}</strong></dd></>
                  )}
                  {!atual && p.prazo_regra && (<><dt>Prazo</dt><dd>{p.prazo_regra}</dd></>)}
                  {p.confianca != null && (<><dt>Confiança</dt><dd>{Math.round(p.confianca * 100)}%</dd></>)}
                </dl>
                {p.trecho_citado && <blockquote>“{p.trecho_citado}”</blockquote>}
                {!souMembro && (
                  <div className="acoes">
                    <button disabled={ocupado !== null}
                      onClick={() => executar(chave, () => decidir(p.obrigacao_id, p.versao, "aprovar"), `${p.obrigacao_id} v${p.versao} aprovada.`)}>
                      {ocupado === chave ? "Aplicando…" : "Aprovar"}
                    </button>
                    <button className="link" disabled={ocupado !== null}
                      onClick={() => executar(chave, () => decidir(p.obrigacao_id, p.versao, "rejeitar"), `${p.obrigacao_id} v${p.versao} rejeitada.`)}>
                      Rejeitar
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </>
      )}

      <div className="resumo-topo">
        <h3>Tarefas</h3>
        <label className="check">
          <input type="checkbox" checked={soRisco} onChange={(e) => setSoRisco(e.target.checked)} /> só em risco
        </label>
      </div>
      <div className="tabela">
        <table>
          <thead>
            <tr><th>Vence</th><th>Tarefa</th><th>Área</th><th>Status</th></tr>
          </thead>
          <tbody>
            {lista.map((t) => {
              const dias = diasAte(t.vencimento);
              return (
                <tr key={t.tarefa_id} className={t.em_risco ? "risco" : ""}>
                  <td>
                    {dataBr(t.vencimento)}
                    {t.em_risco && <small className="texto-erro"><br />{dias < 0 ? `atrasada ${-dias}d` : dias <= 7 ? `${dias}d` : "proposta"}</small>}
                  </td>
                  <td>{t.descricao}<br /><small className="sub">{t.obrigacao_id} v{t.obrigacao_versao}{t.unidade_id ? ` · ${t.unidade_id}` : ""}</small></td>
                  <td>{t.area_responsavel ?? "—"}</td>
                  <td>
                    {souMembro ? STATUS_TAREFA[t.status] : (
                      <select value={t.status} disabled={ocupado !== null}
                        onChange={(e) => executar(t.tarefa_id, () => mudarTarefa(t.tarefa_id, e.target.value as StatusTarefa), "Status atualizado.")}>
                        {Object.entries(STATUS_TAREFA).map(([v, r]) => <option key={v} value={v}>{r}</option>)}
                      </select>
                    )}
                  </td>
                </tr>
              );
            })}
            {lista.length === 0 && <tr><td colSpan={4} className="sub">Nenhuma tarefa.</td></tr>}
          </tbody>
        </table>
      </div>

      <h3>Obrigações vigentes</h3>
      {vigentes.map((o) => (
        <details key={o.obrigacao_id} open={aberta === o.obrigacao_id}
          onToggle={(e) => (e.currentTarget as HTMLDetailsElement).open && setAberta(o.obrigacao_id)}>
          <summary>
            <strong>{o.obrigacao_id}</strong> {o.titulo} <small className="sub">· {o.orgao_sigla} · v{o.versao}</small>
          </summary>
          <dl>
            <dt>Prazo</dt><dd>{o.prazo_regra ?? "—"}</dd>
            <dt>Fonte</dt><dd>{[o.fonte_ato, o.fonte_dispositivo].filter(Boolean).join(", ") || "—"}</dd>
            <dt>Área</dt><dd>{o.area_responsavel ?? "—"}</dd>
            <dt>Aplica a</dt><dd>{o.aplica_a.join(", ") || "empresa toda"}</dd>
            <dt>Criticidade</dt><dd>{o.criticidade ?? "—"}</dd>
            <dt>Evidência</dt><dd>{o.evidencia ?? "—"}</dd>
          </dl>
          {aberta === o.obrigacao_id && <Versoes id={o.obrigacao_id} />}
        </details>
      ))}
    </section>
  );
}

function Versoes({ id }: { id: string }) {
  const [dados, setDados] = useState<{ versoes: Obrigacao[]; historico: Historico[] } | null>(null);
  const [erro, setErro] = useState("");
  useEffect(() => {
    getObrigacao(id).then(setDados).catch((e) => setErro(erroDe(e)));
  }, [id]);
  if (erro) return <p className="msg erro">{erro}</p>;
  if (!dados) return <p className="sub">Carregando histórico…</p>;
  return (
    <table className="historico">
      <tbody>
        {dados.historico.map((h, i) => (
          <tr key={i}>
            <td>{dataBr(h.ocorrido_em)}</td>
            <td>v{h.versao}</td>
            <td>{h.evento}</td>
            <td>{h.resumo}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
