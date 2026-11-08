/**
 * Desenha os blocos de dados da resposta do assistente (src/chatbot.ts). Um componente por tipo:
 * o formato é fixo, então a tela é sempre a mesma para a mesma pergunta.
 *
 * Tudo é texto escapado pelo React. Links só abrem se forem http(s), mesmo que a API já filtre.
 */
import type { Ato, Bloco, Empresa, EventoDaLinhaDoTempo, Obrigacao, Tarefa, Versao } from "./chatbot";

const dataBr = (iso: string | null) => (iso ? iso.slice(0, 10).split("-").reverse().join("/") : "—");
const valor = (v: string | number | null | undefined) => (v === null || v === undefined || v === "" ? "—" : String(v));
const linkSeguro = (url: string | null) => (url && /^https?:\/\//i.test(url) ? url : null);
const diasAte = (iso: string) =>
  Math.round((new Date(`${iso}T00:00:00`).getTime() - new Date(new Date().toDateString()).getTime()) / 86_400_000);

const EVENTO: Record<string, string> = {
  inclusao: "Inclusão", alteracao: "Alteração", revogacao: "Revogação", aprovacao: "Aprovação", rejeicao: "Rejeição",
};
const CAMPO: Record<string, string> = {
  prazo_regra: "Prazo", prazo_json: "Regra de prazo", titulo: "Título", periodicidade: "Periodicidade",
  recorrencia: "Recorrência", area_responsavel: "Área", aplica_a: "Aplica a", criticidade: "Criticidade",
  evidencia: "Evidência", trecho_citado: "Trecho citado", fonte_ato: "Ato", fonte_dispositivo: "Dispositivo",
  fonte_url: "Link do ato", orgao_sigla: "Órgão", tema: "Tema",
};
const STATUS_TAREFA: Record<string, string> = { aberta: "Aberta", em_andamento: "Em andamento", concluida: "Concluída" };

function titulo(b: Bloco): string {
  const p = b.parametros ?? {};
  switch (b.tipo) {
    case "empresa": return "Empresa";
    case "atos": return "Atos do DOU";
    case "obrigacoes": return "Obrigações";
    case "tarefas": return p.em_risco ? "Tarefas em risco" : "Tarefas";
    case "linha_do_tempo": return p.obrigacao_id ? `Linha do tempo de ${p.obrigacao_id}` : "Linha do tempo";
    case "versoes": return p.obrigacao_id ? `Versões de ${p.obrigacao_id}` : "Versões";
  }
}

function Tarefas({ itens }: { itens: Tarefa[] }) {
  return (
    <table>
      <thead><tr><th>Vence</th><th>Tarefa</th><th>Área</th><th>Status</th></tr></thead>
      <tbody>
        {itens.map((t, i) => {
          const dias = t.vencimento ? diasAte(t.vencimento) : null;
          return (
            <tr key={i} className={t.em_risco ? "risco" : ""}>
              <td>
                {dataBr(t.vencimento)}
                {t.em_risco && (
                  <small className="texto-erro"><br />{dias !== null && dias < 0 ? `atrasada ${-dias}d` : "em risco"}</small>
                )}
              </td>
              <td>{valor(t.descricao)}<br /><small className="sub">{valor(t.obrigacao_id)}{t.obrigacao_versao ? ` v${t.obrigacao_versao}` : ""}</small></td>
              <td>{valor(t.area_responsavel)}</td>
              <td>{STATUS_TAREFA[t.status ?? ""] ?? valor(t.status)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function Linha({ e }: { e: EventoDaLinhaDoTempo }) {
  const visiveis = (e.alteracoes ?? []).filter((a) => !["prazo_json", "fonte_url", "trecho_citado"].includes(a.campo));
  return (
    <li className={`evento ${e.evento ?? ""}`}>
      <div className="resumo-topo">
        <span>
          <strong>{dataBr(e.ocorrido_em)}</strong> · {EVENTO[e.evento ?? ""] ?? valor(e.evento)} · {valor(e.obrigacao_id)}{" "}
          <small className="sub">v{valor(e.versao)}</small>
        </span>
        <span className="sub">
          {e.ato_id?.startsWith("matriz_importada") ? "matriz do cliente" : valor(e.ato_id)}
          {e.data_ato && <> · publicado em {dataBr(e.data_ato)}</>}
        </span>
      </div>
      {e.titulo && <div className="sub">{e.titulo}</div>}
      {visiveis.length > 0 && (
        <table className="historico">
          <tbody>
            {visiveis.map((a) => (
              <tr key={a.campo}>
                <td>{CAMPO[a.campo] ?? a.campo}</td>
                <td><s>{valor(a.antes)}</s></td>
                <td>→ <strong>{valor(a.depois)}</strong></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {e.evento === "alteracao" && e.trecho_citado && <blockquote>“{e.trecho_citado}”</blockquote>}
    </li>
  );
}

function Obrigacoes({ itens }: { itens: Obrigacao[] }) {
  return (
    <table>
      <thead><tr><th>Obrigação</th><th>Órgão</th><th>Prazo</th><th>Área</th></tr></thead>
      <tbody>
        {itens.map((o, i) => (
          <tr key={i}>
            <td>
              <strong>{valor(o.obrigacao_id)}</strong> {valor(o.titulo)}
              {o.status === "proposta" && <> <span className="badge aviso">proposta v{valor(o.versao)}</span></>}
            </td>
            <td>{valor(o.orgao_sigla)}</td>
            <td>{valor(o.prazo_regra)}</td>
            <td>{valor(o.area_responsavel)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Versoes({ itens }: { itens: Versao[] }) {
  return (
    <table>
      <thead><tr><th>Versão</th><th>Status</th><th>Em vigor</th><th>Prazo</th></tr></thead>
      <tbody>
        {itens.map((v, i) => (
          <tr key={i}>
            <td>v{valor(v.versao)}</td>
            <td>{valor(v.status)}</td>
            <td>{v.vigente_de ? `${dataBr(v.vigente_de)} – ${v.vigente_ate ? dataBr(v.vigente_ate) : "hoje"}` : "—"}</td>
            <td>{valor(v.prazo_regra)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Atos({ itens }: { itens: Ato[] }) {
  return (
    <ul className="lista-atos">
      {itens.map((a, i) => {
        const link = linkSeguro(a.url_pdf);
        return (
          <li key={i}>
            <strong>{dataBr(a.data_publicacao)}</strong> · {valor(a.orgao)} · {valor(a.tipo)}
            <div>{link ? <a href={link} target="_blank" rel="noreferrer">{valor(a.identifica)}</a> : valor(a.identifica)}</div>
            {a.ementa && <small className="sub">{a.ementa}</small>}
          </li>
        );
      })}
    </ul>
  );
}

function EmpresaDados({ itens }: { itens: Empresa[] }) {
  const e = itens[0];
  if (!e) return null;
  return (
    <dl>
      <dt>Razão social</dt><dd>{valor(e.razao_social)}</dd>
      <dt>CNPJ</dt><dd>{valor(e.cnpj)}</dd>
      <dt>Situação</dt><dd>{valor(e.situacao_cadastral)}</dd>
      <dt>Atos no DOU</dt><dd>{valor(e.atos_no_dou)}{e.ato_mais_recente ? ` (último em ${dataBr(e.ato_mais_recente)})` : ""}</dd>
    </dl>
  );
}

export function BlocosChat({ blocos }: { blocos: Bloco[] }) {
  if (!blocos.length) return null;
  return (
    <div className="blocos">
      {blocos.map((b, i) => (
        <section key={i} className="bloco">
          <h4>{titulo(b)} <small className="sub">({b.itens.length})</small></h4>
          {b.tipo === "tarefas" && <Tarefas itens={b.itens} />}
          {b.tipo === "linha_do_tempo" && <ol className="linha-do-tempo">{b.itens.map((e, j) => <Linha key={j} e={e} />)}</ol>}
          {b.tipo === "obrigacoes" && <Obrigacoes itens={b.itens} />}
          {b.tipo === "versoes" && <Versoes itens={b.itens} />}
          {b.tipo === "atos" && <Atos itens={b.itens} />}
          {b.tipo === "empresa" && <EmpresaDados itens={b.itens} />}
        </section>
      ))}
    </div>
  );
}
