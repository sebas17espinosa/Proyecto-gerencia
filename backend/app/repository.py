from io import BytesIO
from pathlib import Path
from datetime import date
import re
from typing import Any
import unicodedata

import pandas as pd
from pypdf import PdfReader
from sqlalchemy import case, desc, func, or_
from sqlalchemy.orm import Session, joinedload

from . import auth, models, schemas


def _employee_name(employee: models.Employee | None) -> str:
    if not employee:
        return ""
    return f"{employee.nombre} {employee.apellido}"


def _require_employee(db: Session, code: str, *, active: bool = False) -> models.Employee:
    employee = db.query(models.Employee).filter(models.Employee.codigo_empresa == code).first()
    if not employee:
        raise ValueError("El colaborador indicado no existe.")
    if active and employee.estado != "activo":
        raise ValueError("El colaborador indicado no está activo.")
    return employee


def _require_department(db: Session, department_id: int) -> models.Department:
    department = (
        db.query(models.Department)
        .filter(models.Department.id_departamento == department_id)
        .first()
    )
    if not department:
        raise ValueError("El departamento indicado no existe.")
    return department


def next_employee_code(db: Session) -> str:
    count = db.query(models.Employee).count() + 1
    while True:
        code = f"E{count:04d}"[-5:]
        exists = db.query(models.Employee).filter(models.Employee.codigo_empresa == code).first()
        if not exists:
            return code
        count += 1


def list_departments(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.query(
            models.Department,
            func.count(models.Personnel.id_personal).label("colaboradores"),
        )
        .outerjoin(models.Personnel)
        .group_by(models.Department.id_departamento)
        .order_by(models.Department.nombre_departamento)
        .all()
    )
    return [
        {
            "id_departamento": dep.id_departamento,
            "nombre_departamento": dep.nombre_departamento,
            "descripcion": dep.descripcion,
            "colaboradores": colaboradores,
        }
        for dep, colaboradores in rows
    ]


def create_department(db: Session, payload: schemas.DepartmentCreate) -> dict[str, Any]:
    dep = models.Department(**payload.model_dump())
    db.add(dep)
    db.commit()
    db.refresh(dep)
    return {
        "id_departamento": dep.id_departamento,
        "nombre_departamento": dep.nombre_departamento,
        "descripcion": dep.descripcion,
        "colaboradores": 0,
    }


def update_department(
    db: Session,
    department_id: int,
    payload: schemas.DepartmentCreate,
) -> dict[str, Any]:
    department = _require_department(db, department_id)
    department.nombre_departamento = payload.nombre_departamento
    department.descripcion = payload.descripcion
    db.commit()
    db.refresh(department)
    collaborators = (
        db.query(models.Personnel)
        .filter(models.Personnel.id_departamento == department_id)
        .count()
    )
    return {
        "id_departamento": department.id_departamento,
        "nombre_departamento": department.nombre_departamento,
        "descripcion": department.descripcion,
        "colaboradores": collaborators,
    }


def delete_department(db: Session, department_id: int) -> dict[str, str]:
    department = _require_department(db, department_id)
    collaborators = (
        db.query(models.Personnel)
        .filter(models.Personnel.id_departamento == department_id)
        .count()
    )
    if collaborators:
        raise ValueError(
            "No se puede eliminar un departamento que tiene colaboradores asignados."
        )
    db.delete(department)
    db.commit()
    return {"status": "ok"}


def list_employees(
    db: Session,
    q: str | None = None,
    department_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    query = (
        db.query(models.Employee)
        .options(joinedload(models.Employee.personal).joinedload(models.Personnel.departamento))
        .join(models.Personnel)
        .join(models.Department)
        .order_by(models.Employee.codigo_empresa)
    )
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                models.Employee.codigo_empresa.ilike(like),
                models.Employee.nombre.ilike(like),
                models.Employee.apellido.ilike(like),
                models.Employee.numero_cedula.ilike(like),
            )
        )
    if department_id:
        query = query.filter(models.Personnel.id_departamento == department_id)
    if status and status != "todos":
        query = query.filter(models.Employee.estado == status)

    employees = query.limit(min(limit, 500)).all()
    return [employee_to_dict(employee) for employee in employees]


def employee_to_dict(employee: models.Employee) -> dict[str, Any]:
    personal = employee.personal
    dep = personal.departamento if personal else None
    return {
        "id_empleado": employee.id_empleado,
        "codigo_empresa": employee.codigo_empresa,
        "numero_cedula": employee.numero_cedula,
        "nombre": employee.nombre,
        "apellido": employee.apellido,
        "nombre_completo": _employee_name(employee),
        "fecha_nacimiento": employee.fecha_nacimiento,
        "nacionalidad": employee.nacionalidad,
        "direccion": employee.direccion,
        "telefono_principal": employee.telefono_principal,
        "telefono_secundario": employee.telefono_secundario,
        "estado": employee.estado,
        "pct_desempeno": employee.pct_desempeno,
        "salario_mensual": employee.salario_mensual,
        "fecha_ingreso": personal.fecha_ingreso if personal else None,
        "puesto": personal.puesto if personal else None,
        "observaciones": personal.observaciones if personal else None,
        "id_departamento": dep.id_departamento if dep else None,
        "departamento": dep.nombre_departamento if dep else None,
    }


def create_employee(db: Session, payload: schemas.EmployeeCreate) -> dict[str, Any]:
    _require_department(db, payload.id_departamento)
    code = next_employee_code(db)
    employee_data = payload.model_dump(
        exclude={"fecha_ingreso", "puesto", "id_departamento", "observaciones"}
    )
    employee = models.Employee(codigo_empresa=code, estado="activo", pct_desempeno=None, **employee_data)
    db.add(employee)
    db.flush()
    db.add(
        models.Personnel(
            codigo_empresa=code,
            fecha_ingreso=payload.fecha_ingreso,
            puesto=payload.puesto,
            id_departamento=payload.id_departamento,
            observaciones=payload.observaciones,
        )
    )
    db.commit()
    db.refresh(employee)
    return employee_to_dict(employee)


def get_active_employee_options(db: Session) -> list[dict[str, Any]]:
    employees = (
        db.query(models.Employee)
        .join(models.Personnel)
        .filter(models.Employee.estado == "activo")
        .order_by(models.Employee.nombre)
        .all()
    )
    return [
        {
            "codigo_empresa": item.codigo_empresa,
            "nombre_completo": _employee_name(item),
            "puesto": item.personal.puesto if item.personal else "",
        }
        for item in employees
    ]


def list_vacancies() -> list[dict[str, Any]]:
    return [
        {
            "id": 1,
            "puesto": "Analista de Datos RRHH",
            "departamento": "Recursos Humanos",
            "cantidad": 2,
            "estado": "Abierta",
            "prioridad": "Alta",
            "descripcion": "Perfil orientado a reportes, KPI, depuración de datos y soporte al dashboard gerencial.",
        },
        {
            "id": 2,
            "puesto": "Soporte Técnico",
            "departamento": "Tecnología",
            "cantidad": 3,
            "estado": "Abierta",
            "prioridad": "Media",
            "descripcion": "Atención de incidencias, mantenimiento preventivo y soporte a usuarios internos.",
        },
        {
            "id": 3,
            "puesto": "Ejecutivo de Ventas",
            "departamento": "Ventas",
            "cantidad": 4,
            "estado": "Abierta",
            "prioridad": "Alta",
            "descripcion": "Gestión de cartera, prospección comercial y seguimiento de oportunidades.",
        },
        {
            "id": 4,
            "puesto": "Auditor de Calidad",
            "departamento": "Calidad",
            "cantidad": 1,
            "estado": "En evaluación",
            "prioridad": "Media",
            "descripcion": "Revisión de procesos internos, controles y acciones de mejora continua.",
        },
    ]


def list_evaluations(db: Session, codigo_empresa: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    query = (
        db.query(models.PerformanceEvaluation)
        .options(joinedload(models.PerformanceEvaluation.empleado))
        .order_by(desc(models.PerformanceEvaluation.fecha_evaluacion))
    )
    if codigo_empresa:
        query = query.filter(models.PerformanceEvaluation.codigo_empresa == codigo_empresa)
    return [evaluation_to_dict(row) for row in query.limit(min(limit, 500)).all()]


def record_attendance(db: Session, payload: schemas.AttendanceCreate) -> dict[str, Any]:
    _require_employee(db, payload.codigo_empresa, active=True)
    existing = (
        db.query(models.Attendance)
        .filter(
            models.Attendance.codigo_empresa == payload.codigo_empresa,
            models.Attendance.fecha == payload.fecha,
        )
        .first()
    )
    if existing:
        existing.presente = payload.presente
        record = existing
    else:
        record = models.Attendance(**payload.model_dump())
        db.add(record)
    db.commit()
    db.refresh(record)
    return attendance_to_dict(record)


def record_absence(db: Session, payload: schemas.AbsenceCreate) -> dict[str, Any]:
    _require_employee(db, payload.codigo_empresa, active=True)
    attendance_payload = schemas.AttendanceCreate(
        codigo_empresa=payload.codigo_empresa,
        fecha=payload.fecha,
        presente=False,
    )
    record_attendance(db, attendance_payload)
    existing = (
        db.query(models.Absence)
        .filter(
            models.Absence.codigo_empresa == payload.codigo_empresa,
            models.Absence.fecha == payload.fecha,
        )
        .first()
    )
    if existing:
        existing.motivo = payload.motivo
        record = existing
    else:
        record = models.Absence(**payload.model_dump())
        db.add(record)
    db.commit()
    db.refresh(record)
    return absence_to_dict(record)


def record_vacation(db: Session, payload: schemas.VacationCreate) -> dict[str, Any]:
    _require_employee(db, payload.codigo_empresa, active=True)
    days = (payload.fecha_fin - payload.fecha_inicio).days + 1
    record = models.Vacation(**payload.model_dump(), dias_tomados=days)
    db.add(record)
    db.commit()
    db.refresh(record)
    return vacation_to_dict(record)


def record_training(db: Session, payload: schemas.TrainingCreate) -> dict[str, Any]:
    _require_employee(db, payload.codigo_empresa, active=True)
    record = models.Training(**payload.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return training_to_dict(record)


def record_evaluation(db: Session, payload: schemas.EvaluationCreate) -> dict[str, Any]:
    employee = _require_employee(db, payload.codigo_empresa, active=True)
    absence_count = (
        db.query(models.Absence)
        .filter(models.Absence.codigo_empresa == payload.codigo_empresa)
        .count()
    )
    net = round(max(payload.pct_bruto - min(absence_count * 0.8, 12), 0), 2)
    record = models.PerformanceEvaluation(
        codigo_empresa=payload.codigo_empresa,
        fecha_evaluacion=payload.fecha_evaluacion,
        pct_bruto=payload.pct_bruto,
        pct_neto=net,
    )
    employee.pct_desempeno = net
    db.add(record)
    db.commit()
    db.refresh(record)
    return evaluation_to_dict(record)


def record_movement(db: Session, payload: schemas.MovementCreate) -> dict[str, Any]:
    _require_department(db, payload.depto_nuevo)
    employee = (
        db.query(models.Employee)
        .options(joinedload(models.Employee.personal))
        .filter(models.Employee.codigo_empresa == payload.codigo_empresa)
        .first()
    )
    if not employee or not employee.personal:
        raise ValueError("Colaborador no encontrado.")
    if employee.estado != "activo":
        raise ValueError("No se puede trasladar a un colaborador que no está activo.")
    movement = models.Movement(
        codigo_empresa=payload.codigo_empresa,
        fecha_movimiento=payload.fecha_movimiento,
        puesto_anterior=employee.personal.puesto,
        puesto_nuevo=payload.puesto_nuevo,
        depto_anterior=employee.personal.id_departamento,
        depto_nuevo=payload.depto_nuevo,
        motivo=payload.motivo,
    )
    employee.personal.puesto = payload.puesto_nuevo
    employee.personal.id_departamento = payload.depto_nuevo
    db.add(movement)
    db.commit()
    db.refresh(movement)
    return movement_to_dict(movement)


def record_termination(db: Session, payload: schemas.TerminationCreate) -> dict[str, Any]:
    employee = db.query(models.Employee).filter(models.Employee.codigo_empresa == payload.codigo_empresa).first()
    if not employee:
        raise ValueError("Colaborador no encontrado.")
    employee.estado = "terminado"
    existing = (
        db.query(models.Termination)
        .filter(models.Termination.codigo_empresa == payload.codigo_empresa)
        .first()
    )
    if existing:
        existing.fecha_salida = payload.fecha_salida
        existing.motivo_salida = payload.motivo_salida
        existing.observaciones = payload.observaciones
        record = existing
    else:
        record = models.Termination(**payload.model_dump())
        db.add(record)
    db.commit()
    db.refresh(record)
    return termination_to_dict(record)


def attendance_to_dict(record: models.Attendance) -> dict[str, Any]:
    return {
        "id_asistencia": record.id_asistencia,
        "codigo_empresa": record.codigo_empresa,
        "empleado": _employee_name(record.empleado),
        "fecha": record.fecha,
        "presente": record.presente,
    }


def absence_to_dict(record: models.Absence) -> dict[str, Any]:
    return {
        "id_ausencia": record.id_ausencia,
        "codigo_empresa": record.codigo_empresa,
        "empleado": _employee_name(record.empleado),
        "fecha": record.fecha,
        "motivo": record.motivo,
        "justificada": record.justificada,
    }


def vacation_to_dict(record: models.Vacation) -> dict[str, Any]:
    return {
        "id_vacacion": record.id_vacacion,
        "codigo_empresa": record.codigo_empresa,
        "empleado": _employee_name(record.empleado),
        "fecha_inicio": record.fecha_inicio,
        "fecha_fin": record.fecha_fin,
        "dias_tomados": record.dias_tomados,
        "observaciones": record.observaciones,
    }


def training_to_dict(record: models.Training) -> dict[str, Any]:
    return {
        "id_capacitacion": record.id_capacitacion,
        "codigo_empresa": record.codigo_empresa,
        "empleado": _employee_name(record.empleado),
        "nombre_capacitacion": record.nombre_capacitacion,
        "fecha_inicio": record.fecha_inicio,
        "fecha_fin": record.fecha_fin,
    }


def evaluation_to_dict(record: models.PerformanceEvaluation) -> dict[str, Any]:
    return {
        "id_evaluacion": record.id_evaluacion,
        "codigo_empresa": record.codigo_empresa,
        "empleado": _employee_name(record.empleado),
        "fecha_evaluacion": record.fecha_evaluacion,
        "pct_bruto": record.pct_bruto,
        "pct_neto": record.pct_neto,
    }


def termination_to_dict(record: models.Termination) -> dict[str, Any]:
    return {
        "id_salida": record.id_salida,
        "codigo_empresa": record.codigo_empresa,
        "empleado": _employee_name(record.empleado),
        "fecha_salida": record.fecha_salida,
        "motivo_salida": record.motivo_salida,
        "observaciones": record.observaciones,
    }


def movement_to_dict(record: models.Movement) -> dict[str, Any]:
    return {
        "id_movimiento": record.id_movimiento,
        "codigo_empresa": record.codigo_empresa,
        "empleado": _employee_name(record.empleado),
        "fecha_movimiento": record.fecha_movimiento,
        "puesto_anterior": record.puesto_anterior,
        "puesto_nuevo": record.puesto_nuevo,
        "depto_anterior": record.depto_anterior,
        "depto_nuevo": record.depto_nuevo,
        "motivo": record.motivo,
    }


def _month_range(anio: int | None, mes: int | None) -> tuple[date, date] | None:
    if mes is not None and anio is None:
        raise ValueError("Debe indicar el año junto con el mes.")
    if anio is None:
        return None
    if mes is not None:
        if not 1 <= mes <= 12:
            raise ValueError("El mes debe estar entre 1 y 12.")
        start = date(anio, mes, 1)
        end = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
        return start, end
    return date(anio, 1, 1), date(anio + 1, 1, 1)


def list_attendance(
    db: Session,
    codigo_empresa: str | None = None,
    department_id: int | None = None,
    anio: int | None = None,
    mes: int | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    date_range = _month_range(anio, mes)
    query = db.query(models.Attendance).options(joinedload(models.Attendance.empleado))
    if codigo_empresa:
        query = query.filter(models.Attendance.codigo_empresa == codigo_empresa)
    if department_id:
        query = query.join(
            models.Personnel, models.Personnel.codigo_empresa == models.Attendance.codigo_empresa
        ).filter(models.Personnel.id_departamento == department_id)
    if date_range:
        query = query.filter(models.Attendance.fecha >= date_range[0], models.Attendance.fecha < date_range[1])
    rows = query.order_by(desc(models.Attendance.fecha)).limit(limit).all()
    return [attendance_to_dict(row) for row in rows]


def list_absences(
    db: Session,
    codigo_empresa: str | None = None,
    department_id: int | None = None,
    anio: int | None = None,
    mes: int | None = None,
    justificada: bool | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    date_range = _month_range(anio, mes)
    query = db.query(models.Absence).options(joinedload(models.Absence.empleado))
    if codigo_empresa:
        query = query.filter(models.Absence.codigo_empresa == codigo_empresa)
    if department_id:
        query = query.join(
            models.Personnel, models.Personnel.codigo_empresa == models.Absence.codigo_empresa
        ).filter(models.Personnel.id_departamento == department_id)
    if date_range:
        query = query.filter(models.Absence.fecha >= date_range[0], models.Absence.fecha < date_range[1])
    if justificada is not None:
        query = query.filter(models.Absence.justificada.is_(justificada))
    rows = query.order_by(desc(models.Absence.fecha)).limit(limit).all()
    return [absence_to_dict(row) for row in rows]


def recent_records(db: Session) -> dict[str, Any]:
    return {
        "asistencias": [
            attendance_to_dict(row)
            for row in db.query(models.Attendance).options(joinedload(models.Attendance.empleado)).order_by(desc(models.Attendance.fecha)).limit(25)
        ],
        "ausencias": [
            absence_to_dict(row)
            for row in db.query(models.Absence).options(joinedload(models.Absence.empleado)).order_by(desc(models.Absence.fecha)).limit(25)
        ],
        "vacaciones": [
            vacation_to_dict(row)
            for row in db.query(models.Vacation).options(joinedload(models.Vacation.empleado)).order_by(desc(models.Vacation.fecha_inicio)).limit(25)
        ],
        "capacitaciones": [
            training_to_dict(row)
            for row in db.query(models.Training).options(joinedload(models.Training.empleado)).order_by(desc(models.Training.fecha_inicio)).limit(25)
        ],
        "evaluaciones": [
            evaluation_to_dict(row)
            for row in db.query(models.PerformanceEvaluation).options(joinedload(models.PerformanceEvaluation.empleado)).order_by(desc(models.PerformanceEvaluation.fecha_evaluacion)).limit(25)
        ],
        "salidas": [
            termination_to_dict(row)
            for row in db.query(models.Termination).options(joinedload(models.Termination.empleado)).order_by(desc(models.Termination.fecha_salida)).limit(25)
        ],
        "movimientos": [
            movement_to_dict(row)
            for row in db.query(models.Movement).options(joinedload(models.Movement.empleado)).order_by(desc(models.Movement.fecha_movimiento)).limit(25)
        ],
    }


def employee_workspace(db: Session, codigo_empresa: str) -> dict[str, Any]:
    employee = (
        db.query(models.Employee)
        .options(joinedload(models.Employee.personal).joinedload(models.Personnel.departamento))
        .filter(models.Employee.codigo_empresa == codigo_empresa)
        .first()
    )
    if not employee:
        raise ValueError("El colaborador indicado no existe.")

    return {
        "profile": employee_to_dict(employee),
        "asistencias": [
            attendance_to_dict(row)
            for row in (
                db.query(models.Attendance)
                .options(joinedload(models.Attendance.empleado))
                .filter(models.Attendance.codigo_empresa == codigo_empresa)
                .order_by(desc(models.Attendance.fecha))
                .limit(15)
            )
        ],
        "ausencias": [
            absence_to_dict(row)
            for row in (
                db.query(models.Absence)
                .options(joinedload(models.Absence.empleado))
                .filter(models.Absence.codigo_empresa == codigo_empresa)
                .order_by(desc(models.Absence.fecha))
                .limit(15)
            )
        ],
        "vacaciones": [
            vacation_to_dict(row)
            for row in (
                db.query(models.Vacation)
                .options(joinedload(models.Vacation.empleado))
                .filter(models.Vacation.codigo_empresa == codigo_empresa)
                .order_by(desc(models.Vacation.fecha_inicio))
                .limit(15)
            )
        ],
        "capacitaciones": [
            training_to_dict(row)
            for row in (
                db.query(models.Training)
                .options(joinedload(models.Training.empleado))
                .filter(models.Training.codigo_empresa == codigo_empresa)
                .order_by(desc(models.Training.fecha_inicio))
                .limit(15)
            )
        ],
        "evaluaciones": [
            evaluation_to_dict(row)
            for row in (
                db.query(models.PerformanceEvaluation)
                .options(joinedload(models.PerformanceEvaluation.empleado))
                .filter(models.PerformanceEvaluation.codigo_empresa == codigo_empresa)
                .order_by(desc(models.PerformanceEvaluation.fecha_evaluacion))
                .limit(15)
            )
        ],
        "movimientos": [
            movement_to_dict(row)
            for row in (
                db.query(models.Movement)
                .options(joinedload(models.Movement.empleado))
                .filter(models.Movement.codigo_empresa == codigo_empresa)
                .order_by(desc(models.Movement.fecha_movimiento))
                .limit(15)
            )
        ],
    }


def dashboard(
    db: Session,
    start_date: date | None = None,
    end_date: date | None = None,
    department_id: int | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    employee_filters = []
    if department_id:
        employee_filters.append(models.Personnel.id_departamento == department_id)
    if status and status != "todos":
        employee_filters.append(models.Employee.estado == status)

    employee_query = db.query(models.Employee).join(models.Personnel)
    if employee_filters:
        employee_query = employee_query.filter(*employee_filters)

    total = employee_query.count()
    active = employee_query.filter(models.Employee.estado == "activo").count()
    terminated = employee_query.filter(models.Employee.estado != "activo").count()

    attendance_query = (
        db.query(models.Attendance)
        .join(models.Personnel, models.Personnel.codigo_empresa == models.Attendance.codigo_empresa)
        .join(models.Employee, models.Employee.codigo_empresa == models.Attendance.codigo_empresa)
    )
    if employee_filters:
        attendance_query = attendance_query.filter(*employee_filters)
    if start_date:
        attendance_query = attendance_query.filter(models.Attendance.fecha >= start_date)
    if end_date:
        attendance_query = attendance_query.filter(models.Attendance.fecha <= end_date)

    attendance_total = attendance_query.count()
    present_total = attendance_query.filter(models.Attendance.presente.is_(True)).count()
    attendance_rate = round((present_total / attendance_total) * 100, 1) if attendance_total else 0

    absence_query = (
        db.query(models.Absence)
        .join(models.Personnel, models.Personnel.codigo_empresa == models.Absence.codigo_empresa)
        .join(models.Employee, models.Employee.codigo_empresa == models.Absence.codigo_empresa)
    )
    if employee_filters:
        absence_query = absence_query.filter(*employee_filters)
    if start_date:
        absence_query = absence_query.filter(models.Absence.fecha >= start_date)
    if end_date:
        absence_query = absence_query.filter(models.Absence.fecha <= end_date)
    absence_total = absence_query.count()

    training_query = (
        db.query(models.Training)
        .join(models.Personnel, models.Personnel.codigo_empresa == models.Training.codigo_empresa)
        .join(models.Employee, models.Employee.codigo_empresa == models.Training.codigo_empresa)
    )
    if employee_filters:
        training_query = training_query.filter(*employee_filters)
    if start_date:
        training_query = training_query.filter(models.Training.fecha_inicio >= start_date)
    if end_date:
        training_query = training_query.filter(models.Training.fecha_inicio <= end_date)
    training_total = training_query.count()

    performance_query = (
        db.query(models.PerformanceEvaluation)
        .join(models.Personnel, models.Personnel.codigo_empresa == models.PerformanceEvaluation.codigo_empresa)
        .join(models.Employee, models.Employee.codigo_empresa == models.PerformanceEvaluation.codigo_empresa)
    )
    if employee_filters:
        performance_query = performance_query.filter(*employee_filters)
    if start_date:
        performance_query = performance_query.filter(models.PerformanceEvaluation.fecha_evaluacion >= start_date)
    if end_date:
        performance_query = performance_query.filter(models.PerformanceEvaluation.fecha_evaluacion <= end_date)
    avg_performance = performance_query.with_entities(func.avg(models.PerformanceEvaluation.pct_neto)).scalar() or 0
    rotation_rate = round((terminated / total) * 100, 1) if total else 0

    department_count = func.count(models.Personnel.id_personal)
    active_count = func.sum(case((models.Employee.estado == "activo", 1), else_=0))
    terminated_count = func.sum(case((models.Employee.estado != "activo", 1), else_=0))
    by_department = (
        db.query(
            models.Department.nombre_departamento.label("name"),
            department_count.label("value"),
            active_count.label("activos"),
            terminated_count.label("terminados"),
        )
        .outerjoin(models.Personnel, models.Personnel.id_departamento == models.Department.id_departamento)
        .outerjoin(models.Employee, models.Employee.codigo_empresa == models.Personnel.codigo_empresa)
        .group_by(models.Department.id_departamento)
        .order_by(department_count.desc())
    )
    if department_id:
        by_department = by_department.filter(models.Department.id_departamento == department_id)
    if status and status != "todos":
        by_department = by_department.filter(models.Employee.estado == status)
    by_department = by_department.all()

    performance_by_department = (
        db.query(
            models.Department.nombre_departamento.label("departamento"),
            func.round(func.avg(models.PerformanceEvaluation.pct_neto), 1).label("promedio"),
            func.count(models.PerformanceEvaluation.id_evaluacion).label("evaluaciones"),
        )
        .join(models.Personnel, models.Personnel.id_departamento == models.Department.id_departamento)
        .join(models.Employee, models.Employee.codigo_empresa == models.Personnel.codigo_empresa)
        .join(models.PerformanceEvaluation, models.PerformanceEvaluation.codigo_empresa == models.Employee.codigo_empresa)
        .group_by(models.Department.id_departamento)
        .order_by(models.Department.nombre_departamento)
    )
    if employee_filters:
        performance_by_department = performance_by_department.filter(*employee_filters)
    if start_date:
        performance_by_department = performance_by_department.filter(models.PerformanceEvaluation.fecha_evaluacion >= start_date)
    if end_date:
        performance_by_department = performance_by_department.filter(models.PerformanceEvaluation.fecha_evaluacion <= end_date)
    performance_by_department = performance_by_department.all()

    present_count = func.sum(case((models.Attendance.presente.is_(True), 1), else_=0))
    absent_count = func.sum(case((models.Attendance.presente.is_(False), 1), else_=0))

    attendance_by_department = (
        db.query(
            models.Department.nombre_departamento.label("departamento"),
            func.round(
                func.avg(case((models.Attendance.presente.is_(True), 100.0), else_=0.0)),
                1,
            ).label("asistencia"),
            present_count.label("presentes"),
            absent_count.label("ausentes"),
            func.count(models.Attendance.id_asistencia).label("registros"),
        )
        .join(models.Personnel, models.Personnel.id_departamento == models.Department.id_departamento)
        .join(models.Employee, models.Employee.codigo_empresa == models.Personnel.codigo_empresa)
        .join(models.Attendance, models.Attendance.codigo_empresa == models.Personnel.codigo_empresa)
        .group_by(models.Department.id_departamento)
        .order_by(models.Department.nombre_departamento)
    )
    if employee_filters:
        attendance_by_department = attendance_by_department.filter(*employee_filters)
    if start_date:
        attendance_by_department = attendance_by_department.filter(models.Attendance.fecha >= start_date)
    if end_date:
        attendance_by_department = attendance_by_department.filter(models.Attendance.fecha <= end_date)
    attendance_by_department = attendance_by_department.all()

    performance_by_employee = (
        performance_query
        .options(joinedload(models.PerformanceEvaluation.empleado))
        .order_by(desc(models.PerformanceEvaluation.pct_neto))
        .limit(8)
        .all()
    )

    monthly_counts: dict[str, int] = {}
    termination_query = (
        db.query(models.Termination)
        .join(models.Personnel, models.Personnel.codigo_empresa == models.Termination.codigo_empresa)
        .join(models.Employee, models.Employee.codigo_empresa == models.Termination.codigo_empresa)
    )
    if employee_filters:
        termination_query = termination_query.filter(*employee_filters)
    if start_date:
        termination_query = termination_query.filter(models.Termination.fecha_salida >= start_date)
    if end_date:
        termination_query = termination_query.filter(models.Termination.fecha_salida <= end_date)
    for row in termination_query.all():
        key = row.fecha_salida.strftime("%Y-%m")
        monthly_counts[key] = monthly_counts.get(key, 0) + 1

    return {
        "summary": {
            "total_colaboradores": total,
            "activos": active,
            "terminados": terminated,
            "tasa_asistencia": attendance_rate,
            "ausencias": absence_total,
            "capacitaciones": training_total,
            "desempeno_promedio": round(avg_performance, 1),
            "rotacion": rotation_rate,
        },
        "filters": {
            "start_date": start_date,
            "end_date": end_date,
            "department_id": department_id,
            "status": status or "todos",
        },
        "status_breakdown": [
            {"name": "Activos", "value": active},
            {"name": "Inactivos", "value": terminated},
        ],
        "by_department": [
            {
                "name": row.name,
                "value": row.value,
                "activos": row.activos or 0,
                "terminados": row.terminados or 0,
            }
            for row in by_department
        ],
        "performance_by_department": [
            {
                "departamento": row.departamento,
                "promedio": row.promedio or 0,
                "evaluaciones": row.evaluaciones or 0,
            }
            for row in performance_by_department
        ],
        "attendance_by_department": [
            {
                "departamento": row.departamento,
                "asistencia": row.asistencia or 0,
                "presentes": row.presentes or 0,
                "ausentes": row.ausentes or 0,
                "registros": row.registros or 0,
            }
            for row in attendance_by_department
        ],
        "performance_by_employee": [
            evaluation_to_dict(row)
            for row in performance_by_employee
        ],
        "monthly_exits": [
            {"mes": key, "salidas": monthly_counts[key]}
            for key in sorted(monthly_counts)
        ],
    }


def recruitment_report() -> dict[str, Any]:
    csv_path = Path(__file__).resolve().parents[2] / "Modulo_1_Reclutamiento" / "filtered_cv" / "reporte_reclutamiento.csv"
    if not csv_path.exists():
        return {"records": [], "summary": {"total": 0, "alto": 0, "medio": 0, "bajo": 0}}
    df = pd.read_csv(csv_path)
    records = df.fillna("").to_dict(orient="records")
    score_col = next((col for col in df.columns if "porcentaje" in col.lower() or "score" in col.lower()), None)
    if score_col:
        scores = pd.to_numeric(df[score_col], errors="coerce").fillna(0)
        high = int((scores >= 70).sum())
        medium = int(((scores >= 40) & (scores < 70)).sum())
        low = int((scores < 40).sum())
    else:
        high = medium = low = 0
    return {
        "records": records,
        "summary": {"total": len(records), "alto": high, "medio": medium, "bajo": low},
    }


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char)).lower()


def _default_keywords() -> list[str]:
    keyword_path = (
        Path(__file__).resolve().parents[2]
        / "Modulo_1_Reclutamiento"
        / "local_keywords_binder_files"
        / "ingeniero_de_datos.keyb"
    )
    if not keyword_path.exists():
        return ["recursos humanos", "análisis de datos", "Excel", "Python"]
    return [
        item.strip()
        for item in keyword_path.read_text(encoding="utf-8").split(";")
        if item.strip()
    ]


def analyze_cv(
    filename: str,
    content: bytes,
    keywords_text: str | None = None,
    *,
    storage_root: Path | None = None,
) -> dict[str, Any]:
    safe_filename = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)
    suffix = Path(safe_filename).suffix.lower()
    if suffix not in {".pdf", ".txt"}:
        raise ValueError("Solo se admiten hojas de vida en formato PDF o TXT.")
    if not content:
        raise ValueError("El archivo está vacío.")
    if len(content) > 5 * 1024 * 1024:
        raise ValueError("El archivo supera el límite de 5 MB.")

    if suffix == ".pdf":
        try:
            text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages)
        except Exception as exc:
            raise ValueError("No se pudo leer el archivo PDF.") from exc
    else:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1")

    if not text.strip():
        raise ValueError("No se encontró texto legible en el archivo.")

    keywords = (
        [item.strip() for item in keywords_text.split(",") if item.strip()]
        if keywords_text
        else _default_keywords()
    )
    if not keywords:
        raise ValueError("Debe indicar al menos una palabra clave.")

    normalized_text = _normalize_text(text)
    found = [keyword for keyword in keywords if _normalize_text(keyword) in normalized_text]
    missing = [keyword for keyword in keywords if keyword not in found]
    score = round((len(found) / len(keywords)) * 100, 2)
    status = "high_accuracy" if score >= 70 else "low_accuracy" if score >= 40 else "descartado"
    record = {
        "archivo": safe_filename,
        "coincidencias": len(found),
        "total_keywords": len(keywords),
        "porcentaje": score,
        "estado": status,
        "palabras_encontradas": ", ".join(found),
        "palabras_faltantes": ", ".join(missing),
    }

    recruitment_root = storage_root or (
        Path(__file__).resolve().parents[2] / "Modulo_1_Reclutamiento"
    )
    input_dir = recruitment_root / "cv_input_temp"
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / safe_filename).write_bytes(content)

    report_path = recruitment_root / "filtered_cv" / "reporte_reclutamiento.csv"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    current = pd.read_csv(report_path) if report_path.exists() else pd.DataFrame()
    updated = pd.concat([current, pd.DataFrame([record])], ignore_index=True)
    updated.to_csv(report_path, index=False)
    return record


# --------------------------------------------------------------------------
# Autenticacion y usuarios
# --------------------------------------------------------------------------

class AuthError(ValueError):
    """Error de autenticación (credenciales invalidas, correo duplicado, etc.)."""


def user_to_dict(user: "models.User") -> dict[str, Any]:
    return {
        "id_usuario": user.id_usuario,
        "correo": user.correo,
        "nombre": user.nombre,
        "rol": user.rol,
        "codigo_empresa": user.codigo_empresa,
        "activo": user.activo,
    }


def authenticate(db: Session, correo: str, password: str) -> models.User:
    normalized = correo.strip().lower()
    user = db.query(models.User).filter(models.User.correo == normalized).first()
    if not user or not user.activo or not auth.verify_password(password, user.password_hash):
        raise AuthError("Correo o contraseña incorrectos.")
    user.token_actual = auth.generate_token()
    db.commit()
    db.refresh(user)
    return user


def logout(db: Session, user: models.User) -> None:
    user.token_actual = None
    db.commit()


def get_user_by_token(db: Session, token: str | None) -> models.User | None:
    if not token:
        return None
    return (
        db.query(models.User)
        .filter(models.User.token_actual == token, models.User.activo.is_(True))
        .first()
    )


def list_users(db: Session) -> list[dict[str, Any]]:
    return [user_to_dict(u) for u in db.query(models.User).order_by(models.User.correo).all()]


def create_user(db: Session, payload: "schemas.UserCreate") -> dict[str, Any]:
    normalized = payload.correo.strip().lower()
    if db.query(models.User).filter(models.User.correo == normalized).first():
        raise AuthError("Ya existe un usuario con ese correo.")
    if payload.codigo_empresa:
        _require_employee(db, payload.codigo_empresa)
    user = models.User(
        correo=normalized,
        password_hash=auth.hash_password(payload.password),
        nombre=payload.nombre,
        rol=payload.rol,
        codigo_empresa=payload.codigo_empresa,
        activo=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user_to_dict(user)


def delete_user(db: Session, user_id: int) -> dict[str, Any]:
    user = db.query(models.User).filter(models.User.id_usuario == user_id).first()
    if not user:
        raise AuthError("El usuario indicado no existe.")
    user.activo = False
    user.token_actual = None
    db.commit()
    return {"status": "ok"}


# --------------------------------------------------------------------------
# Costo de vacaciones (otorgar vs. no otorgar)
# --------------------------------------------------------------------------

# Supuestos usados para el calculo (documentados tambien en la respuesta de
# la API para que se puedan explicar en la presentacion):
# - factor_prestaciones: recargo estimado por cargas sociales/prestaciones
#   laborales sobre el salario base al calcular el costo de dar vacaciones.
# - factor_riesgo_no_otorgar: estimado de productividad perdida / riesgo de
#   rotacion, como porcentaje del salario mensual, para colaboradores activos
#   que no registran vacaciones en el periodo analizado.
VACATION_FACTOR_PRESTACIONES = 1.3
VACATION_FACTOR_RIESGO_NO_OTORGAR = 0.15


def simulate_vacation_cost(db: Session, codigo_empresa: str, dias: int) -> dict[str, Any]:
    employee = _require_employee(db, codigo_empresa)
    salario = employee.salario_mensual or 0
    salario_diario = round(salario / 30, 2)
    costo_total = round(salario_diario * dias * VACATION_FACTOR_PRESTACIONES, 2)
    return {
        "codigo_empresa": employee.codigo_empresa,
        "nombre": _employee_name(employee),
        "salario_mensual": salario,
        "salario_diario": salario_diario,
        "dias_simulados": dias,
        "factor_prestaciones": VACATION_FACTOR_PRESTACIONES,
        "costo_total": costo_total,
        "nota": (
            "Simulación: si se otorgan estos días de vacaciones a este colaborador, "
            "este sería el costo directo estimado (salario diario x días x factor de prestaciones)."
        ),
    }


def vacation_cost_summary(
    db: Session,
    department_id: int | None = None,
    anio: int | None = None,
    mes: int | None = None,
    semestre: int | None = None,
) -> dict[str, Any]:
    if mes is not None and semestre is not None:
        raise ValueError("Indique solo mes o solo semestre, no ambos.")
    if mes is not None and anio is None:
        raise ValueError("Debe indicar el año junto con el mes.")
    if semestre is not None and anio is None:
        raise ValueError("Debe indicar el año junto con el semestre.")

    date_range = None
    if anio is not None:
        if mes is not None:
            if not 1 <= mes <= 12:
                raise ValueError("El mes debe estar entre 1 y 12.")
            start = date(anio, mes, 1)
            end = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
        elif semestre is not None:
            if semestre not in (1, 2):
                raise ValueError("El semestre debe ser 1 o 2.")
            start = date(anio, 1, 1) if semestre == 1 else date(anio, 7, 1)
            end = date(anio, 7, 1) if semestre == 1 else date(anio + 1, 1, 1)
        else:
            start, end = date(anio, 1, 1), date(anio + 1, 1, 1)
        date_range = (start, end)

    vac_query = (
        db.query(models.Vacation, models.Employee, models.Personnel)
        .join(models.Employee, models.Employee.codigo_empresa == models.Vacation.codigo_empresa)
        .join(models.Personnel, models.Personnel.codigo_empresa == models.Employee.codigo_empresa)
    )
    if department_id:
        vac_query = vac_query.filter(models.Personnel.id_departamento == department_id)
    if date_range:
        vac_query = vac_query.filter(
            models.Vacation.fecha_inicio < date_range[1], models.Vacation.fecha_fin >= date_range[0]
        )

    by_department_cost: dict[str, dict[str, Any]] = {}
    total_dias = 0
    total_costo_otorgadas = 0.0
    employees_with_vacation: set[str] = set()

    for vac, emp, personal in vac_query.all():
        salario = emp.salario_mensual or 0
        salario_diario = salario / 30
        costo = round(salario_diario * vac.dias_tomados * VACATION_FACTOR_PRESTACIONES, 2)
        dep_name = personal.departamento.nombre_departamento if personal.departamento else "Sin departamento"
        entry = by_department_cost.setdefault(dep_name, {"dias": 0, "costo": 0.0, "colaboradores": set()})
        entry["dias"] += vac.dias_tomados
        entry["costo"] += costo
        entry["colaboradores"].add(emp.codigo_empresa)
        total_dias += vac.dias_tomados
        total_costo_otorgadas += costo
        employees_with_vacation.add(emp.codigo_empresa)

    active_query = (
        db.query(models.Employee, models.Personnel)
        .join(models.Personnel, models.Personnel.codigo_empresa == models.Employee.codigo_empresa)
        .filter(models.Employee.estado == "activo")
    )
    if department_id:
        active_query = active_query.filter(models.Personnel.id_departamento == department_id)

    no_vacation_by_department: dict[str, dict[str, Any]] = {}
    total_costo_no_otorgadas = 0.0
    total_sin_vacaciones = 0

    for emp, personal in active_query.all():
        if emp.codigo_empresa in employees_with_vacation:
            continue
        salario = emp.salario_mensual or 0
        costo = round(salario * VACATION_FACTOR_RIESGO_NO_OTORGAR, 2)
        dep_name = personal.departamento.nombre_departamento if personal.departamento else "Sin departamento"
        entry = no_vacation_by_department.setdefault(dep_name, {"colaboradores": 0, "costo": 0.0})
        entry["colaboradores"] += 1
        entry["costo"] += costo
        total_costo_no_otorgadas += costo
        total_sin_vacaciones += 1

    return {
        "supuestos": {
            "factor_prestaciones": VACATION_FACTOR_PRESTACIONES,
            "factor_riesgo_no_otorgar": VACATION_FACTOR_RIESGO_NO_OTORGAR,
            "nota": (
                "Costo de otorgar = salario diario x dias tomados x factor de prestaciones "
                "(cargas sociales estimadas). Costo de no otorgar = estimacion de productividad "
                "perdida / riesgo de rotacion para colaboradores activos sin vacaciones "
                "registradas en el periodo, como % de su salario mensual. Son supuestos "
                "razonables para fines de analisis gerencial, no cifras contables exactas."
            ),
        },
        "periodo": {"anio": anio, "mes": mes, "semestre": semestre},
        "resumen": {
            "total_dias_otorgados": total_dias,
            "total_costo_otorgadas": round(total_costo_otorgadas, 2),
            "colaboradores_con_vacaciones": len(employees_with_vacation),
            "colaboradores_sin_vacaciones": total_sin_vacaciones,
            "total_costo_no_otorgadas": round(total_costo_no_otorgadas, 2),
        },
        "otorgadas_por_departamento": [
            {
                "departamento": name,
                "dias": data["dias"],
                "costo": round(data["costo"], 2),
                "colaboradores": len(data["colaboradores"]),
            }
            for name, data in sorted(by_department_cost.items())
        ],
        "no_otorgadas_por_departamento": [
            {"departamento": name, "colaboradores": data["colaboradores"], "costo": round(data["costo"], 2)}
            for name, data in sorted(no_vacation_by_department.items())
        ],
    }


# --------------------------------------------------------------------------
# Solicitudes entre departamentos (quien pide que documento a quien, y si
# esta pendiente o completada).
# --------------------------------------------------------------------------

def department_request_to_dict(row: models.DepartmentRequest) -> dict[str, Any]:
    return {
        "id_solicitud": row.id_solicitud,
        "id_departamento_origen": row.id_departamento_origen,
        "departamento_origen": row.departamento_origen.nombre_departamento if row.departamento_origen else None,
        "id_departamento_destino": row.id_departamento_destino,
        "departamento_destino": row.departamento_destino.nombre_departamento if row.departamento_destino else None,
        "documento": row.documento,
        "fecha_solicitud": row.fecha_solicitud,
        "estado": row.estado,
        "observaciones": row.observaciones,
        "fecha_completado": row.fecha_completado,
    }


def list_department_requests(
    db: Session,
    department_id: int | None = None,
    estado: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    query = db.query(models.DepartmentRequest).options(
        joinedload(models.DepartmentRequest.departamento_origen),
        joinedload(models.DepartmentRequest.departamento_destino),
    )
    if department_id:
        query = query.filter(
            or_(
                models.DepartmentRequest.id_departamento_origen == department_id,
                models.DepartmentRequest.id_departamento_destino == department_id,
            )
        )
    if estado:
        query = query.filter(models.DepartmentRequest.estado == estado)
    rows = query.order_by(desc(models.DepartmentRequest.fecha_solicitud)).limit(limit).all()
    return [department_request_to_dict(row) for row in rows]


def create_department_request(db: Session, payload: schemas.DepartmentRequestCreate) -> dict[str, Any]:
    _require_department(db, payload.id_departamento_origen)
    _require_department(db, payload.id_departamento_destino)
    request = models.DepartmentRequest(
        id_departamento_origen=payload.id_departamento_origen,
        id_departamento_destino=payload.id_departamento_destino,
        documento=payload.documento,
        fecha_solicitud=payload.fecha_solicitud,
        observaciones=payload.observaciones,
        estado="pendiente",
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return department_request_to_dict(request)


def update_department_request(
    db: Session, request_id: int, payload: schemas.DepartmentRequestUpdate
) -> dict[str, Any]:
    request = (
        db.query(models.DepartmentRequest)
        .filter(models.DepartmentRequest.id_solicitud == request_id)
        .first()
    )
    if not request:
        raise ValueError("La solicitud indicada no existe.")
    request.estado = payload.estado
    request.observaciones = payload.observaciones if payload.observaciones is not None else request.observaciones
    request.fecha_completado = date.today() if payload.estado == "completada" else None
    db.commit()
    db.refresh(request)
    return department_request_to_dict(request)
