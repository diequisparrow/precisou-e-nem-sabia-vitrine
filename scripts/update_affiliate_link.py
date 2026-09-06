from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
PRODUCTS_FILE = PROJECT_ROOT / "public" / "products.json"
SYNC_SCRIPT = BASE_DIR / "sync_products.py"

VALID_LINK_HOSTS = {
    "meli.la",
    "www.meli.la",
    "mercadolivre.com.br",
    "www.mercadolivre.com.br",
    "mercadolibre.com",
    "www.mercadolibre.com",
}


def agora_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def carregar_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def salvar_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def texto(row: dict[str, Any], key: str) -> str:
    value = row.get(key)

    if value is None:
        return ""

    value = str(value).strip()

    if value.lower() in {"", "nan", "none", "null"}:
        return ""

    return value


def numero(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = texto(row, key)

        if not value:
            continue

        try:
            return float(value.replace(",", "."))
        except ValueError:
            continue

    return None


def resolver_affiliate_ai_root(override: str | None) -> Path:
    candidates: list[Path] = []

    if override:
        candidates.append(Path(override).expanduser())

    env_root = os.getenv("AFFILIATE_AI_ROOT")

    if env_root:
        candidates.append(Path(env_root).expanduser())

    candidates.extend(
        [
            PROJECT_ROOT.parent / "Affiliate_AI",
            Path.home() / "Documents" / "Affiliate_AI",
        ]
    )

    seen: set[str] = set()

    for candidate in candidates:
        try:
            key = str(candidate.resolve()).lower()
        except Exception:
            key = str(candidate).lower()

        if key in seen:
            continue

        seen.add(key)

        if (
            candidate.is_dir()
            and (candidate / "data" / "processed").is_dir()
        ):
            return candidate

    raise FileNotFoundError(
        "Projeto Affiliate_AI não encontrado. "
        "Use --affiliate-ai-root C:\\caminho\\Affiliate_AI."
    )


def extrair_numero_batch(path: Path) -> int:
    match = re.search(
        r"experiment_batch_(\d+)\.csv$",
        path.name,
        re.I,
    )

    if not match:
        return -1

    return int(match.group(1))


def encontrar_batch_latest(affiliate_root: Path) -> Path:
    processed_dir = affiliate_root / "data" / "processed"

    candidates = list(
        processed_dir.glob("experiment_batch_*.csv")
    )

    if not candidates:
        raise FileNotFoundError(
            "Nenhum experiment_batch_*.csv encontrado em "
            f"{processed_dir}"
        )

    return max(
        candidates,
        key=extrair_numero_batch,
    )


def resolver_batch(
    affiliate_root: Path,
    batch_file: str | None,
) -> Path:
    if not batch_file:
        return encontrar_batch_latest(
            affiliate_root
        )

    path = Path(batch_file).expanduser()

    if not path.is_absolute():
        path = affiliate_root / path

    if not path.is_file():
        raise FileNotFoundError(
            f"Batch não encontrado: {path}"
        )

    return path


def carregar_batch(path: Path) -> list[dict[str, str]]:
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        return list(
            csv.DictReader(f)
        )


def localizar_produto(
    products: list[dict[str, Any]],
    product_id: str,
) -> dict[str, Any] | None:
    wanted = product_id.upper().strip()

    for product in products:
        current = str(
            product.get("product_id")
            or ""
        ).upper().strip()

        if current == wanted:
            return product

    return None


def escolher_candidato(
    rows: list[dict[str, str]],
    products: list[dict[str, Any]],
    product_id: str | None,
) -> dict[str, str]:
    if product_id:
        wanted = product_id.upper().strip()

        for row in rows:
            if (
                texto(
                    row,
                    "catalog_product_id",
                ).upper()
                == wanted
            ):
                return row

        raise RuntimeError(
            f"Produto {wanted} não encontrado no batch."
        )

    pending: list[dict[str, str]] = []

    for row in rows:
        pid = texto(
            row,
            "catalog_product_id",
        ).upper()

        if not pid:
            continue

        status = texto(
            row,
            "pipeline_status",
        ).upper()

        if status != "DRAFT":
            continue

        existing = localizar_produto(
            products,
            pid,
        )

        if (
            existing
            and str(
                existing.get("affiliate_url")
                or ""
            ).strip()
        ):
            continue

        pending.append(row)

    pending.sort(
        key=lambda row: int(
            float(
                texto(
                    row,
                    "batch_order",
                )
                or "0"
            )
        )
    )

    if not pending:
        raise RuntimeError(
            "Nenhum produto DRAFT aguardando link no batch latest. "
            "Use --product-id MLB... para selecionar explicitamente."
        )

    if len(pending) == 1:
        return pending[0]

    print()
    print("Mais de um Draft aguarda link:")
    print()

    for pos, row in enumerate(
        pending,
        start=1,
    ):
        pid = texto(
            row,
            "catalog_product_id",
        )
        rank = texto(
            row,
            "batch_order",
        ) or "-"
        title = texto(
            row,
            "title",
        )
        price = numero(
            row,
            "validated_current_price",
            "price",
        )
        price_text = (
            f"R$ {price:.2f}".replace(".", ",")
            if price is not None
            else "-"
        )

        print(
            f"  {pos}. rank {rank} | {pid} | "
            f"{price_text} | {title}"
        )

    while True:
        raw = input(
            "\nEscolha o número do produto: "
        ).strip()

        try:
            selected = int(raw)
        except ValueError:
            print(
                "Digite somente o número da opção."
            )
            continue

        if 1 <= selected <= len(pending):
            return pending[selected - 1]

        print("Opção inválida.")


def validar_link(link: str) -> str:
    link = link.strip()

    if not link:
        raise RuntimeError(
            "Link de afiliado vazio."
        )

    parsed = urlparse(link)

    if parsed.scheme.lower() not in {
        "http",
        "https",
    }:
        raise RuntimeError(
            "O link precisa começar com http:// ou https://."
        )

    host = (
        parsed.hostname
        or ""
    ).lower()

    if host not in VALID_LINK_HOSTS:
        raise RuntimeError(
            "Domínio inesperado para link Mercado Livre: "
            f"{host or '(vazio)'}"
        )

    return link


def proximo_codigo(
    products: list[dict[str, Any]],
) -> str:
    numbers: list[int] = []

    for product in products:
        code = str(
            product.get("code")
            or ""
        ).strip()

        if code.isdigit():
            numbers.append(
                int(code)
            )

    next_number = max(
        numbers,
        default=0,
    ) + 1

    return str(next_number).zfill(
        max(
            2,
            len(str(next_number)),
        )
    )


def descricao_padrao(title: str) -> str:
    lower = title.lower()

    if (
        "magn" in lower
        and (
            "bloco" in lower
            or "cubo" in lower
        )
    ):
        return (
            "Blocos magnéticos para montar estruturas, "
            "explorar a criatividade e criar diferentes construções."
        )

    return (
        "Produto selecionado nos nossos vídeos. "
        "Confira os detalhes e a oferta atual no Mercado Livre."
    )


def montar_produto(
    data: dict[str, Any],
    row: dict[str, str],
    affiliate_url: str,
) -> tuple[dict[str, Any], bool]:
    products = data.setdefault(
        "products",
        [],
    )

    if not isinstance(
        products,
        list,
    ):
        raise RuntimeError(
            "products.json inválido: "
            "'products' precisa ser uma lista."
        )

    product_id = texto(
        row,
        "catalog_product_id",
    ).upper()

    item_id = texto(
        row,
        "validated_item_id",
    ).upper()

    if not item_id:
        raise RuntimeError(
            f"{product_id} não possui validated_item_id no batch. "
            "Execute o preflight/auto comercial antes de cadastrar na vitrine."
        )

    title = texto(
        row,
        "title",
    ) or product_id

    current_price = numero(
        row,
        "validated_current_price",
        "price",
    )

    if current_price is None:
        raise RuntimeError(
            f"{product_id} não possui preço validado no batch."
        )

    checked_at = texto(
        row,
        "availability_checked_at",
    )

    price_checked_at = (
        checked_at[:10]
        if checked_at
        else datetime.now().date().isoformat()
    )

    product = localizar_produto(
        products,
        product_id,
    )

    created = product is None

    if product is None:
        product = {
            "code": proximo_codigo(
                products
            ),
            "product_id": product_id,
            "title": title,
            "short_description": descricao_padrao(
                title
            ),
            "price": current_price,
            "currency": "BRL",
            "price_checked_at": price_checked_at,
            "affiliate_url": affiliate_url,
            "ml_public_id": "",
            "image_url": "",
            "badges": [],
            "active": True,
            "featured": False,
        }

        products.append(
            product
        )

    else:
        product[
            "affiliate_url"
        ] = affiliate_url

        if not str(
            product.get("title")
            or ""
        ).strip():
            product[
                "title"
            ] = title

        product[
            "price"
        ] = current_price

        product[
            "price_checked_at"
        ] = price_checked_at

    product[
        "affiliate_item_id"
    ] = item_id

    product[
        "validated_item_id"
    ] = item_id

    product[
        "source_batch"
    ] = texto(
        row,
        "batch_id",
    )

    product[
        "source_batch_order"
    ] = texto(
        row,
        "batch_order",
    )

    product[
        "source_pipeline_status"
    ] = texto(
        row,
        "pipeline_status",
    )

    product[
        "affiliate_link_updated_at"
    ] = agora_iso()

    data[
        "updated_at"
    ] = agora_iso()

    return (
        product,
        created,
    )


def criar_backup() -> Path:
    backup_dir = (
        PROJECT_ROOT
        / "backups"
    )
    backup_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    stamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    backup = (
        backup_dir
        / f"products_before_affiliate_link_{stamp}.json"
    )

    shutil.copy2(
        PRODUCTS_FILE,
        backup,
    )

    return backup


def executar(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        text=True,
        check=check,
    )


def executar_sync(
    affiliate_root: Path,
) -> None:
    if not SYNC_SCRIPT.is_file():
        raise FileNotFoundError(
            f"Sync não encontrado: {SYNC_SCRIPT}"
        )

    env = os.environ.copy()
    env_file = affiliate_root / ".env"

    if env_file.is_file():
        env[
            "AFFILIATE_AI_ENV_FILE"
        ] = str(env_file)

    print()
    print("=" * 72)
    print("SYNC MERCADO LIVRE")
    print("=" * 72)

    executar(
        [
            sys.executable,
            str(SYNC_SCRIPT),
        ],
        cwd=PROJECT_ROOT,
        env=env,
    )


def validar_pos_sync(
    product_id: str,
) -> dict[str, Any]:
    data = carregar_json(
        PRODUCTS_FILE
    )

    products = data.get(
        "products",
        [],
    )

    product = localizar_produto(
        products,
        product_id,
    )

    if product is None:
        raise RuntimeError(
            f"{product_id} desapareceu de products.json após o sync."
        )

    last_sync_status = str(
        product.get("last_sync_status")
        or ""
    ).strip()

    if last_sync_status == "API_ERROR_KEEP_PREVIOUS":
        raise RuntimeError(
            "Sync recebeu erro transitório do Mercado Livre. "
            "A publicação foi interrompida para não versionar "
            "um produto novo sem validação."
        )

    catalog_http = product.get(
        "catalog_http_status"
    )

    offers_http = product.get(
        "offers_http_status"
    )

    if (
        catalog_http != 200
        or offers_http != 200
    ):
        raise RuntimeError(
            "Sync não validou Mercado Livre com HTTP 200/200: "
            f"catálogo={catalog_http}, ofertas={offers_http}."
        )

    affiliate_item_id = str(
        product.get("affiliate_item_id")
        or ""
    ).strip()

    if (
        affiliate_item_id
        and product.get(
            "price_sync_status"
        )
        != "EXACT_AFFILIATE_ITEM"
    ):
        raise RuntimeError(
            "O anúncio afiliado exato não foi confirmado no sync: "
            f"{product.get('price_sync_status')}."
        )

    return product


def git_commit_product(
    product_id: str,
    *,
    created: bool,
) -> bool:
    status = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--",
            "public/products.json",
        ],
        cwd=str(PROJECT_ROOT),
        text=True,
        capture_output=True,
        check=True,
    )

    if not status.stdout.strip():
        print()
        print(
            "○ products.json sem alteração para commit."
        )
        return False

    executar(
        [
            "git",
            "add",
            "public/products.json",
        ],
        cwd=PROJECT_ROOT,
    )

    message = (
        f"Add product {product_id} to storefront"
        if created
        else f"Update affiliate link {product_id}"
    )

    executar(
        [
            "git",
            "commit",
            "-m",
            message,
        ],
        cwd=PROJECT_ROOT,
    )

    return True


def git_push() -> None:
    executar(
        [
            "git",
            "push",
        ],
        cwd=PROJECT_ROOT,
    )


def confirmar() -> bool:
    raw = input(
        "\nAtualizar, sincronizar e publicar a vitrine? [S/n] "
    ).strip().lower()

    return raw in {
        "",
        "s",
        "sim",
        "y",
        "yes",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Recebe o link afiliado de um produto Draft do Affiliate_AI, "
            "atualiza a vitrine oficial, sincroniza com o Mercado Livre "
            "e opcionalmente faz commit/push."
        )
    )

    parser.add_argument(
        "--product-id",
        help=(
            "catalog_product_id MLB... "
            "Se omitido, procura Draft pendente."
        ),
    )

    parser.add_argument(
        "--link",
        help=(
            "Link afiliado Mercado Livre. "
            "Se omitido, solicita no terminal."
        ),
    )

    parser.add_argument(
        "--batch-file",
        help=(
            "Batch CSV específico. "
            "Se omitido, usa o maior experiment_batch_NNN.csv."
        ),
    )

    parser.add_argument(
        "--affiliate-ai-root",
        help=(
            "Caminho do Affiliate_AI. "
            "Normalmente é detectado automaticamente."
        ),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Mostra o que seria feito sem alterar arquivos, "
            "sync ou Git."
        ),
    )

    parser.add_argument(
        "--no-sync",
        action="store_true",
        help="Não executa sync_products.py.",
    )

    parser.add_argument(
        "--no-git",
        action="store_true",
        help="Não cria commit nem faz push.",
    )

    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Cria commit local, mas não faz git push.",
    )

    parser.add_argument(
        "--yes",
        action="store_true",
        help="Não pede confirmação interativa.",
    )

    args = parser.parse_args()

    if not PRODUCTS_FILE.is_file():
        raise FileNotFoundError(
            f"products.json não encontrado: {PRODUCTS_FILE}"
        )

    affiliate_root = resolver_affiliate_ai_root(
        args.affiliate_ai_root
    )

    batch_file = resolver_batch(
        affiliate_root,
        args.batch_file,
    )

    data = carregar_json(
        PRODUCTS_FILE
    )

    products = data.get(
        "products",
        [],
    )

    if not isinstance(
        products,
        list,
    ):
        raise RuntimeError(
            "products.json inválido: "
            "'products' precisa ser uma lista."
        )

    rows = carregar_batch(
        batch_file
    )

    candidate = escolher_candidato(
        rows,
        products,
        args.product_id,
    )

    product_id = texto(
        candidate,
        "catalog_product_id",
    ).upper()

    item_id = texto(
        candidate,
        "validated_item_id",
    ).upper()

    title = texto(
        candidate,
        "title",
    )

    price = numero(
        candidate,
        "validated_current_price",
        "price",
    )

    pipeline_status = texto(
        candidate,
        "pipeline_status",
    )

    affiliate_url = args.link

    print()
    print("=" * 72)
    print("AFFILIATE AI - LINK -> VITRINE V2")
    print("=" * 72)
    print(f"Vitrine:     {PROJECT_ROOT}")
    print(f"Affiliate:   {affiliate_root}")
    print(f"Batch:       {batch_file.name}")
    print(f"Produto:     {product_id}")
    print(f"Item ML:     {item_id or '-'}")
    print(f"Status:      {pipeline_status or '-'}")

    if price is not None:
        print(
            f"Preço:       R$ {price:.2f}".replace(".", ",")
        )

    print(f"Título:      {title}")

    if not affiliate_url:
        print()
        affiliate_url = input(
            "Cole o link de afiliado Mercado Livre:\n> "
        )

    affiliate_url = validar_link(
        affiliate_url
    )

    preview = json.loads(
        json.dumps(data)
    )

    product_preview, created = montar_produto(
        preview,
        candidate,
        affiliate_url,
    )

    print()
    print("Plano:")
    print(
        f"  Ação:      {'ADICIONAR' if created else 'ATUALIZAR'}"
    )
    print(
        f"  Código:    {product_preview.get('code')}"
    )
    print(
        f"  Produto:   {product_preview.get('product_id')}"
    )
    print(
        f"  Item:      {product_preview.get('affiliate_item_id')}"
    )
    print(
        f"  Link:      {product_preview.get('affiliate_url')}"
    )
    print(
        f"  Preço:     R$ {float(product_preview.get('price') or 0):.2f}"
        .replace(".", ",")
    )
    print(
        f"  Sync:      {'NÃO' if args.no_sync else 'SIM'}"
    )
    print(
        f"  Git:       {'NÃO' if args.no_git else 'SIM'}"
    )
    print(
        f"  Push:      {'NÃO' if args.no_git or args.no_push else 'SIM'}"
    )

    if args.dry_run:
        print()
        print("DRY-RUN CONCLUÍDO")
        print("Nenhum arquivo foi alterado.")
        return

    if (
        not args.yes
        and not confirmar()
    ):
        print(
            "Operação cancelada."
        )
        return

    backup = criar_backup()
    commit_created = False

    try:
        salvar_json(
            PRODUCTS_FILE,
            preview,
        )

        print()
        print(
            f"✓ products.json atualizado: {PRODUCTS_FILE}"
        )
        print(
            f"✓ Backup: {backup}"
        )

        if not args.no_sync:
            executar_sync(
                affiliate_root
            )

            synced_product = validar_pos_sync(
                product_id
            )

            print()
            print(
                "✓ Sync validado: "
                f"{synced_product.get('price_sync_status')} | "
                f"{synced_product.get('availability_status')}"
            )

        if not args.no_git:
            commit_created = git_commit_product(
                product_id,
                created=created,
            )

            if (
                commit_created
                and not args.no_push
            ):
                git_push()

    except Exception:
        if commit_created:
            print()
            print(
                "✗ Falha após o commit local. "
                "O commit foi preservado; corrija a causa e rode git push novamente."
            )
        else:
            shutil.copy2(
                backup,
                PRODUCTS_FILE,
            )

            print()
            print(
                "✗ Falha antes do commit. "
                "products.json restaurado a partir do backup."
            )

        raise

    print()
    print("=" * 72)
    print("VITRINE ATUALIZADA")
    print("=" * 72)
    print(f"Produto: {product_id}")
    print(f"Código:  {product_preview.get('code')}")

    if not args.no_git and not args.no_push:
        print(
            "✓ Commit/push concluído. "
            "Cloudflare pode iniciar o deploy automático."
        )


if __name__ == "__main__":
    main()
