# Precisou e nem sabia — Vitrine

## Estrutura

```text
public/
  index.html
  styles.css
  app.js
  products.json

scripts/
  sync_products.py
```

## Teste local

```powershell
python -m http.server 8080 --directory public
```

Abra:

```text
http://localhost:8080
```

## Sincronizar Mercado Livre localmente

Crie `.env` na raiz deste repositório ou use variáveis de ambiente.

```powershell
pip install -r requirements.txt
python scripts\sync_products.py --dry-run
python scripts\sync_products.py
```

## Cloudflare Pages

- Production branch: `main`
- Framework preset: `None`
- Build command: vazio (ou `exit 0`)
- Build output directory: `public`

O diretório `public` é o único conteúdo publicado pela Cloudflare.


## Usar o .env do Affiliate_AI sem copiá-lo

No PowerShell:

```powershell
$env:AFFILIATE_AI_ENV_FILE="C:\Users\GR\Documents\Affiliate_AI\.env"
python scripts\sync_products.py
Remove-Item Env:AFFILIATE_AI_ENV_FILE
```

O `.env` original não é copiado para este repositório.
