"""
Database-level protection: the audit table refuses UPDATE, DELETE and TRUNCATE,
even from code that bypasses the Django model. Created in every schema.

A future data-retention job that must delete very old events will need an
explicit, audited maintenance procedure that temporarily disables this trigger.
"""
from django.db import migrations

CREATE = """
CREATE OR REPLACE FUNCTION audit_event_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit events cannot be changed or deleted';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_event_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_auditevent
    FOR EACH ROW EXECUTE FUNCTION audit_event_immutable();

CREATE TRIGGER audit_event_no_truncate
    BEFORE TRUNCATE ON audit_auditevent
    FOR EACH STATEMENT EXECUTE FUNCTION audit_event_immutable();
"""

DROP = """
DROP TRIGGER IF EXISTS audit_event_no_truncate ON audit_auditevent;
DROP TRIGGER IF EXISTS audit_event_no_update_delete ON audit_auditevent;
DROP FUNCTION IF EXISTS audit_event_immutable();
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]
    operations = [migrations.RunSQL(CREATE, DROP)]
