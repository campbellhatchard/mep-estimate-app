from __future__ import annotations
import io, os, csv, copy, json, re
from datetime import date, datetime
from pathlib import Path
from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from .database import Base, engine, get_db, SessionLocal
from .models import *
from .auth import authenticate, current_user, require_role, normalize_username, hash_password
from .seed import seed_database, slug
from .services.audit import record
from .services.calculation import recalculate_and_store, calculation, Config, ENGINE_VERSION
from .services.schedule import generate_schedule, schedule_metrics

BASE=Path(__file__).parent
app=FastAPI(title="MEP Estimate", version="1.0.0")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET","dev-secret-change-me"), same_site="lax", https_only=os.getenv("ENVIRONMENT", "development").lower()=="production")
app.mount("/static",StaticFiles(directory=BASE/"static"),name="static")
templates=Jinja2Templates(directory=BASE/"templates")

@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
    db=SessionLocal()
    try: seed_database(db)
    finally: db.close()

# ----- helpers -----
def user_or_login(request,db):
    try: return current_user(request,db)
    except HTTPException: return None

def active_config(db):
    v=db.query(ConfigurationVersion).filter(ConfigurationVersion.status=="ACTIVE").order_by(desc(ConfigurationVersion.activated_at),desc(ConfigurationVersion.id)).first()
    if not v: raise HTTPException(500,"No active configuration")
    return v

def revision_or_404(db,rid):
    r=db.get(EstimateRevision,rid)
    if not r: raise HTTPException(404,"Estimate revision not found")
    return r

def estimate_ctx(db,rev):
    cfg=Config(db,rev.config_version_id)
    cats=cfg.by_cat
    def labels(cat): return [x.label for x in cats.get(cat,[]) if x.active]
    return {
      "cfg":cfg,"solutions":labels("Solution Type"),"erps":labels("ERP"),"customer_types":labels("Customer Type"),
      "currencies":labels("Currency"),"entities":labels("Entity"),"user_counts":labels("User Count"),"go_live":labels("Go Live"),
      "test_efforts":[x.value_number for x in cats.get("Test Effort",[]) if x.active],"security":labels("Security Method"),
      "epp_install":labels("EPP Install"),"epp_integration":labels("EPP Integration"),"delivery":labels("Delivery Method"),
      "app_types":labels("Application Effort"),"custom_effort":labels("Custom Effort"),"package_types":labels("Package Effort"),
      "upgrade_types":labels("Upgrade Type")
    }

def sync_catalog(db,rev,erp,force=False):
    parent=slug(erp)
    existing=db.query(EstimateApplication).filter(EstimateApplication.revision_id==rev.id).all()
    if existing and not force: return
    if force:
        db.query(EstimateApplication).filter(EstimateApplication.revision_id==rev.id).delete(synchronize_session=False)
    apps=db.query(ConfigItem).filter(ConfigItem.config_version_id==rev.config_version_id,ConfigItem.category=="ERP Application",ConfigItem.parent_key==parent,ConfigItem.active.is_(True)).order_by(ConfigItem.sort_order).all()
    pkgs=db.query(ConfigItem).filter(ConfigItem.config_version_id==rev.config_version_id,ConfigItem.category=="ERP Package",ConfigItem.parent_key==parent,ConfigItem.active.is_(True)).order_by(ConfigItem.sort_order).all()
    for i,x in enumerate(apps): db.add(EstimateApplication(revision_id=rev.id,kind="APPLICATION",catalog_key=x.key,label=x.label,config_type="No Config",sort_order=i))
    for i,x in enumerate(pkgs): db.add(EstimateApplication(revision_id=rev.id,kind="PACKAGE",catalog_key=x.key,label=x.label,config_type="No Config",sort_order=i))
    db.flush()


def append_catalog_entries(db, rev):
    """Append catalog entries introduced in the revision's pinned configuration without deleting historical selections."""
    parent=slug(rev.erp)
    existing={(a.kind,a.label.casefold()) for a in db.query(EstimateApplication).filter(EstimateApplication.revision_id==rev.id).all()}
    specs=[("APPLICATION","ERP Application"),("PACKAGE","ERP Package")]
    for kind,category in specs:
        rows=db.query(ConfigItem).filter(ConfigItem.config_version_id==rev.config_version_id,ConfigItem.category==category,ConfigItem.parent_key==parent,ConfigItem.active.is_(True)).order_by(ConfigItem.sort_order).all()
        base=max([a.sort_order for a in db.query(EstimateApplication).filter(EstimateApplication.revision_id==rev.id,EstimateApplication.kind==kind).all()] or [-1])+1
        for i,x in enumerate(rows):
            if (kind,x.label.casefold()) not in existing:
                db.add(EstimateApplication(revision_id=rev.id,kind=kind,catalog_key=x.key,label=x.label,config_type="No Config",sort_order=base+i))
                existing.add((kind,x.label.casefold()))
    db.flush()

def recalc(db,rev):
    lines,summary,details,summ=recalculate_and_store(db,rev)
    db.commit()
    return lines,summary,details,summ


def validate_estimate_business_rules(db, rev):
    """Enforce the workbook's visible validation rules before committing a Draft estimate."""
    cfg=Config(db,rev.config_version_id)
    solution=cfg.json_by_label("Solution Type",rev.project_type)
    errors=[]
    if rev.high_availability and not bool(solution.get("ha_valid",False)):
        errors.append(f"MEP High Availability is not valid for {rev.project_type}.")
    if rev.gateway and not bool(solution.get("gateway_valid",False)):
        errors.append(f"MEP Gateway is not valid for {rev.project_type}.")
    if rev.epp_integration != "None" and not rev.project_type.startswith("EPP"):
        errors.append("EPP Integration is valid only for an EPP project type.")
    if rev.epp_install != "No" and rev.label_sites < 1:
        errors.append("At least one label-printing site is required when EPP is installed.")
    if rev.epp_install == "No" and rev.label_sites > 0:
        errors.append("Label-printing site count must be zero when EPP is not installed.")
    if not rev.labels_required and rev.label_count > 0:
        errors.append("Label Count is greater than zero while Labels Required is No.")
    if (not rev.iot_required and rev.iot_count > 0) or (rev.iot_required and rev.iot_count == 0):
        errors.append("Conveyor / scale interface selection and Service Definition Count are inconsistent.")
    if rev.iot_count > 10:
        errors.append("Conveyor / scale Service Definition Count must be between 1 and 10.")
    if not rev.erp_integration_required and rev.erp_integration_count > 0:
        errors.append("ERP Integration Count is greater than zero while ERP Integration Required is No.")
    if (not rev.data_rep_required and rev.data_rep_count > 0) or (rev.data_rep_required and rev.data_rep_count == 0):
        errors.append("Data Replication selection and Data Replication Session Count are inconsistent.")
    if rev.data_rep_count > 20:
        errors.append("Data Replication Session Count must be between 1 and 20.")
    selected_standard=sum(1 for a in rev.applications if a.config_type != "No Config")
    selected_custom=sum(1 for a in rev.custom_apps if a.description and a.complexity != "No Config")
    if (selected_standard+selected_custom)>0 and rev.go_live_type=="None":
        errors.append("A Go Live Type is required when applications or packages are included.")
    if rev.go_live_type != "None" and rev.go_live_sites < 1:
        errors.append("Number of Go Live Sites must be at least 1 when a Go Live Type is selected.")
    for c in rev.custom_apps:
        if not c.description.strip() and c.complexity != "No Config":
            errors.append(f"Custom Application {c.sort_order+1} has effort selected but no description.")
    if errors:
        raise HTTPException(400," ".join(errors))

def bool_form(form,key): return str(form.get(key,"")).lower() in ("1","true","yes","on")

def update_field(db,rev,user,field,value,reason=None):
    old=getattr(rev,field)
    if old!=value:
        setattr(rev,field,value); rev.row_version+=1
        record(db,event_type="ESTIMATE_FIELD_CHANGED",user_id=user.id,estimate_id=rev.estimate_id,revision_id=rev.id,field_name=field,old_value=old,new_value=value,reason=reason)

# ----- auth -----
@app.get("/login",response_class=HTMLResponse)
def login_page(request:Request,db:Session=Depends(get_db)):
    if user_or_login(request,db): return RedirectResponse("/estimates",303)
    return templates.TemplateResponse("login.html",{"request":request,"error":None})

@app.post("/login",response_class=HTMLResponse)
def login(request:Request,username:str=Form(...),password:str=Form(...),db:Session=Depends(get_db)):
    user=authenticate(db,username,password)
    if not user: return templates.TemplateResponse("login.html",{"request":request,"error":"Invalid username or password"},status_code=400)
    request.session["user_id"]=user.id
    return RedirectResponse("/estimates",303)

@app.post("/logout")
def logout(request:Request):
    request.session.clear(); return RedirectResponse("/login",303)

@app.get("/")
def home(request:Request,db:Session=Depends(get_db)):
    return RedirectResponse("/estimates" if user_or_login(request,db) else "/login",303)

# ----- estimate repository -----
@app.get("/estimates",response_class=HTMLResponse)
def estimates(request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db)
    ests=db.query(Estimate).filter(Estimate.deleted.is_(False)).order_by(desc(Estimate.id)).all()
    rows=[]
    for e in ests:
        rev=max(e.revisions,key=lambda r:r.revision_no) if e.revisions else None
        if rev: rows.append((e,rev))
    return templates.TemplateResponse("estimates.html",{"request":request,"user":user,"rows":rows})

@app.post("/estimates/new")
def create_estimate(request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db); require_role(user,"ADMIN","ESTIMATOR","REVIEWER","APPROVER")
    y=date.today().year
    seq=db.query(Estimate).filter(Estimate.estimate_number.like(f"{y}%")).count()+1
    number=f"{y}{seq:03d}"
    e=Estimate(estimate_number=number,created_by=user.id); db.add(e); db.flush()
    cv=active_config(db)
    entity=db.query(ConfigItem).filter(ConfigItem.config_version_id==cv.id,ConfigItem.category=="Entity",ConfigItem.active.is_(True)).order_by(ConfigItem.sort_order).first()
    r=EstimateRevision(estimate_id=e.id,revision_no=1,status="DRAFT",config_version_id=cv.id,engine_version=ENGINE_VERSION,
        proposal_date=date.today(),project_start=date.today(),entity=entity.label if entity else "",created_by=user.id)
    db.add(r); db.flush()
    sync_catalog(db,r,r.erp,force=True)
    for i in range(20): db.add(EstimateCustomApplication(revision_id=r.id,description="",complexity="No Config",sort_order=i))
    record(db,event_type="ESTIMATE_CREATED",user_id=user.id,estimate_id=e.id,revision_id=r.id,config_version_id=cv.id,new_value=number)
    recalculate_and_store(db,r); db.commit()
    return RedirectResponse(f"/estimate/{r.id}",303)

@app.post("/estimate/{rid}/new-revision")
def new_revision(rid:int,request:Request,rebase:bool=False,db:Session=Depends(get_db)):
    user=current_user(request,db); require_role(user,"ADMIN","ESTIMATOR","REVIEWER","APPROVER")
    src=revision_or_404(db,rid)
    maxrev=db.query(EstimateRevision).filter(EstimateRevision.estimate_id==src.estimate_id).order_by(desc(EstimateRevision.revision_no)).first().revision_no
    cv=active_config(db) if rebase else db.get(ConfigurationVersion,src.config_version_id)
    data={c.name:getattr(src,c.name) for c in EstimateRevision.__table__.columns if c.name not in {"id","revision_no","status","config_version_id","created_at","updated_at","row_version","calculated_hours","calculated_fees","low_hours","high_hours","duration_months"}}
    data.update(revision_no=maxrev+1,status="DRAFT",config_version_id=cv.id,engine_version=ENGINE_VERSION,created_by=user.id,row_version=1,schedule_needs_refresh=True)
    r=EstimateRevision(**data); db.add(r); db.flush()
    for a in db.query(EstimateApplication).filter(EstimateApplication.revision_id==src.id):
        db.add(EstimateApplication(revision_id=r.id,kind=a.kind,catalog_key=a.catalog_key,label=a.label,config_type=a.config_type,sort_order=a.sort_order))
    for a in db.query(EstimateCustomApplication).filter(EstimateCustomApplication.revision_id==src.id):
        db.add(EstimateCustomApplication(revision_id=r.id,description=a.description,complexity=a.complexity,sort_order=a.sort_order))
    if rebase:
        append_catalog_entries(db,r)
    record(db,event_type="REVISION_CREATED",user_id=user.id,estimate_id=r.estimate_id,revision_id=r.id,config_version_id=cv.id,old_value=f"Rev {src.revision_no}",new_value=f"Rev {r.revision_no}",reason="Rebased to current configuration" if rebase else "New estimate revision")
    recalculate_and_store(db,r); db.commit()
    return RedirectResponse(f"/estimate/{r.id}",303)

# ----- estimate page -----
@app.get("/estimate/{rid}",response_class=HTMLResponse)
def estimate_page(rid:int,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db); rev=revision_or_404(db,rid)
    sync_catalog(db,rev,rev.erp); db.commit()
    recalc_lines,summary,details,summ=calculation(db,rev)
    ctx=estimate_ctx(db,rev); ctx.update({"request":request,"user":user,"rev":rev,"estimate":rev.estimate,"summary":summary,
      "apps":[a for a in rev.applications if a.kind=="APPLICATION"],"packages":[a for a in rev.applications if a.kind=="PACKAGE"],"customs":rev.custom_apps,"readonly":rev.status in ("APPROVED","FINAL","SUPERSEDED")})
    return templates.TemplateResponse("estimate.html",ctx)

@app.post("/estimate/{rid}")
async def save_estimate(rid:int,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db); rev=revision_or_404(db,rid); require_role(user,"ADMIN","ESTIMATOR","REVIEWER","APPROVER")
    if rev.status in ("APPROVED","FINAL","SUPERSEDED"): raise HTTPException(409,"Approved/final revisions are locked")
    form=await request.form(); old_erp=rev.erp
    text_fields=["customer","customer_type","opportunity_number","currency","entity","upgrade_type","project_type","erp","epp_install","epp_integration","user_count","go_live_type","security_method","delivery_method"]
    int_fields=["upgrade_app_count","label_sites","label_count","iot_count","erp_integration_count","data_rep_count","test_cycles","go_live_sites","uat_sites"]
    float_fields=["billing_rate","base_test_pct"]
    bool_fields=["android_change","high_availability","gateway","labels_required","iot_required","erp_integration_required","data_rep_required","consultant_access_setup","onboarding","pacejet","write_test_scripts","end_user_documentation","end_user_training","app_dev_training"]
    for f in text_fields: update_field(db,rev,user,f,str(form.get(f,"")))
    for f in int_fields:
        try:v=int(float(form.get(f,0) or 0))
        except:v=0
        update_field(db,rev,user,f,v)
    for f in float_fields:
        try:v=float(form.get(f,0) or 0)
        except:v=0
        update_field(db,rev,user,f,v)
    for f in bool_fields: update_field(db,rev,user,f,bool_form(form,f))
    if form.get("proposal_date"):
        update_field(db,rev,user,"proposal_date",date.fromisoformat(form["proposal_date"]))
    if old_erp!=rev.erp: sync_catalog(db,rev,rev.erp,force=True)
    for a in db.query(EstimateApplication).filter(EstimateApplication.revision_id==rev.id):
        val=form.get(f"app_{a.id}")
        if val is not None and val!=a.config_type:
            record(db,event_type="ESTIMATE_FIELD_CHANGED",user_id=user.id,estimate_id=rev.estimate_id,revision_id=rev.id,field_name=f"{a.kind}:{a.label}",old_value=a.config_type,new_value=val); a.config_type=str(val)
    for c in db.query(EstimateCustomApplication).filter(EstimateCustomApplication.revision_id==rev.id):
        nd=str(form.get(f"custom_desc_{c.id}",c.description)); nc=str(form.get(f"custom_complexity_{c.id}",c.complexity))
        if nd!=c.description or nc!=c.complexity:
            record(db,event_type="ESTIMATE_FIELD_CHANGED",user_id=user.id,estimate_id=rev.estimate_id,revision_id=rev.id,field_name=f"Custom Application {c.sort_order+1}",old_value=f"{c.description}|{c.complexity}",new_value=f"{nd}|{nc}")
            c.description=nd; c.complexity=nc
    validate_estimate_business_rules(db,rev)
    rev.schedule_needs_refresh=True
    recalculate_and_store(db,rev); db.commit()
    return RedirectResponse(f"/estimate/{rid}",303)

# ----- detail -----
@app.get("/estimate/{rid}/detail",response_class=HTMLResponse)
def detail_page(rid:int,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db); rev=revision_or_404(db,rid); _,summary,details,summ=calculation(db,rev)
    sections=[]
    for name in ["Upgrade Definition","Baseline Applications","Baseline Packages","Custom Applications","Labels","IoT Service Definitions","ERP Service Definitions","Data Replication Sessions"]:
        sections.append((name,[x for x in details if x.section==name],summ.get(name,{})))
    default_factor=Config(db,rev.config_version_id).param("UNIT_TEST_FACTOR")
    return templates.TemplateResponse("detail.html",{"request":request,"user":user,"rev":rev,"estimate":rev.estimate,"sections":sections,"summary":summary,"default_factor":default_factor,"readonly":rev.status in ("APPROVED","FINAL","SUPERSEDED")})

@app.post("/estimate/{rid}/detail")
async def save_detail(rid:int,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db); rev=revision_or_404(db,rid); require_role(user,"ADMIN","ESTIMATOR","REVIEWER","APPROVER")
    if rev.status in ("APPROVED","FINAL","SUPERSEDED"): raise HTTPException(409,"Revision is locked")
    form=await request.form()
    factor_raw=str(form.get("unit_test_factor_override","")).strip()
    old=rev.unit_test_factor_override
    rev.unit_test_factor_override=float(factor_raw) if factor_raw else None
    rev.unit_test_override_reason=str(form.get("unit_test_override_reason","")).strip() or None
    if rev.unit_test_factor_override is not None and not rev.unit_test_override_reason:
        raise HTTPException(400,"A reason is required when overriding the Unit Testing Factor")
    if old!=rev.unit_test_factor_override:
        record(db,event_type="UNIT_TEST_FACTOR_OVERRIDDEN",user_id=user.id,estimate_id=rev.estimate_id,revision_id=rev.id,field_name="unit_test_factor",old_value=old,new_value=rev.unit_test_factor_override,reason=rev.unit_test_override_reason)
    count=int(form.get("line_count",0) or 0)
    existing={a.line_key:a for a in db.query(DetailAdjustment).filter(DetailAdjustment.revision_id==rev.id).all()}
    for i in range(count):
        key=str(form.get(f"line_key_{i}",""));
        if not key: continue
        desc=str(form.get(f"description_{i}","")); notes=str(form.get(f"notes_{i}",""))
        try: mod=float(form.get(f"mod_{i}",0) or 0)
        except: mod=0
        if mod!=0 and not notes.strip(): raise HTTPException(400,f"Adjustment notes are required for {desc or key}")
        a=existing.get(key)
        if not a and (mod!=0 or notes or desc): a=DetailAdjustment(revision_id=rev.id,line_key=key); db.add(a); existing[key]=a
        if a and (a.mod_hours!=mod or a.notes!=notes or a.description!=desc):
            record(db,event_type="DETAIL_ADJUSTED",user_id=user.id,estimate_id=rev.estimate_id,revision_id=rev.id,field_name=key,old_value=f"{a.mod_hours}|{a.notes}|{a.description}",new_value=f"{mod}|{notes}|{desc}",reason=notes or None)
            a.mod_hours=mod; a.notes=notes; a.description=desc
    rev.schedule_needs_refresh=True
    recalculate_and_store(db,rev); db.commit()
    return RedirectResponse(f"/estimate/{rid}/detail",303)

# ----- calculations -----
@app.get("/estimate/{rid}/calculations",response_class=HTMLResponse)
def calc_page(rid:int,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db); rev=revision_or_404(db,rid); lines,summary,_,_=calculation(db,rev)
    phases=[]
    for p in ["Plan","Design","Build","Test","Go Live"]: phases.append((p,[x for x in lines if x.phase==p],summary["phase_totals"][p]))
    return templates.TemplateResponse("calculations.html",{"request":request,"user":user,"rev":rev,"estimate":rev.estimate,"phases":phases,"summary":summary,"readonly":rev.status in ("APPROVED","FINAL","SUPERSEDED")})

@app.post("/estimate/{rid}/calculations")
async def save_calculations(rid:int,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db); rev=revision_or_404(db,rid); require_role(user,"ADMIN","ESTIMATOR","REVIEWER","APPROVER")
    if rev.status in ("APPROVED","FINAL","SUPERSEDED"): raise HTTPException(409,"Revision is locked")
    form=await request.form(); count=int(form.get("line_count",0) or 0)
    existing={a.line_key:a for a in db.query(CalculationAdjustment).filter(CalculationAdjustment.revision_id==rev.id).all()}
    for i in range(count):
        key=str(form.get(f"line_key_{i}","")); notes=str(form.get(f"notes_{i}",""))
        try: val=float(form.get(f"adjust_{i}",0) or 0)
        except: val=0
        if val!=0 and not notes.strip(): raise HTTPException(400,f"Adjustment notes are required for {key}")
        a=existing.get(key)
        if not a and (val!=0 or notes): a=CalculationAdjustment(revision_id=rev.id,line_key=key); db.add(a); existing[key]=a
        if a and (a.adjust_hours!=val or a.notes!=notes):
            record(db,event_type="CALCULATION_ADJUSTED",user_id=user.id,estimate_id=rev.estimate_id,revision_id=rev.id,field_name=key,old_value=f"{a.adjust_hours}|{a.notes}",new_value=f"{val}|{notes}",reason=notes or None)
            a.adjust_hours=val; a.notes=notes
    rev.schedule_needs_refresh=True
    recalculate_and_store(db,rev); db.commit()
    return RedirectResponse(f"/estimate/{rid}/calculations",303)

# ----- schedule -----
@app.get("/estimate/{rid}/schedule",response_class=HTMLResponse)
def schedule_page(rid:int,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db); rev=revision_or_404(db,rid)
    tasks=db.query(ScheduleTask).filter(ScheduleTask.revision_id==rev.id).order_by(ScheduleTask.sort_order).all()
    if not tasks: tasks=generate_schedule(db,rev,replace=True); db.commit()
    statuses=[x.label for x in Config(db,rev.config_version_id).by_cat.get("Schedule Status",[]) if x.active]
    # Gantt range is intentionally bounded to the generated task span.
    dated=[t for t in tasks if t.start_date and t.end_date]
    min_d=min((t.start_date for t in dated),default=rev.project_start or date.today()); max_d=max((t.end_date for t in dated),default=min_d+__import__('datetime').timedelta(days=30))
    days=[]; d=min_d
    while d<=max_d and len(days)<120: days.append(d); d+=__import__('datetime').timedelta(days=1)
    return templates.TemplateResponse("schedule.html",{"request":request,"user":user,"rev":rev,"estimate":rev.estimate,"tasks":tasks,"metrics":schedule_metrics(tasks),"statuses":statuses,"days":days,"readonly":rev.status in ("APPROVED","FINAL","SUPERSEDED")})

@app.post("/estimate/{rid}/schedule")
async def save_schedule(rid:int,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db); rev=revision_or_404(db,rid); require_role(user,"ADMIN","ESTIMATOR","REVIEWER","APPROVER")
    if rev.status in ("APPROVED","FINAL","SUPERSEDED"): raise HTTPException(409,"Revision is locked")
    form=await request.form()
    if form.get("action")=="regenerate":
        generate_schedule(db,rev,replace=True); record(db,event_type="SCHEDULE_REGENERATED",user_id=user.id,estimate_id=rev.estimate_id,revision_id=rev.id); db.commit(); return RedirectResponse(f"/estimate/{rid}/schedule",303)
    tasks=db.query(ScheduleTask).filter(ScheduleTask.revision_id==rev.id).all()
    for t in tasks:
        if t.task == t.phase:
            continue  # Phase summary rows are calculated from child tasks, matching the workbook.
        changes={}
        vals={"resource_assigned":str(form.get(f"resource_{t.id}",t.resource_assigned)),"status":str(form.get(f"status_{t.id}",t.status)),"comments":str(form.get(f"comments_{t.id}",t.comments))}
        for f,v in vals.items():
            if getattr(t,f)!=v: changes[f]=(getattr(t,f),v); setattr(t,f,v)
        for f,prefix,cast in [("percent_complete","pct",int),("change_order_hours","co",float),("hours_used","used",float)]:
            try:v=cast(form.get(f"{prefix}_{t.id}",getattr(t,f)) or 0)
            except:v=getattr(t,f)
            if getattr(t,f)!=v: changes[f]=(getattr(t,f),v); setattr(t,f,v)
        for f,prefix in [("start_date","start"),("end_date","end")]:
            raw=str(form.get(f"{prefix}_{t.id}","")); v=date.fromisoformat(raw) if raw else None
            if getattr(t,f)!=v: changes[f]=(getattr(t,f),v); setattr(t,f,v)
        for f,(ov,nv) in changes.items(): record(db,event_type="SCHEDULE_FIELD_CHANGED",user_id=user.id,estimate_id=rev.estimate_id,revision_id=rev.id,field_name=f"{t.task_id}:{f}",old_value=ov,new_value=nv)
    db.commit(); return RedirectResponse(f"/estimate/{rid}/schedule",303)

# ----- lifecycle -----
@app.post("/estimate/{rid}/status/{action}")
def status_action(rid:int,action:str,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db); rev=revision_or_404(db,rid)
    action=action.lower(); old=rev.status
    if action=="submit": require_role(user,"ADMIN","ESTIMATOR","REVIEWER","APPROVER"); new="REVIEW"
    elif action=="return": require_role(user,"ADMIN","REVIEWER","APPROVER"); new="DRAFT"
    elif action=="approve": require_role(user,"ADMIN","APPROVER"); new="APPROVED"
    elif action=="supersede": require_role(user,"ADMIN","APPROVER"); new="SUPERSEDED"
    else: raise HTTPException(400,"Unknown action")
    rev.status=new; record(db,event_type=f"ESTIMATE_{new}",user_id=user.id,estimate_id=rev.estimate_id,revision_id=rev.id,old_value=old,new_value=new); db.commit()
    return RedirectResponse(f"/estimate/{rid}",303)

# ----- calculation data -----
@app.get("/data",response_class=HTMLResponse)
def data_page(request:Request,version:int|None=None,q:str="",category:str="",db:Session=Depends(get_db)):
    user=current_user(request,db); versions=db.query(ConfigurationVersion).order_by(desc(ConfigurationVersion.id)).all(); v=db.get(ConfigurationVersion,version) if version else active_config(db)
    query=db.query(ConfigItem).filter(ConfigItem.config_version_id==v.id)
    if q: query=query.filter((ConfigItem.label.ilike(f"%{q}%")) | (ConfigItem.key.ilike(f"%{q}%")) | (ConfigItem.description.ilike(f"%{q}%")))
    if category: query=query.filter(ConfigItem.category==category)
    items=query.order_by(ConfigItem.category,ConfigItem.sort_order,ConfigItem.label).all()
    categories=[x[0] for x in db.query(ConfigItem.category).filter(ConfigItem.config_version_id==v.id).distinct().order_by(ConfigItem.category).all()]
    return templates.TemplateResponse("data.html",{"request":request,"user":user,"versions":versions,"version":v,"items":items,"categories":categories,"q":q,"category":category})

@app.post("/data/version/new")
def new_config_version(request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db); require_role(user,"ADMIN")
    src=active_config(db); stamp=datetime.utcnow().strftime("%Y.%m.%d.%H%M")
    v=ConfigurationVersion(name=f"MEP Estimate Model {stamp}",status="DRAFT",created_by=user.id,change_reason="Draft configuration cloned from active model")
    db.add(v); db.flush()
    for x in db.query(ConfigItem).filter(ConfigItem.config_version_id==src.id):
        db.add(ConfigItem(config_version_id=v.id,category=x.category,key=x.key,label=x.label,value_number=x.value_number,value_text=x.value_text,value_type=x.value_type,unit=x.unit,description=x.description,parent_key=x.parent_key,sort_order=x.sort_order,active=x.active))
    record(db,event_type="CONFIG_VERSION_CREATED",user_id=user.id,config_version_id=v.id,old_value=src.name,new_value=v.name); db.commit()
    return RedirectResponse(f"/data?version={v.id}",303)

@app.post("/data/item/{item_id}")
async def update_config_item(item_id:int,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db); require_role(user,"ADMIN"); item=db.get(ConfigItem,item_id)
    if not item: raise HTTPException(404)
    v=db.get(ConfigurationVersion,item.config_version_id)
    if v.status!="DRAFT": raise HTTPException(409,"Only draft configuration versions can be edited")
    form=await request.form(); old=f"{item.label}|{item.value_number}|{item.value_text}|{item.active}"
    item.label=str(form.get("label",item.label)); item.description=str(form.get("description",item.description or ""))
    raw=str(form.get("value_number","")).strip(); item.value_number=float(raw) if raw else None
    item.value_text=str(form.get("value_text",item.value_text or "")) or None; item.active=bool_form(form,"active")
    reason=str(form.get("reason","")).strip()
    if not reason: raise HTTPException(400,"Change reason is required")
    record(db,event_type="CONFIG_VALUE_CHANGED",user_id=user.id,config_version_id=v.id,field_name=item.key,old_value=old,new_value=f"{item.label}|{item.value_number}|{item.value_text}|{item.active}",reason=reason); db.commit()
    return RedirectResponse(f"/data?version={v.id}&q={item.key}",303)

@app.post("/data/version/{vid}/activate")
def activate_config(vid:int,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db); require_role(user,"ADMIN"); v=db.get(ConfigurationVersion,vid)
    if not v or v.status!="DRAFT": raise HTTPException(409,"Only a draft can be activated")
    for a in db.query(ConfigurationVersion).filter(ConfigurationVersion.status=="ACTIVE"): a.status="RETIRED"
    v.status="ACTIVE"; v.activated_at=datetime.utcnow(); v.approval_status="ACTIVE"
    record(db,event_type="CONFIG_VERSION_ACTIVATED",user_id=user.id,config_version_id=v.id,new_value=v.name,reason=v.change_reason); db.commit()
    return RedirectResponse(f"/data?version={v.id}",303)

@app.post("/data/item/new")
async def new_config_item(request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db); require_role(user,"ADMIN"); form=await request.form(); vid=int(form.get("version_id")); v=db.get(ConfigurationVersion,vid)
    if not v or v.status!="DRAFT": raise HTTPException(409,"Add items to a draft configuration")
    category=str(form.get("category","")).strip(); label=str(form.get("label","")).strip(); key=str(form.get("key","")).strip() or slug(label)
    if not category or not label: raise HTTPException(400,"Category and label are required")
    raw=str(form.get("value_number","")).strip(); num=float(raw) if raw else None
    item=ConfigItem(config_version_id=vid,category=category,key=key,label=label,value_number=num,value_text=str(form.get("value_text","")).strip() or None,value_type=str(form.get("value_type","text")),parent_key=str(form.get("parent_key","")).strip() or None,active=True,sort_order=999)
    db.add(item); record(db,event_type="CONFIG_ITEM_ADDED",user_id=user.id,config_version_id=vid,field_name=key,new_value=label,reason=str(form.get("reason","New configuration item"))); db.commit()
    return RedirectResponse(f"/data?version={vid}&q={key}",303)

# ----- audit -----
@app.get("/estimate/{rid}/audit",response_class=HTMLResponse)
def audit_page(rid:int,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db); rev=revision_or_404(db,rid); events=db.query(AuditEvent).filter((AuditEvent.estimate_id==rev.estimate_id)|(AuditEvent.revision_id==rev.id)).order_by(desc(AuditEvent.created_at)).all(); users={u.id:u.username for u in db.query(User).all()}
    return templates.TemplateResponse("audit.html",{"request":request,"user":user,"rev":rev,"estimate":rev.estimate,"events":events,"users":users})

# ----- users -----
@app.get("/admin/users",response_class=HTMLResponse)
def users_page(request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db); require_role(user,"ADMIN"); return templates.TemplateResponse("users.html",{"request":request,"user":user,"users":db.query(User).order_by(User.username).all()})

@app.post("/admin/users/new")
def users_new(request:Request,username:str=Form(...),password:str=Form(...),role:str=Form(...),db:Session=Depends(get_db)):
    user=current_user(request,db); require_role(user,"ADMIN"); norm=normalize_username(username)
    if db.query(User).filter(User.username_normalized==norm).first(): raise HTTPException(409,"Username already exists ignoring case")
    u=User(username=username.strip(),username_normalized=norm,password_hash=hash_password(password),role=role); db.add(u); db.commit(); return RedirectResponse("/admin/users",303)

# ----- exports -----
@app.get("/estimate/{rid}/pdf")
def export_pdf(rid:int,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db); rev=revision_or_404(db,rid); lines,summary,details,summ=calculation(db,rev)
    buf=io.BytesIO(); doc=SimpleDocTemplate(buf,pagesize=letter,rightMargin=36,leftMargin=36,topMargin=36,bottomMargin=36); styles=getSampleStyleSheet(); story=[]
    story += [Paragraph("Cloud Inventory — MEP Services Estimate",styles["Title"]),Spacer(1,12)]
    meta=[["Customer",rev.customer],["Estimate",f"{rev.estimate.estimate_number} Rev {rev.revision_no}"],["Opportunity",rev.opportunity_number],["Proposal Date",str(rev.proposal_date or "")],["Project Type",rev.project_type],["ERP",rev.erp],["Configuration",db.get(ConfigurationVersion,rev.config_version_id).name]]
    t=Table(meta,colWidths=[120,360]); t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.25,colors.grey),('BACKGROUND',(0,0),(0,-1),colors.HexColor('#d9edf7')),('VALIGN',(0,0),(-1,-1),'TOP')])); story += [t,Spacer(1,14)]
    story.append(Paragraph("Estimate Summary",styles["Heading2"])); data=[["Solution","Hours","Fees","Duration"],["Estimate",f"{summary['hours']:.0f}",f"{summary['fees']:,.2f}",f"{summary['duration_months']:.2f} Months"],["Range Low",f"{summary['low_hours']:.0f}",f"{summary['low_fees']:,.2f}",""],["Range High",f"{summary['high_hours']:.0f}",f"{summary['high_fees']:,.2f}",""]]
    t=Table(data,colWidths=[180,80,120,120]); t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.25,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#0089a8')),('TEXTCOLOR',(0,0),(-1,0),colors.white)])); story += [t,Spacer(1,14)]
    story.append(Paragraph("Phase Summary",styles["Heading2"])); pdata=[["Phase","Hours"]]+[[p,f"{v['extended']:.0f}"] for p,v in summary['phase_totals'].items()]; pt=Table(pdata,colWidths=[300,100]); pt.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.25,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#0089a8')),('TEXTCOLOR',(0,0),(-1,0),colors.white)])); story += [pt,Spacer(1,14)]
    selected=[a for a in rev.applications if a.config_type!="No Config"]
    if selected:
        story.append(Paragraph("Selected Applications / Packages",styles["Heading2"])); ad=[["Type","Definition","Configuration"]]+[[a.kind.title(),a.label,a.config_type] for a in selected]; at=Table(ad,colWidths=[80,300,100]); at.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.25,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#d9edf7'))])); story += [at,Spacer(1,12)]
    story.append(Paragraph("Assumptions",styles["Heading2"])); story.append(Paragraph(f"This estimate uses configuration {db.get(ConfigurationVersion,rev.config_version_id).name} and calculation engine {rev.engine_version}. Manual adjustments are retained in the application audit history.",styles["BodyText"]))
    doc.build(story); buf.seek(0); record(db,event_type="PDF_GENERATED",user_id=user.id,estimate_id=rev.estimate_id,revision_id=rev.id); db.commit()
    return StreamingResponse(buf,media_type="application/pdf",headers={"Content-Disposition":f'attachment; filename="Estimate-{rev.estimate.estimate_number}-Rev-{rev.revision_no}.pdf"'})

@app.get("/estimate/{rid}/jira.csv")
def export_jira(rid:int,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db); rev=revision_or_404(db,rid); tasks=db.query(ScheduleTask).filter(ScheduleTask.revision_id==rev.id).order_by(ScheduleTask.sort_order).all()
    if not tasks: tasks=generate_schedule(db,rev,replace=True); db.commit()
    out=io.StringIO(); w=csv.writer(out)
    jira_headers=[
      "Issue Type","Issue Type ID","Summary","Description","Reporter","Original estimate (in hours)","Remaining Estimate",
      "Outward issue link (Blocks) Issue Summary","Outward issue link (Blocks) Issue Type ID",
      "Outward issue link (Blocks) Issue Summary 31","Outward issue link (Blocks) Issue Type ID 31",
      "Outward issue link (Blocks) Issue Summary 32","Outward issue link (Blocks) Issue Type ID 32",
      "Outward issue link (Blocks) Issue Summary 33","Outward issue link (Blocks) Issue Type ID 33",
      "Outward issue link (Blocks) Issue Summary 34","Outward issue link (Blocks) Issue Type ID 34",
      "Outward issue link (Blocks) Issue Summary 35","Outward issue link (Blocks) Issue Type ID 35",
      "Outward issue link (Discovery - Connected) Issue Summary","Outward issue link (Discovery - Connected) Issue Type ID",
      "Outward issue link (Relates) Issue Type Summary","Outward issue link (Relates) Issue Type ID",
      "Outward issue link (Relates) Issue Type Summary 57","Outward issue link (Relates) Issue Type ID 57","Parent","Epic Name"]
    w.writerow(jira_headers)
    epic_ids={}; issue_id=1
    for phase in ["Plan","Design","Build","Test","Go Live"]:
        row=[""]*27; row[0]="Epic"; row[1]=issue_id; row[2]=phase; w.writerow(row); epic_ids[phase]=issue_id; issue_id+=1
        for t in [x for x in tasks if x.phase==phase and x.task not in (phase,"Not Included") and x.billable_hours_budgeted>0]:
            remaining=max(0,t.billable_hours_budgeted+t.change_order_hours-t.hours_used)
            row=[""]*27; row[0]="Story"; row[1]=issue_id; row[2]=t.task; row[3]=t.description or t.purpose; row[5]=t.billable_hours_budgeted; row[6]=remaining; row[25]=epic_ids[phase]; row[26]=phase
            w.writerow(row); issue_id+=1
    record(db,event_type="JIRA_CSV_EXPORTED",user_id=user.id,estimate_id=rev.estimate_id,revision_id=rev.id); db.commit(); data=out.getvalue().encode()
    return StreamingResponse(io.BytesIO(data),media_type="text/csv",headers={"Content-Disposition":f'attachment; filename="Estimate-{rev.estimate.estimate_number}-Jira.csv"'})

@app.get("/health")
def health(): return {"status":"ok","engine_version":ENGINE_VERSION}
