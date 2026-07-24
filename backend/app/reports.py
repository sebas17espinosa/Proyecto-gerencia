"""Generación de reportes descargables (Excel y PDF) por módulo.

Soporta filtros por departamento (o todos), por colaborador individual
(o todos) y por periodo (año, mes o semestre).
"""

from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Any

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from . import models

MODULOS = {
    "empleados": "Personal",
    "asistencia": "Control diario - Asistencia",
    "ausencias": "Control diario - Ausencias",
    "vacaciones": "Control diario - Vacaciones",
    "capacitaciones": "Desarrollo - Capacitaciones",
    "evaluaciones": "Desarrollo - Evaluaciones de desempeño",
    "salidas": "Salida de personal",
    "movimientos": "Movimientos internos",
}


class ReportError(ValueError):
    """Error de validación al armar un reporte."""


def _period_range(anio: int | None, mes: int | None, semestre: int | None) -> tuple[date, date] | None:
    """Convierte año/mes/semestre en un rango de fechas [inicio, fin]."""
    if mes is not None and anio is None:
        raise ReportError("Debe indicar el año junto con el mes.")
    if semestre is not None and anio is None:
        raise ReportError("Debe indicar el año junto con el semestre.")
    if mes is not None and semestre is not None:
        raise ReportError("Indique solo mes o solo semestre, no ambos.")

    if anio is None:
        return None

    if mes is not None:
        if not 1 <= mes <= 12:
            raise ReportError("El mes debe estar entre 1 y 12.")
        start = date(anio, mes, 1)
        end = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
        return start, end

    if semestre is not None:
        if semestre not in (1, 2):
            raise ReportError("El semestre debe ser 1 o 2.")
        start = date(anio, 1, 1) if semestre == 1 else date(anio, 7, 1)
        end = date(anio, 7, 1) if semestre == 1 else date(anio + 1, 1, 1)
        return start, end

    return date(anio, 1, 1), date(anio + 1, 1, 1)


def _base_employee_query(db: Session, department_id: int | None, codigo_empresa: str | None):
    query = (
        db.query(models.Employee)
        .join(models.Personnel, models.Personnel.codigo_empresa == models.Employee.codigo_empresa)
        .join(models.Department, models.Department.id_departamento == models.Personnel.id_departamento)
    )
    if department_id:
        query = query.filter(models.Personnel.id_departamento == department_id)
    if codigo_empresa:
        query = query.filter(models.Employee.codigo_empresa == codigo_empresa)
    return query


def _build_dataframe(
    db: Session,
    modulo: str,
    department_id: int | None,
    codigo_empresa: str | None,
    date_range: tuple[date, date] | None,
) -> pd.DataFrame:
    if modulo not in MODULOS:
        raise ReportError(f"Módulo de reporte desconocido: {modulo}")

    if modulo == "empleados":
        rows = _base_employee_query(db, department_id, codigo_empresa).all()
        data = [
            {
                "Codigo": e.codigo_empresa,
                "Nombre": f"{e.nombre} {e.apellido}",
                "Cedula": e.numero_cedula,
                "Departamento": e.personal.departamento.nombre_departamento if e.personal else "",
                "Puesto": e.personal.puesto if e.personal else "",
                "Estado": e.estado,
                "Fecha ingreso": e.personal.fecha_ingreso if e.personal else None,
                "Desempeño %": e.pct_desempeno,
            }
            for e in rows
        ]
        return pd.DataFrame(data)

    if modulo == "asistencia":
        query = (
            db.query(models.Attendance, models.Employee, models.Personnel)
            .join(models.Employee, models.Employee.codigo_empresa == models.Attendance.codigo_empresa)
            .join(models.Personnel, models.Personnel.codigo_empresa == models.Employee.codigo_empresa)
        )
        if department_id:
            query = query.filter(models.Personnel.id_departamento == department_id)
        if codigo_empresa:
            query = query.filter(models.Attendance.codigo_empresa == codigo_empresa)
        if date_range:
            query = query.filter(models.Attendance.fecha >= date_range[0], models.Attendance.fecha < date_range[1])
        data = [
            {
                "Codigo": a.codigo_empresa,
                "Nombre": f"{emp.nombre} {emp.apellido}",
                "Fecha": a.fecha,
                "Presente": "Sí" if a.presente else "No",
            }
            for a, emp, _p in query.all()
        ]
        return pd.DataFrame(data)

    if modulo == "ausencias":
        query = (
            db.query(models.Absence, models.Employee, models.Personnel)
            .join(models.Employee, models.Employee.codigo_empresa == models.Absence.codigo_empresa)
            .join(models.Personnel, models.Personnel.codigo_empresa == models.Employee.codigo_empresa)
        )
        if department_id:
            query = query.filter(models.Personnel.id_departamento == department_id)
        if codigo_empresa:
            query = query.filter(models.Absence.codigo_empresa == codigo_empresa)
        if date_range:
            query = query.filter(models.Absence.fecha >= date_range[0], models.Absence.fecha < date_range[1])
        data = [
            {
                "Codigo": a.codigo_empresa,
                "Nombre": f"{emp.nombre} {emp.apellido}",
                "Fecha": a.fecha,
                "Motivo": a.motivo,
            }
            for a, emp, _p in query.all()
        ]
        return pd.DataFrame(data)

    if modulo == "vacaciones":
        query = (
            db.query(models.Vacation, models.Employee, models.Personnel)
            .join(models.Employee, models.Employee.codigo_empresa == models.Vacation.codigo_empresa)
            .join(models.Personnel, models.Personnel.codigo_empresa == models.Employee.codigo_empresa)
        )
        if department_id:
            query = query.filter(models.Personnel.id_departamento == department_id)
        if codigo_empresa:
            query = query.filter(models.Vacation.codigo_empresa == codigo_empresa)
        if date_range:
            query = query.filter(
                models.Vacation.fecha_inicio < date_range[1], models.Vacation.fecha_fin >= date_range[0]
            )
        data = [
            {
                "Codigo": v.codigo_empresa,
                "Nombre": f"{emp.nombre} {emp.apellido}",
                "Fecha inicio": v.fecha_inicio,
                "Fecha fin": v.fecha_fin,
                "Dias tomados": v.dias_tomados,
                "Observaciones": v.observaciones,
            }
            for v, emp, _p in query.all()
        ]
        return pd.DataFrame(data)

    if modulo == "capacitaciones":
        query = (
            db.query(models.Training, models.Employee, models.Personnel)
            .join(models.Employee, models.Employee.codigo_empresa == models.Training.codigo_empresa)
            .join(models.Personnel, models.Personnel.codigo_empresa == models.Employee.codigo_empresa)
        )
        if department_id:
            query = query.filter(models.Personnel.id_departamento == department_id)
        if codigo_empresa:
            query = query.filter(models.Training.codigo_empresa == codigo_empresa)
        if date_range:
            query = query.filter(
                models.Training.fecha_inicio >= date_range[0], models.Training.fecha_inicio < date_range[1]
            )
        data = [
            {
                "Codigo": t.codigo_empresa,
                "Nombre": f"{emp.nombre} {emp.apellido}",
                "Capacitacion": t.nombre_capacitacion,
                "Fecha inicio": t.fecha_inicio,
                "Fecha fin": t.fecha_fin,
            }
            for t, emp, _p in query.all()
        ]
        return pd.DataFrame(data)

    if modulo == "evaluaciones":
        query = (
            db.query(models.PerformanceEvaluation, models.Employee, models.Personnel)
            .join(models.Employee, models.Employee.codigo_empresa == models.PerformanceEvaluation.codigo_empresa)
            .join(models.Personnel, models.Personnel.codigo_empresa == models.Employee.codigo_empresa)
        )
        if department_id:
            query = query.filter(models.Personnel.id_departamento == department_id)
        if codigo_empresa:
            query = query.filter(models.PerformanceEvaluation.codigo_empresa == codigo_empresa)
        if date_range:
            query = query.filter(
                models.PerformanceEvaluation.fecha_evaluacion >= date_range[0],
                models.PerformanceEvaluation.fecha_evaluacion < date_range[1],
            )
        data = [
            {
                "Codigo": ev.codigo_empresa,
                "Nombre": f"{emp.nombre} {emp.apellido}",
                "Fecha evaluacion": ev.fecha_evaluacion,
                "% Bruto": ev.pct_bruto,
                "% Neto": ev.pct_neto,
            }
            for ev, emp, _p in query.all()
        ]
        return pd.DataFrame(data)

    if modulo == "salidas":
        query = (
            db.query(models.Termination, models.Employee, models.Personnel)
            .join(models.Employee, models.Employee.codigo_empresa == models.Termination.codigo_empresa)
            .join(models.Personnel, models.Personnel.codigo_empresa == models.Employee.codigo_empresa)
        )
        if department_id:
            query = query.filter(models.Personnel.id_departamento == department_id)
        if codigo_empresa:
            query = query.filter(models.Termination.codigo_empresa == codigo_empresa)
        if date_range:
            query = query.filter(
                models.Termination.fecha_salida >= date_range[0], models.Termination.fecha_salida < date_range[1]
            )
        data = [
            {
                "Codigo": s.codigo_empresa,
                "Nombre": f"{emp.nombre} {emp.apellido}",
                "Fecha salida": s.fecha_salida,
                "Motivo": s.motivo_salida,
                "Observaciones": s.observaciones,
            }
            for s, emp, _p in query.all()
        ]
        return pd.DataFrame(data)

    if modulo == "movimientos":
        query = (
            db.query(models.Movement, models.Employee, models.Personnel)
            .join(models.Employee, models.Employee.codigo_empresa == models.Movement.codigo_empresa)
            .join(models.Personnel, models.Personnel.codigo_empresa == models.Employee.codigo_empresa)
        )
        if department_id:
            query = query.filter(
                (models.Movement.depto_anterior == department_id) | (models.Movement.depto_nuevo == department_id)
            )
        if codigo_empresa:
            query = query.filter(models.Movement.codigo_empresa == codigo_empresa)
        if date_range:
            query = query.filter(
                models.Movement.fecha_movimiento >= date_range[0], models.Movement.fecha_movimiento < date_range[1]
            )
        data = [
            {
                "Codigo": m.codigo_empresa,
                "Nombre": f"{emp.nombre} {emp.apellido}",
                "Fecha": m.fecha_movimiento,
                "Puesto anterior": m.puesto_anterior,
                "Puesto nuevo": m.puesto_nuevo,
                "Motivo": m.motivo,
            }
            for m, emp, _p in query.all()
        ]
        return pd.DataFrame(data)

    raise ReportError(f"Módulo de reporte desconocido: {modulo}")


def _period_label(anio: int | None, mes: int | None, semestre: int | None) -> str:
    if anio is None:
        return "Todo el historico"
    if mes is not None:
        return f"{mes:02d}/{anio}"
    if semestre is not None:
        return f"Semestre {semestre} - {anio}"
    return f"Año {anio}"


def _to_excel(df: pd.DataFrame, sheet_name: str) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        (df if not df.empty else pd.DataFrame({"Aviso": ["No hay registros para los filtros indicados."]})).to_excel(
            writer, index=False, sheet_name=sheet_name[:31] or "Reporte"
        )
        worksheet = writer.sheets[sheet_name[:31] or "Reporte"]
        for column_cells in worksheet.columns:
            length = max(len(str(cell.value)) if cell.value is not None else 0 for cell in column_cells)
            worksheet.column_dimensions[column_cells[0].column_letter].width = min(max(length + 2, 10), 40)
    buffer.seek(0)
    return buffer.read()


def _to_pdf(df: pd.DataFrame, title: str, subtitle: str) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )
    styles = getSampleStyleSheet()
    elements: list[Any] = [
        Paragraph(title, styles["Title"]),
        Paragraph(subtitle, styles["Normal"]),
        Spacer(1, 0.5 * cm),
    ]

    if df.empty:
        elements.append(Paragraph("No hay registros para los filtros indicados.", styles["Normal"]))
    else:
        display_df = df.copy()
        for col in display_df.columns:
            display_df[col] = display_df[col].apply(lambda v: "" if v is None else str(v))
        table_data = [list(display_df.columns)] + display_df.values.tolist()
        table = Table(table_data, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f766e")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        elements.append(table)

    doc.build(elements)
    buffer.seek(0)
    return buffer.read()


def build_report(
    db: Session,
    modulo: str,
    formato: str,
    department_id: int | None = None,
    codigo_empresa: str | None = None,
    anio: int | None = None,
    mes: int | None = None,
    semestre: int | None = None,
) -> tuple[bytes, str, str]:
    if formato not in ("pdf", "excel"):
        raise ReportError("El formato debe ser 'pdf' o 'excel'.")

    date_range = _period_range(anio, mes, semestre)
    df = _build_dataframe(db, modulo, department_id, codigo_empresa, date_range)

    scope_bits = []
    department = None
    if department_id:
        department = db.query(models.Department).filter(models.Department.id_departamento == department_id).first()
        scope_bits.append(department.nombre_departamento if department else "Departamento desconocido")
    else:
        scope_bits.append("Todos los departamentos")
    if codigo_empresa:
        scope_bits.append(f"Colaborador {codigo_empresa}")
    else:
        scope_bits.append("Todos los colaboradores")
    scope_bits.append(_period_label(anio, mes, semestre))

    titulo = MODULOS[modulo]
    subtitulo = " · ".join(scope_bits)

    slug_parts = [modulo]
    if department_id:
        slug_parts.append(f"depto{department_id}")
    if codigo_empresa:
        slug_parts.append(codigo_empresa)
    if anio:
        slug_parts.append(str(anio))
    if mes:
        slug_parts.append(f"m{mes:02d}")
    if semestre:
        slug_parts.append(f"s{semestre}")
    filename_base = "_".join(slug_parts)

    if formato == "excel":
        content = _to_excel(df, titulo)
        return content, f"{filename_base}.xlsx", (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    content = _to_pdf(df, titulo, subtitulo)
    return content, f"{filename_base}.pdf", "application/pdf"
