# Deploy (Basico + Premium)

## Visao geral

- **Basico (Hotmart)**: voce vende um pacote avulso e o cliente roda localmente com `streamlit run mvp/basic_app.py`.
- **Premium (SaaS)**: voce hospeda `streamlit run mvp/streamlit_app.py` e cobra mensalidade no seu site.

Estrutura recomendada de dominios:

- `www.seudominio.com` -> landing page (site estatico)
- `app.seudominio.com` -> aplicativo Premium (Streamlit)

## 1) Dominio e DNS (passo a passo)

1. Compre um dominio em um registrar (ex.: Registro.br ou outros).
2. Use um provedor de DNS (Cloudflare e o mais simples) e aponte os nameservers.
3. Crie os registros:
   - `A`/`CNAME` para `www` (dependendo do host da landing)
   - `CNAME` para `app` (dependendo do host do Streamlit)

## 2) Landing page (site/)

O diretorio `site/` ja tem um `index.html` e `styles.css`.

Opcoes de deploy:

- Netlify / Vercel (site estatico)
- GitHub Pages (se quiser com repo publico)

Checklist:

- Ajustar e-mail de contato
- Colocar link do Hotmart no botao "Comprar (Hotmart)"
- Colocar link do checkout no botao "Assinar Premium"

## 3) Deploy do Premium (Streamlit)

Opções:

- Streamlit Community Cloud (para teste rápido)
- Render / Railway / Heroku (para produção)

O repo já está pronto para deploy Python com:

- `requirements.txt`
- `Procfile`
- `.gitignore`

### Como implantar

1. Crie um repositório Git com este código.
2. Conecte o repositório ao host escolhido.
3. Configure o comando de start:
   - Render / Heroku: `streamlit run mvp/streamlit_app.py --server.port=$PORT --server.address=0.0.0.0`
4. Defina as variáveis de ambiente:
   - `DATABASE_URL` (opcional)
   - `MERCADOPAGO_ACCESS_TOKEN`
   - `BASE_URL` (a URL pública do app)
   - `UPGRADE_URL` (opcional)
5. Publicar e verificar que o app abre na URL gerada.

### Observação importante

- a landing page do `site/` é um produto diferente do app Streamlit.
- os botões do site devem apontar para o app publicado, não para `localhost`.
- o `BASE_URL` em produção deve ser a URL do Streamlit app.

### Exemplo de fluxo

- `https://orcamentario-saas.netlify.app` → landing page pública
- `https://seu-app.onrender.com` → app Streamlit Premium

Quando o app estiver publicado, atualize os links do site para essa URL.

## 4) Entrega do Basico (Hotmart)

Crie um ZIP com:

- `requirements.txt`
- `mvp/basic_app.py`
- `mvp/utils.py`
- `mvp/upload_template.csv`
- `README` com o passo a passo de instalacao/execucao

Comando de execucao para o cliente:

`python -m venv .venv`
`.\.venv\Scripts\Activate.ps1`
`pip install -r requirements.txt`
`streamlit run mvp/basic_app.py`

