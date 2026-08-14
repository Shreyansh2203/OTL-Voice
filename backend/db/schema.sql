-- Dummy reference tables for the OTL Timesheet Assistant.
--
-- Column names map onto the TimecardEntry_c fields the app writes (see
-- otl_client.map_entry_to_otl):
--   employees.employee_id  -> Employee_Number_c
--   employees.full_name    -> Employee_Name_c
--   work_orders.work_order -> Work_Order_c
--   projects.project_no    -> Project_No_c   (integer, per the live API)
--   projects.project_name  -> Project_Name_c
--   project_tasks.task_details -> Tasks_Details_c (Oracle caps this at 80 chars)
--
-- The two relationship rules are enforced structurally rather than by trigger:
--   * one work order has many project numbers, but a project number belongs to
--     exactly one work order -- projects.work_order is a single NOT NULL FK, so
--     a project row cannot physically carry two work orders;
--   * a project number determines its name and its tasks -- project_name lives
--     only in projects (keyed by the project_no primary key) and tasks hang off
--     project_tasks.project_no.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Employees (front-end auth)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS employees (
    employee_id   TEXT PRIMARY KEY,                     -- OTL Employee_Number_c
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,  -- sign-in name
    password_hash TEXT NOT NULL,                        -- pbkdf2_sha256$iters$salt$hash
    full_name     TEXT NOT NULL,                        -- OTL Employee_Name_c
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- Labour catalogue
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS work_orders (
    work_order  TEXT PRIMARY KEY,                       -- OTL Work_Order_c
    description TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS projects (
    project_no   INTEGER PRIMARY KEY,                   -- OTL Project_No_c
    work_order   TEXT NOT NULL REFERENCES work_orders(work_order),
    project_name TEXT NOT NULL,                         -- OTL Project_Name_c
    is_active    INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_projects_work_order ON projects(work_order);

CREATE TABLE IF NOT EXISTS project_tasks (
    task_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    project_no   INTEGER NOT NULL REFERENCES projects(project_no) ON DELETE CASCADE,
    task_details TEXT NOT NULL CHECK (length(task_details) <= 80),  -- Tasks_Details_c
    is_active    INTEGER NOT NULL DEFAULT 1,
    UNIQUE (project_no, task_details)
);

CREATE INDEX IF NOT EXISTS idx_project_tasks_project ON project_tasks(project_no);

-- ---------------------------------------------------------------------------
-- Who works on what
-- ---------------------------------------------------------------------------
-- Deliberately carries no work_order or project_name column: both are functions
-- of project_no, so storing them here would let them drift out of sync with
-- projects. Read them back through v_employee_labour instead.
CREATE TABLE IF NOT EXISTS assignments (
    employee_id TEXT    NOT NULL REFERENCES employees(employee_id) ON DELETE CASCADE,
    project_no  INTEGER NOT NULL REFERENCES projects(project_no)   ON DELETE CASCADE,
    assigned_at TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (employee_id, project_no)
);

CREATE INDEX IF NOT EXISTS idx_assignments_project ON assignments(project_no);

-- ---------------------------------------------------------------------------
-- Flat read model: employee -> work order -> project -> task
-- ---------------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_employee_labour AS
SELECT e.employee_id,
       e.username,
       e.full_name,
       p.work_order,
       p.project_no,
       p.project_name,
       t.task_id,
       t.task_details
FROM assignments a
JOIN employees e USING (employee_id)
JOIN projects  p USING (project_no)
LEFT JOIN project_tasks t
       ON t.project_no = p.project_no AND t.is_active = 1
WHERE e.is_active = 1 AND p.is_active = 1;
