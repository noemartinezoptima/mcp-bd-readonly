from mcp_bd_readonly.setup import mcp_command


def test_mcp_command_ends_in_venv_bin():
    cmd = mcp_command()
    assert cmd.endswith(".venv/bin/mcp-optima-bd") or cmd.endswith(
        ".venv\\Scripts\\mcp-optima-bd.exe"
    )


def test_mcp_command_is_absolute():
    from pathlib import Path

    assert Path(mcp_command()).is_absolute()
