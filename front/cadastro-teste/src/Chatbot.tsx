/**
 * Painel do assistente: conversa com o agente da Kalman sobre a empresa, o DOU e a matriz de
 * obrigações. Usa a API do chatbot (src/chatbot.ts). A resposta é sempre mostrada como texto.
 */
import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError } from "./api";
import { BlocosChat } from "./BlocosChat";
import { enviarMensagem, novaConversa, PROMPT_MAX, type Bloco } from "./chatbot";

type Mensagem = { de: "usuario" | "assistente" | "erro"; texto: string; blocos?: Bloco[] };

const SUGESTOES = [
  "Quais tarefas estão em risco?",
  "O que mudou nas minhas obrigações por causa de atos recentes?",
  "Quais atos do DOU foram publicados sobre a minha empresa?",
];

const erroDe = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message : String(e));

export function Chatbot() {
  const [mensagens, setMensagens] = useState<Mensagem[]>([]);
  const [texto, setTexto] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [sessao, setSessao] = useState(novaConversa);
  const fim = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fim.current?.scrollIntoView?.({ block: "nearest" });
  }, [mensagens, enviando]);

  async function perguntar(pergunta: string) {
    const prompt = pergunta.trim();
    if (!prompt || enviando) return;
    setTexto("");
    setMensagens((m) => [...m, { de: "usuario", texto: prompt }]);
    setEnviando(true);
    try {
      const { resposta, blocos } = await enviarMensagem(prompt, sessao);
      setMensagens((m) => [...m, { de: "assistente", texto: resposta, blocos }]);
    } catch (e) {
      setMensagens((m) => [...m, { de: "erro", texto: erroDe(e) }]);
    } finally {
      setEnviando(false);
    }
  }

  const enviar = (e: FormEvent) => {
    e.preventDefault();
    perguntar(texto);
  };

  return (
    <section className="card">
      <div className="resumo-topo">
        <h2>6. Assistente</h2>
        <button className="link" disabled={enviando}
          onClick={() => { setMensagens([]); setSessao(novaConversa()); }}>Nova conversa</button>
      </div>
      <p className="sub">Pergunte sobre a empresa, os atos do DOU e a matriz de obrigações. Ele responde só com os dados da sua organização.</p>

      <div className="chat">
        {mensagens.length === 0 && (
          <div className="sugestoes">
            {SUGESTOES.map((s) => (
              <button key={s} type="button" className="chip-botao" disabled={enviando} onClick={() => perguntar(s)}>{s}</button>
            ))}
          </div>
        )}
        {mensagens.map((m, i) => (
          // texto puro: o React escapa; nunca dangerouslySetInnerHTML numa resposta de modelo
          <div key={i} className={`balao ${m.de}${m.blocos?.length ? " com-blocos" : ""}`}>
            {m.texto}
            {m.blocos && <BlocosChat blocos={m.blocos} />}
          </div>
        ))}
        {enviando && <div className="balao assistente pensando">Consultando os dados…</div>}
        <div ref={fim} />
      </div>

      <form onSubmit={enviar} className="linha" style={{ marginTop: 12 }}>
        <input value={texto} maxLength={PROMPT_MAX} placeholder="Escreva sua pergunta" disabled={enviando}
          onChange={(e) => setTexto(e.target.value)} />
        <button type="submit" disabled={enviando || !texto.trim()}>{enviando ? "Aguarde…" : "Enviar"}</button>
      </form>
    </section>
  );
}
