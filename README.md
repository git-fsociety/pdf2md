# pdf2md

Converte PDF em Markdown pela linha de comando. Preserva títulos, listas, tabelas e negrito/itálico (motor `pymupdf4llm`); se ele não estiver instalado, usa o `pdftotext` do sistema (só texto corrido).

## Instalação

```bash
./install.sh   # cria .venv/ e o atalho ~/.local/bin/pdf2md
```

## Uso

```bash
pdf2md arquivo.pdf                 # gera arquivo.md ao lado do PDF
pdf2md arquivo.pdf -o -            # imprime no stdout (bom para pipe)
pdf2md arquivo.pdf -o saida.md     # escolhe o destino
pdf2md arquivo.pdf -p 1-3,7        # só algumas páginas
pdf2md arquivo.pdf -i              # extrai imagens para arquivo_images/
pdf2md arquivo.pdf -m              # marca onde cada página termina
pdf2md ~/Documentos -r -o ~/md     # converte uma pasta (recursivo)
PDF2MD_PASSWORD='...' pdf2md protegido.pdf
```

| Opção | Descrição |
|---|---|
| `-f` | sobrescreve `.md` existente (por padrão não sobrescreve) |
| `-e auto\|pymupdf\|pdftotext` | força um motor |
| `--max-size MB` | limite de tamanho do PDF (padrão 200 MB) |
| `--debug` | mostra stack trace em erro inesperado |

## Limitações

- PDF escaneado (imagem) não tem texto: a ferramenta avisa, mas não faz OCR.
- Tabelas sem bordas desenhadas podem sair como texto corrido.

## Segurança

- Valida extensão, assinatura `%PDF-` e tamanho antes de abrir.
- A senha vem só de variável de ambiente (não aparece em `ps` nem no histórico do shell).
- `pdftotext` roda sem shell (lista de argumentos, `--` antes do caminho).
- Grava de forma atômica e não sobrescreve sem `-f`.
- Erros mostram mensagem genérica; o stack trace só aparece com `--debug`.
- Dependências fixadas em `requirements.txt`.
