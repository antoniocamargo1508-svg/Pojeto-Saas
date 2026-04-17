# Deploy com 2 URLs

Este projeto usa duas publicações separadas:

- `site/` → landing page estática
- `mvp/streamlit_app.py` → app SaaS Premium

## URL 1: landing page estática

Recomendado: Netlify ou Vercel.

1. crie uma conta no Netlify ou Vercel.
2. crie um novo site e conecte ao repositório Git deste projeto.
3. configure o diretório de publicação como `site`.
4. publique.

O resultado será algo como:

- `https://orcamentario-saas.netlify.app`
- ou `https://seu-site.vercel.app`

### Alternativa rápida

Use o Netlify Drop:

1. abra `https://app.netlify.com/drop`
2. arraste `site/index.html` e `site/styles.css`
3. publique

## URL 2: app SaaS Streamlit

Recomendado: Streamlit Community Cloud ou Render.

### Streamlit Community Cloud

1. crie uma conta em https://streamlit.io/cloud.
2. conecte o repositório Git.
3. selecione a pasta raiz do projeto.
4. configure variáveis de ambiente no painel:
   - `MERCADOPAGO_ACCESS_TOKEN`
   - `BASE_URL` = URL pública do app Streamlit
   - `DATABASE_URL` (opcional)
   - `UPGRADE_URL` (opcional)
5. publique.

### Render

1. crie uma conta em https://render.com.
2. conecte o repositório Git.
3. crie um novo Web Service.
4. selecione o repositório e configure:
   - Branch: `main`
   - Build command: `pip install -r requirements.txt`
   - Start command: `streamlit run mvp/streamlit_app.py --server.port=$PORT --server.address=0.0.0.0`
5. configure as variáveis de ambiente.
6. publique.

### URL resultante

Será algo como:

- `https://seu-app.streamlit.app`
- ou `https://seu-app.onrender.com`

## Ajuste final no site

Depois que o app estiver ativo, atualize os links do `site/index.html`:

- `premium.html` deve apontar para a URL do app Python
- `starter.html` deve apontar para a URL do app Python ou para a página de cadastro/login específica

## O que precisamos fazer agora

1. criar conta no Netlify / Vercel
2. criar conta em Streamlit Cloud / Render
3. criar repositório Git e subir o código
4. publicar `site/` e `mvp/streamlit_app.py`
5. pegar as duas URLs e usar no site
