/**
 * Cliente da API do chatbot (stack chatbot-api). Referência para o front no Lovable.
 *
 * Mesmo login do cadastro (access token do Cognito). O CNPJ vem da organização do usuário,
 * decidida pela API: nunca envie cnpj nem user_id. A resposta é TEXTO: mostre como texto, nunca
 * como HTML (ela vem de um modelo e cita trechos de atos).
 *
 * Erros: 429 (limite de mensagens por hora ou dia; header Retry-After), 504 (o assistente
 * demorou), 502 (falha; tente de novo), 404 (usuário sem organização), 400 (mensagem inválida).
 * A mensagem para o usuário já vem em `erro`.
 */
import { ApiError, request } from "./api";
import { config } from "./config";

export const PROMPT_MAX = 2000; // o mesmo limite da API

/** Uma conversa = um session_id. A API deriva a sessão do usuário: não dá para entrar na de outro. */
export const novaConversa = () => crypto.randomUUID();

/** Envia uma mensagem e devolve o texto da resposta. */
export async function enviarMensagem(prompt: string, sessionId: string): Promise<string> {
  // sem esta guarda, o request cairia na URL do cadastro (valor padrão) e chamaria a API errada
  if (!config.chatbotApiUrl) throw new Error("VITE_CHATBOT_API_URL não está configurada (make front-env)");
  const { status, data } = await request(
    "POST", "/chatbot/mensagens", { prompt, session_id: sessionId }, config.chatbotApiUrl);
  if (status !== 200) throw new ApiError(status, data);
  return (data as { resposta: string }).resposta;
}
