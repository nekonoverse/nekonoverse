"""FEP-521a Multikey 形式の Ed25519 鍵カラムを追加し、既存ローカル User に backfill する。

issue #1040 (Fedibird/Mitra 等が Ed25519 をサポートしているため対応)。
RSA 鍵は据え置きで、新カラムを追加するだけのため後方互換あり。

Revision ID: 044
Revises: 043
"""

import sqlalchemy as sa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from alembic import op

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None

# crypto.py と同一の定義 (migration を独立して動かせるよう手書きで複製)
_ED25519_MULTICODEC_PREFIX = b"\xed\x01"
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _base58btc_encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    out = ""
    while n > 0:
        n, r = divmod(n, 58)
        out = _BASE58_ALPHABET[r] + out
    for byte in data:
        if byte == 0:
            out = _BASE58_ALPHABET[0] + out
        else:
            break
    return out


def _gen_ed25519() -> tuple[str, str]:
    private_key = ed25519.Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    raw_public = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    multibase = "z" + _base58btc_encode(_ED25519_MULTICODEC_PREFIX + raw_public)
    return pem, multibase


def upgrade() -> None:
    op.add_column(
        "actors",
        sa.Column("public_key_ed25519_multibase", sa.String(255), nullable=True),
    )
    op.add_column(
        "actors",
        sa.Column("key_id_ed25519", sa.String(2048), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("private_key_ed25519_pem", sa.Text(), nullable=True),
    )

    # 既存ローカル User (actors.domain IS NULL) 全員に Ed25519 鍵ペアを生成して backfill。
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT u.id AS user_id, a.id AS actor_id, a.ap_id "
            "FROM users u JOIN actors a ON u.actor_id = a.id "
            "WHERE a.domain IS NULL"
        )
    ).fetchall()
    for row in rows:
        private_pem, multibase = _gen_ed25519()
        conn.execute(
            sa.text("UPDATE users SET private_key_ed25519_pem = :pem WHERE id = :uid"),
            {"pem": private_pem, "uid": row.user_id},
        )
        conn.execute(
            sa.text(
                "UPDATE actors SET public_key_ed25519_multibase = :mb, "
                "key_id_ed25519 = :kid WHERE id = :aid"
            ),
            {
                "mb": multibase,
                "kid": f"{row.ap_id}#ed25519-key",
                "aid": row.actor_id,
            },
        )


def downgrade() -> None:
    op.drop_column("users", "private_key_ed25519_pem")
    op.drop_column("actors", "key_id_ed25519")
    op.drop_column("actors", "public_key_ed25519_multibase")
