/** Política de Privacidade e Termos de Uso (texto da versão em HTML da landing). */
import { useEffect, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Marca } from "../identidade/marca";
import "./legal.css";

function Layout({ titulo, outra, children }: { titulo: string; outra: { rota: string; nome: string }; children: ReactNode }) {
  useEffect(() => { document.title = `Kalman · ${titulo}`; window.scrollTo(0, 0); }, [titulo]);
  return (
    <div className="legal">
      <header className="topo">
        <div className="moldura">
          <Link to="/" aria-label="Kalman, início"><Marca className="marca" /></Link>
          <Link className="voltar" to="/">← Voltar ao início</Link>
        </div>
      </header>
      <main className="moldura">{children}</main>
      <footer className="rodape">
        <div className="moldura"><span>© 2026 Kalman</span><Link to={outra.rota}>{outra.nome}</Link></div>
      </footer>
    </div>
  );
}

export function Privacidade() {
  return (
    <Layout titulo="Política de Privacidade" outra={{ rota: "/termos", nome: "Termos de Uso" }}>
      <p className="rotulo">Legal</p>
      <h1>Política de Privacidade</h1>
      <p className="data">Última atualização: 7 de novembro de 2026</p>
      <h2>1. Sobre esta política</h2>
      <p>Esta Política de Privacidade explica como o Kalman coleta, usa, armazena e protege dados pessoais de quem usa a plataforma, em conformidade com a Lei Geral de Proteção de Dados Pessoais (Lei nº 13.709/2018, LGPD).</p>
      <h2>2. Dados que coletamos</h2>
      <ul>
      <li><strong>Dados de cadastro:</strong> e-mail, senha (guardada de forma criptografada pelo serviço de autenticação, sem acesso da nossa equipe) e CNPJ da empresa.</li>
      <li><strong>Dados públicos da empresa:</strong> razão social, atividade econômica, endereço e demais informações públicas do CNPJ, obtidas na base da Receita Federal.</li>
      <li><strong>Dados informados no perfil:</strong> nome e cargo do responsável, telefone, site e outras informações que você preencher.</li>
      <li><strong>Dados de uso:</strong> registros de acesso, ações realizadas na plataforma (como aprovar ou rejeitar uma tarefa) e informações técnicas do navegador.</li>
      </ul>
      <h2>3. Para que usamos os dados</h2>
      <ul>
      <li>Criar e manter a sua conta e o perfil da empresa.</li>
      <li>Identificar quais normas e atos publicados se aplicam à empresa e enviar os alertas por e-mail.</li>
      <li>Registrar as decisões tomadas sobre cada alerta, para histórico e auditoria.</li>
      <li>Garantir a segurança da plataforma, prevenir fraudes e cumprir obrigações legais.</li>
      <li>Melhorar o serviço, com base em dados de uso agregados.</li>
      </ul>
      <h2>4. Bases legais</h2>
      <p>Tratamos dados pessoais com base na execução do contrato com você (art. 7º, V, da LGPD), no cumprimento de obrigação legal ou regulatória (art. 7º, II), no legítimo interesse para segurança e melhoria do serviço (art. 7º, IX) e, quando necessário, no seu consentimento (art. 7º, I).</p>
      <h2>5. Compartilhamento</h2>
      <p>Não vendemos dados pessoais. Compartilhamos dados apenas com fornecedores que nos ajudam a operar o serviço, como provedores de infraestrutura em nuvem, autenticação e envio de e-mail, sempre sob contrato e com as medidas de segurança adequadas, e com autoridades públicas quando houver obrigação legal ou ordem judicial.</p>
      <h2>6. Armazenamento e segurança</h2>
      <p>Os dados ficam em servidores de provedores de nuvem com controles de acesso, criptografia em trânsito e em repouso e registro de acessos. Apenas pessoas autorizadas, e na medida do necessário, acessam os dados.</p>
      <h2>7. Por quanto tempo guardamos</h2>
      <p>Mantemos os dados enquanto a conta estiver ativa. Após o encerramento, os dados são excluídos ou anonimizados, exceto quando a lei exigir a guarda por mais tempo ou para o exercício regular de direitos.</p>
      <h2>8. Seus direitos</h2>
      <p>Você pode, a qualquer momento, solicitar:</p>
      <ul>
      <li>confirmação de que tratamos seus dados e acesso a eles;</li>
      <li>correção de dados incompletos, inexatos ou desatualizados;</li>
      <li>anonimização, bloqueio ou eliminação de dados desnecessários ou tratados em desconformidade com a LGPD;</li>
      <li>portabilidade dos dados;</li>
      <li>informação sobre com quem compartilhamos seus dados;</li>
      <li>revogação do consentimento, quando ele for a base do tratamento.</li>
      </ul>
      <p>As solicitações podem ser feitas pelos canais de atendimento disponíveis na plataforma.</p>
      <h2>9. Cookies</h2>
      <p>Usamos cookies e tecnologias semelhantes necessários para manter a sua sessão e a segurança da conta. Você pode gerenciar cookies nas configurações do navegador, mas alguns recursos podem deixar de funcionar.</p>
      <h2>10. Alterações nesta política</h2>
      <p>Podemos atualizar esta política. Quando a mudança for relevante, avisaremos por e-mail ou na própria plataforma. A data da última atualização aparece no início desta página.</p>
    </Layout>
  );
}

export function Termos() {
  return (
    <Layout titulo="Termos de Uso" outra={{ rota: "/privacidade", nome: "Política de Privacidade" }}>
      <p className="rotulo">Legal</p>
      <h1>Termos de Uso</h1>
      <p className="data">Última atualização: 7 de novembro de 2026</p>
      <h2>1. Aceitação</h2>
      <p>Ao criar uma conta ou usar o Kalman, você concorda com estes Termos de Uso e com a <Link to="/privacidade">Política de Privacidade</Link>. Se você usa a plataforma em nome de uma empresa, declara ter poderes para aceitar estes termos por ela.</p>
      <h2>2. O serviço</h2>
      <p>O Kalman acompanha publicações oficiais, como o Diário Oficial da União e os atos de órgãos reguladores, identifica as que podem afetar a empresa cadastrada e as apresenta como alertas e tarefas, com prazo, responsável sugerido e o trecho da norma que fundamenta cada uma.</p>
      <h2>3. Conta e cadastro</h2>
      <ul>
      <li>As informações de cadastro devem ser verdadeiras e mantidas atualizadas.</li>
      <li>Você é responsável por manter a senha em sigilo e por todas as ações feitas com a sua conta.</li>
      <li>Avise-nos imediatamente se suspeitar de uso não autorizado da conta.</li>
      </ul>
      <h2>4. Uso permitido</h2>
      <p>Você se compromete a não:</p>
      <ul>
      <li>usar a plataforma para fins ilegais ou que violem direitos de terceiros;</li>
      <li>tentar acessar áreas, contas ou dados sem autorização;</li>
      <li>copiar, revender ou redistribuir o serviço ou seus resultados de forma automatizada sem autorização;</li>
      <li>interferir no funcionamento ou na segurança da plataforma.</li>
      </ul>
      <h2>5. Natureza das informações</h2>
      <p>Os alertas e as tarefas são uma ferramenta de apoio à gestão regulatória. Eles não constituem parecer jurídico nem substituem a análise de profissionais habilitados. A decisão sobre como cumprir cada norma é da empresa usuária. Recomendamos conferir o texto oficial da publicação, sempre indicado em cada alerta.</p>
      <h2>6. Disponibilidade</h2>
      <p>Trabalhamos para manter o serviço disponível de forma contínua, mas podem ocorrer interrupções para manutenção, por falhas de terceiros ou por indisponibilidade das fontes oficiais. Nesses casos, faremos o possível para restabelecer o serviço no menor prazo.</p>
      <h2>7. Propriedade intelectual</h2>
      <p>A plataforma, a marca Kalman, os textos, o design e o software são protegidos por lei e pertencem ao Kalman ou a seus licenciadores. As publicações oficiais citadas são de domínio público. Os dados que você cadastra continuam sendo seus.</p>
      <h2>8. Limitação de responsabilidade</h2>
      <p>Na extensão permitida pela lei, o Kalman não se responsabiliza por decisões tomadas exclusivamente com base nos alertas, por danos indiretos ou lucros cessantes, nem por falhas nas fontes oficiais ou em serviços de terceiros fora do nosso controle.</p>
      <h2>9. Suspensão e encerramento</h2>
      <p>Você pode encerrar a sua conta a qualquer momento. Podemos suspender ou encerrar contas que violem estes termos, com aviso prévio sempre que possível.</p>
      <h2>10. Alterações nos termos</h2>
      <p>Podemos atualizar estes termos. Mudanças relevantes serão comunicadas por e-mail ou na plataforma, e o uso continuado após o aviso significa concordância com a nova versão.</p>
      <h2>11. Lei aplicável</h2>
      <p>Estes termos são regidos pelas leis da República Federativa do Brasil.</p>
    </Layout>
  );
}
