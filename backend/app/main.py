from contextlib import asynccontextmanager
from datetime import date
import os
import secrets

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models, repository, reports, schemas
from .database import Base, SessionLocal, engine, get_db
from .seed import reset_demo_data, seed_demo_data, seed_demo_users


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_demo_data(db, employee_count=300)
        seed_demo_users(db)
    yield


app = FastAPI(
    title="Sistema de Gestión de Recursos Humanos",
    description="Backend del proyecto semestral de Gerencia de Recursos Humanos.",
    version="1.0.0",
    lifespan=lifespan,
)

origins = [
    item.strip()
    for item in os.getenv("BACKEND_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if item.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ValueError)
async def value_error_handler(_request: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(IntegrityError)
async def integrity_error_handler(_request: Request, _exc: IntegrityError):
    return JSONResponse(
        status_code=409,
        content={"detail": "El registro está duplicado o hace referencia a datos no válidos."},
    )


# --------------------------------------------------------------------------
# Autenticacion y control de acceso por rol
# --------------------------------------------------------------------------

def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> models.User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Debe iniciar sesión para continuar.")
    token = authorization.split(" ", 1)[1].strip()
    user = repository.get_user_by_token(db, token)
    if not user:
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada. Inicie sesión de nuevo.")
    return user


def require_roles(*roles: str):
    def dependency(user: models.User = Depends(get_current_user)) -> models.User:
        if user.rol not in roles:
            raise HTTPException(status_code=403, detail="No tiene permisos para realizar esta acción.")
        return user

    return dependency


# Cualquier usuario autenticado (admin, gerencia_rrhh o usuario).
require_any_user = Depends(get_current_user)
# Solo perfiles de gestion (crear/editar/eliminar datos de RRHH).
require_management = Depends(require_roles("admin", "gerencia_rrhh"))
# Solo administrador (gestion de cuentas del sistema).
require_admin = Depends(require_roles("admin"))


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/login", response_model=schemas.LoginResponse)
def login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    try:
        user = repository.authenticate(db, payload.correo, payload.password)
    except repository.AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return {"access_token": user.token_actual, "user": repository.user_to_dict(user)}


@app.post("/api/auth/logout")
def logout(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    repository.logout(db, user)
    return {"status": "ok"}


@app.get("/api/auth/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(get_current_user)):
    return repository.user_to_dict(user)


@app.get("/api/auth/users", dependencies=[require_admin])
def get_users(db: Session = Depends(get_db)):
    return repository.list_users(db)


@app.post("/api/auth/users", dependencies=[require_admin])
def post_user(payload: schemas.UserCreate, db: Session = Depends(get_db)):
    try:
        return repository.create_user(db, payload)
    except repository.AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/auth/users/{user_id}", dependencies=[require_admin])
def delete_user(user_id: int, db: Session = Depends(get_db)):
    try:
        return repository.delete_user(db, user_id)
    except repository.AuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/seed", dependencies=[require_admin])
def seed(
    reset: bool = False,
    employees: int = Query(default=300, ge=300, le=1000),
    reset_key: str | None = Header(default=None, alias="X-Demo-Reset-Key"),
    db: Session = Depends(get_db),
):
    if reset:
        expected_key = os.getenv("DEMO_RESET_KEY")
        if not expected_key or not reset_key or not secrets.compare_digest(reset_key, expected_key):
            raise HTTPException(
                status_code=403,
                detail="La regeneración de datos requiere la clave de demostración.",
            )
        reset_demo_data(db, employee_count=employees)
    else:
        seed_demo_data(db, employee_count=employees)
    seed_demo_users(db)
    return {"status": "ok", "employees": db.query(models.Employee).count()}


@app.get("/api/dashboard", dependencies=[require_management])
def get_dashboard(
    start_date: date | None = None,
    end_date: date | None = None,
    department_id: int | None = None,
    status: str | None = "todos",
    db: Session = Depends(get_db),
):
    return repository.dashboard(
        db,
        start_date=start_date,
        end_date=end_date,
        department_id=department_id,
        status=status,
    )


@app.get("/api/departments", dependencies=[require_any_user])
def get_departments(db: Session = Depends(get_db)):
    return repository.list_departments(db)


@app.post("/api/departments", dependencies=[require_management])
def post_department(payload: schemas.DepartmentCreate, db: Session = Depends(get_db)):
    return repository.create_department(db, payload)


@app.put("/api/departments/{department_id}", dependencies=[require_management])
def put_department(
    department_id: int,
    payload: schemas.DepartmentCreate,
    db: Session = Depends(get_db),
):
    return repository.update_department(db, department_id, payload)


@app.delete("/api/departments/{department_id}", dependencies=[require_management])
def delete_department(department_id: int, db: Session = Depends(get_db)):
    return repository.delete_department(db, department_id)


@app.get("/api/employees", dependencies=[require_management])
def get_employees(
    q: str | None = None,
    department_id: int | None = None,
    status: str | None = "todos",
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return repository.list_employees(db, q=q, department_id=department_id, status=status, limit=limit)


@app.get("/api/employees/options", dependencies=[require_management])
def get_employee_options(db: Session = Depends(get_db)):
    return repository.get_active_employee_options(db)


@app.get("/api/employees/{codigo_empresa}/workspace")
def get_employee_workspace(
    codigo_empresa: str,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.rol == "usuario" and user.codigo_empresa != codigo_empresa:
        raise HTTPException(status_code=403, detail="Solo puede consultar su propia información.")
    return repository.employee_workspace(db, codigo_empresa)


@app.get("/api/vacancies", dependencies=[require_management])
def get_vacancies():
    return repository.list_vacancies()


@app.get("/api/evaluations", dependencies=[require_management])
def get_evaluations(
    codigo_empresa: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return repository.list_evaluations(db, codigo_empresa=codigo_empresa, limit=limit)


@app.post("/api/employees", dependencies=[require_management])
def post_employee(payload: schemas.EmployeeCreate, db: Session = Depends(get_db)):
    return repository.create_employee(db, payload)


@app.get("/api/records/recent", dependencies=[require_management])
def get_recent_records(db: Session = Depends(get_db)):
    return repository.recent_records(db)


@app.get("/api/attendance", dependencies=[require_management])
def get_attendance(
    codigo_empresa: str | None = None,
    department_id: int | None = None,
    anio: int | None = None,
    mes: int | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    return repository.list_attendance(
        db, codigo_empresa=codigo_empresa, department_id=department_id, anio=anio, mes=mes, limit=limit
    )


@app.get("/api/absences", dependencies=[require_management])
def get_absences(
    codigo_empresa: str | None = None,
    department_id: int | None = None,
    anio: int | None = None,
    mes: int | None = None,
    justificada: bool | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    return repository.list_absences(
        db,
        codigo_empresa=codigo_empresa,
        department_id=department_id,
        anio=anio,
        mes=mes,
        justificada=justificada,
        limit=limit,
    )


def _guard_own_record(user: models.User, codigo_empresa: str) -> None:
    """Un rol 'usuario' solo puede registrar movimientos sobre si mismo."""
    if user.rol == "usuario" and user.codigo_empresa != codigo_empresa:
        raise HTTPException(status_code=403, detail="Solo puede registrar información sobre su propio perfil.")


@app.post("/api/attendance")
def post_attendance(
    payload: schemas.AttendanceCreate,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _guard_own_record(user, payload.codigo_empresa)
    return repository.record_attendance(db, payload)


@app.post("/api/absences")
def post_absence(
    payload: schemas.AbsenceCreate,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _guard_own_record(user, payload.codigo_empresa)
    return repository.record_absence(db, payload)


@app.post("/api/vacations", dependencies=[require_management])
def post_vacation(payload: schemas.VacationCreate, db: Session = Depends(get_db)):
    return repository.record_vacation(db, payload)


@app.post("/api/trainings", dependencies=[require_management])
def post_training(payload: schemas.TrainingCreate, db: Session = Depends(get_db)):
    return repository.record_training(db, payload)


@app.post("/api/evaluations", dependencies=[require_management])
def post_evaluation(payload: schemas.EvaluationCreate, db: Session = Depends(get_db)):
    return repository.record_evaluation(db, payload)


@app.post("/api/movements", dependencies=[require_management])
def post_movement(payload: schemas.MovementCreate, db: Session = Depends(get_db)):
    return repository.record_movement(db, payload)


@app.post("/api/terminations", dependencies=[require_management])
def post_termination(payload: schemas.TerminationCreate, db: Session = Depends(get_db)):
    return repository.record_termination(db, payload)


@app.get("/api/recruitment", dependencies=[require_management])
def get_recruitment():
    return repository.recruitment_report()


@app.post("/api/recruitment/analyze", dependencies=[require_management])
async def post_recruitment_analysis(
    file: UploadFile = File(...),
    keywords: str | None = Form(default=None),
):
    content = await file.read()
    return repository.analyze_cv(file.filename or "hoja_de_vida.txt", content, keywords)


@app.get("/api/reports/vacation-cost", dependencies=[require_management])
def get_vacation_cost(
    department_id: int | None = None,
    anio: int | None = None,
    mes: int | None = None,
    semestre: int | None = None,
    db: Session = Depends(get_db),
):
    return repository.vacation_cost_summary(
        db, department_id=department_id, anio=anio, mes=mes, semestre=semestre
    )


@app.get("/api/reports/vacation-cost/simulate", dependencies=[require_management])
def get_vacation_cost_simulation(
    codigo_empresa: str,
    dias: int = Query(ge=1, le=60),
    db: Session = Depends(get_db),
):
    return repository.simulate_vacation_cost(db, codigo_empresa=codigo_empresa, dias=dias)


@app.get("/api/department-requests", dependencies=[require_management])
def get_department_requests(
    department_id: int | None = None,
    estado: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    return repository.list_department_requests(db, department_id=department_id, estado=estado, limit=limit)


@app.post("/api/department-requests", dependencies=[require_management])
def post_department_request(payload: schemas.DepartmentRequestCreate, db: Session = Depends(get_db)):
    return repository.create_department_request(db, payload)


@app.put("/api/department-requests/{request_id}", dependencies=[require_management])
def put_department_request(
    request_id: int, payload: schemas.DepartmentRequestUpdate, db: Session = Depends(get_db)
):
    try:
        return repository.update_department_request(db, request_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/reports/modules", dependencies=[require_management])
def get_report_modules():
    return [{"id": key, "label": value} for key, value in reports.MODULOS.items()]


@app.get("/api/reports/export", dependencies=[require_management])
def get_report_export(
    modulo: str,
    formato: str,
    department_id: int | None = None,
    codigo_empresa: str | None = None,
    anio: int | None = None,
    mes: int | None = None,
    semestre: int | None = None,
    db: Session = Depends(get_db),
):
    try:
        content, filename, media_type = reports.build_report(
            db,
            modulo=modulo,
            formato=formato,
            department_id=department_id,
            codigo_empresa=codigo_empresa,
            anio=anio,
            mes=mes,
            semestre=semestre,
        )
    except reports.ReportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
