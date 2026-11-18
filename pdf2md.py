#!/usr/bin/env python3
"""pdf2md - converte arquivos PDF em Markdown.

Motor principal: pymupdf4llm (preserva títulos, listas, tabelas, negrito/itálico).
Fallback: pdftotext (poppler) - só texto corrido, sem formatação.

Exemplos:
    pdf2md relatorio.pdf                    # gera relatorio.md ao lado do PDF
    pdf2md relatorio.pdf -o -               # imprime no stdout
    pdf2md relatorio.pdf -p 1-3,7           # só as páginas 1, 2, 3 e 7
    pdf2md manual.pdf --images              # extrai imagens para manual_images/
    pdf2md ~/Documentos -r -o ~/md          # converte uma pasta inteira
    PDF2MD_PASSWORD=... pdf2md protegido.pdf  # PDF com senha (via variável de ambiente)
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PASSWORD_ENV = "PDF2MD_PASSWORD"
DEFAULT_MAX_MB = 200


class Pdf2MdError(Exception):
    """Erro esperado, mostrado ao usuário sem stack trace."""


# ---------------------------------------------------------------- validação

def validate_pdf(path: Path, max_mb: int) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise Pdf2MdError(f"arquivo não encontrado: {path}")
    if path.suffix.lower() != ".pdf":
        raise Pdf2MdError(f"extensão não suportada (esperado .pdf): {path.name}")
    size = path.stat().st_size
    if size == 0:
        raise Pdf2MdError(f"arquivo vazio: {path.name}")
    if size > max_mb * 1024 * 1024:
        raise Pdf2MdError(f"{path.name} tem {size / 1048576:.1f} MB (limite {max_mb} MB; use --max-size)")
    with path.open("rb") as fh:
        if b"%PDF-" not in fh.read(1024):
            raise Pdf2MdError(f"{path.name} não parece ser um PDF válido (assinatura %PDF- ausente)")
    return path


def parse_pages(spec: str | None, page_count: int) -> list[int] | None:
    """'1-3,7' -> [0, 1, 2, 6] (índices base 0)."""
    if not spec:
        return None
    pages: list[int] = []
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                start, end = int(a or 1), int(b or page_count)
            else:
                start = end = int(part)
        except ValueError:
            raise Pdf2MdError(f"intervalo de páginas inválido: '{part}'") from None
        if start < 1 or end > page_count or start > end:
            raise Pdf2MdError(f"páginas '{part}' fora do intervalo 1-{page_count}")
        pages.extend(range(start - 1, end))
    return sorted(set(pages))


# ---------------------------------------------------------------- motores

def have_pymupdf() -> bool:
    try:
        import pymupdf4llm  # noqa: F401
        return True
    except ImportError:
        return False


def convert_pymupdf(pdf: Path, pages_spec: str | None, images_dir: Path | None,
                    page_markers: bool) -> str:
    import pymupdf
    import pymupdf4llm

    try:
        doc = pymupdf.open(pdf)
    except Exception:
        raise Pdf2MdError(f"não foi possível abrir {pdf.name} (arquivo corrompido?)") from None

    try:
        if doc.needs_pass:
            password = os.environ.get(PASSWORD_ENV)
            if not password:
                raise Pdf2MdError(f"{pdf.name} é protegido por senha; defina {PASSWORD_ENV}")
            if not doc.authenticate(password):
                raise Pdf2MdError(f"senha incorreta para {pdf.name}")

        kwargs: dict = {
            "pages": parse_pages(pages_spec, doc.page_count),
            "page_separators": page_markers,
            "show_progress": False,
            "use_ocr": False,  # sem isso o parser imprime aviso de OCR no stdout
        }
        if images_dir:
            images_dir.mkdir(parents=True, exist_ok=True)
            kwargs.update(write_images=True, image_path=str(images_dir), image_format="png")
        else:
            kwargs["ignore_images"] = True

        md = pymupdf4llm.to_markdown(doc, **kwargs)
    finally:
        doc.close()

    if images_dir:
        # deixa os links de imagem relativos ao .md
        md = re.sub(r"\]\([^)\s]*?" + re.escape(images_dir.name + "/"),
                    "](" + images_dir.name + "/", md)
    return md


def convert_pdftotext(pdf: Path, pages_spec: str | None, page_markers: bool) -> str:
    exe = shutil.which("pdftotext")
    if not exe:
        raise Pdf2MdError("nenhum motor disponível: instale pymupdf4llm (install.sh) ou poppler-utils")
    if os.environ.get(PASSWORD_ENV):
        # pdftotext só aceita senha via argv (visível em `ps`); não vazamos o segredo.
        raise Pdf2MdError("PDF com senha exige o motor pymupdf (rode install.sh)")

    # lista de argumentos, sem shell -> sem injeção de comando
    result = subprocess.run([exe, "-enc", "UTF-8", "--", str(pdf), "-"],
                            capture_output=True, timeout=300, check=False)
    if result.returncode != 0:
        raise Pdf2MdError(f"pdftotext falhou ao ler {pdf.name} (código {result.returncode})")

    raw_pages = result.stdout.decode("utf-8", "replace").split("\f")
    if raw_pages and not raw_pages[-1].strip():
        raw_pages.pop()
    selected = parse_pages(pages_spec, len(raw_pages)) or range(len(raw_pages))

    out = []
    for i in selected:
        paragraphs = [" ".join(p.split()) for p in raw_pages[i].split("\n\n")]
        body = "\n\n".join(p for p in paragraphs if p)
        if page_markers:
            out.append(f"\n--- página {i + 1} ---\n")
        out.append(body + "\n")
    return "\n".join(out)


# ---------------------------------------------------------------- CLI

def collect_inputs(items: list[str], recursive: bool) -> list[Path]:
    files: list[Path] = []
    for item in items:
        p = Path(item).expanduser()
        if p.is_dir():
            pattern = "**/*" if recursive else "*"
            files.extend(sorted(f for f in p.glob(pattern) if f.is_file() and f.suffix.lower() == ".pdf"))
        else:
            files.append(p)
    if not files:
        raise Pdf2MdError("nenhum PDF encontrado nas entradas informadas")
    return files


def resolve_output(pdf: Path, output: str | None, multiple: bool) -> Path | None:
    if output == "-":
        return None
    if output is None:
        return pdf.with_suffix(".md")
    out = Path(output).expanduser()
    if multiple or out.is_dir() or output.endswith(("/", os.sep)):
        out.mkdir(parents=True, exist_ok=True)
        return out / (pdf.stem + ".md")
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def write_atomic(target: Path, content: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="pdf2md",
        description="Converte PDF em Markdown.",
        epilog=f"PDF com senha: defina a variável de ambiente {PASSWORD_ENV}.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("inputs", nargs="+", help="arquivos .pdf ou pastas")
    ap.add_argument("-o", "--output", help="arquivo .md, pasta de destino, ou '-' para stdout "
                                           "(padrão: .md ao lado do PDF)")
    ap.add_argument("-p", "--pages", help="páginas a converter, ex.: 1-3,7")
    ap.add_argument("-r", "--recursive", action="store_true", help="procura PDFs em subpastas")
    ap.add_argument("-i", "--images", action="store_true", help="extrai imagens para <nome>_images/")
    ap.add_argument("-m", "--page-markers", action="store_true", help="marca o início de cada página")
    ap.add_argument("-f", "--force", action="store_true", help="sobrescreve .md existente")
    ap.add_argument("-e", "--engine", choices=["auto", "pymupdf", "pdftotext"], default="auto",
                    help="motor de conversão (padrão: auto)")
    ap.add_argument("--max-size", type=int, default=DEFAULT_MAX_MB, metavar="MB",
                    help=f"tamanho máximo do PDF (padrão: {DEFAULT_MAX_MB} MB)")
    ap.add_argument("--debug", action="store_true", help="mostra stack trace em erros inesperados")
    args = ap.parse_args(argv)

    engine = args.engine
    if engine == "auto":
        engine = "pymupdf" if have_pymupdf() else "pdftotext"
        if engine == "pdftotext":
            print("aviso: pymupdf4llm ausente, usando pdftotext (sem títulos/tabelas). "
                  "Rode install.sh para melhor qualidade.", file=sys.stderr)
    elif engine == "pymupdf" and not have_pymupdf():
        print("erro: pymupdf4llm não instalado (rode install.sh)", file=sys.stderr)
        return 2
    if args.images and engine != "pymupdf":
        print("aviso: --images só funciona com o motor pymupdf; ignorado.", file=sys.stderr)

    try:
        files = collect_inputs(args.inputs, args.recursive)
    except Pdf2MdError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2

    multiple = len(files) > 1
    if multiple and args.output == "-":
        print("erro: '-o -' só é permitido com um único PDF", file=sys.stderr)
        return 2

    failures = 0
    for f in files:
        try:
            pdf = validate_pdf(f, args.max_size)
            target = resolve_output(pdf, args.output, multiple)
            if target and target.exists() and not args.force:
                raise Pdf2MdError(f"{target} já existe (use --force para sobrescrever)")

            if engine == "pymupdf":
                images_dir = None
                if args.images:
                    base = target.parent if target else Path.cwd()
                    images_dir = (base / f"{pdf.stem}_images").resolve()
                md = convert_pymupdf(pdf, args.pages, images_dir, args.page_markers)
            else:
                md = convert_pdftotext(pdf, args.pages, args.page_markers)

            if not md.strip():
                print(f"aviso: {pdf.name} não tem texto extraível (PDF escaneado? precisa de OCR)",
                      file=sys.stderr)

            if target is None:
                sys.stdout.write(md)
            else:
                write_atomic(target, md)
                print(f"ok  {pdf.name} -> {target}", file=sys.stderr)
        except Pdf2MdError as exc:
            failures += 1
            print(f"erro: {exc}", file=sys.stderr)
        except KeyboardInterrupt:
            print("\ninterrompido", file=sys.stderr)
            return 130
        except Exception:
            failures += 1
            if args.debug:
                raise
            print(f"erro: falha inesperada ao converter {f.name} (use --debug para detalhes)",
                  file=sys.stderr)

    if multiple:
        print(f"\n{len(files) - failures}/{len(files)} convertidos", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
