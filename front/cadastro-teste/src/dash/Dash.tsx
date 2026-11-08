/**
 * O dash (área logada depois do cadastro): Visão geral · IA · Obrigações · Prazos · Mudanças · Configurações.
 * Montado pelo Painel (App.tsx) em /painel/* quando o cadastro foi concluído; o onboarding continua em
 * /painel/cadastro e /painel/matriz.
 *
 * Navegação lateral (grafite); recolhe para ícones em telas médias e vira gaveta no celular.
 * A pessoa aparece só como as iniciais; o menu dela tem tema, configurações e sair.
 * Tema claro e escuro só aqui (a landing e o cadastro são só claros, como manda o kit Laudo).
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import type { Cadastro } from "../api";
import { Marca } from "../identidade/marca";
import { nomeProprio } from "./cartoes";
import { acoes, propostasDe, useLoja } from "./dados";
import { Configuracoes } from "./Configuracoes";
import { DetalheObrigacao } from "./DetalheObrigacao";
import { Hoje } from "./Hoje";
import { Ia } from "./Ia";
import { Mudancas } from "./Mudancas";
import { Obrigacoes } from "./Obrigacoes";
import { Prazos } from "./Prazos";
import { Robo } from "./Robo";
import "./dash.css";

type Tema = "claro" | "escuro";
const CHAVE_TEMA = "kalman:tema";
const CHAVE_RECOLHIDA = "kalman:menu-recolhido";
function temaInicial(): Tema {
  try { const t = localStorage.getItem(CHAVE_TEMA); if (t === "claro" || t === "escuro") return t; } catch { /* sem storage */ }
  return matchMedia("(prefers-color-scheme: dark)").matches ? "escuro" : "claro";
}

export type Contexto = { cadastro: Cadastro; email: string; nome: string; leitura: boolean };

const iniciais = (nome: string, email: string) => {
  const p = nome.trim().split(/\s+/).filter(Boolean);
  return (p.length > 1 ? p[0][0] + p[p.length - 1][0] : (p[0] ?? email).slice(0, 2)).toUpperCase();
};

const ICONE: Record<string, ReactNode> = {
  hoje: <path d="M3.5 3.5h5.5v6H3.5zM11 3.5h5.5v3.5H11zM11 9h5.5v7.5H11zM3.5 11.5h5.5v5H3.5z" />,
  obrigacoes: <path d="M7 5h9.5M7 10h9.5M7 15h9.5M3.5 5h.01M3.5 10h.01M3.5 15h.01" />,
  prazos: <><rect x="3" y="4.5" width="14" height="12.5" rx="2" /><path d="M3 8.5h14M7 2.8v3.2M13 2.8v3.2" /></>,
  mudancas: <><circle cx="5.5" cy="5" r="2" /><circle cx="5.5" cy="15" r="2" /><circle cx="14.5" cy="9" r="2" /><path d="M5.5 7v6M14.5 11c0 2.5-2 4-5 4H7.5" /></>,
  config: <><path d="M3 5.5h8M15 5.5h2M3 10h2M9 10h8M3 14.5h10" /><circle cx="13" cy="5.5" r="1.8" /><circle cx="7" cy="10" r="1.8" /><circle cx="15" cy="14.5" r="1.8" /></>,
};
const Ic = ({ n }: { n: string }) => <svg viewBox="0 0 20 20" className="d-ic" aria-hidden="true">{ICONE[n]}</svg>;

export function Dash({ cadastro, email, nome, onSair, equipe }: {
  cadastro: Cadastro; email: string; nome: string; onSair: () => void; equipe: ReactNode;
}) {
  const [tema, setTema] = useState<Tema>(temaInicial);
  const [menuAberto, setMenuAberto] = useState(false); // gaveta do celular
  const [recolhida, setRecolhida] = useState(() => { try { return localStorage.getItem(CHAVE_RECOLHIDA) === "1"; } catch { return false; } });
  const alternarRecolhida = () => {
    setRecolhida((r) => { try { localStorage.setItem(CHAVE_RECOLHIDA, r ? "0" : "1"); } catch { /* sem storage */ } return !r; });
  };
  const loja = useLoja();
  const ir = useNavigate();
  const local = useLocation();
  const leitura = cadastro.papel === "membro";
  const ctx: Contexto = { cadastro, email, nome, leitura };
  const pendentes = propostasDe(loja).length;
  const empresa = nomeProprio(cadastro.empresa?.nome_fantasia || cadastro.empresa?.razao_social || "Empresa");

  // dados reais da empresa (no modo demonstração não faz nada)
  useEffect(() => { acoes.carregar(); }, [cadastro.cnpj]);

  useEffect(() => {
    document.documentElement.dataset.tema = tema;
    try { localStorage.setItem(CHAVE_TEMA, tema); } catch { /* sem storage */ }
    return () => { delete document.documentElement.dataset.tema; };
  }, [tema]);

  // Ctrl+K (ou ⌘K) abre a IA de qualquer tela
  useEffect(() => {
    const tecla = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); ir("/painel/ia"); }
    };
    addEventListener("keydown", tecla);
    return () => removeEventListener("keydown", tecla);
  }, [ir]);

  useEffect(() => {
    setMenuAberto(false);
    const nomes: Record<string, string> = { "": "Visão geral", ia: "IA", obrigacoes: "Obrigações", prazos: "Prazos", mudancas: "Mudanças", configuracoes: "Configurações" };
    document.title = `Kalman · ${nomes[local.pathname.replace(/^\/painel\/?/, "").split("/")[0]] ?? "Painel"}`;
  }, [local.pathname]);

  const item = (para: string, rotulo: string, icone: ReactNode, extra?: ReactNode) => (
    <NavLink to={para} end={para === "/painel"} className="d-item" title={rotulo}>
      {icone}<span className="d-item-rotulo">{rotulo}</span>{extra}
    </NavLink>
  );

  return (
    <div className="dash" data-tema={tema} data-recolhida={recolhida || undefined}>
      <header className="d-movel">
        <button type="button" className="d-movel-btn" aria-label="Abrir o menu" aria-expanded={menuAberto} onClick={() => setMenuAberto(true)}>
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 6h14M3 10h14M3 14h14" /></svg>
        </button>
        <Link to="/painel" aria-label="Kalman"><Marca escuro className="d-movel-marca" /></Link>
      </header>
      {menuAberto && <div className="d-veu" onClick={() => setMenuAberto(false)} />}

      <aside className="d-lateral" data-aberta={menuAberto || undefined} aria-label="Navegação">
        <div className="d-lateral-topo">
          <Link to="/painel" className="d-lateral-marca" aria-label="Kalman, ir para a visão geral"><Marca escuro className="d-marca" /></Link>
          <button type="button" className="d-recolher" onClick={alternarRecolhida} aria-pressed={recolhida}
            aria-label={recolhida ? "Expandir o menu" : "Recolher o menu"} title={recolhida ? "Expandir o menu" : "Recolher o menu"}>
            <svg viewBox="0 0 20 20" aria-hidden="true"><rect x="3" y="3.5" width="14" height="13" rx="2.5" /><path d="M8 3.5v13" /><path d={recolhida ? "M11.5 8l2 2-2 2" : "M13.5 8l-2 2 2 2"} /></svg>
          </button>
        </div>
        <nav className="d-lateral-nav">
          {item("/painel", "Visão geral", <Ic n="hoje" />, pendentes > 0 && <span className="d-item-conta" aria-label={`${pendentes} para decidir`}>{pendentes}</span>)}
          {item("/painel/ia", "IA do Kalman", <Robo tamanho={20} escuro className="d-ic d-ic-robo" />)}
          {item("/painel/obrigacoes", "Obrigações", <Ic n="obrigacoes" />)}
          {item("/painel/prazos", "Prazos", <Ic n="prazos" />)}
          {item("/painel/mudancas", "Mudanças", <Ic n="mudancas" />)}
        </nav>
        <div className="d-lateral-base">
          {item("/painel/configuracoes", "Configurações", <Ic n="config" />)}
          <Usuario nome={nome} email={email} empresa={empresa} tema={tema} onTema={() => setTema(tema === "claro" ? "escuro" : "claro")} onSair={onSair} />
        </div>
      </aside>

      <main className="d-principal">
        {loja.erro && (
          <div className="d-erro" role="alert">
            <span>{loja.erro}</span>
            <button type="button" className="d-link" onClick={() => acoes.carregar()}>Tentar de novo</button>
            <button type="button" className="d-icone-btn" aria-label="Fechar aviso" onClick={() => acoes.limparErro()}>
              <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 5l10 10M15 5L5 15" /></svg>
            </button>
          </div>
        )}
        {(() => {
          const livre = /\/(ia|configuracoes)/.test(local.pathname);
          const rodando = loja.processamento?.estado === "RUNNING";
          const falhou = !!loja.processamento && ["FAILED", "TIMED_OUT", "ABORTED"].includes(loja.processamento.estado);
          if (livre) return null;
          if (rodando && loja.obrigacoes.length > 0) return (
            <div className="d-faixa d-faixa--topo d-faixa--info" role="status"><Robo estado="pensando" tamanho={22} />
              Atualizando a matriz com a planilha nova. A tela atualiza sozinha quando terminar.</div>
          );
          if (loja.semMatriz && !rodando) return (
            <div className="d-faixa d-faixa--topo" role="status">
              {falhou ? "A última análise da matriz falhou e roda de novo sozinha em até 1 hora." : "A matriz de obrigações desta empresa ainda não foi enviada."}
              <Link className="d-link" to="/painel/matriz">{falhou ? "Ver a matriz" : "Enviar a planilha"}</Link>
            </div>
          );
          return null;
        })()}
        {loja.carregando && !/\/(ia|configuracoes)/.test(local.pathname) ? (
          <CarregandoMatriz desde={loja.carregandoDesde} />
        ) : loja.processamento?.estado === "RUNNING" && loja.obrigacoes.length === 0 && !/\/(ia|configuracoes)/.test(local.pathname) ? (
          <Analisando inicio={loja.processamento.inicio} email={email} />
        ) : (
        <Routes>
          <Route index element={<Hoje ctx={ctx} />} />
          <Route path="ia" element={<Ia ctx={ctx} />} />
          <Route path="obrigacoes" element={<Obrigacoes ctx={ctx} />} />
          <Route path="prazos" element={<Prazos ctx={ctx} />} />
          <Route path="mudancas" element={<Mudancas />} />
          <Route path="configuracoes" element={<Configuracoes ctx={ctx} equipe={equipe} />} />
          <Route path="*" element={<Navigate to="/painel" replace />} />
        </Routes>
        )}
        <DetalheObrigacao ctx={ctx} />
      </main>
    </div>
  );
}

/** Carregamento dos dados da empresa: 4 consultas em paralelo (obrigações, tarefas, linha do tempo e importações), cada uma
 *  no Athena. Costuma levar alguns segundos; a estimativa é conservadora. */
const CARGA_TIPICA_S = 10;
const CARGA_LENTA_S = 30;

function CarregandoMatriz({ desde }: { desde: number | null }) {
  const [agora, setAgora] = useState(Date.now());
  useEffect(() => { const t = window.setInterval(() => setAgora(Date.now()), 500); return () => window.clearInterval(t); }, []);
  const s = Math.max(0, (agora - (desde ?? agora)) / 1000);
  const faltam = Math.ceil(CARGA_TIPICA_S - s);
  const estimativa = faltam >= 1 ? `faltam cerca de ${faltam} s` : s < CARGA_LENTA_S ? "quase lá" : "está demorando mais que o normal";
  const pct = Math.min(95, Math.round((s / CARGA_TIPICA_S) * 100));
  return (
    <section className="d-analisando" role="status" aria-live="polite">
      <Robo estado="pensando" tamanho={120} />
      <h2>Carregando a matriz da empresa</h2>
      <p><b className="k-mono">{Math.floor(s)} s</b> · <b>{estimativa}</b></p>
      <span className="d-analisando-barra" role="progressbar" aria-label="Carregando a matriz" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
        <i style={{ width: `${pct}%` }} />
      </span>
      <p className="d-nota">Obrigações, tarefas e mudanças da empresa.</p>
    </section>
  );
}

/** Duração típica da análise (Step Functions + Glue), medida nas execuções de 08/11: 5,4 a 6,6 min. Com fila, até 15. */
const ANALISE_TIPICA_MIN = 7;
const ANALISE_MAXIMA_MIN = 15;

/** Primeira análise da matriz em andamento. A loja confere de novo a cada 30 s; aqui só o relógio anda. */
function Analisando({ inicio, email }: { inicio: string; email: string }) {
  const [agora, setAgora] = useState(Date.now());
  useEffect(() => { const t = window.setInterval(() => setAgora(Date.now()), 10_000); return () => window.clearInterval(t); }, []);
  const comeco = new Date(inicio);
  const passados = Math.max(0, (agora - comeco.getTime()) / 60_000);
  const faltam = Math.ceil(ANALISE_TIPICA_MIN - passados);
  const previsao = new Date(comeco.getTime() + ANALISE_TIPICA_MIN * 60_000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  const estimativa = faltam >= 1 ? `faltam cerca de ${faltam} min (previsão ${previsao})`
    : passados < ANALISE_MAXIMA_MIN ? "deve terminar em instantes" : "está demorando mais que o normal";
  // barra determinada pelo tempo típico; para em 95% até a análise terminar de fato
  const pct = Math.min(95, Math.round((passados / ANALISE_TIPICA_MIN) * 100));
  const hora = comeco.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  return (
    <section className="d-analisando" role="status" aria-live="polite">
      <Robo estado="pensando" tamanho={120} />
      <h2>Analisando a matriz da empresa</h2>
      <p>Começou às <b className="k-mono">{hora}</b> · <b>{estimativa}</b></p>
      <span className="d-analisando-barra" role="progressbar" aria-label="Análise da matriz" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
        <i style={{ width: `${pct}%` }} />
      </span>
      <p className="d-nota">A tela atualiza sozinha. Também avisamos por e-mail{email ? <> em <b>{email}</b></> : null} quando terminar.</p>
      <Link className="k-btn k-btn--contorno k-btn--sm" to="/painel/ia">Perguntar à IA enquanto isso</Link>
    </section>
  );
}

function Usuario({ nome, email, empresa, tema, onTema, onSair }: {
  nome: string; email: string; empresa: string; tema: Tema; onTema: () => void; onSair: () => void;
}) {
  const [aberto, setAberto] = useState(false);
  const caixa = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!aberto) return;
    const fora = (e: MouseEvent) => { if (!caixa.current?.contains(e.target as Node)) setAberto(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setAberto(false); };
    addEventListener("mousedown", fora); addEventListener("keydown", esc);
    return () => { removeEventListener("mousedown", fora); removeEventListener("keydown", esc); };
  }, [aberto]);
  return (
    <div className="d-usuario" ref={caixa}>
      <button type="button" className="d-usuario-btn" aria-haspopup="menu" aria-expanded={aberto} onClick={() => setAberto(!aberto)} title={nome || email}>
        <span className="d-avatar" aria-hidden="true">{iniciais(nome, email)}</span>
        <span className="d-usuario-txt"><b>{nome || email}</b><small>{empresa}</small></span>
        <span className="sr">Menu da conta</span>
      </button>
      {aberto && (
        <div className="d-menu" role="menu">
          <div className="d-menu-quem">
            <span className="d-avatar d-avatar--grande" aria-hidden="true">{iniciais(nome, email)}</span>
            <div><b>{nome || email}</b><small>{email}</small><small>{empresa}</small></div>
          </div>
          <button type="button" role="menuitemcheckbox" aria-checked={tema === "escuro"} className="d-menu-item" onClick={onTema}>
            Tema escuro<span className="d-chave" data-ligada={tema === "escuro" || undefined} aria-hidden="true"><i /></span>
          </button>
          <Link role="menuitem" className="d-menu-item" to="/painel/configuracoes" onClick={() => setAberto(false)}>Configurações</Link>
          <button type="button" role="menuitem" className="d-menu-item d-menu-sair" onClick={onSair}>Sair</button>
        </div>
      )}
    </div>
  );
}
