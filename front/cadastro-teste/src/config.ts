import { Amplify } from "aws-amplify";

/**
 * Valores públicos (vão para o navegador de qualquer forma; não são segredo).
 * Ordem: variável VITE_* do .env (make front-env) → valores da stack cnpj-cadastro publicada.
 * O fallback existe para o front rodar na Lovable sem .env. Se a stack for recriada, troque os três abaixo
 * pelos outputs novos: aws cloudformation describe-stacks --stack-name cnpj-cadastro --query "Stacks[0].Outputs"
 */
const STACK = {
  apiUrl: "https://usxtt4q6zi.execute-api.us-east-1.amazonaws.com/cadastro",
  userPoolId: "us-east-1_MmMe6Ii7z",
  userPoolClientId: "7d9om4gaq7b24kbn1augsijj29",
  matrizApiUrl: "https://ooe7nuoz9l.execute-api.us-east-1.amazonaws.com", // stack matriz-api
  chatbotApiUrl: "https://idgv0m8bmd.execute-api.us-east-1.amazonaws.com", // stack chatbot-api
};

export const config = {
  apiUrl: (import.meta.env.VITE_API_URL as string | undefined) || STACK.apiUrl,
  userPoolId: (import.meta.env.VITE_USER_POOL_ID as string | undefined) || STACK.userPoolId,
  userPoolClientId: (import.meta.env.VITE_USER_POOL_CLIENT_ID as string | undefined) || STACK.userPoolClientId,
  // API da matriz de obrigações (stack matriz-api): base do dashboard
  matrizApiUrl: (import.meta.env.VITE_MATRIZ_API_URL as string | undefined) || STACK.matrizApiUrl,
  // API do assistente (stack chatbot-api)
  chatbotApiUrl: (import.meta.env.VITE_CHATBOT_API_URL as string | undefined) || STACK.chatbotApiUrl,
};

export const configured = Boolean(config.apiUrl && config.userPoolId && config.userPoolClientId);

if (configured) {
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId: config.userPoolId,
        userPoolClientId: config.userPoolClientId,
        loginWith: { email: true },
        signUpVerificationMethod: "code",
      },
    },
  });
}
