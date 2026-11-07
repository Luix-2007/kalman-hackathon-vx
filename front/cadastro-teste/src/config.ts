import { Amplify } from "aws-amplify";

// Valores públicos (vão para o navegador). Vêm dos outputs da stack: make front-env
export const config = {
  apiUrl: import.meta.env.VITE_API_URL as string | undefined,
  userPoolId: import.meta.env.VITE_USER_POOL_ID as string | undefined,
  userPoolClientId: import.meta.env.VITE_USER_POOL_CLIENT_ID as string | undefined,
  // opcional: com ele aparece a tela da matriz de obrigações (stack matriz-api)
  matrizApiUrl: import.meta.env.VITE_MATRIZ_API_URL as string | undefined,
};

export const configured = Boolean(config.apiUrl && config.userPoolId && config.userPoolClientId);

if (configured) {
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId: config.userPoolId!,
        userPoolClientId: config.userPoolClientId!,
        loginWith: { email: true },
        signUpVerificationMethod: "code",
      },
    },
  });
}
