/**
 * Configurações em três abas: Empresa e matriz (dados da Receita, planilha, áreas e responsáveis), Equipe (o componente
 * Equipe do App.tsx, recebido pronto) e Conta e alertas. Áreas, alertas e nome ainda não salvam (faltam campos na API).
 */
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { Contexto } from "./Dash";
import { Topo, dataBr, nomeProprio } from "./cartoes";
import { areasDe, useLoja, vigentesDe } from "./dados";

const ABAS = ["Empresa e matriz", "Equipe", "Conta e alertas"] as const;
type Aba = (typeof ABAS)[number];

const mascara = (c: string | null | undefined) => (c ?? "").replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, "$1.$2.$3/$4-$5");

export function Configuracoes({ ctx, equipe }: { ctx: Contexto; equipe: ReactNode }) {
  const [aba, setAba] = useState<Aba>("Empresa e matriz");
  return (
    <div className="d-pagina">
      <Topo titulo="Configurações" />
      <div className="d-abas" role="tablist">
        {ABAS.map((a) => <button key={a} type="button" role="tab" aria-selected={aba === a} onClick={() => setAba(a)}>{a}</button>)}
      </div>
      {aba === "Empresa e matriz" && <EmpresaMatriz ctx={ctx} />}
      {aba === "Equipe" && <div className="d-config-equipe">{equipe}</div>}
      {aba === "Conta e alertas" && <ContaAlertas ctx={ctx} />}
    </div>
  );
}

function Bloco({ titulo, acao, children }: { titulo: string; acao?: ReactNode; children: ReactNode }) {
  return (
    <section className="d-config-bloco">
      <header><h2>{titulo}</h2>{acao}</header>
      {children}
    </section>
  );
}

function EmpresaMatriz({ ctx }: { ctx: Contexto }) {
  const e = useLoja();
  const emp = ctx.cadastro.empresa;
  const d = ctx.cadastro.dados as Record<string, unknown>;
  const ufs = Array.isArray(d.ufs_atuacao) ? (d.ufs_atuacao as string[]) : [];
  const vig = vigentesDe(e);
  const [resp, setResp] = useState<Record<string, string>>({ Comercial: "comercial@empresa-exemplo.com.br", "Medição e faturamento": "medicao@empresa-exemplo.com.br", Regulação: ctx.email });
  return (
    <div className="d-config">
      <Bloco titulo="Empresa" acao={<Link className="d-link" to="/painel/cadastro">Rever dados</Link>}>
        <dl className="d-fatos d-fatos--config">
          <div><dt>Razão social</dt><dd>{nomeProprio(emp?.razao_social ?? "")}</dd></div>
          <div><dt>CNPJ</dt><dd className="k-mono">{mascara(ctx.cadastro.cnpj)}</dd></div>
          <div><dt>Sede</dt><dd>{emp?.municipio ? `${nomeProprio(emp.municipio)}/${emp.uf ?? ""}` : "—"}</dd></div>
          <div><dt>Atua em</dt><dd>{ufs.length ? ufs.join(", ") : "—"}</dd></div>
          <div><dt>Conferidos</dt><dd>{typeof d.conferido_em === "string" ? `${dataBr(d.conferido_em)}${d.conferido_por_nome ? ` · ${String(d.conferido_por_nome)}` : ""}` : "—"}</dd></div>
        </dl>
      </Bloco>
      <Bloco titulo="Matriz de obrigações" acao={!ctx.leitura && <Link className="d-link" to="/painel/matriz">Enviar nova planilha</Link>}>
        <dl className="d-fatos d-fatos--config">
          <div><dt>Da planilha</dt><dd className="k-mono">{vig.filter((o) => o.origem === "matriz_importada").length}</dd></div>
          <div><dt>Aprovadas da IA</dt><dd className="k-mono">{vig.filter((o) => o.origem === "llm").length}</dd></div>
          <div><dt>Vigentes</dt><dd className="k-mono">{vig.length}</dd></div>
        </dl>
      </Bloco>
      <Bloco titulo="Áreas e responsáveis">
        <ul className="d-config-lista">
          {areasDe(e).map((a) => (
            <li key={a}>
              <label htmlFor={`area-${a}`}>{a}</label>
              <input id={`area-${a}`} type="email" placeholder="e-mail do responsável" value={resp[a] ?? ""} disabled={ctx.leitura}
                onChange={(ev) => setResp({ ...resp, [a]: ev.target.value })} />
            </li>
          ))}
        </ul>
      </Bloco>
    </div>
  );
}

function ContaAlertas({ ctx }: { ctx: Contexto }) {
  return (
    <div className="d-config">
      <Bloco titulo="Sua conta">
        <ul className="d-config-lista">
          <li><label htmlFor="ct-nome">Nome</label><input id="ct-nome" defaultValue={ctx.nome} /></li>
          <li><label htmlFor="ct-email">E-mail</label><input id="ct-email" value={ctx.email} readOnly /></li>
          <li><label>Papel</label><span>{ctx.leitura ? "Membro (só leitura)" : "Dono da conta"}</span></li>
        </ul>
      </Bloco>
      <Bloco titulo="Resumo por e-mail">
        <ul className="d-config-lista">
          <li><label htmlFor="al-email">Enviar para</label><input id="al-email" type="email" defaultValue={ctx.email} disabled={ctx.leitura} /></li>
          <li><label htmlFor="al-hora">Horário</label>
            <select id="al-hora" defaultValue="08:00" disabled={ctx.leitura}>{["07:00", "08:00", "09:00", "12:00"].map((h) => <option key={h}>{h}</option>)}</select></li>
        </ul>
        <fieldset className="d-config-marcar" disabled={ctx.leitura}>
          <legend>Incluir</legend>
          <label><input type="checkbox" defaultChecked /> Propostas para decidir</label>
          <label><input type="checkbox" defaultChecked /> Tarefas em risco</label>
          <label><input type="checkbox" defaultChecked /> Mudanças aprovadas</label>
          <label><input type="checkbox" /> Atos para acompanhar</label>
        </fieldset>
      </Bloco>
    </div>
  );
}
