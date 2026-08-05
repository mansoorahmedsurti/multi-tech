-- ==============================================================================
-- 1. CLEANUP & STRUCTURAL RESET (Ensures clean sync with new role scopes)
-- ==============================================================================
DROP TABLE IF EXISTS advance_spends CASCADE;
DROP TABLE IF EXISTS advances CASCADE;
DROP TABLE IF EXISTS ledgers CASCADE;
DROP TABLE IF EXISTS vouchers CASCADE;
DROP TABLE IF EXISTS projects CASCADE;
DROP TABLE IF EXISTS companies CASCADE;
DROP TABLE IF EXISTS users CASCADE;

-- ==============================================================================
-- 2. CORE TABLE CREATION (Aligned exactly with app.py definitions)
-- ==============================================================================

-- Create users table with correct system roles: 'CEO', 'Accountant', 'Advance'
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(255) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    role VARCHAR(255) NOT NULL,
    can_view_dashboard BOOLEAN NOT NULL DEFAULT FALSE,
    reset_token TEXT
);

-- Create companies table
CREATE TABLE companies (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    site VARCHAR(255),
    description TEXT
);

-- Create projects table
CREATE TABLE projects (
    id SERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    UNIQUE(company_id, name)
);

-- Create ledgers table (Voucher approvals land safely here as 'expense')
CREATE TABLE ledgers (
    id SERIAL PRIMARY KEY,
    project_id INT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    type VARCHAR(50) NOT NULL CHECK (type IN ('expense', 'income', 'loan')),
    title VARCHAR(255) NOT NULL,
    cheque_number VARCHAR(100),
    voucher_ref_id INT, -- Keeps strict mapping to prevent double-payout loops
    amount FLOAT NOT NULL DEFAULT 0.0,
    created_at DATE NOT NULL DEFAULT CURRENT_DATE
);

-- Create advances table
CREATE TABLE advances (
    id SERIAL PRIMARY KEY,
    project_id INT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    person_name VARCHAR(255) NOT NULL,
    allocated_amount FLOAT NOT NULL DEFAULT 0.0,
    UNIQUE(project_id, person_name)
);

-- Create advance_spends table
CREATE TABLE advance_spends (
    id SERIAL PRIMARY KEY,
    advance_id INT NOT NULL REFERENCES advances(id) ON DELETE CASCADE,
    item_name VARCHAR(255) NOT NULL,
    amount_spent FLOAT NOT NULL DEFAULT 0.0,
    created_at DATE NOT NULL DEFAULT CURRENT_DATE
);

-- Create vouchers table with historical review logging parameters
CREATE TABLE vouchers (
    id SERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    project_id INT REFERENCES projects(id) ON DELETE SET NULL,
    title VARCHAR(255) NOT NULL,
    amount FLOAT NOT NULL DEFAULT 0.0,
    remarks TEXT,
    type VARCHAR(100) NOT NULL,
    created_by VARCHAR(255),
    review_remarks TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'Pending' CHECK (status IN ('Pending', 'Approved', 'Declined', 'To Be Discussed')),
    created_at DATE NOT NULL DEFAULT CURRENT_DATE
);

-- Create quotations table
CREATE TABLE IF NOT EXISTS quotations (
    id SERIAL PRIMARY KEY,
    company_name VARCHAR(255) NOT NULL,
    project_name VARCHAR(255) NOT NULL,
    quotation_number VARCHAR(100),
    amount FLOAT NOT NULL DEFAULT 0.0,
    status VARCHAR(50) NOT NULL DEFAULT 'Sent' CHECK (status IN ('Sent', 'Successful', 'Declined')),
    lead_generator VARCHAR(255),
    created_by VARCHAR(255),
    notes TEXT,
    created_at DATE NOT NULL DEFAULT CURRENT_DATE
);

-- Create quotation_estimates_invoices table (Connected Cost Estimates & Invoices)
CREATE TABLE IF NOT EXISTS quotation_estimates_invoices (
    id SERIAL PRIMARY KEY,
    quotation_id INT NOT NULL REFERENCES quotations(id) ON DELETE CASCADE,
    invoice_number VARCHAR(100),
    est_material_cost FLOAT NOT NULL DEFAULT 0.0,
    est_labor_cost FLOAT NOT NULL DEFAULT 0.0,
    est_overhead_cost FLOAT NOT NULL DEFAULT 0.0,
    invoice_amount FLOAT NOT NULL DEFAULT 0.0,
    invoice_status VARCHAR(50) NOT NULL DEFAULT 'Draft' CHECK (invoice_status IN ('Draft', 'Issued', 'Paid', 'Partially Paid')),
    updated_by VARCHAR(255),
    created_at DATE NOT NULL DEFAULT CURRENT_DATE
);

-- Create quotation_cost_components table (Itemized Cost Components for Quotation Planning & Purchase Comparison)
CREATE TABLE IF NOT EXISTS quotation_cost_components (
    id SERIAL PRIMARY KEY,
    quotation_id INT NOT NULL REFERENCES quotations(id) ON DELETE CASCADE,
    component_name VARCHAR(255) NOT NULL,
    price FLOAT NOT NULL DEFAULT 0.0,
    description TEXT,
    actual_price FLOAT NOT NULL DEFAULT 0.0,
    purchaser_notes TEXT,
    purchased_by VARCHAR(255),
    created_by VARCHAR(255),
    created_at DATE NOT NULL DEFAULT CURRENT_DATE
);

-- Enable Row Level Security (RLS) and grant explicit CRUD access policies
ALTER TABLE quotations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Allow public select on quotations" ON quotations;
DROP POLICY IF EXISTS "Allow public insert on quotations" ON quotations;
DROP POLICY IF EXISTS "Allow public update on quotations" ON quotations;
DROP POLICY IF EXISTS "Allow public delete on quotations" ON quotations;

CREATE POLICY "Allow public select on quotations" ON quotations FOR SELECT USING (true);
CREATE POLICY "Allow public insert on quotations" ON quotations FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow public update on quotations" ON quotations FOR UPDATE USING (true);
CREATE POLICY "Allow public delete on quotations" ON quotations FOR DELETE USING (true);

ALTER TABLE quotation_estimates_invoices ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Allow public select on quotation_estimates_invoices" ON quotation_estimates_invoices;
DROP POLICY IF EXISTS "Allow public insert on quotation_estimates_invoices" ON quotation_estimates_invoices;
DROP POLICY IF EXISTS "Allow public update on quotation_estimates_invoices" ON quotation_estimates_invoices;
DROP POLICY IF EXISTS "Allow public delete on quotation_estimates_invoices" ON quotation_estimates_invoices;

CREATE POLICY "Allow public select on quotation_estimates_invoices" ON quotation_estimates_invoices FOR SELECT USING (true);
CREATE POLICY "Allow public insert on quotation_estimates_invoices" ON quotation_estimates_invoices FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow public update on quotation_estimates_invoices" ON quotation_estimates_invoices FOR UPDATE USING (true);
CREATE POLICY "Allow public delete on quotation_estimates_invoices" ON quotation_estimates_invoices FOR DELETE USING (true);

ALTER TABLE quotation_cost_components ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Allow public select on quotation_cost_components" ON quotation_cost_components;
DROP POLICY IF EXISTS "Allow public insert on quotation_cost_components" ON quotation_cost_components;
DROP POLICY IF EXISTS "Allow public update on quotation_cost_components" ON quotation_cost_components;
DROP POLICY IF EXISTS "Allow public delete on quotation_cost_components" ON quotation_cost_components;

CREATE POLICY "Allow public select on quotation_cost_components" ON quotation_cost_components FOR SELECT USING (true);
CREATE POLICY "Allow public insert on quotation_cost_components" ON quotation_cost_components FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow public update on quotation_cost_components" ON quotation_cost_components FOR UPDATE USING (true);
CREATE POLICY "Allow public delete on quotation_cost_components" ON quotation_cost_components FOR DELETE USING (true);

-- ==============================================================================
-- 3. INITIAL SEED LOGISTICS PIPELINE (Deterministic Values)
-- ==============================================================================

-- Seed Default Security User Access Credentials (Including your master admin profile)
INSERT INTO users (username, password, role, can_view_dashboard) VALUES
('asif.arain', 'admin123', 'CEO', TRUE),
('ceo', 'ceo', 'CEO', TRUE),
('accountant', 'accountant', 'Accountant', TRUE)
ON CONFLICT (username) DO NOTHING;

-- Seed Sample Corporate Entities
INSERT INTO companies (name, site, description) VALUES
('Apex Holdings', 'Headquarters Main', 'Core operations firm'),
('Nexus Ventures', 'North Zone', 'Tech project venture portfolio')
ON CONFLICT (name) DO NOTHING;

-- Seed Sample Project Portfolios map
INSERT INTO projects (company_id, name, description) VALUES
((SELECT id FROM companies WHERE name='Apex Holdings'), 'Alpha Phase 1', 'Initial ground build'),
((SELECT id FROM companies WHERE name='Apex Holdings'), 'Beta Towers', 'Highrise framework execution'),
((SELECT id FROM companies WHERE name='Nexus Ventures'), 'Cloud Sync', 'Distributed server node setups')
ON CONFLICT (company_id, name) DO NOTHING;

-- Seed Core Balance Sheet Entries
INSERT INTO ledgers (project_id, type, title, amount, created_at) VALUES
((SELECT id FROM projects WHERE name='Alpha Phase 1'), 'income', 'Client Milestone 1', 150000.00, '2026-07-09'),
((SELECT id FROM projects WHERE name='Alpha Phase 1'), 'expense', 'Office Supplies', 12000.00, '2026-07-08'),
((SELECT id FROM projects WHERE name='Cloud Sync'), 'income', 'Pre-seed funding', 500000.00, '2026-06-20'),
((SELECT id FROM projects WHERE name='Cloud Sync'), 'loan', 'Bridge Loan', 100000.00, '2026-05-10');

-- Seed Sample Petty Cash Advances
INSERT INTO advances (project_id, person_name, allocated_amount) VALUES
((SELECT id FROM projects WHERE name='Alpha Phase 1'), 'Alice Smith', 5000.00),
((SELECT id FROM projects WHERE name='Alpha Phase 1'), 'Bob Johnson', 3000.00)
ON CONFLICT (project_id, person_name) DO NOTHING;

-- Seed Sample Quotations
INSERT INTO quotations (company_name, project_name, quotation_number, amount, status, created_by, notes) VALUES
('Apex Holdings', 'HVAC Installation Phase 2', 'QT-2026-001', 450000.00, 'Successful', 'asif.arain', 'Quotation approved by client. Proceeding with cost estimation.'),
('Nexus Ventures', 'Solar Panel Array Setup', 'QT-2026-002', 850000.00, 'Sent', 'accountant', 'Quotation sent via email. Awaiting review.')
ON CONFLICT DO NOTHING;