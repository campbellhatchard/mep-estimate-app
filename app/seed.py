from __future__ import annotations
import json, os, re
from pathlib import Path
from datetime import datetime
from sqlalchemy.orm import Session
from .models import User, ConfigurationVersion, ConfigItem
from .auth import normalize_username, hash_password

SEED_PATH = Path(__file__).parent / "seed" / "approved_model_2026_08_1.json"

def slug(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_") or "BLANK"

def add_item(db: Session, version_id: int, category: str, key: str, label: str, *,
             value_number=None, value_text=None, value_type="text", unit=None,
             description=None, parent_key=None, sort_order=0, active=True):
    db.add(ConfigItem(config_version_id=version_id, category=category, key=key, label=label,
                      value_number=value_number, value_text=value_text, value_type=value_type,
                      unit=unit, description=description, parent_key=parent_key,
                      sort_order=sort_order, active=active))

def seed_database(db: Session):
    admin = db.query(User).filter(User.username_normalized == "admin").first()
    if not admin:
        password = os.getenv("ADMIN_PASSWORD", "ChangeMe123!")
        admin = User(username="Admin", username_normalized="admin", password_hash=hash_password(password), role="ADMIN")
        db.add(admin); db.flush()
    if db.query(ConfigurationVersion).count():
        db.commit(); return
    data = json.loads(SEED_PATH.read_text())
    v = ConfigurationVersion(name=data["configuration_name"], status="ACTIVE", created_by=admin.id,
                             change_reason="Initial application model extracted from approved MEP 2026 workbook",
                             activated_at=datetime.utcnow(), approval_status="ACTIVE")
    db.add(v); db.flush()
    for i,p in enumerate(data["parameters"]):
        add_item(db,v.id,p["category"],p["key"],p["label"],value_number=p["value"],value_type=p["type"],sort_order=i)
    for i,row in enumerate(data["solutions"]):
        add_item(db,v.id,"Solution Type",row["key"],row["label"],value_text=json.dumps(row),value_type="json",sort_order=i)
    for i,row in enumerate(data["erps"]):
        add_item(db,v.id,"ERP",row["key"],row["label"],value_number=row.get("base_effort"),value_type="hours",sort_order=i)
    for i,row in enumerate(data["user_counts"]):
        add_item(db,v.id,"User Count",row["key"],row["label"],value_text=json.dumps(row),value_type="json",sort_order=i)
    simple_groups = {
        "Customer Type": data["customer_types"], "Yes No": data["yes_no"], "Go Live": data["go_live"],
        "Test Effort": data["test_effort"], "EPP Install": data["epp_install"],
        "Currency": data["currencies"], "Entity": data["entities"], "Schedule Status": data["schedule_status"],
    }
    for cat, values in simple_groups.items():
        for i,label in enumerate(values):
            add_item(db,v.id,cat,slug(str(label)),str(label),value_number=float(label) if cat=="Test Effort" else None,
                     value_type="percentage" if cat=="Test Effort" else "text",sort_order=i)
    for cat, rows, value_field, value_type in [
        ("Application Effort", data["app_types"], "hours", "hours"),
        ("Custom Effort", data["custom_effort"], "hours", "hours"),
        ("Package Effort", data["package_types"], "hours", "hours"),
        ("Delivery Method", data["delivery_methods"], "markup", "percentage"),
        ("Security Method", data["security"], "hours", "hours"),
        ("EPP Integration", data["epp_integration_effort"], "hours", "hours"),
        ("Upgrade Type", data["upgrade_types"], "factor", "multiplier"),
    ]:
        for i,row in enumerate(rows):
            add_item(db,v.id,cat,slug(row["label"] or "NONE"),row["label"] or "None",value_number=row[value_field],value_type=value_type,sort_order=i)
    for i,row in enumerate(data["uat_site_multipliers"]):
        add_item(db,v.id,"UAT Site Multiplier",f"SITES_{row['sites']}",str(row["sites"]),value_number=row["multiplier"],value_type="multiplier",sort_order=i)
    # ERP application and package catalogs use parent_key to keep the catalog normalized and searchable.
    for erp, apps in data["erp_applications"].items():
        parent = slug(erp)
        for i,label in enumerate(apps):
            add_item(db,v.id,"ERP Application",f"{parent}__APP_{i+1:02d}",label,parent_key=parent,sort_order=i)
    for erp, pkgs in data["erp_packages"].items():
        parent = slug(erp)
        for i,label in enumerate(pkgs):
            add_item(db,v.id,"ERP Package",f"{parent}__PKG_{i+1:02d}",label,parent_key=parent,sort_order=i)
    db.commit()
