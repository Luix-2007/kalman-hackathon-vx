# Identidade visual do Kalman · versão "Laudo"

Tudo o que é preciso para criar uma página, um painel, um slide ou um e-mail com a cara do Kalman. Abra
**`especime.html`** no navegador para ver cada peça funcionando.

> **Conceito.** O filtro de Kalman recebe muitas medições com ruído e devolve a melhor estimativa. O produto faz o
> mesmo com a regulação: entra o Diário Oficial inteiro e sai só a norma que muda a obrigação da distribuidora. A
> identidade é um **laudo técnico bem feito**: branco, grafite e linhas finas. O **laranja é o sinal**: marca a ação,
> o prazo e o trecho que importa, e aparece pouco.

## O que tem aqui

```
identidade-visual/
├── especime.html           guia visual: marca, cores, tipos, componentes, movimento, voz
├── marca/                  logo e grafismos em SVG
│   ├── kalman-horizontal.svg           ícone + palavra, fundo claro
│   ├── kalman-horizontal-escuro.svg    ícone + palavra, fundo grafite
│   ├── kalman-icone.svg                só o ícone (40 × 40)
│   ├── kalman-wordmark.svg             só a palavra, em contorno
│   ├── kalman-app.svg                  ícone de app, quadrado cheio (512)
│   ├── kalman-favicon.svg              favicon
│   ├── kalman-og.svg                   imagem de compartilhamento (1200 × 630)
│   ├── motivo-convergencia.svg         o ícone em grande, para hero, capa e slide
│   ├── motivo-traco.svg                o mesmo em traço único, sem fundo
│   └── png/                            og 1200×630, app 512 e 192, apple-touch 180
├── css/
│   ├── tokens.css          variáveis (--k-*): cor, tipo, raio, sombra, movimento, layout
│   ├── base.css            fontes, padrões de página e utilitários (.k-mono, .k-rotulo, .k-cantos…)
│   └── componentes.css     botão, campo, selo, chip, card da tarefa, citação, KPI, painel, tabela
├── tailwind/kalman.css     tema para Tailwind v4 + variáveis do shadcn/ui
├── tokens.json             os mesmos valores para Python, gráficos e e-mail
├── js/revelar.js           entrada ao rolar, sem dependência
└── react/marca.tsx         <Marca /> e <Icone /> em React
```

## Como usar

### HTML puro (mockup, página estática)

```html
<link rel="stylesheet" href="identidade-visual/css/tokens.css">
<link rel="stylesheet" href="identidade-visual/css/base.css">        <!-- já importa as fontes -->
<link rel="stylesheet" href="identidade-visual/css/componentes.css">
<script src="identidade-visual/js/revelar.js" defer></script>

<main class="k-moldura">
  <h1>Saiu uma norma. Saiba o que fazer<span class="k-ponto-final">.</span></h1>
  <button class="k-btn">Começar pelo CNPJ</button>
</main>
```

### Next.js + Tailwind v4 + shadcn/ui (o front)

1. Copie `identidade-visual/` para dentro do app (ou aponte o caminho relativo).
2. No `globals.css`:

   ```css
   @import "tailwindcss";
   @import "../identidade-visual/css/tokens.css";
   @import "../identidade-visual/tailwind/kalman.css";
   ```

   Não importe o `base.css` aqui: ele traz as fontes pelo Google Fonts, e no Next o certo é `next/font`.
3. Fontes no `layout.tsx` (os nomes das variáveis são os que o tema espera):

   ```tsx
   import { IBM_Plex_Mono, Instrument_Sans } from "next/font/google"

   const instrument = Instrument_Sans({ variable: "--font-instrument", subsets: ["latin"] })
   const plexMono = IBM_Plex_Mono({ variable: "--font-plex-mono", subsets: ["latin"], weight: ["400", "500", "600"] })

   <html lang="pt-BR" className={`${instrument.variable} ${plexMono.variable}`}>
   ```

4. Use as classes geradas: `bg-grafite`, `text-laranja`, `bg-ceu-claro`, `text-tinta-2`, `border-linha`,
   `font-mono`, `rounded-card`, `shadow-elevada`, `ease-out`. Os componentes do shadcn já saem na paleta
   (`primary` = grafite, `ring` = laranja). A marca: `react/marca.tsx`.
5. Ícone do app: copie `marca/kalman-favicon.svg` para `src/app/icon.svg` e `marca/png/kalman-apple-touch-180.png`
   para `src/app/apple-icon.png`. Imagem social: `marca/png/kalman-og.png` como `src/app/opengraph-image.png`.

### Python, gráficos, e-mail

`tokens.json` tem cores (com uso e contraste), fontes, tamanhos e tempos. Em gráfico, a série que importa é laranja e
o resto é grafite, céu e cinza (`tokens.json → grafico`).

## Regras que fazem a identidade

**Cor**
- Proporção aproximada: 70% branco, 20% grafite, 8% céu, 2% laranja. **Um elemento laranja por tela** (o botão
  principal, o prazo, o ponto). Se tudo é sinal, nada é.
- **Texto sobre laranja é grafite** (5.6:1). Branco sobre laranja dá 3.1:1 e não passa em texto normal.
- Laranja como cor de texto só em título grande (24 px ou mais) ou no ponto final do título.
- `tinta-3` (legenda) só sobre branco. Sobre céu claro ela cai para 4.3:1: lá use `tinta-2`.

**Tipografia**
- **Instrument Sans** para ler (títulos 600, corpo 400). **IBM Plex Mono** para todo dado: número de ato, artigo,
  CNPJ, prazo, contagem, rótulo. Números sempre tabulares.
- Títulos com espaçamento negativo (−3% a −3.5%). Rótulos em mono, caixa alta, +8%.

**Marca**
- Não recolorir, esticar, pôr sombra ou trocar a cor do ponto. Não escrever "kalman" digitado no lugar do contorno.
- Respiro mínimo em volta: duas vezes o diâmetro do ponto laranja. Mínimo: ícone em 16 px, horizontal em 96 px.
- O ícone (dois traços céu e um branco que convergem numa reta até o ponto) pode virar grafismo: `motivo-*.svg`.

**Linguagem gráfica**
- Linhas finas (`--k-linha`) em vez de caixas pesadas. Marcas de canto (`.k-cantos`) em quadros que citam documento.
- Grade de pontos (`.k-pontos`) só em painel grafite. Sombra só para elevação (card sobre painel), borda para estrutura.
- Raios concêntricos: o externo é o interno mais o espaçamento (card 12 dentro de painel 14 com pouca margem; botão 8).

**Movimento** (das skills `animate` e `better-ui`)
- Entrada: 300 ms, opacidade + 12 px + desfoque 4 px, `--k-ease-out`, itens a cada 100 ms. Saída: 150 ms.
- Botão pressionado: escala 0.96 em 150 ms; desabilitado não reage. Hover só em `@media (hover: hover)`.
- Nunca `transition: all`, nunca `ease-in` em interface, nunca animar algo usado o dia todo.
- `prefers-reduced-motion`: só opacidade. Demonstração longa vira um quadro estático completo.
- Cuidado com Tailwind v4/Lightning CSS: `translate` e `scale` avulsos são convertidos em `transform` e brigam com
  outro `transform` no mesmo elemento. Prefira `transform` composto.

**Voz**
- Português do Brasil, frases curtas e concretas, como um vendedor experiente do setor elétrico falando com um gerente
  de regulação. Título até 8 palavras e no máximo 1 frase de apoio.
- Todo número com fonte. Nada de depoimento, logo de cliente ou métrica inventada. Empresa de exemplo é fictícia
  ("Distribuidora Exemplo").
- Proibido: "revolucione", "potencialize", "transforme a maneira", "solução inovadora", "de ponta", "sem esforço",
  "o futuro da", "não é apenas X, é Y", listas de três adjetivos, emoji, travessão e exclamação.

## Origem

Paleta e tipografia escolhidas como "versão 3 · Laudo" no estudo de identidade; ícone "Sinal" do kit
`kalman-brand-kit-svg`. Valores e regras extraídos da landing do Kalman (Next 16, Tailwind 4, shadcn base-ui).
