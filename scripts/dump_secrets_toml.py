"""Streamlit Cloud の Secrets に貼り付ける TOML を標準出力に書き出す。

Usage:
    python scripts/dump_secrets_toml.py > secrets_for_streamlit_cloud.toml
    # 中身を Streamlit Cloud → Manage app → Settings → Secrets に貼り付け
    # 出力ファイルはコミットしないこと（.gitignore 済み）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def dump_section(name: str, info: dict) -> str:
    lines = [f"[{name}]"]
    for k, v in info.items():
        if isinstance(v, str) and "\n" in v:
            esc = v.replace('"""', '\\"\\"\\"')
            lines.append(f'{k} = """{esc}"""')
        elif isinstance(v, str):
            lines.append(f'{k} = "{v}"')
        elif isinstance(v, bool):
            lines.append(f"{k} = {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k} = {v}")
        else:
            lines.append(f'{k} = "{v}"')
    return "\n".join(lines)


def main() -> None:
    root = Path(__file__).resolve().parent.parent

    sa_path = root / "secrets" / "dashboard-bq-key.json"
    adc_path = Path(os.environ.get("APPDATA", "")) / "gcloud" / "application_default_credentials.json"

    out: list[str] = []
    out.append("# Streamlit Cloud → Manage app → Settings → Secrets に貼り付け")
    out.append("# ⚠️ このファイルはコミット禁止（.gitignore 済み）")
    out.append("")

    if sa_path.exists():
        with open(sa_path, "r", encoding="utf-8") as f:
            sa = json.load(f)
        out.append("# ── Sheets API 用 SA キー ──")
        out.append(dump_section("gcp_service_account", sa))
        out.append("")
    else:
        out.append(f"# SA key not found at {sa_path}\n")

    if adc_path.exists():
        with open(adc_path, "r", encoding="utf-8") as f:
            adc = json.load(f)
        if adc.get("type") == "authorized_user":
            out.append("# ── BigQuery 用 ユーザー ADC ──")
            out.append(dump_section("gcp_user_credentials", adc))
            out.append("")
        else:
            out.append(f"# ADC at {adc_path} is type={adc.get('type')!r}, not 'authorized_user'\n")
    else:
        out.append(f"# ADC not found at {adc_path}\n")

    print("\n".join(out))


if __name__ == "__main__":
    main()
