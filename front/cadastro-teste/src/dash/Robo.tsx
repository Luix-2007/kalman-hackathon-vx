/**
 * O robô da IA do Kalman (SVGs originais em public/ia/: aplicacoes/, frames/ e robo-animado.html).
 *
 * Uma peça por elemento, com a geometria de cada estado tirada dos frames. A geometria vai em CSS (x, y, width,
 * height, d, cx, cy, r), então trocar de estado anima sozinho (transição) e a boca faz morph: em todos os estados
 * ela é "M + 5 L". Os movimentos contínuos (piscar, onda da boca, pulso da antena) ficam no dash.css (.robo--*).
 * Com movimento reduzido, fica o desenho parado de cada estado.
 *
 * Usa classes, não ids: a página tem vários robôs ao mesmo tempo.
 */
import type { CSSProperties } from "react";

/** Nome da IA na interface. Ainda não decidido: trocar só aqui. */
export const NOME_IA = "IA do Kalman";

export type EstadoRobo = "repouso" | "ouvindo" | "pensando" | "respondendo" | "concluido" | "nao-sei";

type R = { x: number; y: number; w: number; h: number; rx: number };
type Geo = {
  antena: [number, number]; // y inicial e final da haste (x = 20)
  orelhaE: R; orelhaD: R; rosto: R; visor: R; olhoE: R; olhoD: R;
  boca: string; bocaCeu?: boolean; detalhe: { cy: number; r: number };
};

const orelha = (x: number, y = 18, w = 3.5, h = 9, rx = 1.5): R => ({ x, y, w, h, rx });
const olho = (x: number, y: number, h: number, w = 3.2, rx = 1.6): R => ({ x, y, w, h, rx });
const ROSTO: R = { x: 5, y: 10, w: 30, h: 25, rx: 7 };
const VISOR: R = { x: 9, y: 14, w: 22, h: 11, rx: 4 };

const GEO: Record<EstadoRobo, Geo> = {
  repouso: {
    antena: [5.5, 11], orelhaE: orelha(2), orelhaD: orelha(34.5), rosto: ROSTO, visor: VISOR,
    olhoE: olho(13, 17.2, 4.6), olhoD: olho(23.8, 17.2, 4.6),
    boca: "M 13.5 30 L 17 30 L 18.5 27.8 L 21.5 32.2 L 23 30 L 26.5 30", detalhe: { cy: 5, r: 3 },
  },
  ouvindo: {
    antena: [4.8, 10], orelhaE: orelha(1.5, 16.5, 4, 11, 1.8), orelhaD: orelha(34.5, 16.5, 4, 11, 1.8),
    rosto: { ...ROSTO, y: 9.5 }, visor: { ...VISOR, y: 13.5, h: 11.5 },
    olhoE: olho(12.8, 16.4, 5.6, 3.6, 1.8), olhoD: olho(23.6, 16.4, 5.6, 3.6, 1.8),
    boca: "M 14.5 29.8 L 17 29.8 L 18.8 29.8 L 21.2 29.8 L 23 29.8 L 25.5 29.8", bocaCeu: true, detalhe: { cy: 4.5, r: 3.4 },
  },
  pensando: {
    antena: [5.5, 11], orelhaE: orelha(2), orelhaD: orelha(34.5), rosto: ROSTO, visor: VISOR,
    olhoE: olho(13, 16.5, 4.4), olhoD: olho(23.8, 16.5, 4.4),
    boca: "M 13 30 L 15.8 27.2 L 18.5 32.5 L 21.5 27.2 L 24.2 32.5 L 27 30", bocaCeu: true, detalhe: { cy: 4.8, r: 3.2 },
  },
  respondendo: {
    antena: [5.5, 11], orelhaE: orelha(2), orelhaD: orelha(34.5), rosto: ROSTO, visor: VISOR,
    olhoE: olho(13, 16.8, 5), olhoD: olho(23.8, 16.8, 5),
    boca: "M 12.5 30 L 16 26.5 L 18.8 33.5 L 21.2 26.5 L 24 33.5 L 27.5 30", detalhe: { cy: 4.6, r: 3.4 },
  },
  concluido: {
    antena: [5.5, 11], orelhaE: orelha(2), orelhaD: orelha(34.5), rosto: ROSTO, visor: VISOR,
    olhoE: olho(13, 16.8, 4.2), olhoD: olho(23.8, 16.8, 4.2),
    boca: "M 13.5 30.2 L 16.5 30.2 L 18.5 30.2 L 21 30 L 23.8 29.3 L 26.5 28.2", detalhe: { cy: 4.8, r: 3.4 },
  },
  "nao-sei": {
    antena: [7, 11], orelhaE: orelha(2, 18.5, 3.5, 8.5), orelhaD: orelha(34.5, 18.5, 3.5, 8.5), rosto: ROSTO, visor: VISOR,
    olhoE: olho(13, 17.2, 4.6), olhoD: olho(23.8, 18.4, 2.6, 3.2, 1.3),
    boca: "M 14 30.2 L 16.8 30.2 L 19 30.2 L 21 30.2 L 23.2 30.2 L 26 30.2", bocaCeu: true, detalhe: { cy: 6.5, r: 2.6 },
  },
};

const ret = (r: R) => ({ x: r.x, y: r.y, width: r.w, height: r.h, rx: r.rx }) as CSSProperties;

export function Robo({ estado = "repouso", tamanho = 40, escuro = false, rotulo, className = "" }: {
  estado?: EstadoRobo;
  tamanho?: number;
  /** contorno céu no rosto, para fundo grafite */
  escuro?: boolean;
  /** texto para leitor de tela; sem ele o robô é decorativo */
  rotulo?: string;
  className?: string;
}) {
  const g = GEO[estado];
  const mini = tamanho <= 28; // como o ia-robo-mini.svg: sem orelhas
  return (
    <svg viewBox="0 0 40 40" width={tamanho} height={tamanho} className={`robo robo--${estado} ${className}`}
      role={rotulo ? "img" : undefined} aria-label={rotulo} aria-hidden={rotulo ? undefined : true} data-mini={mini || undefined}>
      <path className="robo-antena" style={{ d: `path("M 20 ${g.antena[0]} L 20 ${g.antena[1]}")` } as CSSProperties} />
      {!mini && <rect className="robo-orelha robo-orelha-esq" style={ret(g.orelhaE)} />}
      {!mini && <rect className="robo-orelha robo-orelha-dir" style={ret(g.orelhaD)} />}
      <rect className="robo-rosto" style={ret(g.rosto)} data-escuro={escuro || undefined} />
      <rect className="robo-visor" style={ret(g.visor)} />
      <rect className="robo-olho robo-olho-esq" style={ret(g.olhoE)} />
      <rect className="robo-olho robo-olho-dir" style={ret(g.olhoD)} />
      <path className="robo-boca" data-ceu={g.bocaCeu || undefined} style={{ d: `path("${g.boca}")` } as CSSProperties} />
      <circle className="robo-detalhe" style={{ cx: 20, cy: g.detalhe.cy, r: g.detalhe.r } as CSSProperties} />
    </svg>
  );
}
