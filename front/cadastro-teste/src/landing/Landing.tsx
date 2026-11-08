/**
 * Landing do Kalman (rota /). Marcação e estilo vêm da versão aprovada em HTML
 * (torre-regulatoria/mockups/landing-final/index.html); o comportamento está em ./iniciar.ts.
 * Os "Começar" e os campos de CNPJ levam a /criar-conta (com ?cnpj= quando preenchido).
 * A seção 04 (IA do Kalman) foi acrescentada depois, só no React: ver SecaoIa no fim do arquivo.
 */
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { NOME_IA, Robo, type EstadoRobo } from "../dash/Robo";
import { iniciarLanding } from "./iniciar";
import "./landing.css";

const quadrados = (total: number, destaque: number[], classe: string) => {
  const marcados = new Set(destaque);
  return Array.from({ length: total }, (_, i) => <i key={i} className={marcados.has(i) ? classe : undefined} />);
};
/** 595 normas por dia, uma acesa. */
const GRADE = quadrados(595, [395], "um");
/** Duelo da semana de 03 a 06/11/2026: 224 alertas do clipping (7 obrigações) × 9 do Kalman (6 obrigações). */
const ALERTAS_CLIPPING = quadrados(224, [17, 48, 83, 119, 140, 171, 205], "acerto");
const ALERTAS_KALMAN = quadrados(9, [0, 1, 3, 4, 6, 7], "acerto");

export default function Landing() {
  const raiz = useRef<HTMLDivElement>(null);
  const navegar = useNavigate();

  useEffect(() => {
    document.title = "Kalman · Saiba quais normas afetam a sua empresa";
    if (!raiz.current) return;
    return iniciarLanding(raiz.current, (cnpj) => navegar(cnpj ? `/criar-conta?cnpj=${cnpj}` : "/criar-conta"));
  }, [navegar]);

  return (
    <div className="lp" ref={raiz}>
      <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true">
        <symbol id="marca-icone" viewBox="0 0 40 40">
          <rect x="1" y="1" width="38" height="38" rx="9" fill="#0E1A24"/>
          <path d="M7 10 C 13 10, 16 20, 22 20" fill="none" stroke="#BFD9EA" strokeWidth="1.8" strokeLinecap="round"/>
          <path d="M7 30 C 13 30, 16 20, 22 20" fill="none" stroke="#BFD9EA" strokeWidth="1.8" strokeLinecap="round"/>
          <path d="M7 17 C 11 17, 13 23, 17 20 L 29.5 20" fill="none" stroke="#FFFFFF" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"/>
          <circle cx="31.5" cy="20" r="4.8" fill="#0E1A24"/><circle cx="31.5" cy="20" r="3.2" fill="#FF5A1F"/>
        </symbol>
        <g id="marca-palavra">
          <path d="M62 14 H66.8 V27.2 L75.2 20.5 H81.0 L71.8 28.0 L81.6 38 H75.8 L68.2 30.2 L66.8 31.4 V38 H62 Z"/>
          <path fillRule="evenodd" d="M99.8 20.5 H94.8 V22.4 A7.8 8.8 0 1 0 94.8 36.1 V38 H99.8 Z M91.4 24.4 A4.4 4.8 0 1 0 91.4 34.1 A4.4 4.8 0 1 0 91.4 24.4 Z"/>
          <path d="M104.8 14.8 L109.6 13.6 V38 H104.8 Z"/>
          <path d="M114.6 20.5 H119.2 V22.5 C120.4 20.9 122.2 20.1 124.4 20.1 C126.8 20.1 128.6 21.1 129.6 22.9 C131.0 21.0 133.0 20.1 135.4 20.1 C139.2 20.1 141.6 22.6 141.6 26.8 V38 H136.8 V27.6 C136.8 25.3 135.6 24.1 133.7 24.1 C131.8 24.1 130.5 25.4 130.5 27.6 V38 H125.7 V27.6 C125.7 25.3 124.5 24.1 122.6 24.1 C120.7 24.1 119.4 25.4 119.4 27.6 V38 H114.6 Z"/>
          <path fillRule="evenodd" d="M161.4 20.5 H156.4 V22.4 A7.8 8.8 0 1 0 156.4 36.1 V38 H161.4 Z M153.0 24.4 A4.4 4.8 0 1 0 153.0 34.1 A4.4 4.8 0 1 0 153.0 24.4 Z"/>
          <path d="M166.4 20.5 H171.0 V22.6 C172.2 21.0 174.1 20.1 176.5 20.1 C180.5 20.1 183.0 22.7 183.0 27.0 V38 H178.2 V27.8 C178.2 25.4 176.9 24.1 174.8 24.1 C172.7 24.1 171.2 25.5 171.2 27.9 V38 H166.4 Z"/>
        </g>
      </svg>

      <header className="topo">
        <div className="moldura">
          <a href="#" aria-label="Kalman, início">
            <svg className="marca" viewBox="8 8 180 40" role="img" aria-label="Kalman">
              <g transform="translate(8 8)"><use href="#marca-icone" width="40" height="40"/></g>
              <use href="#marca-palavra" fill="#FFFFFF"/>
            </svg>
          </a>
          <nav aria-label="Seções">
            <a href="#problema">Normas</a>
            <a href="#prova">Comparativo</a>
            <a href="#ia">{NOME_IA}</a>
            <a href="#como-funciona">Como funciona</a>
            <Link className="btn btn--sm" to="/criar-conta">Começar</Link>
          </nav>
        </div>
      </header>

      <main>
        {/* HERO: o filtro em movimento */}
        <section className="hero" aria-labelledby="t-hero">
          <div className="moldura">
            <div>
              <h1 id="t-hero">Saiba quais normas afetam <em>a sua empresa.</em></h1>
              <form className="cnpj" data-cadastro>
                <label className="rotulo" htmlFor="cnpj-hero" style={{ position: "absolute", left: "-9999px" }}>CNPJ da empresa</label>
                <input id="cnpj-hero" inputMode="numeric" autoComplete="off" placeholder="00.000.000/0000-00" />
                <button className="btn" type="submit">Ver normas pelo CNPJ
                  <svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M3 8h9M8.5 4.5 12 8l-3.5 3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>
                </button>
              </form>
              <p className="hero-nota">O Kalman lê o Diário Oficial todo dia e avisa só o que vale para você.</p>
            </div>

            <figure className="demo" style={{ margin: "0" }} aria-label="Demonstração: 1.931 atos do Diário Oficial passam pelo filtro do Kalman. Saem 9 alertas, 6 deles obrigações reais, como responder o pedido de migração ao mercado livre em até 5 dias úteis.">
              <canvas id="filtro"></canvas>
              <div className="tarefa" aria-hidden="true">
                <span className="tarefa-ato">REN 1.174/2026 · art. 166-A</span>
                <span className="tarefa-titulo">Responder o pedido de migração ao mercado livre</span>
                <dl><dt>Prazo</dt><dd className="prazo">5 dias úteis</dd><dt>Dono</dt><dd>Comercial</dd></dl>
                <div className="tarefa-acoes"><span>Aprovar</span><span>Corrigir</span></div>
              </div>
              <div className="demo-legenda">
                <div><b className="mono" data-conta="1931">1.931</b><span>atos no DOU</span></div>
                <div><b className="mono" data-conta="9">9</b><span>alertas</span></div>
                <div><b className="mono" data-conta="6">6</b><span>obrigações</span></div>
              </div>
            </figure>
          </div>
        </section>

        {/* 1 · O RUÍDO */}
        <section className="secao" id="problema" aria-labelledby="t-ruido">
          <div className="moldura">
            <div className="cabeca">
              <p className="rotulo">01 · Normas e multas</p>
              <h2 id="t-ruido">Das 595 normas publicadas por dia, <span className="laranja-txt">uma</span> afeta a sua empresa.</h2>
            </div>
            <div className="problema-visual" id="problema-visual">
            <span className="conector" aria-hidden="true"></span>
            <span className="tag-um" aria-hidden="true">afeta você</span>
            <div className="faixa" id="grade" role="img" aria-label="595 quadrados, um em destaque">{GRADE}</div>
            <div className="faixa-rodape">
              <span className="fonte">Média de normas editadas por dia no Brasil desde 1988 · IBPT, 2024, via <a href="https://monitormercantil.com.br/constituicao-faz-36-anos-com-cerca-de-78-milhoes-de-normas-editadas-595-por-dia/" target="_blank" rel="noopener">Monitor Mercantil</a></span>
              <span className="legenda-faixa"><span><i className="cinza"></i>594 não se aplicam</span><span><i></i>1 afeta você</span></span>
            </div>

            <div className="multas" aria-labelledby="t-multa">
              <h3 id="t-multa">O que acontece quando uma norma passa batido</h3>
              <div className="multas-linha">
                <div className="multa"><b>R$ 606<small>mi</small></b><p>em multas aplicadas ao grupo Enel em 5 anos</p><span className="fonte">Aplicadas · <a href="https://viva.com.br/cidadania-e-direitos/enel-acumula-mais-de-600-milhoes-em-multas-a-maioria-em-sp.html" target="_blank" rel="noopener">Viva, 12/12/2025</a></span></div>
                <div className="multa"><b>R$ 53,8<small>mi</small></b><p>da Arce à Enel Ceará, só em 2024</p><span className="fonte"><a href="https://diariodonordeste.verdesmares.com.br/negocios/enel-ceara-acumula-multas-de-r-53-milhoes-em-2024-o-maior-valor-em-6-anos-1.3640803" target="_blank" rel="noopener">Diário do Nordeste</a></span></div>
                <div className="multa"><b>2,5<small>%</small></b><p>da Parcela B em risco a partir de 2027</p><span className="fonte">IASC abaixo de 50 · <a href="https://www.poder360.com.br/poder-energia/satisfacao-do-consumidor-passa-a-influenciar-tarifa-de-energia/" target="_blank" rel="noopener">Poder360</a></span></div>
              </div>
            </div>
            </div>
          </div>
        </section>

        {/* 2 · CLIPPING x KALMAN */}
        <section className="secao" id="prova" aria-labelledby="t-duelo">
          <div className="moldura">
            <div className="cabeca">
              <p className="rotulo">02 · Comparativo</p>
              <h2 id="t-duelo">Clipping <em>&times;</em> Kalman</h2>
              <p className="apoio-secao">O clipping avisa toda vez que um termo cadastrado, como “tarifa” ou o nome da empresa, aparece no Diário Oficial.</p>
            </div>
            <div className="ab">
              <div className="lado">
                <div className="lado-topo"><span className="lado-nome">Clipping</span><span className="lado-tipo">palavra-chave</span></div>
                <div className="lado-num"><b>224</b><span>alertas na semana</span></div>
                <div className="alertas" id="alertas-clipping" role="img" aria-label="224 alertas, 7 deles obrigações">{ALERTAS_CLIPPING}</div>
                <dl className="comparar">
                  <div><dt>Alertas inúteis</dt><dd>217</dd></div>
                  <div><dt>Alertas lidos por obrigação</dt><dd>32</dd></div>
                  <div><dt>O que chega</dt><dd className="texto">a palavra apareceu</dd></div>
                </dl>
              </div>
              <div className="lado kalman">
                <div className="lado-topo"><span className="lado-nome">Kalman</span><span className="lado-tipo">lê o ato inteiro</span></div>
                <div className="lado-num"><b>9</b><span>alertas na semana</span></div>
                <div className="alertas" id="alertas-kalman" role="img" aria-label="9 alertas, 6 deles obrigações">{ALERTAS_KALMAN}</div>
                <dl className="comparar">
                  <div><dt>Alertas inúteis</dt><dd>3</dd></div>
                  <div><dt>Alertas lidos por obrigação</dt><dd className="destaque">1,5</dd></div>
                  <div><dt>O que chega</dt><dd className="texto">tarefa com prazo e dono</dd></div>
                </dl>
              </div>
            </div>
            <div className="legenda-alertas">
              <span><i style={{ background: "var(--grafite)" }}></i><i style={{ background: "var(--laranja)", marginLeft: "-.2rem" }}></i>obrigação real</span>
              <span><i style={{ background: "var(--ceu-claro)" }}></i>alerta inútil</span>
            </div>
          </div>
        </section>

        {/* 3 · O PRODUTO */}
        <section className="secao" id="produto" aria-labelledby="t-produto">
          <div className="moldura">
            <div className="cabeca revelar">
              <p className="rotulo">03 · Da norma à tarefa</p>
              <h2 id="t-produto">O que a sua equipe recebe</h2>
            </div>
            <div className="produto revelar">
              <figure className="folha">
                <i></i>
                <span className="rotulo">DOU · 04/11/2026 · Seção 1 · p. 68</span>
                <strong>RESOLUÇÃO NORMATIVA Nº 1.174, DE 27 DE OUTUBRO DE 2026</strong><br /><br />
                “Art. 166-A. (...) tem o <span className="grifo">prazo de até 5 dias úteis</span>, contados a partir do recebimento da comunicação da migração prevista no art. 166, para verificar os requisitos técnicos e a existência de motivos que impeçam a migração (...)”
              </figure>
              <svg className="seta" viewBox="0 0 48 16" fill="none" aria-hidden="true"><path d="M2 8h40M36 2l6 6-6 6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>
              <div className="tarefa">
                <span className="tarefa-ato">Tarefa · Empresa Exemplo</span>
                <span className="tarefa-titulo">Responder o pedido de migração ao mercado livre</span>
                <dl>
                  <dt>Prazo</dt><dd className="prazo">5 dias úteis</dd>
                  <dt>Conta de</dt><dd>recebimento da comunicação</dd>
                  <dt>Unidade</dt><dd>Comercial · Grupo A</dd>
                  <dt>Evidência</dt><dd>protocolo da resposta</dd>
                </dl>
                <div className="tarefa-acoes"><span>Aprovar</span><span>Corrigir</span><span>Rejeitar</span></div>
              </div>
            </div>
          </div>
        </section>

        {/* 4 · A IA */}
        <SecaoIa />

        {/* 5 · COMO FUNCIONA */}
        <section className="secao" id="como-funciona" aria-labelledby="t-passos">
          <div className="moldura">
            <div className="cabeca">
              <p className="rotulo">05 · Do CNPJ ao alerta</p>
              <h2 id="t-passos">Como funciona</h2>
            </div>
            <ol className="fluxo">
              <span className="fluxo-linha" aria-hidden="true"></span>
              <li className="etapa">
                <span className="etapa-marca">01</span>
                <div className="etapa-card">
                  <h3>Digite o CNPJ</h3>
                  <p>Os dados da empresa vêm da Receita Federal.</p>
                  <div className="mini" aria-hidden="true">
                    <div className="mini-campo">12.345.678/0001-95</div>
                    <div className="mini-botao">Ver normas</div>
                  </div>
                </div>
              </li>
              <li className="etapa">
                <span className="etapa-marca">02</span>
                <div className="etapa-card">
                  <h3>Confira o perfil</h3>
                  <p>Atividade, fontes e quem responde por cada tema.</p>
                  <div className="mini" aria-hidden="true">
                    <div className="mini-linha"><span>Atividade</span><b>pelo CNAE</b></div>
                    <div className="mini-linha"><span>Fontes</span><b>DOU e agências</b></div>
                    <div className="mini-linha"><span>Licenças ambientais</span><b>Meio ambiente</b></div>
                  </div>
                </div>
              </li>
              <li className="etapa">
                <span className="etapa-marca">03</span>
                <div className="etapa-card">
                  <h3>Leitura diária</h3>
                  <p>O Kalman lê cada ato novo do Diário Oficial.</p>
                  <div className="mini" aria-hidden="true">
                    <div className="mini-funil"><span>1.931</span><i></i><span className="laranja">9</span></div>
                    <div className="mini-legenda"><span>atos na semana</span><span>alertas</span></div>
                  </div>
                </div>
              </li>
              <li className="etapa">
                <span className="etapa-marca">04</span>
                <div className="etapa-card">
                  <h3>Alerta automático</h3>
                  <p>Por e-mail, todo dia às 08:00.</p>
                  <div className="mini" aria-hidden="true">
                    <div className="mini-canal"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg><span>Resumo do dia</span><b>08:00</b></div>
                    <div className="mini-canal"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="3"/><path d="m8.5 12 2.5 2.5 4.5-5"/></svg><span>Responder migração</span><b>5 dias</b></div>
                  </div>
                </div>
              </li>
            </ol>
          </div>
        </section>

        {/* CTA */}
        <section className="cta" id="comecar" aria-labelledby="t-cta">
          <svg className="cta-motivo" viewBox="0 0 600 300" aria-hidden="true">
            <g fill="none" stroke="#0E1A24" strokeLinecap="round">
              <path d="M0 40 C 160 40, 220 150, 380 150" strokeWidth="10"/>
              <path d="M0 260 C 160 260, 220 150, 380 150" strokeWidth="10"/>
              <path d="M0 120 C 90 120, 130 190, 240 150 L 520 150" strokeWidth="16"/>
            </g>
            <circle cx="540" cy="150" r="26" fill="#0E1A24"/>
          </svg>
          <div className="moldura">
            <div className="cta-texto">
              <h2 id="t-cta">Veja o que vale para <span className="cta-destaque">a sua empresa.</span></h2>
              <p className="cta-apoio">Comece pelo CNPJ. O perfil vem da Receita Federal.</p>
            </div>
            <div className="cta-acao">
              <ul className="cta-lista">
                <li><svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m3.5 8.5 3 3 6-7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg>Perfil da empresa montado pelo CNPJ</li>
                <li><svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m3.5 8.5 3 3 6-7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg>Alertas por e-mail todo dia às 08:00</li>
                <li><svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m3.5 8.5 3 3 6-7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg>Cada alerta com prazo, responsável e trecho da norma</li>
              </ul>
              <form className="cnpj" data-cadastro>
                <label htmlFor="cnpj-final" className="cta-rotulo">CNPJ da empresa</label>
                <div className="cnpj-linha">
                  <input id="cnpj-final" inputMode="numeric" autoComplete="off" placeholder="00.000.000/0000-00" />
                  <button className="btn" type="submit">Começar</button>
                </div>
              </form>
            </div>
          </div>
        </section>
      </main>

      <footer className="rodape">
        <div className="moldura rodape-grade">
          <div className="rodape-marca">
            <svg className="marca" viewBox="8 8 180 40" role="img" aria-label="Kalman">
              <g transform="translate(8 8)"><use href="#marca-icone" width="40" height="40"/></g>
              <use href="#marca-palavra" fill="#FFFFFF"/>
            </svg>
            <p>As normas que valem para a sua empresa, com prazo e responsável.</p>
          </div>
          <nav className="rodape-col" aria-label="Seções">
            <span className="rotulo">Página</span>
            <a href="#problema">Normas</a>
            <a href="#prova">Clipping × Kalman</a>
            <a href="#produto">Da norma à tarefa</a>
            <a href="#ia">{NOME_IA}</a>
            <a href="#como-funciona">Como funciona</a>
          </nav>
          <nav className="rodape-col" aria-label="Conta">
            <span className="rotulo">Conta</span>
            <Link to="/criar-conta">Criar conta</Link>
            <Link to="/entrar">Entrar</Link>
          </nav>
          <nav className="rodape-col" aria-label="Legal">
            <span className="rotulo">Legal</span>
            <Link to="/privacidade">Política de Privacidade</Link>
            <Link to="/termos">Termos de Uso</Link>
          </nav>
        </div>
        <div className="moldura rodape-base">
          <span>© 2026 Kalman</span>
          <a href="#">Voltar ao topo ↑</a>
        </div>
      </footer>
    </div>
  );
}

/* ─────────────────────────── 04 · IA do Kalman ───────────────────────────
 * Conversa encenada (não chama a API): quando a seção aparece, a pergunta entra, o robô pensa e a resposta
 * chega com o cartão e a fonte. O texto todo está no DOM desde o início (o leitor de tela lê a conversa
 * inteira); só a encenação muda a opacidade. Com movimento reduzido, começa e fica na fase final.
 * Sem data-fase (ou na fase "parado") tudo fica visível. */
type FaseIa = "espera" | "pergunta" | "pensando" | "resposta" | "fim" | "parado";
const ROTEIRO_IA: [FaseIa, number][] = [["pergunta", 0], ["pensando", 900], ["resposta", 2500], ["fim", 4100], ["parado", 5600]];
const ROBO_NA_FASE: Record<FaseIa, EstadoRobo> = {
  espera: "repouso", pergunta: "ouvindo", pensando: "pensando", resposta: "respondendo", fim: "concluido", parado: "repouso",
};
const PERGUNTA_IA = "O que mudou no prazo de migração?";

function SecaoIa() {
  const palco = useRef<HTMLDivElement>(null);
  const [fase, setFase] = useState<FaseIa>(() =>
    matchMedia("(prefers-reduced-motion: reduce)").matches ? "parado" : "espera");

  useEffect(() => {
    if (fase !== "espera" || !palco.current) return;
    const timers: number[] = [];
    const io = new IntersectionObserver(([e]) => {
      if (!e.isIntersecting) return;
      io.disconnect();
      for (const [f, t] of ROTEIRO_IA) timers.push(window.setTimeout(() => setFase(f), t));
    }, { threshold: 0.45 });
    io.observe(palco.current);
    return () => { io.disconnect(); timers.forEach(clearTimeout); };
  }, []); // só arma na montagem; as trocas de fase vêm dos timers

  const robo = ROBO_NA_FASE[fase];
  return (
    <section className="secao secao-ia" id="ia" aria-labelledby="t-ia">
      <div className="moldura">
        <div className="cabeca">
          <p className="rotulo">04 · {NOME_IA}</p>
          <h2 id="t-ia">Tire dúvidas sobre as suas normas</h2>
          <p className="apoio-secao">Prazos, obrigações e atos do DOU da sua empresa, com o trecho da norma em cada resposta.</p>
        </div>

        <div className="ia-palco" ref={palco} data-fase={fase}>
          <Robo estado={robo} tamanho={76} escuro className="ia-robo" />
          <figure className="ia-chat">
            <figcaption className="sr-only">Exemplo de conversa com a {NOME_IA}</figcaption>
            <ol className="ia-mensagens">
              <li className="ia-msg ia-msg--pessoa"><span className="sr-only">Pergunta: </span>{PERGUNTA_IA}</li>
              <li className="ia-msg ia-msg--ia">
                <Robo estado={fase === "pensando" ? "pensando" : "repouso"} tamanho={28} className="ia-avatar" />
                <div className="ia-msg-corpo">
                  <p className="ia-pensando" aria-hidden="true">Lendo os atos e a matriz<i>.</i><i>.</i><i>.</i></p>
                  <div className="ia-resposta">
                    <p className="ia-texto"><span className="sr-only">Resposta da {NOME_IA}: </span>A REN ANEEL nº 1.174/2026, publicada em <span className="mono">04/11/2026</span>, reduziu o prazo de <span className="mono">10</span> para <span className="mono">5</span> dias úteis (<span className="mono">art.&nbsp;166-A</span>).</p>
                    <div className="ia-dado">
                      <span className="ia-dado-rotulo">Prazo para responder a migração</span>
                      <p className="ia-troca">
                        <span className="ia-antes"><small>antes</small><s>10 dias úteis</s></span>
                        <svg className="ia-seta" viewBox="0 0 24 12" fill="none" aria-hidden="true"><path d="M1 6h20M16 1.5 21 6l-5 4.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>
                        <span className="ia-depois"><small>agora</small><b>5 dias úteis</b></span>
                      </p>
                      <p className="ia-fonte"><span>Fonte</span>REN&nbsp;1.174/2026 · art.&nbsp;166-A · DOU&nbsp;04/11/2026 · p.&nbsp;68</p>
                    </div>
                  </div>
                </div>
              </li>
            </ol>
            <div className="ia-campo" aria-hidden="true">
              <span>Pergunte sobre prazos, obrigações ou um ato do DOU…</span>
              <i><svg viewBox="0 0 16 16" fill="none"><path d="M3 8h9M8.5 4.5 12 8l-3.5 3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg></i>
            </div>
          </figure>
        </div>
      </div>
    </section>
  );
}
