from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
PUBLIC_DIR = PROJECT_ROOT / "public"
ENV_FILE = PROJECT_ROOT / ".env"
PRODUCTS_FILE = PUBLIC_DIR / "products.json"

ML_API = "https://api.mercadolibre.com"
TIMEOUT = 25


def carregar_env() -> None:
    """
    Usa, nesta ordem:
    1) caminho indicado por AFFILIATE_AI_ENV_FILE;
    2) .env da raiz deste repositório.

    Assim podemos sincronizar localmente usando o .env do projeto
    Affiliate_AI sem copiar segredos para o repositório da vitrine.
    """
    env_override = os.getenv("AFFILIATE_AI_ENV_FILE")

    env_path = (
        Path(env_override)
        if env_override
        else ENV_FILE
    )

    load_dotenv(
        env_path,
        override=True,
    )


def obter_ml_token() -> str | None:
    carregar_env()

    nomes = [
        "ML_ACCESS_TOKEN",
        "MERCADO_LIVRE_ACCESS_TOKEN",
        "MERCADOLIBRE_ACCESS_TOKEN",
        "MELI_ACCESS_TOKEN",
    ]

    for nome in nomes:
        valor = os.getenv(nome)

        if valor:
            return valor.strip()

    return None


def carregar_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def salvar_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def agora_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(
        timespec="seconds"
    )


def get_json(
    url: str,
) -> tuple[int, Any]:
    """
    Replica a mesma autenticação já usada pelo Auto Pipeline.

    Os endpoints /products/{id} e /products/{id}/items podem exigir
    Authorization: Bearer em algumas chamadas/contas.
    """
    token = obter_ml_token()

    headers = {
        "User-Agent":
            "AffiliateAI-Vitrine/1.2",

        "Accept":
            "application/json",
    }

    if token:
        headers[
            "Authorization"
        ] = f"Bearer {token}"

    response = requests.get(
        url,
        timeout=TIMEOUT,
        headers=headers,
    )

    # Mantém o mesmo fallback do pipeline principal.
    if (
        token
        and response.status_code
        in (
            401,
            403,
        )
    ):
        response = requests.get(
            url,
            timeout=TIMEOUT,
            headers={
                "User-Agent":
                    "AffiliateAI-Vitrine/1.2",

                "Accept":
                    "application/json",
            },
        )

    try:
        payload = response.json()

    except Exception:
        payload = None

    return (
        response.status_code,
        payload,
    )


def extrair_imagem_catalogo(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""

    pictures = payload.get("pictures") or []

    for picture in pictures:
        if not isinstance(picture, dict):
            continue

        for key in (
            "secure_url",
            "url",
        ):
            value = (
                picture.get(key)
                or ""
            ).strip()

            if value:
                return value

    return ""


def extrair_titulo_catalogo(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""

    return str(
        payload.get("name")
        or payload.get("title")
        or ""
    ).strip()


def normalizar_ofertas(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [
            item
            for item in payload
            if isinstance(item, dict)
        ]

    if not isinstance(payload, dict):
        return []

    for key in (
        "results",
        "items",
        "offers",
    ):
        value = payload.get(key)

        if isinstance(value, list):
            return [
                item
                for item in value
                if isinstance(item, dict)
            ]

    # Alguns formatos podem trazer o próprio payload como oferta.
    if any(
        key in payload
        for key in (
            "price",
            "item_id",
            "id",
        )
    ):
        return [payload]

    return []


def extrair_price(item: dict[str, Any]) -> float | None:
    value = item.get("price")

    if value is None:
        return None

    try:
        return float(value)
    except Exception:
        return None


def extrair_item_id(item: dict[str, Any]) -> str:
    for key in (
        "item_id",
        "id",
    ):
        value = item.get(key)

        if value is not None:
            return str(value).strip()

    return ""


def escolher_oferta(
    offers: list[dict[str, Any]],
    *,
    affiliate_item_id: str = "",
) -> tuple[dict[str, Any] | None, str]:
    """
    Preço de vitrine deve corresponder ao anúncio/link afiliado.

    Se affiliate_item_id estiver configurado, usamos exatamente essa oferta.
    Caso contrário NÃO usamos automaticamente a oferta mais barata do catálogo,
    porque ela pode ser de outro vendedor/anúncio e gerar divergência com o link.
    """

    affiliate_item_id = str(
        affiliate_item_id
        or ""
    ).strip()

    valid: list[dict[str, Any]] = []

    for offer in offers:
        price = extrair_price(
            offer
        )

        if price is None or price <= 0:
            continue

        valid.append(
            offer
        )

    if not valid:
        return (
            None,
            "NO_VALID_OFFER",
        )

    if affiliate_item_id:
        for offer in valid:
            if (
                extrair_item_id(
                    offer
                )
                == affiliate_item_id
            ):
                return (
                    offer,
                    "EXACT_AFFILIATE_ITEM",
                )

        return (
            None,
            "AFFILIATE_ITEM_NOT_FOUND",
        )

    return (
        None,
        "PRICE_LOCKED_NO_AFFILIATE_ITEM",
    )


def sincronizar_produto(
    product: dict[str, Any],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    product_id = str(product.get("product_id") or "").strip()

    if not product_id:
        return {
            "code": product.get("code"),
            "product_id": "",
            "status": "SKIP",
            "reason": "product_id ausente",
        }

    catalog_status, catalog = get_json(
        f"{ML_API}/products/{product_id}"
    )
    offers_status, offers_payload = get_json(
        f"{ML_API}/products/{product_id}/items"
    )

    image_url = (
        extrair_imagem_catalogo(catalog)
        if catalog_status == 200
        else ""
    )
    catalog_title = (
        extrair_titulo_catalogo(catalog)
        if catalog_status == 200
        else ""
    )
    offers = (
        normalizar_ofertas(offers_payload)
        if offers_status == 200
        else []
    )

    affiliate_item_id = str(
        product.get("affiliate_item_id") or ""
    ).strip()

    matched_offer, price_sync_status = escolher_oferta(
        offers,
        affiliate_item_id=affiliate_item_id,
    )

    current_price = (
        extrair_price(matched_offer)
        if matched_offer
        else None
    )
    current_item_id = (
        extrair_item_id(matched_offer)
        if matched_offer
        else ""
    )

    previous_active = bool(product.get("active", True))

    transient_statuses = {401, 403, 408, 409, 425, 429}
    api_transient_error = bool(
        catalog_status in transient_statuses
        or offers_status in transient_statuses
        or catalog_status >= 500
        or offers_status >= 500
    )

    if api_transient_error:
        available = previous_active
        availability_status = "API_ERROR_KEEP_PREVIOUS"

    elif catalog_status == 200 and offers_status == 200:
        if affiliate_item_id:
            available = matched_offer is not None
            availability_status = (
                "EXACT_ITEM_ACTIVE"
                if available
                else "EXACT_ITEM_NOT_FOUND"
            )
        else:
            any_valid_offer = any(
                extrair_price(offer) is not None
                and extrair_price(offer) > 0
                for offer in offers
            )
            available = bool(image_url and any_valid_offer)
            availability_status = (
                "CATALOG_ACTIVE"
                if available
                else "CATALOG_NO_VALID_OFFER"
            )

    else:
        available = False
        availability_status = "UNAVAILABLE_HTTP"

    if not dry_run:
        if image_url:
            product["image_url"] = image_url

        if catalog_title:
            product["catalog_title"] = catalog_title

        fixed_price = product.get("fixed_price")

        if fixed_price is not None:
            product["price"] = float(fixed_price)
            product["price_sync_status"] = "FIXED_PRICE"

        elif current_price is not None and affiliate_item_id:
            product["price"] = current_price
            product["price_checked_at"] = datetime.now().date().isoformat()
            product["price_sync_status"] = "EXACT_AFFILIATE_ITEM"

        else:
            product["price_sync_status"] = price_sync_status

        if current_item_id:
            product["validated_item_id"] = current_item_id

        if not api_transient_error:
            product["active"] = available

        product["availability_status"] = availability_status
        product["availability_checked_at"] = agora_iso()
        product["catalog_http_status"] = catalog_status
        product["offers_http_status"] = offers_status

    display_price = (
        float(product.get("fixed_price"))
        if product.get("fixed_price") is not None
        else (
            current_price
            if current_price is not None
            else product.get("price")
        )
    )

    return {
        "code": product.get("code"),
        "product_id": product_id,
        "status": "OK" if available else "UNAVAILABLE",
        "catalog_http": catalog_status,
        "offers_http": offers_status,
        "image": bool(image_url),
        "offers": len(offers),
        "price": display_price,
        "item_id": current_item_id,
        "price_sync_status": (
            "FIXED_PRICE"
            if product.get("fixed_price") is not None
            else price_sync_status
        ),
        "availability_status": availability_status,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Sincroniza imagem oficial, preço "
            "e disponibilidade da vitrine."
        )
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Consulta o Mercado Livre "
            "sem alterar products.json."
        ),
    )

    args = parser.parse_args()

    if not PRODUCTS_FILE.exists():
        raise FileNotFoundError(
            f"Arquivo não encontrado: "
            f"{PRODUCTS_FILE}"
        )

    data = carregar_json(
        PRODUCTS_FILE
    )

    products = data.get(
        "products",
        []
    )

    if not isinstance(
        products,
        list
    ):
        raise RuntimeError(
            "products.json inválido: "
            "'products' precisa ser uma lista."
        )

    print(
        "=" * 72
    )

    print(
        "VITRINE V1.2 - SYNC MERCADO LIVRE AUTENTICADO"
    )

    print(
        "=" * 72
    )

    print(
        f"Produtos: {len(products)}"
    )

    print(
        f"Dry-run: {args.dry_run}"
    )

    ml_token = obter_ml_token()

    print(
        "Token ML: "
        + (
            "encontrado"
            if ml_token
            else "NÃO encontrado"
        )
    )

    if not ml_token:
        print(
            "⚠ A sincronização pode receber 401/403. "
            "O Auto Pipeline usa um token ML do .env."
        )

    print()

    results = []

    for product in products:
        result = sincronizar_produto(
            product,
            dry_run=args.dry_run,
        )

        results.append(
            result
        )

        print(
            f"[{result.get('status')}] "
            f"{result.get('code')} "
            f"{result.get('product_id')}"
        )

        if result.get(
            "catalog_http"
        ) is not None:
            print(
                "  catálogo:",
                result.get(
                    "catalog_http"
                ),
            )

            print(
                "  ofertas :",
                result.get(
                    "offers_http"
                ),
            )

            print(
                "  imagem  :",
                (
                    "sim"
                    if result.get(
                        "image"
                    )
                    else "não"
                ),
            )

            print(
                "  ofertas :",
                result.get(
                    "offers"
                ),
            )

            price = result.get(
                "price"
            )

            if price is not None:
                print(
                    "  preço   : "
                    f"R$ {price:.2f}"
                )

            if result.get(
                "item_id"
            ):
                print(
                    "  item    :",
                    result.get(
                        "item_id"
                    ),
                )

            sync_status = result.get(
                "price_sync_status"
            )

            if sync_status:
                print(
                    "  preço sync:",
                    sync_status,
                )

            availability_status = result.get(
                "availability_status"
            )

            if availability_status:
                print(
                    "  disponibilidade:",
                    availability_status,
                )

        print()

    if not args.dry_run:
        data[
            "updated_at"
        ] = agora_iso()

        salvar_json(
            PRODUCTS_FILE,
            data,
        )

        print(
            "✓ products.json atualizado."
        )

    else:
        print(
            "✓ Dry-run concluído. "
            "Nenhum arquivo alterado."
        )


if __name__ == "__main__":
    main()
