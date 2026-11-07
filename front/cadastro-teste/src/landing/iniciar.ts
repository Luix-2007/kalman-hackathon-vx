/**
 * Comportamento da landing (o <script> da versão em HTML, portado para rodar dentro do React).
 * Tudo é procurado dentro de `raiz` e a função devolve a limpeza: ao sair da rota, para as animações,
 * os observers e os listeners.
 */
export function iniciarLanding(raiz: HTMLElement, irParaCadastro: (cnpj: string) => void): () => void {
  const reduzido = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const limpezas: (() => void)[] = [];
  let parado = false;

  const $ = <T extends Element>(seletor: string) => raiz.querySelector<T>(seletor);
  const $$ = <T extends Element>(seletor: string) => Array.from(raiz.querySelectorAll<T>(seletor));
  const ouvir = (alvo: EventTarget, tipo: string, fn: (e: Event) => void) => {
    alvo.addEventListener(tipo, fn);
    limpezas.push(() => alvo.removeEventListener(tipo, fn));
  };
  const quadros = new Set<number>();
  const proximoQuadro = (fn: (t: number) => void) => {
    const id = requestAnimationFrame((t) => { quadros.delete(id); if (!parado) fn(t); });
    quadros.add(id);
  };

  /* máscara de CNPJ */
  for (const el of $$<HTMLInputElement>(".cnpj input")) {
    ouvir(el, "input", () => {
      const d = el.value.replace(/\D/g, "").slice(0, 14);
      const p = [d.slice(0, 2), d.slice(2, 5), d.slice(5, 8), d.slice(8, 12), d.slice(12)];
      el.value = d.length <= 2 ? p[0] : d.length <= 5 ? `${p[0]}.${p[1]}` : d.length <= 8 ? `${p[0]}.${p[1]}.${p[2]}`
        : d.length <= 12 ? `${p[0]}.${p[1]}.${p[2]}/${p[3]}` : `${p[0]}.${p[1]}.${p[2]}/${p[3]}-${p[4]}`;
    });
  }

  /* formulários de CNPJ: abrem "Criar conta" com o CNPJ preenchido */
  for (const f of $$<HTMLFormElement>("form[data-cadastro]")) {
    ouvir(f, "submit", (e) => {
      e.preventDefault();
      irParaCadastro((f.querySelector("input")?.value || "").replace(/\D/g, ""));
    });
  }

  /* 01 · conector: do quadrado laranja até o painel das multas */
  const grade = $<HTMLElement>("#grade");
  const visual = $<HTMLElement>("#problema-visual");
  const posicionar = () => {
    const um = grade?.querySelector(".um"), painel = visual?.querySelector(".multas");
    if (!visual || !um || !painel) return;
    const v = visual.getBoundingClientRect(), u = um.getBoundingClientRect(), m = painel.getBoundingClientRect();
    visual.style.setProperty("--x", `${u.left - v.left + u.width / 2}px`);
    visual.style.setProperty("--y", `${u.bottom - v.top + 4}px`);
    visual.style.setProperty("--ytop", `${u.top - v.top}px`);
    visual.style.setProperty("--h", `${m.top - u.bottom - 10}px`);
  };
  posicionar();
  ouvir(window, "resize", posicionar);
  document.fonts?.ready.then(() => { if (!parado) posicionar(); });

  /* entrada ao rolar */
  const io = new IntersectionObserver((es) => es.forEach((e) => {
    if (e.isIntersecting) { e.target.classList.add("visivel"); io.unobserve(e.target); }
  }), { threshold: 0.15 });
  $$(".revelar").forEach((el) => io.observe(el));
  limpezas.push(() => io.disconnect());

  /* contadores do funil */
  const fmt = (n: number) => n.toLocaleString("pt-BR");
  $$<HTMLElement>("[data-conta]").forEach((el, i) => {
    const alvo = Number(el.dataset.conta);
    if (reduzido) { el.textContent = fmt(alvo); return; }
    const ini = performance.now() + i * 700, dur = 1100;
    const passo = (t: number) => {
      const k = Math.min(1, Math.max(0, (t - ini) / dur));
      el.textContent = fmt(Math.round(alvo * (1 - Math.pow(1 - k, 3))));
      if (k < 1) proximoQuadro(passo);
    };
    el.textContent = "0";
    proximoQuadro(passo);
  });

  /* o filtro: ruído (atos) → lente → sinal (reta até o ponto laranja) */
  const cv = $<HTMLCanvasElement>("#filtro");
  const ctx = cv?.getContext("2d");
  if (!cv || !ctx) return () => { parado = true; limpezas.forEach((f) => f()); };

  let W = 0, H = 0, dpr = 1;
  const medir = () => {
    const r = cv.getBoundingClientRect();
    dpr = Math.min(devicePixelRatio || 1, 2);
    W = r.width; H = r.height;
    cv.width = W * dpr; cv.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  };
  medir();
  ouvir(window, "resize", () => { medir(); if (reduzido) quadro(true); });

  type Ato = { x: number; y: number; v: number; s: number; sinal: boolean; fase: 0 | 1 | 2; vy: number; a: number };
  const LENTE = 0.46, CENTRO_Y = 0.26, PONTO = 0.8;
  const base = () => H - 64; // a legenda ocupa o rodapé
  const rand = (a: number, b: number) => a + Math.random() * (b - a);
  const novo = (x0?: number): Ato => ({ x: x0 ?? rand(-0.15, 0), y: rand(0.06, 0.8), v: rand(0.0016, 0.0032), s: rand(0.6, 1), sinal: Math.random() < 0.035, fase: 0, vy: 0, a: 1 });
  const atos = Array.from({ length: 230 }, () => novo(rand(-0.2, LENTE)));
  let pulso = 0;

  function quadro(estatico: boolean) {
    if (!ctx) return;
    ctx.clearRect(0, 0, W, H);
    const h = base(), lx = LENTE * W, cy = CENTRO_Y * h, px = PONTO * W;
    // lente
    const g = ctx.createLinearGradient(lx - 14, 0, lx + 14, 0);
    g.addColorStop(0, "rgba(191,217,234,0)"); g.addColorStop(.5, "rgba(191,217,234,.18)"); g.addColorStop(1, "rgba(191,217,234,0)");
    ctx.fillStyle = g; ctx.fillRect(lx - 14, h * 0.02, 28, h * 0.94);
    ctx.strokeStyle = "rgba(191,217,234,.55)"; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(lx, h * 0.02); ctx.lineTo(lx, h * 0.96); ctx.stroke();
    // reta do sinal
    ctx.strokeStyle = "rgba(255,255,255,.9)"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(lx, cy); ctx.lineTo(px - 8, cy); ctx.stroke();
    // atos
    for (const a of atos) {
      const x = a.x * W, y = a.y * h;
      if (a.fase === 0) {
        ctx.fillStyle = a.sinal ? "rgba(255,255,255,.95)" : `rgba(191,217,234,${0.25 + 0.35 * a.s})`;
        ctx.fillRect(x, y, 5 * a.s + 2, 7 * a.s + 2);
      } else if (a.fase === 1) { // descartado: vira poeira e cai
        ctx.fillStyle = `rgba(102,114,125,${a.a * 0.6})`; ctx.fillRect(x, y, 2, 2);
      } else { // sinal: corre pela reta
        ctx.fillStyle = "#ffffff"; ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2); ctx.fill();
      }
    }
    // ponto (a tarefa)
    const r = 9 + (estatico ? 0 : pulso * 6);
    ctx.fillStyle = `rgba(255,90,31,${estatico ? 0 : 0.25 * pulso})`; ctx.beginPath(); ctx.arc(px, cy, r + 6, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "#0E1A24"; ctx.beginPath(); ctx.arc(px, cy, 12, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "#FF5A1F"; ctx.beginPath(); ctx.arc(px, cy, 8, 0, Math.PI * 2); ctx.fill();
    // rótulos
    ctx.fillStyle = "rgba(191,217,234,.75)"; ctx.font = "500 10px 'IBM Plex Mono', monospace";
    ctx.fillText("RUÍDO", 14, h * 0.04 + 12); ctx.fillText("FILTRO", lx + 10, h * 0.04 + 12); ctx.fillText("SINAL", px - 18, cy + 30);
  }

  function passo() {
    for (let i = 0; i < atos.length; i++) {
      const a = atos[i];
      if (a.fase === 0) {
        a.x += a.v;
        if (a.x >= LENTE) {
          if (a.sinal) { a.fase = 2; a.x = LENTE; }
          else { a.fase = 1; a.vy = rand(0.001, 0.004); }
        }
      } else if (a.fase === 1) {
        a.x += a.v * 0.35; a.y += a.vy; a.vy += 0.0002; a.a -= 0.012;
        if (a.a <= 0 || a.y > 0.98) atos[i] = novo();
      } else {
        a.y += (CENTRO_Y - a.y) * 0.18; a.x += 0.006;
        if (a.x >= PONTO - 0.01) { pulso = 1; atos[i] = novo(); }
      }
    }
    pulso *= 0.94;
  }

  const limpar = () => { parado = true; quadros.forEach(cancelAnimationFrame); quadros.clear(); limpezas.forEach((f) => f()); };

  if (reduzido) {
    // quadro estático completo: ruído à esquerda, poeira à direita da lente, reta e ponto
    atos.forEach((a) => { if (a.x > LENTE) { a.fase = 1; a.a = Math.random() * .8; a.y = rand(.5, .95); } });
    quadro(true);
    return limpar;
  }

  let rodando = !document.hidden, visivel = true;
  const vis = new IntersectionObserver(([e]) => { visivel = e.isIntersecting; });
  vis.observe(cv);
  limpezas.push(() => vis.disconnect());
  ouvir(document, "visibilitychange", () => { rodando = !document.hidden; });
  quadro(false); // primeiro quadro mesmo se a página abrir rolada
  const loop = () => { if (rodando && visivel) { passo(); quadro(false); } proximoQuadro(loop); };
  loop();

  return limpar;
}
