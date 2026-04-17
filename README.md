# Controle Orçamentário SaaS MVP

Este projeto contém duas versões funcionais do dashboard de controle orçamentário:

- `mvp/streamlit_app.py`: versão SaaS com login, multiusuário, banco de dados, upload, dashboard, alertas e exportação.
- `mvp/basic_app.py`: versão avulsa sem autenticação, com upload manual e dashboard local.

## Funcionalidades entregues

### SaaS MVP (`mvp/streamlit_app.py`)

- Autenticação de usuário: cadastro, login, logout, convite para membros e reset de senha.
- Multiusuário / multi-tenant com dados isolados por empresa.
- Upload de arquivos CSV, XLS e XLSX.
- Parser flexível que aceita colunas comuns como data, categoria, tipo, orçado e realizado.
- Dashboard com filtros por ano, mês, categoria e tipo.
- Comparação orçado x real, evolução mensal e análise de desvios.
- Ranking de categorias por desvio e lista de lançamentos não previstos.
- Exportação em Excel: recorte de dados filtrados e lançamentos não previstos.
- Histórico de uploads por empresa.
- Configuração de SMTP e alertas automáticos por e-mail.

### Versão básica (`mvp/basic_app.py`)

- Upload manual de CSV/XLS/XLSX sem login.
- Validação de dados com template de exemplo.
- Dashboard de orçamento versus realizado.
- Filtros por ano, mês, categoria e tipo.
- Exportação de recorte e não previsto.

## Como rodar

1. Crie um ambiente virtual Python:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Instale as dependências:

```powershell
pip install -r requirements.txt
```

3. Configure a conexão com o banco de dados (opcional):

```powershell
$env:DATABASE_URL = "sqlite:///app.db"
```

Para PostgreSQL:

```powershell
$env:DATABASE_URL = "postgresql://user:senha@host:porta/banco"
```

4. Crie um arquivo `.env` para variáveis de SMTP se quiser usar alertas por e-mail.

Se for usar Mercado Pago para o checkout de assinatura, inclua também:

```powershell
MERCADOPAGO_ACCESS_TOKEN=seu_token_de_acesso
BASE_URL=https://orcamentario-saas.netlify.app
```

Como obter e configurar:

1. Acesse o Painel do Mercado Pago em https://developers.mercadopago.com.br/ e faça login.
2. Abra a seção de credenciais do seu aplicativo e copie o `access token` (token de produção ou sandbox).
3. Cole o token em `MERCADOPAGO_ACCESS_TOKEN` no arquivo `.env`.
4. Defina `BASE_URL` para a URL onde o Streamlit está rodando.
   - em desenvolvimento local: `http://localhost:8501`
   - em produção: a URL pública do app (ex: `https://seu-app.onrender.com`)
5. Se quiser testar antes, use o token de `sandbox` do Mercado Pago.

## Deploy dos produtos

- `site/`: landing page estática. Pode ser publicada em Netlify, Vercel ou GitHub Pages.
- `mvp/streamlit_app.py`: app SaaS Premium. Pode ser publicado em Render, Railway, Streamlit Community Cloud ou Heroku.

### Recomendação de deploy

1. publique `site/` no Netlify para usar `https://orcamentario-saas.netlify.app`.
2. publique `mvp/streamlit_app.py` em um host Python com `requirements.txt` e `Procfile`.
3. em produção, o `BASE_URL` deve ser a URL pública do app, não a do Netlify.

### Variáveis de ambiente importantes

- `DATABASE_URL` - opcional, se quiser usar Postgres em produção.
- `MERCADOPAGO_ACCESS_TOKEN` - token de produção do Mercado Pago.
- `BASE_URL` - URL pública do app Streamlit.
- `UPGRADE_URL` - opcional, URL de upgrade externa se não quiser usar o checkout integrado.

Notas importantes:

- `MERCADOPAGO_ACCESS_TOKEN` é o token secreto daquele app Mercado Pago. Nunca compartilhe em público.
- `BASE_URL` é usado para redirecionar de volta ao app após o cliente finalizar o checkout.
- O checkout do Mercado Pago mostrará cartão de crédito e, se a sua conta estiver habilitada, Pix também.
- Se preferir, você pode manter `UPGRADE_URL` apontando para um link de compra externo enquanto finaliza o checkout via Mercado Pago.

5. Execute o app SaaS:

```powershell
streamlit run mvp/streamlit_app.py
```

Para usar a versão básica:

```powershell
streamlit run mvp/basic_app.py
```

## Publicação com 2 URLs

Este projeto precisa de duas publicações:

- URL 1: landing page estática para `site/` (ex: Netlify ou Vercel)
- URL 2: app SaaS para `mvp/streamlit_app.py` (ex: Streamlit Community Cloud, Render, Railway)

### Fluxo recomendado

1. crie um repositório Git com este código
2. publique `site/` na plataforma de site estático
3. publique `mvp/streamlit_app.py` em uma plataforma de apps Python
4. configure `BASE_URL` como a URL pública do app Streamlit
5. atualize os links do site quando o app estiver ativo

### O que cada URL serve

- `site/`: página de apresentação, planos e chamadas para ação
- `mvp/streamlit_app.py`: app real de teste/venda do produto SaaS

## Arquivos relevantes

- `mvp/upload_template.csv`: modelo de importação.
- `mvp/auth.py`: lógica de autenticação, convite e reset de senha.
- `mvp/database.py`: inicialização do banco e suporte SQLite/PostgreSQL.
- `mvp/utils.py`: conversão de arquivo, validação de upload e geração de relatórios.

## Observações

- O banco padrão é `sqlite:///app.db` se `DATABASE_URL` não estiver definido.
- Se `plotly` não estiver instalado, o app usa `altair` como fallback para gráficos.
- Use `mvp/basic_app.py` quando precisar de um fluxo mais simples e sem persistência.
