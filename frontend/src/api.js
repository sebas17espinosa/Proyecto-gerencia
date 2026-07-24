const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000/api";
const TOKEN_KEY = "talento360-token";

export function getToken() {
  try {
    return window.localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

export function setToken(token) {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Almacenamiento no disponible; la sesión no persiste al recargar.
  }
}

async function request(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  const token = getToken();
  const response = await fetch(`${API_URL}${path}`, {
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
    ...options,
  });

  if (response.status === 401) {
    setToken("");
  }

  if (!response.ok) {
    let detail = "Error de comunicación con el servidor";
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch {
      detail = response.statusText || detail;
    }
    throw new Error(detail);
  }

  return response.json();
}

function withParams(path, params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, value);
  });
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return `${path}${suffix}`;
}

export const api = {
  login: (correo, password) => request("/auth/login", { method: "POST", body: JSON.stringify({ correo, password }) }),
  logout: () => request("/auth/logout", { method: "POST" }),
  getMe: () => request("/auth/me"),
  getUsers: () => request("/auth/users"),
  createUser: (payload) => request("/auth/users", { method: "POST", body: JSON.stringify(payload) }),
  deleteUser: (id) => request(`/auth/users/${id}`, { method: "DELETE" }),

  getDashboard: (params = {}) => request(withParams("/dashboard", params)),
  getDepartments: () => request("/departments"),
  createDepartment: (payload) => request("/departments", { method: "POST", body: JSON.stringify(payload) }),
  updateDepartment: (id, payload) => request(`/departments/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteDepartment: (id) => request(`/departments/${id}`, { method: "DELETE" }),
  getEmployees: (params = {}) => request(withParams("/employees", params)),
  getEmployeeOptions: () => request("/employees/options"),
  getEmployeeWorkspace: (codigoEmpresa) => request(`/employees/${codigoEmpresa}/workspace`),
  getVacancies: () => request("/vacancies"),
  getEvaluations: (params = {}) => request(withParams("/evaluations", params)),
  createEmployee: (payload) => request("/employees", { method: "POST", body: JSON.stringify(payload) }),
  getRecentRecords: () => request("/records/recent"),
  getAttendance: (params = {}) => request(withParams("/attendance", params)),
  getAbsences: (params = {}) => request(withParams("/absences", params)),
  recordAttendance: (payload) => request("/attendance", { method: "POST", body: JSON.stringify(payload) }),
  recordAbsence: (payload) => request("/absences", { method: "POST", body: JSON.stringify(payload) }),
  recordVacation: (payload) => request("/vacations", { method: "POST", body: JSON.stringify(payload) }),
  recordTraining: (payload) => request("/trainings", { method: "POST", body: JSON.stringify(payload) }),
  recordEvaluation: (payload) => request("/evaluations", { method: "POST", body: JSON.stringify(payload) }),
  recordMovement: (payload) => request("/movements", { method: "POST", body: JSON.stringify(payload) }),
  recordTermination: (payload) => request("/terminations", { method: "POST", body: JSON.stringify(payload) }),
  getRecruitment: () => request("/recruitment"),
  getReportModules: () => request("/reports/modules"),
  getVacationCost: (params = {}) => request(withParams("/reports/vacation-cost", params)),
  simulateVacationCost: (params = {}) => request(withParams("/reports/vacation-cost/simulate", params)),
  getDepartmentRequests: (params = {}) => request(withParams("/department-requests", params)),
  createDepartmentRequest: (payload) => request("/department-requests", { method: "POST", body: JSON.stringify(payload) }),
  updateDepartmentRequest: (id, payload) => request(`/department-requests/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  exportReport: async (params = {}) => {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") search.set(key, value);
    });
    const token = getToken();
    const response = await fetch(`${API_URL}/reports/export?${search.toString()}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) {
      let detail = "No se pudo generar el reporte";
      try {
        const payload = await response.json();
        detail = payload.detail || detail;
      } catch {
        detail = response.statusText || detail;
      }
      throw new Error(detail);
    }
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^"]+)"?/);
    const filename = match ? match[1] : `reporte.${params.formato === "excel" ? "xlsx" : "pdf"}`;
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  },
  analyzeCv: (file, keywords = "") => {
    const body = new FormData();
    body.append("file", file);
    if (keywords.trim()) body.append("keywords", keywords);
    return request("/recruitment/analyze", { method: "POST", body });
  },
  seed: (reset = false, resetKey = "") => request(`/seed?reset=${reset}&employees=300`, {
    method: "POST",
    headers: resetKey ? { "X-Demo-Reset-Key": resetKey } : {},
  }),
};
