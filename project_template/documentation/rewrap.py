import pathlib
import re
import textwrap

W = 100

# Fields for which we want to consider automatic multiline conversion.
# You can add/remove fields here as needed.
MULTILINE_FIELDS = {
    "STATEMENT",
    "RATIONALE",
    "ACCEPTANCE",
    "VERIFICATION_METHOD",
    "OPERATING_MODES",
    "SAFE_STATE",
}


def rewrap_sdoc(path):
    lines = path.read_text().splitlines()
    out = []

    in_multiline = False

    for line in lines:
        stripped = line.strip()

        # Already inside a StrictDoc multiline field.
        if in_multiline:
            out.append(line)

            if stripped == "<<<":
                in_multiline = False

            continue

        # Preserve existing multiline blocks unchanged.
        #
        # Example:
        # STATEMENT: >>>
        # ...
        # <<<
        if re.match(r"^\s*\w[\w_]*:\s*>>>\s*$", line):
            out.append(line)
            in_multiline = True
            continue

        # Match a normal field:
        #
        #     STATEMENT: Some text...
        #
        # Capture indentation, field name, and value separately.
        match = re.match(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)

        if not match:
            out.append(line)
            continue

        indent, field, value = match.groups()

        # Only transform fields we're interested in.
        if field not in MULTILINE_FIELDS:
            out.append(line)
            continue

        # The complete original field line fits within the limit.
        if len(line) <= W:
            out.append(line)
            continue

        # Convert the field to StrictDoc multiline syntax.
        out.append(f"{indent}{field}: >>>")

        # Leave enough room for indentation.
        #
        # The text itself is indented by four spaces relative to
        # the field. Adjust this if your preferred StrictDoc style differs.
        text_indent = indent + ""
        available = W - len(text_indent)

        wrapped = textwrap.wrap(
            value,
            width=available,
            break_long_words=False,
            break_on_hyphens=False,
        )

        out.extend(text_indent + chunk for chunk in wrapped)
        out.append(f"{indent}<<<")

    if in_multiline:
        raise ValueError(f"Unterminated multiline field in {path}")

    path.write_text("\n".join(out) + "\n")


def rewrap_md(path):
    lines = path.read_text().splitlines()
    out = []
    in_fence = False
    para = []

    def flush():
        if para:
            out.extend(textwrap.wrap(" ".join(para), width=W))
            para.clear()

    for line in lines:
        if line.lstrip().startswith("```"):
            flush()
            in_fence = not in_fence
            out.append(line)

        elif in_fence:
            out.append(line)

        elif not line.strip():
            flush()
            out.append("")

        else:
            para.append(line.strip())

    flush()
    path.write_text("\n".join(out) + "\n")


for p in pathlib.Path("docs").rglob("*"):
    if not p.is_file():
        continue

    if p.suffix in (".sdoc", ".template"):
        rewrap_sdoc(p)
    elif p.suffix == ".md":
        rewrap_md(p)
