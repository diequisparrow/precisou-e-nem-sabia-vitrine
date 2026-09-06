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


## Cadastrar link afiliado e publicar na vitrine

O script oficial da vitrine lê o batch do projeto `Affiliate_AI`, grava diretamente em
`public/products.json`, sincroniza preço/imagem/disponibilidade e pode fazer commit/push.

Teste sem alterar nada:

```powershell
python scripts\update_affiliate_link.py --product-id MLB73945552 --dry-run
```

Fluxo completo:

```powershell
python scripts\update_affiliate_link.py --product-id MLB73945552
```

Quando existir apenas um Draft aguardando link:

```powershell
python scripts\update_affiliate_link.py
```

Opções úteis:

```powershell
# Atualiza e sincroniza, mas não usa Git
python scripts\update_affiliate_link.py --product-id MLB73945552 --no-git

# Cria o commit local, mas não faz push
python scripts\update_affiliate_link.py --product-id MLB73945552 --no-push

# Informar link diretamente
python scripts\update_affiliate_link.py --product-id MLB73945552 --link https://meli.la/SEU_LINK

# Sem confirmação interativa
python scripts\update_affiliate_link.py --product-id MLB73945552 --link https://meli.la/SEU_LINK --yes
```

### Fonte de verdade

A fonte oficial da vitrine é:

```text
public/products.json
```

Não mantenha uma segunda cópia operacional em `Affiliate_AI\vitrine`.

### Autenticação Mercado Livre local

O `sync_products.py` procura o `.env` nesta ordem:

1. `AFFILIATE_AI_ENV_FILE`;
2. `.env` da vitrine;
3. `Affiliate_AI\.env` ao lado do repositório;
4. `~/Documents/Affiliate_AI/.env`.

Assim o token local pode continuar no projeto `Affiliate_AI` sem ser copiado para este repositório.
