import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Porta fixa: http://localhost:5173 está liberada no CORS da API (AllowedOrigins no template.yaml).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
});
