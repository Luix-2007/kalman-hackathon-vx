import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Porta fixa: http://localhost:5173 está liberada no CORS da API (AllowedOrigins no template.yaml).
// host: true escuta em IPv4 e IPv6. Sem isso, o Node no Windows escuta só em [::1] e o navegador que resolve
// "localhost" como 127.0.0.1 não abre a página. Efeito colateral: o servidor de dev também fica visível na rede local.
// As rotas (/entrar, /painel...) funcionam em dev porque o Vite devolve o index.html para qualquer caminho (SPA).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true, host: true },
});
