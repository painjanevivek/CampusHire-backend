from pathlib import Path


def test_production_shell_blocks_do_not_embed_dispatch_inputs() -> None:
    workflow = Path(".github/workflows/deploy-production.yml").read_text(encoding="utf-8")
    lines = workflow.splitlines()
    in_run_block = False
    run_indent = 0

    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if stripped.startswith("run:"):
            for expression in ("${{ inputs.", "${{ github.event.inputs."):
                assert expression not in stripped, (
                    "workflow_dispatch inputs must enter shell steps through env, "
                    "never as Bash source"
                )
            in_run_block = stripped.removeprefix("run:").lstrip().startswith(("|", ">"))
            run_indent = indent
            continue
        if in_run_block and stripped and indent <= run_indent:
            in_run_block = False
        if in_run_block:
            for expression in ("${{ inputs.", "${{ github.event.inputs."):
                assert expression not in line, (
                    "workflow_dispatch inputs must enter shell steps through env, "
                    "never as Bash source"
                )
