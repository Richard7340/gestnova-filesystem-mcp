"""MCP tool definitions over the VDR core."""
from __future__ import annotations
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from .vdr import VDR


def _entry_dict(entry: Any) -> dict:
    return asdict(entry) if hasattr(entry, '__dataclass_fields__') else dict(entry)


def build_tool_registry(vdr: VDR) -> dict[str, dict]:
    """Returns {tool_name: {description, input_schema, handler}}."""

    def ensure_layout(args: dict) -> dict:
        slug = args["companySlug"]
        return {"slug": slug, "created": vdr.ensureCompanyLayout(slug)}

    def list_folder(args: dict) -> dict:
        return {
            "slug": args["companySlug"],
            "relPath": args.get("relPath", ""),
            "entries": [_entry_dict(e) for e in vdr.listFolder(args["companySlug"], args.get("relPath", ""))],
        }

    def read_file(args: dict) -> dict:
        return vdr.readFile(args["companySlug"], args["relPath"], maxBytes=int(args.get("maxBytes", 1_000_000)))

    def write_file(args: dict) -> dict:
        e = vdr.writeFile(args["companySlug"], args["relPath"], args["content"], overwrite=bool(args.get("overwrite", False)))
        return _entry_dict(e)

    def move_file(args: dict) -> dict:
        e = vdr.moveFile(args["companySlug"], args["fromRelPath"], args["toRelPath"])
        return _entry_dict(e)

    def delete_file(args: dict) -> dict:
        deleted = vdr.deleteFile(args["companySlug"], args["relPath"])
        return {"deleted": deleted, "relPath": args["relPath"]}

    def search_files(args: dict) -> dict:
        results = vdr.searchFiles(args["companySlug"], args["query"], int(args.get("maxResults", 50)))
        return {"query": args["query"], "results": [_entry_dict(e) for e in results]}

    def folder_tree(args: dict) -> dict:
        return vdr.getFolderTree(args["companySlug"], int(args.get("depth", 3)), args.get("relPath", ""))

    def archive_invoice(args: dict) -> dict:
        return _entry_dict(vdr.archiveInvoice(args["companySlug"], args["number"], args["content"], args["dateISO"]))

    def archive_payroll(args: dict) -> dict:
        return _entry_dict(vdr.archivePayroll(args["companySlug"], args["employeeId"], args["period"], args["content"]))

    def archive_compliance(args: dict) -> dict:
        return _entry_dict(vdr.archiveComplianceDoc(args["companySlug"], args["documentType"], args["content"], args.get("version", "v1")))

    def search_content(args: dict) -> dict:
        results = vdr.searchContent(args["companySlug"], args["query"], int(args.get("maxResults", 20)))
        return {"query": args["query"], "results": results}

    def reindex_company(args: dict) -> dict:
        count = vdr.reindexCompany(args["companySlug"])
        return {"companySlug": args["companySlug"], "indexedDocs": count}

    company_slug_schema = {"companySlug": {"type": "string", "description": "Company slug (e.g. 'gestnova')"}}

    return {
        "ensureCompanyLayout": {
            "description": "Crea/asegura las carpetas estándar de una empresa (facturas/gastos/nóminas/compliance/contratos/scenarios/informes). Idempotente.",
            "input_schema": {"type": "object", "properties": company_slug_schema, "required": ["companySlug"]},
            "handler": ensure_layout,
        },
        "listFolder": {
            "description": "Lista archivos y subcarpetas de una ruta relativa al root de la empresa. Pasa relPath='' para el root.",
            "input_schema": {"type": "object", "properties": {**company_slug_schema, "relPath": {"type": "string", "default": ""}}, "required": ["companySlug"]},
            "handler": list_folder,
        },
        "readFile": {
            "description": "Lee el contenido de un archivo (texto UTF-8). Archivos binarios devuelven encoding='binary' + content=null. Cap de tamaño 1MB por defecto.",
            "input_schema": {"type": "object", "properties": {**company_slug_schema, "relPath": {"type": "string"}, "maxBytes": {"type": "integer"}}, "required": ["companySlug", "relPath"]},
            "handler": read_file,
        },
        "writeFile": {
            "description": "Escribe contenido a un archivo (crea carpetas padre si faltan). Por defecto NO sobrescribe (error si existe). Pasa overwrite=true para forzar.",
            "input_schema": {"type": "object", "properties": {**company_slug_schema, "relPath": {"type": "string"}, "content": {"type": "string"}, "overwrite": {"type": "boolean"}}, "required": ["companySlug", "relPath", "content"]},
            "handler": write_file,
        },
        "moveFile": {
            "description": "Mueve/renombra un archivo dentro del VDR de una empresa.",
            "input_schema": {"type": "object", "properties": {**company_slug_schema, "fromRelPath": {"type": "string"}, "toRelPath": {"type": "string"}}, "required": ["companySlug", "fromRelPath", "toRelPath"]},
            "handler": move_file,
        },
        "deleteFile": {
            "description": "Borra un archivo (no carpetas — para borrar una carpeta usa otra herramienta admin). Devuelve deleted=true/false.",
            "input_schema": {"type": "object", "properties": {**company_slug_schema, "relPath": {"type": "string"}}, "required": ["companySlug", "relPath"]},
            "handler": delete_file,
        },
        "searchFiles": {
            "description": "Búsqueda por substring (case-insensitive) en nombre+path de TODOS los archivos de la empresa. Útil para 'busca factura de Acme'.",
            "input_schema": {"type": "object", "properties": {**company_slug_schema, "query": {"type": "string"}, "maxResults": {"type": "integer"}}, "required": ["companySlug", "query"]},
            "handler": search_files,
        },
        "getFolderTree": {
            "description": "Devuelve el árbol recursivo de carpetas/archivos hasta `depth` niveles. Útil para que el agente conozca la estructura antes de buscar.",
            "input_schema": {"type": "object", "properties": {**company_slug_schema, "depth": {"type": "integer"}, "relPath": {"type": "string"}}, "required": ["companySlug"]},
            "handler": folder_tree,
        },
        "archiveInvoice": {
            "description": "Auto-archiva una factura emitida en facturas/<year>/Q<n>/<number>.html. El año y trimestre se infieren de dateISO.",
            "input_schema": {"type": "object", "properties": {**company_slug_schema, "number": {"type": "string"}, "content": {"type": "string"}, "dateISO": {"type": "string"}}, "required": ["companySlug", "number", "content", "dateISO"]},
            "handler": archive_invoice,
        },
        "archivePayroll": {
            "description": "Auto-archiva un recibo de nómina en nominas/<year>/<month>/<employeeId>.html. period='YYYY-MM'.",
            "input_schema": {"type": "object", "properties": {**company_slug_schema, "employeeId": {"type": "string"}, "period": {"type": "string"}, "content": {"type": "string"}}, "required": ["companySlug", "employeeId", "period", "content"]},
            "handler": archive_payroll,
        },
        "archiveComplianceDoc": {
            "description": "Auto-archiva un documento de compliance en compliance/<documentType>/<version>.html. version='v1' por defecto.",
            "input_schema": {"type": "object", "properties": {**company_slug_schema, "documentType": {"type": "string"}, "content": {"type": "string"}, "version": {"type": "string"}}, "required": ["companySlug", "documentType", "content"]},
            "handler": archive_compliance,
        },
        "searchContent": {
            "description": "Búsqueda FULL-TEXT en el contenido de los archivos (TXT/MD/HTML/PDF). Devuelve relPath + snippet con [match]. Usa esto cuando 'searchFiles' por nombre no encuentre — ej: 'busca el contrato que menciona 30 días de preaviso'.",
            "input_schema": {"type": "object", "properties": {**company_slug_schema, "query": {"type": "string"}, "maxResults": {"type": "integer"}}, "required": ["companySlug", "query"]},
            "handler": search_content,
        },
        "reindexCompany": {
            "description": "Recorre todo el VDR de la empresa y reconstruye el índice full-text. Útil tras migraciones masivas o si el índice está desactualizado. Operación pesada — usar con criterio.",
            "input_schema": {"type": "object", "properties": company_slug_schema, "required": ["companySlug"]},
            "handler": reindex_company,
        },
    }


def default_vdr() -> VDR:
    root = os.getenv("VDR_ROOT_PATH", str(Path.home() / ".gestnova-vdr"))
    return VDR(root)
