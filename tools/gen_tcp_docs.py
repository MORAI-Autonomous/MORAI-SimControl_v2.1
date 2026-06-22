from __future__ import annotations

import argparse
from datetime import datetime
import html
import re
import subprocess
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (SRC, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import transport.protocol_defs as proto
from transport.message_schema import (
    describe_payload_size,
    FieldSpec,
    get_message,
    get_response_message,
    get_min_payload_size,
    iter_messages,
    iter_notification_messages,
    iter_response_messages,
    render_struct_format,
    render_wire_type,
)
OUTPUT_PATH = ROOT / "docs" / "tcp-api.md"
HTML_OUTPUT_PATH = ROOT / "docs" / "tcp-api.html"


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _run_git(args: Sequence[str], repo_root: Path = ROOT) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_root), *args],
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def render_generation_note(revision_root: Path = ROOT, revision_ref: str | None = None) -> list[str]:
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z")
    if revision_ref:
        revision = revision_ref
    else:
        branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], revision_root)
        revision = branch if branch != "unknown" else "unknown"
    return [
        "> \uc774 \ubb38\uc11c\ub294 \uc790\ub3d9 \uc0dd\uc131\ub429\ub2c8\ub2e4. Confluence\uc5d0\uc11c \uc9c1\uc811 \ud3b8\uc9d1\ud558\uc9c0 \ub9d0\uace0 \ucf54\ub4dc\uc640 \uc2a4\ud06c\ub9bd\ud2b8\uc5d0\uc11c \uc218\uc815\ud55c \ub4a4 \ub2e4\uc2dc \uc0dd\uc131\ud558\uc138\uc694.",
        ">",
        f"> - \uc0dd\uc131 \uc2dc\uac01: `{generated_at}`",
        f"> - \uae30\uc900 \ube0c\ub79c\uce58: `{revision}`",
    ]


def validate_schema_against_protocol_defs() -> None:
    msg_1001 = get_message(0x1001)
    _expect(get_min_payload_size(msg_1001) == 0, "0x1001 request size mismatch")

    msg_1002 = get_message(0x1002)
    _expect(get_min_payload_size(msg_1002) == 0, "0x1002 request size mismatch")

    msg_1003 = get_message(0x1003)
    _expect(proto.SET_SIMULATOR_MODE_REQ_SIZE == get_min_payload_size(msg_1003), "0x1003 request size mismatch")

    msg_1004 = get_message(0x1004)
    _expect(get_min_payload_size(msg_1004) == 4, "0x1004 request size mismatch")

    msg_1102 = get_message(0x1102)
    _expect(
        proto.SET_SIM_TIME_MODE_REQ_SIZE == get_min_payload_size(msg_1102),
        "0x1102 request size mismatch",
    )

    msg_1201 = get_message(0x1201)
    _expect(proto.SET_TRAJECTORY_FOLLOW_MODE_SIZE == 4, "internal protocol size invariant changed")
    _expect(get_min_payload_size(msg_1201) == 4, "0x1201 min size mismatch")

    msg_1302 = get_message(0x1302)
    _expect(proto.MANUAL_CONTROL_BY_ID_VALUES_FMT.endswith("ddd"), "0x1302 format mismatch")
    _expect(proto.MANUAL_CONTROL_BY_ID_MIN_SIZE == get_min_payload_size(msg_1302), "0x1302 min size mismatch")

    msg_1303 = get_message(0x1303)
    _expect(proto.TRANSFORM_CONTROL_BY_ID_VALUES_FMT.endswith("fffffffd"), "0x1303 format mismatch")
    _expect(proto.TRANSFORM_CONTROL_BY_ID_MIN_SIZE == get_min_payload_size(msg_1303), "0x1303 min size mismatch")

    msg_1304 = get_message(0x1304)
    _expect(proto.SET_TRAJECTORY_MIN_SIZE == get_min_payload_size(msg_1304), "0x1304 min size mismatch")

    msg_1402 = get_message(0x1402)
    _expect(get_min_payload_size(msg_1402) == 4, "0x1402 min size mismatch")

    msg_1505 = get_message(0x1505)
    _expect(get_min_payload_size(msg_1505) == 8, "0x1505 min size mismatch")

    msg_1601 = get_message(0x1601)
    _expect(get_min_payload_size(msg_1601) == 4, "0x1601 min size mismatch")

    msg_1602 = get_message(0x1602)
    _expect(get_min_payload_size(msg_1602) == 8, "0x1602 request size mismatch")

    resp_1101 = get_response_message(0x1101)
    _expect(get_min_payload_size(resp_1101) == proto.GET_STATUS_SIZE, "0x1101 response size mismatch")

    resp_1102 = get_response_message(0x1102)
    _expect(proto.SET_SIM_TIME_MODE_RESP_SIZE == get_min_payload_size(resp_1102), "0x1102 response size mismatch")

    resp_1001 = get_response_message(0x1001)
    _expect(proto.GET_SIMULATOR_STATUS_SIZE == get_min_payload_size(resp_1001), "0x1001 response size mismatch")

    resp_1002 = get_response_message(0x1002)
    _expect(proto.GET_SIMULATOR_MODE_RESP_SIZE == get_min_payload_size(resp_1002), "0x1002 response size mismatch")

    resp_1003 = get_response_message(0x1003)
    _expect(proto.RESULT_SIZE == get_min_payload_size(resp_1003), "0x1003 response size mismatch")

    resp_1004 = get_response_message(0x1004)
    _expect(proto.RESULT_SIZE == get_min_payload_size(resp_1004), "0x1004 response size mismatch")

    resp_1201 = get_response_message(0x1201)
    _expect(proto.RESULT_SIZE == get_min_payload_size(resp_1201), "0x1201 response size mismatch")

    resp_1202 = get_response_message(0x1202)
    _expect(proto.RESULT_SIZE == get_min_payload_size(resp_1202), "0x1202 response size mismatch")

    resp_1301 = get_response_message(0x1301)
    _expect(get_min_payload_size(resp_1301) == proto.RESULT_SIZE + 4, "0x1301 response min size mismatch")

    resp_1302 = get_response_message(0x1302)
    _expect(proto.RESULT_SIZE == get_min_payload_size(resp_1302), "0x1302 response size mismatch")

    resp_1303 = get_response_message(0x1303)
    _expect(proto.RESULT_SIZE == get_min_payload_size(resp_1303), "0x1303 response size mismatch")

    resp_1304 = get_response_message(0x1304)
    _expect(proto.RESULT_SIZE == get_min_payload_size(resp_1304), "0x1304 response size mismatch")

    msg_1305 = get_message(0x1305)
    _expect(get_min_payload_size(msg_1305) == 0, "0x1305 request min size mismatch")

    resp_1305 = get_response_message(0x1305)
    _expect(proto.RESULT_SIZE == get_min_payload_size(resp_1305), "0x1305 response size mismatch")

    resp_1401 = get_response_message(0x1401)
    _expect(
        proto.RESULT_SIZE + proto.ACTIVE_SUITE_STATUS_RESP_MIN_SIZE == get_min_payload_size(resp_1401),
        "0x1401 response min size mismatch",
    )

    resp_1402 = get_response_message(0x1402)
    _expect(proto.RESULT_SIZE == get_min_payload_size(resp_1402), "0x1402 response size mismatch")

    resp_1504 = get_response_message(0x1504)
    _expect(get_min_payload_size(resp_1504) == 16, "0x1504 response size mismatch")

    resp_1505 = get_response_message(0x1505)
    _expect(proto.RESULT_SIZE == get_min_payload_size(resp_1505), "0x1505 response size mismatch")

    resp_1601 = get_response_message(0x1601)
    _expect(proto.RESULT_SIZE == get_min_payload_size(resp_1601), "0x1601 response size mismatch")

    resp_1602 = get_response_message(0x1602)
    _expect(proto.RESULT_SIZE == get_min_payload_size(resp_1602), "0x1602 response size mismatch")


def append_field_table(lines: list[str], fields: Sequence[FieldSpec]) -> None:
    lines.extend(
        [
            "| Field | Type | Description |",
            "|------|------|-------------|",
        ]
    )
    for field in fields:
        desc = field.description or "-"
        if field.field_type == "string_u32":
            lines.append(f"| `{field.name}_len` | `uint32` | {field.name} UTF-8 byte length |")
            lines.append(f"| `{field.name}` | `utf-8 bytes` | {desc} |")
        else:
            lines.append(f"| `{field.name}` | `{render_wire_type(field.field_type)}` | {desc} |")
    lines.append("")


def render_message_section(message: MessageSpec) -> str:
    binding_label = "Builder" if message.direction == "request" else "Parser"
    binding_value = message.handler if message.direction == "request" else message.parser
    lines = [
        f"## `0x{message.msg_type:04X}` {message.name}",
        "",
        f"- Direction: `{message.direction}`",
        f"- Payload: `{describe_payload_size(message)}`",
        f"- {binding_label}: `{binding_value}`" if binding_value else f"- {binding_label}: n/a",
        "",
        message.summary,
        "",
        f"Wire layout: `{render_struct_format(message.fields)}`" if message.fields else "Wire layout: variant-specific",
        "",
    ]

    if message.fields:
        append_field_table(lines, message.fields)
    elif not message.variants:
        lines.append("This message has no payload.\n")

    if message.variants:
        lines.append("Variants:")
        lines.append("")
        for variant in message.variants:
            lines.append(f"### {variant.name}")
            lines.append("")
            if variant.summary:
                lines.append(f"- Selector: `{variant.summary}`")
                lines.append("")
            lines.append(f"Wire layout: `{render_struct_format(variant.fields)}`")
            lines.append("")
            append_field_table(lines, variant.fields)

    if message.repeat_fields:
        lines.extend(
            [
                "Repeat layout:",
                "",
            ]
        )
        append_field_table(lines, message.repeat_fields)

    if message.notes:
        lines.append("Notes:")
        for note in message.notes:
            lines.append(f"- {note}")
        lines.append("")

    return "\n".join(lines)


def render_endpoint_section(title: str, message) -> list[str]:
    binding_label = "Builder" if message.direction == "request" else "Parser"
    binding_value = message.handler if message.direction == "request" else message.parser
    lines = [
        f"### {title}",
        "",
        f"- Payload: `{describe_payload_size(message)}`",
        f"- {binding_label}: `{binding_value}`" if binding_value else f"- {binding_label}: n/a",
        "",
        message.summary,
        "",
        f"Wire layout: `{render_struct_format(message.fields)}`" if message.fields else "Wire layout: variant-specific",
        "",
    ]

    if message.fields:
        append_field_table(lines, message.fields)
    elif not message.variants:
        lines.append("This message has no payload.\n")

    if message.variants:
        lines.append("Variants:")
        lines.append("")
        for variant in message.variants:
            lines.append(f"#### {variant.name}")
            lines.append("")
            if variant.summary:
                lines.append(f"- Selector: `{variant.summary}`")
                lines.append("")
            lines.append(f"Wire layout: `{render_struct_format(variant.fields)}`")
            lines.append("")
            append_field_table(lines, variant.fields)

    if message.repeat_fields:
        lines.extend(
            [
                "Repeat layout:",
                "",
            ]
        )
        append_field_table(lines, message.repeat_fields)

    if message.notes:
        lines.append("Notes:")
        for note in message.notes:
            lines.append(f"- {note}")
        lines.append("")

    return lines


def render_api_anchor(msg_type: int) -> str:
    return f"api-0x{msg_type:04x}"


def render_summary_rows(request_messages: list[MessageSpec], response_messages: list[MessageSpec]) -> list[str]:
    response_by_type = {message.msg_type: message for message in response_messages}
    seen_msg_types = set()
    rows: list[str] = []

    for request in request_messages:
        response = response_by_type.get(request.msg_type)
        anchor = render_api_anchor(request.msg_type)
        rows.append(
            f"| [`0x{request.msg_type:04X}`](#{anchor}) | [`{request.name}`](#{anchor}) | "
            f"`{describe_payload_size(request)}` | "
            f"`{describe_payload_size(response) if response else '-'}` |"
        )
        seen_msg_types.add(request.msg_type)

    for response in response_messages:
        if response.msg_type in seen_msg_types:
            continue
        anchor = render_api_anchor(response.msg_type)
        rows.append(
            f"| [`0x{response.msg_type:04X}`](#{anchor}) | [`{response.name}`](#{anchor}) | "
            f"`-` | `{describe_payload_size(response)}` |"
        )

    return rows


def render_document(revision_root: Path = ROOT, revision_ref: str | None = None) -> str:
    request_messages = list(iter_messages())
    response_messages = list(iter_response_messages())
    notification_messages = list(iter_notification_messages())
    request_by_type = {message.msg_type: message for message in request_messages}
    response_by_type = {message.msg_type: message for message in response_messages}
    notification_by_type = {message.msg_type: message for message in notification_messages}
    ordered_msg_types = []
    for message in request_messages + response_messages + notification_messages:
        if message.msg_type not in ordered_msg_types:
            ordered_msg_types.append(message.msg_type)
    lines = [
        "# TCP API Reference",
        "",
        *render_generation_note(revision_root, revision_ref),
        "",
        "## Common Header",
        "",
        "Every TCP packet uses this 16-byte header before the payload described below.",
        "",
        "| Offset | Type | Field | Description |",
        "|--------|------|-------|-------------|",
        "| `+0` | `uint8` | `magic` | Fixed magic byte `0x4D` (`'M'`) |",
        "| `+1` | `uint8` | `msg_class` | `0x01` = request, `0x02` = response, `0x03` = notification |",
        "| `+2` | `uint32` | `msg_type` | Command / response type such as `0x1102` |",
        "| `+6` | `uint32` | `payload_size` | Payload size in bytes, excluding the 16-byte header |",
        "| `+10` | `uint32` | `request_id` | Request / response correlation id |",
        "| `+14` | `uint16` | `flag` | Reserved, currently `0` |",
        "",
        "- Header format: `proto.HEADER_FMT = <BBIIIH`",
        "- Header size: `16 bytes`",
        "- Payload sizes shown in this document do not include the 16-byte header.",
        "",
        "## Summary",
        "",
        "| Msg Type | Name | Request Payload | Response Payload |",
        "|----------|------|-----------------|------------------|",
    ]
    for row in render_summary_rows(request_messages, response_messages):
        lines.append(row)
    lines.append("")

    lines.append("## APIs")
    lines.append("")
    for msg_type in ordered_msg_types:
        base = request_by_type.get(msg_type) or response_by_type.get(msg_type) or notification_by_type.get(msg_type)
        lines.append(f'<a id="{render_api_anchor(msg_type)}"></a>')
        lines.append(f"## `0x{msg_type:04X}` {base.name}")
        lines.append("")
        if msg_type in request_by_type:
            lines.extend(render_endpoint_section("Req", request_by_type[msg_type]))
        if msg_type in response_by_type:
            lines.extend(render_endpoint_section("Resp", response_by_type[msg_type]))
        if msg_type in notification_by_type:
            lines.extend(render_endpoint_section("Noti", notification_by_type[msg_type]))

    return "\n".join(lines).rstrip() + "\n"


def render_inline_html(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", lambda match: f"<code>{match.group(1)}</code>", escaped)
    escaped = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda match: f'<a href="{html.escape(match.group(2), quote=True)}">{match.group(1)}</a>',
        escaped,
    )
    return escaped


def render_table_html(lines: Sequence[str]) -> str:
    rows = []
    for index, line in enumerate(lines):
        if index == 1:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        tag = "th" if index == 0 else "td"
        rows.append(
            "<tr>"
            + "".join(f"<{tag}>{render_inline_html(cell)}</{tag}>" for cell in cells)
            + "</tr>"
        )
    return "<table>\n" + "\n".join(rows) + "\n</table>"


def render_markdown_as_html(markdown: str) -> str:
    lines = markdown.splitlines()
    output: list[str] = []
    paragraph: list[str] = []
    index = 0

    def flush_paragraph() -> None:
        if paragraph:
            output.append(f"<p>{render_inline_html(' '.join(paragraph))}</p>")
            paragraph.clear()

    while index < len(lines):
        line = lines[index]

        if not line.strip():
            flush_paragraph()
            index += 1
            continue

        if line.startswith("```"):
            flush_paragraph()
            index += 1
            code_lines = []
            while index < len(lines) and not lines[index].startswith("```"):
                code_lines.append(lines[index])
                index += 1
            output.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
            index += 1
            continue

        if line.startswith("<a id="):
            flush_paragraph()
            output.append(line)
            index += 1
            continue

        heading = re.match(r"^(#{1,4})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            output.append(f"<h{level}>{render_inline_html(heading.group(2))}</h{level}>")
            index += 1
            continue

        if line.startswith("> "):
            flush_paragraph()
            output.append(f"<blockquote>{render_inline_html(line[2:])}</blockquote>")
            index += 1
            continue

        if line.startswith("- "):
            flush_paragraph()
            items = []
            while index < len(lines) and lines[index].startswith("- "):
                items.append(f"<li>{render_inline_html(lines[index][2:])}</li>")
                index += 1
            output.append("<ul>\n" + "\n".join(items) + "\n</ul>")
            continue

        if line.startswith("|") and index + 1 < len(lines) and lines[index + 1].startswith("|"):
            flush_paragraph()
            table_lines = []
            while index < len(lines) and lines[index].startswith("|"):
                table_lines.append(lines[index])
                index += 1
            output.append(render_table_html(table_lines))
            continue

        paragraph.append(line.strip())
        index += 1

    flush_paragraph()

    style = """
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.5;
  color: #172b4d;
}
table {
  border-collapse: collapse;
  width: 1183px;
  max-width: 100%;
  margin: 12px 0;
}
th, td {
  border: 1px solid #dfe1e6;
  padding: 6px 8px;
  text-align: left;
  vertical-align: top;
}
th {
  background: #f4f5f7;
}
code {
  background: #f4f5f7;
  border-radius: 3px;
  padding: 1px 3px;
}
pre {
  background: #f4f5f7;
  border-radius: 3px;
  padding: 12px;
  overflow-x: auto;
}
blockquote {
  border-left: 4px solid #dfe1e6;
  color: #44546f;
  margin-left: 0;
  padding-left: 12px;
}
""".strip()
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        "<title>TCP API Reference</title>\n"
        f"<style>\n{style}\n</style>\n"
        "</head>\n"
        "<body>\n"
        + "\n".join(output)
        + "\n</body>\n</html>\n"
    )


def normalize_generated_at(text: str) -> str:
    text = re.sub(r"> - 생성 시각: `[^`]+`", "> - 생성 시각: `<generated-at>`", text)
    return re.sub(
        r"<blockquote>- 생성 시각: <code>[^<]+</code></blockquote>",
        "<blockquote>- 생성 시각: <code>&lt;generated-at&gt;</code></blockquote>",
        text,
    )


def write_document(output_path: Path, revision_root: Path = ROOT, revision_ref: str | None = None) -> None:
    output_path.write_text(render_document(revision_root, revision_ref), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate TCP API markdown from transport.message_schema.")
    parser.add_argument("--check", action="store_true", help="Fail if the generated file is out of date.")
    parser.add_argument(
        "--revision-root",
        type=Path,
        default=ROOT,
        help="Git repository path used for the generated branch/commit note. Defaults to this project root.",
    )
    parser.add_argument(
        "--revision-ref",
        help="Git ref used for the generated branch/commit note, such as origin/v1.0-Official-26.H1.",
    )
    args = parser.parse_args(argv)

    validate_schema_against_protocol_defs()
    revision_root = args.revision_root.resolve()
    rendered = render_document(revision_root, args.revision_ref)
    rendered_html = render_markdown_as_html(rendered)

    if args.check:
        current = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.exists() else ""
        current_html = HTML_OUTPUT_PATH.read_text(encoding="utf-8") if HTML_OUTPUT_PATH.exists() else ""
        if normalize_generated_at(current) != normalize_generated_at(rendered):
            raise SystemExit("docs/tcp-api.md is out of date. Run: python tools/gen_tcp_docs.py")
        if normalize_generated_at(current_html) != normalize_generated_at(rendered_html):
            raise SystemExit("docs/tcp-api.html is out of date. Run: python tools/gen_tcp_docs.py")
        return 0

    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    HTML_OUTPUT_PATH.write_text(rendered_html, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")
    print(f"Wrote {HTML_OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
