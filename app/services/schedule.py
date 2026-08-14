from __future__ import annotations
import json, re
from pathlib import Path
from datetime import date, timedelta
from sqlalchemy.orm import Session
from ..models import EstimateRevision, ScheduleTask
from .calculation import calculation

TEMPLATE_PATH=Path(__file__).resolve().parents[1]/"seed"/"schedule_template_2026.json"

def norm(s: str) -> str:
    s=(s or "").casefold().replace("go-live","go live").replace("go-live","go live")
    s=re.sub(r"^not included\s*-\s*", "", s)
    s=re.sub(r"\s*\(did not opt-in\)\s*", "", s)
    s=re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())

def business_add(start: date, days: int) -> date:
    d=start; added=0
    while added < max(0,days):
        d += timedelta(days=1)
        if d.weekday()<5: added+=1
    return d

def generate_schedule(db: Session, rev: EstimateRevision, replace=True):
    calc_lines, summary, details, detail_summ = calculation(db,rev)
    if replace:
        db.query(ScheduleTask).filter(ScheduleTask.revision_id==rev.id).delete(synchronize_session=False)
    calc_by_norm={norm(x.description):x.extended_hours for x in calc_lines}
    # aliases where Schedule wording differs slightly from Calculations wording.
    aliases={
        norm("Go-live Project Management"):"GO_LIVE_PM",
        norm("Project Preparation and Setup"):"PLAN_PREP",
        norm("MEP On-Premise Installation"):"PLAN_MEP_INSTALL",
        norm("Enterprise Printing Platform Installation"):"PLAN_EPP_INSTALL",
        norm("EPP Print Bridge Installation"):"PLAN_PRINT_BRIDGE",
        norm("Gateway Installation"):"PLAN_GATEWAY",
        norm("SSO Setup / Configure"):"PLAN_SSO",
        norm("Base Application Package Install"):"PLAN_BASE_PACKAGE",
        norm("Customer Facility Review"):"PLAN_FACILITY",
        norm("Solution Orientation Prep"):"PLAN_ORIENTATION_PREP",
        norm("Solution Orientation Session"):"PLAN_ORIENTATION",
        norm("Pacejet Requirements Session"):"PLAN_PACEJET",
        norm("Gap Analysis"):"PLAN_GAP",
        norm("Business Requirement Document (BRD) Creation & Review Sessions"):"PLAN_BRD",
        norm("Solution Design"):"DESIGN_SOLUTION",
        norm("CI to Write Test Scripts"):"DESIGN_CI_TEST_SCRIPTS",
        norm("Internal Solution Design Review"):"DESIGN_INTERNAL_REVIEW",
        norm("Application Developer Training"):"BUILD_APP_DEV_TRAINING",
        norm("Setup Unit Test Data"):"BUILD_UNIT_TEST_DATA",
        norm("Admin Setup User / Roles Training"):"BUILD_ADMIN_TRAINING",
        norm("Pacejet Solution Validation"):"BUILD_PACEJET_VALIDATION",
        norm("Application Demonstrations"):"BUILD_APP_DEMOS",
        norm("Application Remediation Review"):"BUILD_REMEDIATION",
        norm("Solution Workshop / Conference Room Pilot and Train the Trainer"):"BUILD_WORKSHOP",
        norm("Application Promotion & Stage Environment Validation"):"BUILD_PROMOTION",
        norm("Develop End User Documentation"):"TEST_END_USER_DOC",
        norm("CI Led End User Training"):"TEST_END_USER_TRAINING",
    }
    by_key={x.key:x.extended_hours for x in calc_lines}
    phase_totals=summary["phase_totals"]
    section_lists={}
    for sec in ["Baseline Applications","Baseline Packages","Custom Applications","Labels","IoT Service Definitions","ERP Service Definitions","Data Replication Sessions"]:
        section_lists[sec]=[x for x in details if x.section==sec]
    template=json.loads(TEMPLATE_PATH.read_text())
    start=rev.project_start or rev.proposal_date or date.today()
    rev.project_start=start
    current=start
    phase="Plan"
    phase_headers={9:"Plan",56:"Design",64:"Build",227:"Test",246:"Go Live"}
    ranges=[(74,108,"Baseline Applications"),(110,114,"Baseline Packages"),(116,135,"Custom Applications"),(139,158,"Labels"),(160,169,"IoT Service Definitions"),(171,190,"ERP Service Definitions"),(192,211,"Data Replication Sessions")]
    for order,row in enumerate(template):
        r=row["source_row"]
        if r in phase_headers: phase=phase_headers[r]
        task=str(row.get("task") or "")
        bill=0.0
        detail_line=None
        for lo,hi,sec in ranges:
            if lo<=r<=hi:
                idx=r-lo
                if idx<len(section_lists[sec]): detail_line=section_lists[sec][idx]
                task=detail_line.definition if detail_line and detail_line.total>0 else "Not Included"
                bill=detail_line.total if detail_line and detail_line.total>0 else 0
                break
        if r==137:
            up=[x for x in details if x.section=="Upgrade Definition"]
            detail_line=up[0] if up else None
            task="Upgrade Application Conversion" if detail_line and detail_line.total>0 else "Not Included"
            bill=detail_line.total if detail_line else 0
        if r in phase_headers:
            bill=phase_totals.get(phase,{}).get("extended",0)
        elif r==72:
            bill=by_key.get("BUILD_EPP_INTEGRATION",0)
        elif detail_line is None and row.get("billable_formula") and "Calculations" in row["billable_formula"]:
            n=norm(task)
            key=aliases.get(n)
            bill=by_key.get(key,calc_by_norm.get(n,0)) if key else calc_by_norm.get(n,0)
        # Dynamic Not Included wording where a matching calculation exists at zero.
        if task.startswith("Not Included - "):
            base=task[len("Not Included - "):]
            base=re.sub(r"\s*\(did not opt-in\)\s*","",base)
            n=norm(base); key=aliases.get(n)
            if (by_key.get(key,0) if key else calc_by_norm.get(n,0))>0:
                task=base.strip()
        days=max(1,int(round(bill/8))) if bill>0 else 0
        task_start=current if (bill>0 or r in phase_headers) else None
        task_end=business_add(task_start,max(0,days-1)) if task_start else None
        if bill>0 and r not in phase_headers: current=business_add(task_end,1)
        st=ScheduleTask(revision_id=rev.id,task_id=str(row.get("task_id") or ""),phase=phase,task=task,
            task_owner=str(row.get("task_owner") or ""),description=str(row.get("description") or ""),purpose=str(row.get("purpose") or ""),
            status="Planned",percent_complete=0,non_bill_hours=float(row.get("nonbill_cached") or 0) if isinstance(row.get("nonbill_cached"),(int,float)) else 0,
            billable_hours_budgeted=float(bill or 0),change_order_hours=0,hours_used=0,start_date=task_start,end_date=task_end,sort_order=order)
        db.add(st)
    rev.schedule_needs_refresh=False
    db.flush()
    return db.query(ScheduleTask).filter(ScheduleTask.revision_id==rev.id).order_by(ScheduleTask.sort_order).all()


def schedule_metrics(tasks):
    """Reproduce the Schedule workbook's derived budget metrics without storing calculated values."""
    metrics={}
    def leaf(t):
        budget=float(t.billable_hours_budgeted or 0)+float(t.change_order_hours or 0)
        used=float(t.hours_used or 0)
        pct=max(0,min(100,int(t.percent_complete or 0)))/100.0
        remaining=budget-used
        if remaining < 0:
            trend="Over Budget"
        elif budget <= 0:
            trend="On Track"
        else:
            ratio=used/budget
            if ratio > pct + 1e-9: trend="Trending Over"
            elif ratio < pct - 1e-9: trend="Trending Under"
            else: trend="On Track"
        if pct>0 and used==0: eac=budget-(pct*budget)
        elif pct==0 and used>0: eac=used
        elif pct>0 and used>0: eac=used/pct
        else: eac=budget
        return {"percent":pct,"non_bill":float(t.non_bill_hours or 0),"budget":float(t.billable_hours_budgeted or 0),"co":float(t.change_order_hours or 0),"used":used,"remaining":remaining,"trend":trend,"eac":eac,"start":t.start_date,"end":t.end_date,"phase":False}
    for t in tasks:
        if t.task != t.phase: metrics[t.id]=leaf(t)
    for t in tasks:
        if t.task != t.phase: continue
        children=[x for x in tasks if x.phase==t.phase and x.task != x.phase]
        cm=[metrics[x.id] for x in children]
        j=sum(x["budget"] for x in cm); k=sum(x["co"] for x in cm); l=sum(x["used"] for x in cm); i=sum(x["non_bill"] for x in cm)
        denom=j+k
        pct=(sum((x["budget"]+x["co"])*x["percent"] for x in cm)/denom) if denom else 0
        remaining=((j+k)-l) if t.phase=="Plan" else ((i+j+k)-l)
        if remaining < 0: trend="Over Budget"
        elif denom<=0: trend="On Track"
        else:
            ratio=l/denom
            if ratio > pct + 1e-9: trend="Trending Over"
            elif ratio < pct - 1e-9: trend="Trending Under"
            else: trend="On Track"
        starts=[x["start"] for x in cm if x["start"]]; ends=[x["end"] for x in cm if x["end"]]
        metrics[t.id]={"percent":pct,"non_bill":i,"budget":j,"co":k,"used":l,"remaining":remaining,"trend":trend,"eac":sum(x["eac"] for x in cm),"start":min(starts) if starts else t.start_date,"end":max(ends) if ends else t.end_date,"phase":True}
    return metrics
