/**
 * O motivo de convergência da marca (identidade-visual/marca/motivo-convergencia.svg), em movimento:
 * pontos céu correm pelas curvas (o ruído) até a convergência; de tempos em tempos um ponto branco segue
 * pela reta (o sinal) e o ponto laranja pulsa quando ele chega (a tarefa).
 * Com movimento reduzido, fica o desenho parado. Pausa com a aba escondida.
 */
import { useEffect, useRef } from "react";

const CURVAS = [70, 122, 174, 226, 278, 330, 382, 434, 486];
const OPACIDADES = [0.16, 0.26, 0.36];
const SINAL = "M -20 240 C 130 240, 190 320, 300 270 L 430 270";
const POR_CURVA = 2;

export function MotivoAnimado({ className }: { className?: string }) {
  const svg = useRef<SVGSVGElement>(null);

  useEffect(() => {
    const raiz = svg.current;
    if (!raiz || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const curvas = Array.from(raiz.querySelectorAll<SVGPathElement>("path[data-curva]"));
    const sinal = raiz.querySelector<SVGPathElement>("path[data-sinal]")!;
    const camada = raiz.querySelector<SVGGElement>("g[data-pontos]")!;
    const anel = raiz.querySelector<SVGCircleElement>("circle[data-anel]")!;
    const ns = "http://www.w3.org/2000/svg";

    type P = { el: SVGCircleElement; path: SVGPathElement; len: number; t: number; v: number; branco: boolean };
    const pontos: P[] = [];
    const novo = (path: SVGPathElement, branco: boolean, t0: number): P => {
      const el = document.createElementNS(ns, "circle");
      el.setAttribute("r", branco ? "4" : "2.4");
      el.setAttribute("fill", branco ? "#FFFFFF" : "#BFD9EA");
      camada.appendChild(el);
      return { el, path, len: path.getTotalLength(), t: t0, v: branco ? 0.0042 : 0.0016 + Math.random() * 0.0016, branco };
    };
    curvas.forEach((c) => { for (let i = 0; i < POR_CURVA; i++) pontos.push(novo(c, false, Math.random())); });
    const brancos = [novo(sinal, true, 0), novo(sinal, true, 0.5)];

    let pulso = 0;
    let quadro = 0;
    const passo = () => {
      if (!document.hidden) {
        for (const p of [...pontos, ...brancos]) {
          p.t += p.v;
          if (p.t >= 1) {
            p.t = 0;
            if (p.branco) pulso = 1;
            else p.v = 0.0016 + Math.random() * 0.0016;
          }
          const pt = p.path.getPointAtLength(p.t * p.len);
          p.el.setAttribute("cx", pt.x.toFixed(1));
          p.el.setAttribute("cy", pt.y.toFixed(1));
          // aparece no começo e some ao chegar: o ruído se dissolve na convergência
          const a = p.branco ? Math.min(1, p.t * 6) : Math.min(1, p.t * 5) * Math.min(1, (1 - p.t) * 3) * 0.85;
          p.el.setAttribute("opacity", a.toFixed(2));
        }
        pulso *= 0.955;
        anel.setAttribute("r", (9 + 22 * (1 - pulso)).toFixed(1));
        anel.setAttribute("opacity", (0.55 * pulso).toFixed(2));
      }
      quadro = requestAnimationFrame(passo);
    };
    quadro = requestAnimationFrame(passo);
    return () => {
      cancelAnimationFrame(quadro);
      [...pontos, ...brancos].forEach((p) => p.el.remove());
    };
  }, []);

  return (
    <svg ref={svg} className={className} viewBox="0 0 800 560" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <g fill="none" strokeLinecap="round">
        {CURVAS.map((y, i) => (
          <path key={y} data-curva d={`M -20 ${y} C 140 ${y}, 230 270, 430 270`} stroke="#BFD9EA" strokeOpacity={OPACIDADES[i % 3]} strokeWidth="1.4" />
        ))}
        <path data-sinal className="motivo-sinal" d={SINAL} stroke="#FFFFFF" strokeWidth="3" />
      </g>
      <g data-pontos />
      <circle data-anel cx="438" cy="270" r="9" fill="none" stroke="#FF5A1F" strokeWidth="2" opacity="0" />
      <circle cx="438" cy="270" r="14" fill="#0E1A24" />
      <circle className="motivo-ponto" cx="438" cy="270" r="9" fill="#FF5A1F" />
    </svg>
  );
}
