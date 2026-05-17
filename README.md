# gestnova-filesystem-mcp

Virtual Data Room (VDR) por empresa con estructura estándar y navegación
graph-aware. MCP server (stdio + HTTP) para que el agente Ian organice y
recupere documentos sin re-crearlos.

## Estructura estándar por empresa

```
<root>/companies/<slug>/
├── facturas/<year>/Q<n>/        # facturas emitidas
├── gastos/<year>/Q<n>/           # tickets, recibos, facturas recibidas
├── nominas/<year>/<month>/       # PDFs de recibo de nómina
├── compliance/<docType>/         # LOPD, plan-igualdad, PRL, ...
├── contratos/clientes/           # contratos con clientes
├── contratos/proveedores/        # contratos con proveedores
├── scenarios/<scenario_id>/      # exports XLSX de scenarios financieros
└── informes/<year>/<month>/      # dashboards exportados, reports
```

## Quick start

```bash
uv sync --extra dev
uv run pytest                          # unit tests
uv run gestnova-filesystem-mcp         # stdio MCP
uv run gestnova-filesystem-http        # HTTP on :8016
```

## Env

- `VDR_ROOT_PATH` — base path (default `~/.gestnova-vdr`)
- `PORT` — HTTP port (default 8016)
