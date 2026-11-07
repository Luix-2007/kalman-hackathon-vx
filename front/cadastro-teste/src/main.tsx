import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "./config"; // configura o Amplify antes de qualquer chamada
import App from "./App";
// Identidade "Laudo": tokens → base (fontes e utilitários) → componentes → estilos desta tela
import "./identidade/tokens.css";
import "./identidade/base.css";
import "./identidade/componentes.css";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
