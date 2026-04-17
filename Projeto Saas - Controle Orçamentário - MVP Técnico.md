Projeto Saas - Controle Orçamentário - MVP Técnico

# 1. Visão Geral

Objetivo: transformar o projeto de controle orçamentário em um SaaS escalável que possa ser vendido.

Foco inicial: validar um MVP técnico com fluxo completo de login, upload de arquivo, armazenamento multiusuário e dashboard financeiro.

## 1.1 Foco genérico

Este MVP não será uma cópia de um painel customizado para um cliente específico. A meta é construir uma solução mais genérica, com suporte a formatos de arquivo flexíveis, leitura de colunas padrão e filtros simples, para atender um público maior.

- importar arquivos Excel/CSV com colunas comuns de orçamento e realizado
- evitar dependência de nomes de colunas exclusivos de uma base específica
- oferecer uma experiência padrão para pequenas empresas e gestores financeiros

# 2. Proposta de valor

Venda principal: "Controle orçamentário profissional sem precisar de BI caro ou planilhas complexas." 

Diferencial:
- upload simples de Excel/CSV
- análise automática de orçado vs real
- dados separados por cliente
- interface acessível e imediata

# 3. Escopo do MVP

## Funcionalidades obrigatórias

1. Autenticação de usuário
   - cadastro por e-mail + senha
   - login
   - logout
   - convite por empresa
   - reset de senha via código

2. Multiusuário
   - cada cliente vê somente seus próprios dados
   - dados separados por `tenant_id`
   - histórico de uploads por empresa

3. Upload de arquivo
   - upload de Excel e/ou CSV/XLSX
   - parser flexível para colunas comuns de orçamento
   - validação de formato e normalização de datas

4. Processamento e armazenamento
   - salvar registros no banco de dados
   - associar dados ao usuário e tenant
   - suporte SQLite e PostgreSQL

5. Dashboard
   - Orçado vs Real
   - Desvios por categoria
   - Evolução mensal
   - Ranking de categorias por desvio
   - Detalhe de lançamentos não previstos
   - Filtros por ano, mês, categoria e tipo
   - Exportação de recorte e não previsto

6. Deploy inicial
   - versão pronta para Render/Railway
   - banco PostgreSQL ou SQLite configurável

## Funcionalidades a adiar para fase 2

- pagamentos integrados
- planos e assinatura
- recuperação de senha por e-mail
- importação de múltiplos arquivos por cliente
- dashboard customizável
- relatórios exportáveis

# 4. Requisitos técnicos

## Requisitos funcionais

- Usuário cadastra e faz login
- Usuário pode subir arquivo e ver confirmação
- Sistema salva e processa dados
- Dashboard exibe resultados filtrados por usuário

## Requisitos não funcionais

- Separação de dados por cliente
- Deploy em nuvem com URL pública
- Banco de dados seguro e persistente
- Aplicação leve e fácil de manter

# 5. Arquitetura recomendada

### Opção 1: Streamlit + PostgreSQL

- Frontend + backend no mesmo app
- Interface rápida de montar
- Boa opção para protótipo MVP

### Opção 2: Web app leve em FastAPI + React ou Streamlit

- permite separar frontend e backend
- melhor para escalar depois
- mais trabalho inicial

### Recomendação para MVP

Comece com Streamlit + PostgreSQL. É mais rápido e entrega a proposta de valor imediatamente.

# 6. Modelo de dados

Tabelas mínimas:

- `users`
  - id
  - email
  - senha hash
  - criado_em

- `uploads`
  - id
  - user_id
  - nome_arquivo
  - data_upload
  - status

- `financial_records`
  - id
  - upload_id
  - user_id
  - data
  - categoria
  - orcado
  - real
  - tipo (receita / despesa)
  - mes_ano

# 7. Fluxo do usuário

1. Cadastro ou login
2. Upload de Excel/CSV
3. Sistema processa o arquivo
4. Dados são salvos no banco
5. Dashboard é exibido com métricas e gráficos

# 8. Tecnologias recomendadas

- Linguagem: Python 3.11+
- App: Streamlit
- Banco: PostgreSQL
- ORM: SQLAlchemy ou outro leve
- Hospedagem: Render ou Railway
- Armazenamento de arquivos: local no servidor (MVP) ou S3/Blob em fase 2
- Planos de pagamento: Stripe ou Hotmart após MVP

# 9. Plano de implementação

## Semana 1: Protótipo técnico

- estruturar app Streamlit
- criar tela de login/cadastro
- implementar conexão com PostgreSQL
- criar modelo de dados básico

## Semana 2: Upload e processamento

- implementar upload de Excel/CSV
- parse básico de colunas financeiras
- salvar registros no banco
- criar dashboard de métricas principais

## Semana 3: Deploy e validação

- fazer deploy no Render/Railway
- testar cadastro, upload e dashboard
- corrigir bugs de isolamento de dados
- obter URL pública de teste

# 10. Entregáveis do MVP

- aplicação online funcional com autenticação e multiusuário
- cadastro/login, convite e reset de senha operando
- upload de arquivo CSV/XLS/XLSX funcionando
- dashboard com orçado vs real, desvios, filtros e exportação
- armazenamento de dados por cliente/tenant
- histórico de uploads por empresa
- configuração de alertas por e-mail

# 11. Critérios de sucesso

- usuário consegue iniciar e autenticar
- upload aceita arquivo válido e retorna resultado
- dashboard exibe dados apenas do cliente logado
- app está disponível online

# 12. Próximos passos após o MVP

- integrar pagamento e planos
- adicionar recuperação de senha
- melhorar validação de importação
- criar página de vendas simples
- lançar piloto com primeiros clientes

# 13. Tarefa imediata

1. montar protótipo Streamlit com login simples
2. configurar PostgreSQL local ou na nuvem
3. criar upload e dashboard básico
4. fazer deploy de teste

---

Este documento define o projeto técnico do MVP. Se quiser, posso agora gerar o roteiro detalhado de telas e rotas ou iniciar a implementação de código em Python/Streamlit.
