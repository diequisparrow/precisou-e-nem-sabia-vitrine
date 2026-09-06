from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import requests


ML_TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
TIMEOUT = 30


def required_env(name: str) -> str:
    value = str(os.getenv(name) or "").strip()

    if not value:
        raise RuntimeError(
            f"Variável obrigatória ausente: {name}"
        )

    return value


def mask_secret(value: str) -> None:
    # Comando especial do GitHub Actions: evita que o valor apareça nos logs.
    if value:
        print(f"::add-mask::{value}")


def append_github_env(name: str, value: str) -> None:
    env_file = str(
        os.getenv("GITHUB_ENV")
        or ""
    ).strip()

    if not env_file:
        raise RuntimeError(
            "GITHUB_ENV não encontrado. "
            "Este script foi criado para execução no GitHub Actions."
        )

    with Path(env_file).open(
        "a",
        encoding="utf-8",
    ) as f:
        f.write(
            f"{name}={value}\n"
        )


def atualizar_refresh_secret(
    new_refresh_token: str,
) -> None:
    repo = required_env(
        "GITHUB_REPOSITORY"
    )
    gh_secrets_token = required_env(
        "GH_SECRETS_TOKEN"
    )

    env = os.environ.copy()

    # O GitHub CLI usa GH_TOKEN para autenticação.
    env["GH_TOKEN"] = gh_secrets_token

    completed = subprocess.run(
        [
            "gh",
            "secret",
            "set",
            "ML_REFRESH_TOKEN",
            "--repo",
            repo,
        ],
        input=new_refresh_token,
        text=True,
        env=env,
        capture_output=True,
    )

    if completed.returncode != 0:
        stderr = (
            completed.stderr
            or ""
        ).strip()

        raise RuntimeError(
            "O Mercado Livre renovou o token, mas não foi possível "
            "salvar o novo ML_REFRESH_TOKEN no GitHub. "
            "Execução interrompida para evitar perder a cadeia de refresh. "
            f"gh exit={completed.returncode}. "
            f"Detalhe: {stderr[:500]}"
        )


def main() -> None:
    client_id = required_env(
        "ML_CLIENT_ID"
    )
    client_secret = required_env(
        "ML_CLIENT_SECRET"
    )
    refresh_token = required_env(
        "ML_REFRESH_TOKEN"
    )

    print(
        "Renovando credenciais Mercado Livre..."
    )

    response = requests.post(
        ML_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
        headers={
            "Accept": "application/json",
            "User-Agent": "AffiliateAI-Storefront-CI/1.0",
        },
        timeout=TIMEOUT,
    )

    if response.status_code != 200:
        body = (
            response.text
            or ""
        )[:1000]

        raise RuntimeError(
            "Falha ao renovar token Mercado Livre: "
            f"HTTP {response.status_code}. "
            f"Resposta: {body}"
        )

    data = response.json()

    access_token = str(
        data.get("access_token")
        or ""
    ).strip()

    new_refresh_token = str(
        data.get("refresh_token")
        or ""
    ).strip()

    expires_in = data.get(
        "expires_in"
    )

    if not access_token:
        raise RuntimeError(
            "Mercado Livre não retornou access_token."
        )

    if not new_refresh_token:
        raise RuntimeError(
            "Mercado Livre não retornou refresh_token."
        )

    mask_secret(
        access_token
    )
    mask_secret(
        new_refresh_token
    )

    # Primeiro preserva a cadeia de refresh para a próxima execução.
    atualizar_refresh_secret(
        new_refresh_token
    )

    # Só disponibiliza o access token para as etapas seguintes
    # depois que o novo refresh token foi salvo com sucesso.
    append_github_env(
        "ML_ACCESS_TOKEN",
        access_token,
    )

    print(
        "✓ ACCESS TOKEN renovado para esta execução."
    )
    print(
        "✓ ML_REFRESH_TOKEN atualizado no GitHub Secrets."
    )

    if expires_in is not None:
        print(
            f"  Expira em: {expires_in} segundos"
        )


if __name__ == "__main__":
    try:
        main()

    except Exception as exc:
        print(
            f"ERRO: {exc}",
            file=sys.stderr,
        )
        raise
