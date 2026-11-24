from pathlib import Path
import re


DIAGNOSTICS_DIR = Path(__file__).resolve().parents[2] / "supabase" / "diagnostics"


def _sql_statements(path: Path) -> list[str]:
    source = re.sub(r"/\\*.*?\\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
    source = re.sub(r"--[^\\n]*", "", source)
    return [part.strip() for part in source.split(";") if part.strip()]


def test_supabase_diagnostic_sql_files_are_select_only():
    files = sorted(DIAGNOSTICS_DIR.glob("*.sql"))
    assert files, "Expected read-only Supabase diagnostic scripts."

    for path in files:
        statements = _sql_statements(path)
        assert statements, f"{path.name} contains no SQL statements."
        for statement in statements:
            assert re.match(r"^(select|with)\\b", statement, flags=re.I), (
                f"{path.name} contains a non-read-only statement: "
                f"{statement[:100]!r}"
            )
