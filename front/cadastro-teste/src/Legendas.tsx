/**
 * Camada de cenas para o vídeo da demonstração (só no modo demo), na identidade Laudo. Quem grava dispara pelo
 * console ou por automação (torre-regulatoria/demo-gravacao/roteiro.js):
 *
 *   window.kalmanCena({ tipo: "titulo", texto: "Saiba quais normas *afetam a sua empresa*." })   // *…* = destaque
 *   window.kalmanCena({ tipo: "capitulo", numero: "01", titulo: "Visão geral", numeros: [{ valor: "4", rotulo: "para decidir" }] })
 *   window.kalmanCena({ tipo: "email", … })   // o resumo das 08:00 chegando
 *   window.kalmanCena({ tipo: "fim", … })     // números da semana + marca
 *   window.kalmanCena(null)                    // some (com animação de saída)
 *
 * Com ?gravar na URL a página já abre coberta (grafite), para a gravação não pegar a plataforma antes da abertura.
 * Também marca cada clique com um círculo laranja (o vídeo não mostra o cursor).
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Icone, Marca } from "./identidade/marca";
import { Robo } from "./dash/Robo";
import "./legendas.css";

type Numero = { valor: string; rotulo: string; tom?: "laranja" | "verde" };

type Cena =
  | { tipo: "capa" }
  | { tipo: "titulo"; texto: string; sub?: string }
  | { tipo: "legenda"; texto: string; rotulo?: string; topo?: boolean }
  | { tipo: "capitulo"; numero: string; titulo: string; sub?: string; numeros?: Numero[]; antes?: string; depois?: string; robo?: boolean }
  /** o resumo diário chegando: notificação + o e-mail real (public/demo/aviso-mudancas.html) rolando */
  | { tipo: "email"; texto: string; sub?: string; assunto: string; previa: string }
  | { tipo: "fim"; numeros: Numero[]; texto: string }
  | null;

declare global {
  interface Window { kalmanCena?: (c: Cena) => void }
}

type Toque = { id: number; x: number; y: number };
const TELA_CHEIA = new Set(["titulo", "capitulo", "email", "fim"]);
const comCapa = () => new URLSearchParams(location.search).has("gravar");

export function Legendas() {
  const [cena, setCena] = useState<Cena>(() => (comCapa() ? { tipo: "capa" } : null));
  const [saindo, setSaindo] = useState<{ cena: Cena; chave: number } | null>(null);
  const [chave, setChave] = useState(0);
  const [toques, setToques] = useState<Toque[]>([]);
  const camada = useRef<HTMLDivElement>(null);
  const atual = useRef<{ cena: Cena; chave: number }>({ cena, chave: 0 });

  // a camada fica na "top layer" do navegador (popover) para não sumir atrás do modal (<dialog>);
  // cada vez que um dialog abre, ela é reaberta para voltar ao topo da pilha
  useEffect(() => {
    const el = camada.current;
    if (!el?.showPopover) return;
    const subir = () => { try { if (el.matches(":popover-open")) el.hidePopover(); el.showPopover(); } catch { /* sem suporte */ } };
    subir();
    const obs = new MutationObserver((ms) => { if (ms.some((m) => m.target instanceof HTMLDialogElement && m.target.open)) subir(); });
    obs.observe(document.body, { subtree: true, attributes: true, attributeFilter: ["open"] });
    return () => obs.disconnect();
  }, []);

  useEffect(() => {
    let saida = 0;
    window.kalmanCena = (c) => {
      const antes = atual.current;
      // a tela cheia que sai fica por cima da nova durante a animação de saída
      if (antes.cena && TELA_CHEIA.has(antes.cena.tipo)) {
        setSaindo(antes);
        window.clearTimeout(saida);
        saida = window.setTimeout(() => setSaindo(null), 650);
      }
      const k = antes.chave + 1;
      atual.current = { cena: c, chave: k };
      setCena(c); setChave(k);
    };
    let seq = 0;
    const marcar = (ev: MouseEvent) => {
      // clique dado por trás de uma tela cheia (preparando a próxima cena) não aparece
      if (atual.current.cena && TELA_CHEIA.has(atual.current.cena.tipo)) return;
      let { clientX: x, clientY: y } = ev;
      // clique disparado por código (sem coordenadas): marca o centro do elemento
      if (!x && !y && ev.target instanceof Element) {
        const r = ev.target.getBoundingClientRect();
        x = r.left + r.width / 2; y = r.top + r.height / 2;
      }
      const id = ++seq;
      setToques((t) => [...t, { id, x, y }]);
      window.setTimeout(() => setToques((t) => t.filter((k) => k.id !== id)), 900);
    };
    document.addEventListener("click", marcar, true);
    return () => { delete window.kalmanCena; document.removeEventListener("click", marcar, true); window.clearTimeout(saida); };
  }, []);

  return (
    <div className="lg" aria-hidden="true" popover="manual" ref={camada}>
      <Quadro cena={cena} key={chave} />
      {saindo && <div className="lg-sai" key={`s${saindo.chave}`}><Quadro cena={saindo.cena} /></div>}
      {toques.map((t) => <span key={t.id} className="lg-toque" style={{ left: t.x, top: t.y }} />)}
    </div>
  );
}

function Quadro({ cena }: { cena: Cena }) {
  if (!cena) return null;
  switch (cena.tipo) {
    case "capa":
      return <div className="lg-fundo lg-capa" />;
    case "titulo":
      return (
        <div className="lg-fundo lg-titulo">
          <Marca escuro className="lg-marca" />
          <p className="lg-titulo-texto">{destacar(cena.texto)}</p>
          {cena.sub && <p className="lg-titulo-sub">{cena.sub}</p>}
        </div>
      );
    case "capitulo":
      return <Capitulo c={cena} />;
    case "email":
      return <CenaEmail cena={cena} />;
    case "fim":
      return (
        <div className="lg-fundo lg-fim">
          <ol className="lg-fim-funil">
            {cena.numeros.map((n, i) => (
              <li key={i} style={{ ["--i" as string]: i }} data-tom={n.tom}>
                <b><Contador valor={n.valor} atraso={200 + i * 450} /></b><span>{n.rotulo}</span>
              </li>
            ))}
          </ol>
          <div className="lg-fim-marca">
            <Marca escuro className="lg-fim-logo" />
            <p className="lg-fim-texto">{destacar(cena.texto)}</p>
          </div>
        </div>
      );
    case "legenda":
      return (
        <div className="lg-legenda" data-topo={cena.topo || undefined}>
          {cena.rotulo && <span className="lg-legenda-rotulo">{cena.rotulo}</span>}
          <span className="lg-legenda-texto">{cena.texto}</span>
        </div>
      );
  }
}

/** Abertura de cada tela: número, nome e o resumo do que ela mostra, em tela cheia. */
function Capitulo({ c }: { c: Extract<Cena, { tipo: "capitulo" }> }) {
  return (
    <div className="lg-fundo lg-cap">
      <div className="lg-cap-topo">
        <span className="lg-cap-num">{c.numero}</span>
        {c.robo && <Robo estado="respondendo" tamanho={88} escuro className="lg-cap-robo" />}
        <p className="lg-cap-titulo">{c.titulo}</p>
      </div>
      {c.antes && c.depois && (
        <p className="lg-cap-diff"><s>{c.antes}</s><span className="lg-cap-seta">→</span><b>{c.depois}</b></p>
      )}
      {c.numeros && (
        <ul className="lg-cap-numeros">
          {c.numeros.map((n, i) => (
            <li key={i} style={{ ["--i" as string]: i }} data-tom={n.tom}>
              <b><Contador valor={n.valor} atraso={300 + i * 110} /></b><span>{n.rotulo}</span>
            </li>
          ))}
        </ul>
      )}
      {c.sub && <p className="lg-cap-sub">{destacar(c.sub)}</p>}
    </div>
  );
}

/** "*trecho*" vira destaque com marca-texto laranja animado. */
function destacar(texto: string): ReactNode {
  return texto.split(/\*([^*]+)\*/).map((p, i) => (i % 2 ? <mark key={i} className="lg-destaque">{p}</mark> : p));
}

/** Conta de 0 até o valor, mantendo o formato ("1.931", "93%"). */
function Contador({ valor, atraso = 0, ms = 900 }: { valor: string; atraso?: number; ms?: number }) {
  const m = valor.match(/^(\D*)([\d.]+)(.*)$/);
  const alvo = m ? Number(m[2].replace(/\./g, "")) : 0;
  const [n, setN] = useState(0);
  useEffect(() => {
    let raf = 0;
    const t0 = performance.now() + atraso;
    const passo = (t: number) => {
      const p = Math.min(1, Math.max(0, (t - t0) / ms));
      setN(Math.round(alvo * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(passo);
    };
    raf = requestAnimationFrame(passo);
    return () => cancelAnimationFrame(raf);
  }, [alvo, atraso, ms]);
  if (!m) return <>{valor}</>;
  return <>{m[1]}{n.toLocaleString("pt-BR")}{m[3]}</>;
}

/** O resumo das 08:00 chegando: a notificação desliza, depois o e-mail real abre e rola dentro da moldura. */
function CenaEmail({ cena }: { cena: Extract<Cena, { tipo: "email" }> }) {
  const quadro = useRef<HTMLIFrameElement>(null);
  const [altura, setAltura] = useState(0);
  const medir = () => {
    const doc = quadro.current?.contentDocument;
    if (doc) setAltura(doc.documentElement.scrollHeight);
  };
  const passeio = Math.max(0, Math.min(altura - 560, 700));
  return (
    <div className="lg-fundo lg-email">
      <div className="lg-email-texto">
        <p className="lg-email-hora">08:00</p>
        <p className="lg-titulo-texto lg-email-titulo">{destacar(cena.texto)}</p>
        {cena.sub && <p className="lg-titulo-sub">{cena.sub}</p>}
      </div>
      <div className="lg-email-palco">
        <div className="lg-notif">
          <Icone className="lg-notif-icone" />
          <div className="lg-notif-corpo">
            <p className="lg-notif-topo"><b>Kalman</b><span>agora</span></p>
            <p className="lg-notif-assunto">{cena.assunto}</p>
            <p className="lg-notif-previa">{cena.previa}</p>
          </div>
        </div>
        <div className="lg-janela">
          <div className="lg-janela-barra"><i /><i /><i /><span>{cena.assunto}</span></div>
          <div className="lg-janela-corpo">
            <iframe ref={quadro} title="E-mail de aviso de mudanças" src="/demo/aviso-mudancas.html" onLoad={medir} scrolling="no"
              style={{ height: altura || 1600, ["--passeio" as string]: `-${passeio}px` }} />
          </div>
        </div>
      </div>
    </div>
  );
}
