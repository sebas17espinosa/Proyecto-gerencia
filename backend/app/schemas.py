from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RequestModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class DepartmentCreate(RequestModel):
    nombre_departamento: str = Field(min_length=2, max_length=100)
    descripcion: Optional[str] = Field(default=None, max_length=255)


class EmployeeCreate(RequestModel):
    numero_cedula: str = Field(min_length=3, max_length=20)
    nombre: str = Field(min_length=2, max_length=100)
    apellido: str = Field(min_length=2, max_length=100)
    fecha_nacimiento: date
    nacionalidad: str = "Panameña"
    direccion: str = Field(min_length=5, max_length=255)
    telefono_principal: str = Field(min_length=7, max_length=20)
    telefono_secundario: Optional[str] = Field(default=None, max_length=20)
    fecha_ingreso: date
    puesto: str = Field(min_length=2, max_length=100)
    id_departamento: int = Field(gt=0)
    observaciones: Optional[str] = Field(default=None, max_length=1000)
    salario_mensual: Optional[float] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.fecha_nacimiento >= self.fecha_ingreso:
            raise ValueError("La fecha de nacimiento debe ser anterior a la fecha de ingreso.")
        return self


class AttendanceCreate(RequestModel):
    codigo_empresa: str = Field(pattern=r"^E\d{4}$")
    fecha: date
    presente: bool = True


class AbsenceCreate(RequestModel):
    codigo_empresa: str = Field(pattern=r"^E\d{4}$")
    fecha: date
    motivo: str = Field(min_length=2, max_length=255)
    justificada: bool = True


class VacationCreate(RequestModel):
    codigo_empresa: str = Field(pattern=r"^E\d{4}$")
    fecha_inicio: date
    fecha_fin: date
    observaciones: Optional[str] = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.fecha_fin < self.fecha_inicio:
            raise ValueError("La fecha final de las vacaciones no puede ser anterior a la fecha inicial.")
        return self


class TrainingCreate(RequestModel):
    codigo_empresa: str = Field(pattern=r"^E\d{4}$")
    nombre_capacitacion: str = Field(min_length=2, max_length=150)
    fecha_inicio: date
    fecha_fin: Optional[date] = None

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.fecha_fin and self.fecha_fin < self.fecha_inicio:
            raise ValueError("La fecha final de la capacitación no puede ser anterior a la fecha inicial.")
        return self


class EvaluationCreate(RequestModel):
    codigo_empresa: str = Field(pattern=r"^E\d{4}$")
    fecha_evaluacion: date
    pct_bruto: float = Field(ge=0, le=100)


class TerminationCreate(RequestModel):
    codigo_empresa: str = Field(pattern=r"^E\d{4}$")
    fecha_salida: date
    motivo_salida: str = Field(min_length=2, max_length=255)
    observaciones: Optional[str] = Field(default=None, max_length=1000)


class MovementCreate(RequestModel):
    codigo_empresa: str = Field(pattern=r"^E\d{4}$")
    fecha_movimiento: date
    puesto_nuevo: str = Field(min_length=2, max_length=100)
    depto_nuevo: int = Field(gt=0)
    motivo: Optional[str] = Field(default=None, max_length=255)


ROLES_VALIDOS = ("admin", "gerencia_rrhh", "usuario")


class DepartmentRequestCreate(RequestModel):
    id_departamento_origen: int = Field(gt=0)
    id_departamento_destino: int = Field(gt=0)
    documento: str = Field(min_length=2, max_length=255)
    fecha_solicitud: date
    observaciones: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_departments(self):
        if self.id_departamento_origen == self.id_departamento_destino:
            raise ValueError("El departamento de origen y destino deben ser diferentes.")
        return self


class DepartmentRequestUpdate(RequestModel):
    estado: str
    observaciones: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_estado(self):
        if self.estado not in ("pendiente", "completada"):
            raise ValueError("El estado debe ser 'pendiente' o 'completada'.")
        return self


class LoginRequest(RequestModel):
    correo: str = Field(min_length=3, max_length=150)
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_usuario: int
    correo: str
    nombre: str
    rol: str
    codigo_empresa: Optional[str] = None
    activo: bool


class LoginResponse(BaseModel):
    access_token: str
    user: UserOut


class UserCreate(RequestModel):
    correo: str = Field(min_length=3, max_length=150)
    password: str = Field(min_length=6, max_length=200)
    nombre: str = Field(min_length=2, max_length=150)
    rol: str
    codigo_empresa: Optional[str] = None

    @model_validator(mode="after")
    def validate_rol(self):
        if self.rol not in ROLES_VALIDOS:
            raise ValueError(f"Rol inválido. Use uno de: {', '.join(ROLES_VALIDOS)}.")
        if self.rol == "usuario" and not self.codigo_empresa:
            raise ValueError("Un usuario con rol 'usuario' debe estar ligado a un código de colaborador.")
        return self
