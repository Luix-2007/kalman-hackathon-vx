import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./config"; // configura o Amplify antes de qualquer chamada
import App from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
