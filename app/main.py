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
app=FastAPI(title="Services Estimator", version="1.0.0")
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

def ensure_editable(r):
    if r.status in ("APPROVED","FINAL","SUPERSEDED") or r.locked_at:
        raise HTTPException(409,"Approved/final/superseded revisions are locked")

def mark_changed(r,db):
    r.recalculation_status="STALE"; r.schedule_stale=True; r.updated_at=datetime.utcnow(); db.flush()

def validate_input(r):
    errors=[]
    if not r.customer_name.strip(): errors.append("Customer is required")
    if not r.customer_type: errors.append("Customer Type is required")
    if r.billing_rate<=0: errors.append("Billing Rate must be greater than zero")
    if not r.currency: errors.append("Currency is required")
    if not r.erp: errors.append("ERP is required")
    if r.erp=="Stand Alone": errors.append("Stand Alone ERP is invalid for an MEP estimate")
    if not r.project_type: errors.append("Project Type is required")
    if not r.solution_type: errors.append("Solution Type is required")
    if r.solution_type=="Upgrade" and not r.upgrade_type: errors.append("Upgrade Type is required for an Upgrade")
    if r.epp_install=="Yes" and r.epp_integration<=0: errors.append("EPP Integration Sites must be greater than zero when EPP is installed")
    if r.gateway_required=="Yes" and r.gateway_sites<=0: errors.append("Gateway Sites must be greater than zero when Gateway is required")
    if r.ha_required=="Yes" and r.ha_instances<=0: errors.append("HA Instances must be greater than zero when HA is required")
    if r.go_live_count<=0: errors.append("Go-Live count must be greater than zero")
    if r.custom_app_count<0: errors.append("Custom Application count cannot be negative")
    if r.custom_app_count>20: errors.append("Custom Application count cannot exceed 20")
    return errors

def sync_catalog(db,r,erp,force=False):
    cfg=Config(db,r.config_version_id)
    current=db.query(EstimateApplication).filter(EstimateApplication.revision_id==r.id).all()
    if force:
        for x in current: db.delete(x)
        db.flush(); current=[]
    if not current:
        for i,label in enumerate(cfg.catalog("ERP Application",slug(erp))):
            db.add(EstimateApplication(revision_id=r.id,app_key=f"APP_{i+1:02d}",label=label,app_type="No Config",sort_order=i))
    if not db.query(EstimatePackage).filter(EstimatePackage.revision_id==r.id).count():
        for i,label in enumerate(cfg.catalog("ERP Package",slug(erp))):
            db.add(EstimatePackage(revision_id=r.id,package_key=f"PKG_{i+1:02d}",label=label,package_type="No Config",sort_order=i))
    db.flush()

def estimate_context(db,r):
    c=calculation(db,r)
    estimate=r.estimate
    apps=db.query(EstimateApplication).filter(EstimateApplication.revision_id==r.id).order_by(EstimateApplication.sort_order).all()
    pkgs=db.query(EstimatePackage).filter(EstimatePackage.revision_id==r.id).order_by(EstimatePackage.sort_order).all()
    customs=db.query(CustomApplication).filter(CustomApplication.revision_id==r.id).order_by(CustomApplication.sort_order).all()
    return estimate,c,apps,pkgs,customs

@app.get("/health")
def health(): return {"ok":True}

@app.get("/login", response_class=HTMLResponse)
def login_page(request:Request,db:Session=Depends(get_db)):
    if user_or_login(request,db): return RedirectResponse("/estimates",303)
    return templates.TemplateResponse("login.html",{"request":request,"user":None,"error":None})

@app.post("/login")
def login(request:Request,username:str=Form(...),password:str=Form(...),db:Session=Depends(get_db)):
    user=authenticate(db,username,password)
    if not user: return templates.TemplateResponse("login.html",{"request":request,"user":None,"error":"Invalid username or password"},status_code=401)
    request.session["user_id"]=user.id; return RedirectResponse("/estimates",303)

@app.post("/logout")
def logout(request:Request): request.session.clear(); return RedirectResponse("/login",303)

@app.get("/")
def root(): return RedirectResponse("/estimates",303)

@app.get("/estimates",response_class=HTMLResponse)
def estimates(request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db)
    rows=db.query(EstimateRevision).join(Estimate).order_by(Estimate.created_at.desc()).all()
    return templates.TemplateResponse("estimates.html",{"request":request,"user":user,"rows":rows})

@app.post("/estimates/new")
def new_estimate(request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db); require_role(user,"ADMIN","ESTIMATOR")
    cfg=active_config(db)
    est=Estimate(estimate_number=allocate_estimate_number(db),created_by=user.id)
    db.add(est); db.flush()
    r=EstimateRevision(estimate_id=est.id,revision_no=1,config_version_id=cfg.id,engine_version=ENGINE_VERSION,
                       customer_name="",customer_type="Net New",proposal_date=date.today(),billing_rate=250,currency="US Dollar",
                       entity="Cloud Inventory LLC",erp="JD Edwards",project_type="Standard",solution_type="New",delivery_method="Remote",
                       gateway_required="No",gateway_sites=0,epp_install="No",epp_integration=0,ha_required="No",ha_instances=0,
                       security_method="None",go_live_count=1,custom_app_count=0,status="DRAFT",created_by=user.id)
    db.add(r); db.flush(); sync_catalog(db,r,r.erp)
    record(db,est.id,r.id,user.id,"ESTIMATE_CREATED","Estimate",est.id,None,{"estimate_number":est.estimate_number})
    recalculate_and_store(db,r); db.commit(); return RedirectResponse(f"/estimate/{r.id}",303)

@app.get("/estimate/{rid}",response_class=HTMLResponse)
def estimate_page(rid:int,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db); r=revision_or_404(db,rid); estimate,c,apps,pkgs,customs=estimate_context(db,r)
    cfg=Config(db,r.config_version_id)
    return templates.TemplateResponse("estimate.html",{"request":request,"user":user,"estimate":estimate,"rev":r,"calc":c,"apps":apps,"packages":pkgs,"customs":customs,"cfg":cfg,"active_tab":"estimate"})

@app.post("/estimate/{rid}")
async def estimate_save(rid:int,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db); require_role(user,"ADMIN","ESTIMATOR"); r=revision_or_404(db,rid); ensure_editable(r)
    form=await request.form(); before={c.name:getattr(r,c.name) for c in EstimateRevision.__table__.columns if c.name not in {"updated_at"}}
    string_fields=["customer_name","customer_type","ae_opportunity","currency","entity","erp","project_type","solution_type","upgrade_type","delivery_method","gateway_required","epp_install","ha_required","security_method"]
    numeric_fields=["billing_rate","gateway_sites","epp_integration","ha_instances","go_live_count","custom_app_count"]
    old_erp=r.erp
    for f in string_fields:
        if f in form: setattr(r,f,str(form.get(f) or ""))
    for f in numeric_fields:
        if f in form:
            try: setattr(r,f,float(form.get(f) or 0) if f=="billing_rate" else int(form.get(f) or 0))
            except ValueError: pass
    if "proposal_date" in form:
        try:r.proposal_date=date.fromisoformat(str(form.get("proposal_date")))
        except:pass
    errors=validate_input(r)
    if errors: raise HTTPException(400,"; ".join(errors))
    if old_erp!=r.erp: sync_catalog(db,r,r.erp,force=True)
    for a in db.query(EstimateApplication).filter(EstimateApplication.revision_id==r.id):
        k=f"app_{a.id}"; 
        if k in form: a.app_type=str(form.get(k))
    for p in db.query(EstimatePackage).filter(EstimatePackage.revision_id==r.id):
        k=f"pkg_{p.id}"; 
        if k in form: p.package_type=str(form.get(k))
    for i in range(1,21):
        descv=str(form.get(f"custom_desc_{i}") or "").strip(); typ=str(form.get(f"custom_type_{i}") or "No Config")
        row=db.query(CustomApplication).filter(CustomApplication.revision_id==r.id,CustomApplication.sort_order==i).first()
        if i<=r.custom_app_count:
            if not descv: raise HTTPException(400,f"Custom Application {i} description is required")
            if row is None: row=CustomApplication(revision_id=r.id,sort_order=i,description=descv,app_type=typ); db.add(row)
            else: row.description=descv; row.app_type=typ
        elif row: db.delete(row)
    mark_changed(r,db); recalculate_and_store(db,r)
    after={c.name:getattr(r,c.name) for c in EstimateRevision.__table__.columns if c.name not in {"updated_at"}}
    if before!=after: record(db,r.estimate_id,r.id,user.id,"ESTIMATE_UPDATED","EstimateRevision",r.id,before,after)
    db.commit(); return RedirectResponse(f"/estimate/{r.id}",303)

@app.post("/estimate/{rid}/recalculate")
def recalc(rid:int,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db); require_role(user,"ADMIN","ESTIMATOR"); r=revision_or_404(db,rid); ensure_editable(r)
    recalculate_and_store(db,r); record(db,r.estimate_id,r.id,user.id,"RECALCULATED","EstimateRevision",r.id,None,{"engine":r.engine_version}); db.commit(); return RedirectResponse(f"/estimate/{r.id}",303)

@app.post("/estimate/{rid}/adjust")
def adjust(rid:int,request:Request,key:str=Form(...),hours:float=Form(...),notes:str=Form(...),db:Session=Depends(get_db)):
    user=current_user(request,db); require_role(user,"ADMIN","ESTIMATOR"); r=revision_or_404(db,rid); ensure_editable(r)
    if abs(hours)>0 and not notes.strip(): raise HTTPException(400,"Adjustment reason is required")
    adj=db.query(CalculationAdjustment).filter(CalculationAdjustment.revision_id==r.id,CalculationAdjustment.line_key==key).first()
    before={"hours":adj.adjustment_hours,"notes":adj.notes} if adj else None
    if not adj: adj=CalculationAdjustment(revision_id=r.id,line_key=key,created_by=user.id); db.add(adj)
    adj.adjustment_hours=hours;adj.notes=notes.strip();adj.created_by=user.id;mark_changed(r,db);recalculate_and_store(db,r)
    record(db,r.estimate_id,r.id,user.id,"CALCULATION_ADJUSTMENT","CalculationAdjustment",key,before,{"hours":hours,"notes":notes});db.commit();return RedirectResponse(f"/estimate/{r.id}/calculations",303)

@app.get("/estimate/{rid}/detail",response_class=HTMLResponse)
def detail(rid:int,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db);r=revision_or_404(db,rid);estimate,c,apps,pkgs,customs=estimate_context(db,r)
    return templates.TemplateResponse("detail.html",{"request":request,"user":user,"estimate":estimate,"rev":r,"calc":c,"apps":apps,"packages":pkgs,"customs":customs,"active_tab":"detail"})

@app.get("/estimate/{rid}/calculations",response_class=HTMLResponse)
def calculations(rid:int,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db);r=revision_or_404(db,rid);estimate,c,apps,pkgs,customs=estimate_context(db,r)
    return templates.TemplateResponse("calculations.html",{"request":request,"user":user,"estimate":estimate,"rev":r,"calc":c,"active_tab":"calculations"})

@app.post("/estimate/{rid}/status")
def set_status(rid:int,request:Request,status:str=Form(...),db:Session=Depends(get_db)):
    user=current_user(request,db);r=revision_or_404(db,rid)
    allowed={"DRAFT":"REVIEW","REVIEW":"APPROVED","APPROVED":"SUPERSEDED"}
    if allowed.get(r.status)!=status: raise HTTPException(409,"Invalid status transition")
    if status=="REVIEW": require_role(user,"ADMIN","ESTIMATOR")
    else: require_role(user,"ADMIN","APPROVER")
    before=r.status;r.status=status
    if status=="APPROVED": r.locked_at=datetime.utcnow();r.locked_by=user.id
    record(db,r.estimate_id,r.id,user.id,"STATUS_CHANGED","EstimateRevision",r.id,before,status);db.commit();return RedirectResponse(f"/estimate/{r.id}",303)

@app.post("/estimate/{rid}/new-revision")
def new_revision(rid:int,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db);require_role(user,"ADMIN","ESTIMATOR");src=revision_or_404(db,rid)
    new=EstimateRevision(estimate_id=src.estimate_id,revision_no=max(x.revision_no for x in src.estimate.revisions)+1,config_version_id=src.config_version_id,engine_version=src.engine_version,
                         **{c.name:getattr(src,c.name) for c in EstimateRevision.__table__.columns if c.name not in {"id","estimate_id","revision_no","config_version_id","engine_version","status","created_at","updated_at","locked_at","locked_by","created_by","calculated_hours","calculated_fees","duration_months","recalculation_status","schedule_stale"}},status="DRAFT",created_by=user.id)
    db.add(new);db.flush()
    for model in [EstimateApplication,EstimatePackage,CustomApplication,CalculationAdjustment]:
        for row in db.query(model).filter(model.revision_id==src.id):
            vals={c.name:getattr(row,c.name) for c in model.__table__.columns if c.name not in {"id","revision_id","created_at","updated_at"}}
            db.add(model(revision_id=new.id,**vals))
    recalculate_and_store(db,new);record(db,new.estimate_id,new.id,user.id,"REVISION_CREATED","EstimateRevision",new.id,src.id,new.revision_no);db.commit();return RedirectResponse(f"/estimate/{new.id}",303)

@app.post("/estimate/{rid}/rebase")
def rebase(rid:int,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db);require_role(user,"ADMIN","ESTIMATOR");src=revision_or_404(db,rid);cfg=active_config(db)
    if cfg.id==src.config_version_id: raise HTTPException(409,"Estimate is already on the active configuration")
    new=copy.deepcopy(src);new.id=None;new.revision_no=max(x.revision_no for x in src.estimate.revisions)+1;new.config_version_id=cfg.id;new.status="DRAFT";new.locked_at=None;new.locked_by=None;new.created_by=user.id
    db.add(new);db.flush();sync_catalog(db,new,new.erp,force=True);recalculate_and_store(db,new);record(db,new.estimate_id,new.id,user.id,"CONFIG_REBASE","EstimateRevision",new.id,src.config_version_id,cfg.id);db.commit();return RedirectResponse(f"/estimate/{new.id}",303)

@app.get("/estimate/{rid}/schedule",response_class=HTMLResponse)
def schedule(rid:int,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db);r=revision_or_404(db,rid);estimate,c,_,_,_=estimate_context(db,r);metrics=schedule_metrics(db,r)
    tasks=db.query(ScheduleTask).filter(ScheduleTask.revision_id==r.id).order_by(ScheduleTask.sort_order).all()
    return templates.TemplateResponse("schedule.html",{"request":request,"user":user,"estimate":estimate,"rev":r,"calc":c,"tasks":tasks,"metrics":metrics,"active_tab":"schedule"})

@app.post("/estimate/{rid}/schedule/generate")
def schedule_generate(rid:int,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db);require_role(user,"ADMIN","ESTIMATOR");r=revision_or_404(db,rid);ensure_editable(r);generate_schedule(db,r,replace=True);db.commit();return RedirectResponse(f"/estimate/{r.id}/schedule",303)

@app.post("/estimate/{rid}/schedule/task/{tid}")
async def schedule_task_save(rid:int,tid:int,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db);require_role(user,"ADMIN","ESTIMATOR");r=revision_or_404(db,rid);ensure_editable(r);t=db.get(ScheduleTask,tid)
    if not t or t.revision_id!=r.id: raise HTTPException(404)
    form=await request.form();before={c.name:getattr(t,c.name) for c in ScheduleTask.__table__.columns}
    for f in ["resource_assigned","status","comments"]:
        if f in form:setattr(t,f,str(form.get(f) or ""))
    for f in ["percent_complete","change_order_hours","hours_used"]:
        if f in form:
            try:setattr(t,f,float(form.get(f) or 0))
            except:pass
    for f in ["start_date","end_date"]:
        if f in form:
            try:setattr(t,f,date.fromisoformat(str(form.get(f))))
            except:setattr(t,f,None)
    t.updated_by=user.id;after={c.name:getattr(t,c.name) for c in ScheduleTask.__table__.columns};record(db,r.estimate_id,r.id,user.id,"SCHEDULE_TASK_UPDATED","ScheduleTask",t.id,before,after);db.commit();return RedirectResponse(f"/estimate/{r.id}/schedule",303)

@app.get("/estimate/{rid}/audit",response_class=HTMLResponse)
def audit_page(rid:int,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db);r=revision_or_404(db,rid);events=db.query(AuditEvent).filter(AuditEvent.revision_id==r.id).order_by(AuditEvent.created_at.desc()).all();return templates.TemplateResponse("audit.html",{"request":request,"user":user,"estimate":r.estimate,"rev":r,"events":events,"active_tab":"audit"})

@app.get("/estimate/{rid}/pdf")
def pdf(rid:int,request:Request,db:Session=Depends(get_db)):
    current_user(request,db);r=revision_or_404(db,rid);est,c,apps,pkgs,customs=estimate_context(db,r);buf=io.BytesIO();styles=getSampleStyleSheet();doc=SimpleDocTemplate(buf,pagesize=letter)
    story=[Paragraph("Cloud Inventory Services Estimate",styles["Title"]),Spacer(1,12),Paragraph(f"Estimate {est.estimate_number} · Revision {r.revision_no}",styles["Heading2"]),Paragraph(f"Customer: {r.customer_name}",styles["Normal"]),Paragraph(f"ERP: {r.erp} · Solution: {r.solution_type}",styles["Normal"]),Spacer(1,12)]
    data=[["Phase","Activity","Hours"]]+[[x.phase,x.label,str(round(x.adjusted_hours,2))] for x in c.lines]+[["","Total",str(c.total_hours)]]
    story.append(Table(data,repeatRows=1));doc.build(story);buf.seek(0);return StreamingResponse(buf,media_type="application/pdf",headers={"Content-Disposition":f'attachment; filename="{est.estimate_number}-r{r.revision_no}.pdf"'})

@app.get("/estimate/{rid}/jira.csv")
def jira(rid:int,request:Request,db:Session=Depends(get_db)):
    current_user(request,db);r=revision_or_404(db,rid);est,c,_,_,_=estimate_context(db,r);out=io.StringIO();headers=["Summary","Issue Type","Description","Priority","Component/s","Original estimate","Assignee","Reporter","Labels","Epic Name","Epic Link","Parent","Fix Version/s","Affects Version/s","Due Date","Start date","Team","Story Points","Sprint","Environment","Linked Issues","Issue Links","Attachment","Comment","Status","Resolution","Project key"]
    w=csv.DictWriter(out,fieldnames=headers);w.writeheader()
    for phase in ["Plan","Design","Build","Test","Go-Live"]:
        epic=f"{est.estimate_number} - {phase}";w.writerow({"Summary":epic,"Issue Type":"Epic","Epic Name":epic,"Description":f"{phase} services for {r.customer_name}"})
        for line in [x for x in c.lines if x.phase==phase and x.adjusted_hours>0]: w.writerow({"Summary":line.label,"Issue Type":"Story","Description":line.trace,"Original estimate":line.adjusted_hours,"Parent":epic,"Epic Link":epic})
    return PlainTextResponse(out.getvalue(),media_type="text/csv",headers={"Content-Disposition":f'attachment; filename="{est.estimate_number}-jira.csv"'})

@app.get("/data",response_class=HTMLResponse)
def data_page(request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db);versions=db.query(ConfigurationVersion).order_by(ConfigurationVersion.created_at.desc()).all();v=versions[0] if versions else None
    items=db.query(ConfigItem).filter(ConfigItem.config_version_id==v.id).order_by(ConfigItem.category,ConfigItem.sort_order).all() if v else []
    return templates.TemplateResponse("data.html",{"request":request,"user":user,"versions":versions,"version":v,"items":items})

@app.post("/admin/config/clone")
def clone_config(request:Request,reason:str=Form(...),db:Session=Depends(get_db)):
    user=current_user(request,db);require_role(user,"ADMIN");src=active_config(db);v=ConfigurationVersion(name=f"Draft {datetime.utcnow().strftime('%Y.%m.%d.%H%M')}",status="DRAFT",created_by=user.id,change_reason=reason)
    db.add(v);db.flush()
    for x in db.query(ConfigItem).filter(ConfigItem.config_version_id==src.id):
        db.add(ConfigItem(config_version_id=v.id,**{c.name:getattr(x,c.name) for c in ConfigItem.__table__.columns if c.name not in {"id","config_version_id","created_at","updated_at"}}))
    record(db,None,None,user.id,"CONFIG_CLONED","ConfigurationVersion",v.id,src.id,v.name);db.commit();return RedirectResponse(f"/data?version={v.id}",303)

@app.post("/admin/config/{vid}/item/{iid}")
def update_config_item(vid:int,iid:int,request:Request,label:str=Form(...),value_number:str=Form(""),value_text:str=Form(""),active:str=Form("on"),db:Session=Depends(get_db)):
    user=current_user(request,db);require_role(user,"ADMIN");v=db.get(ConfigurationVersion,vid);x=db.get(ConfigItem,iid)
    if not v or not x or x.config_version_id!=v.id:raise HTTPException(404)
    if v.status!="DRAFT":raise HTTPException(409,"Only Draft configurations can be edited")
    before={"label":x.label,"value_number":x.value_number,"value_text":x.value_text,"active":x.active};x.label=label.strip();x.value_text=value_text or None;x.active=(active=="on")
    try:x.value_number=float(value_number) if value_number.strip() else None
    except:raise HTTPException(400,"Numeric value is invalid")
    record(db,None,None,user.id,"CONFIG_ITEM_UPDATED","ConfigItem",x.id,before,{"label":x.label,"value_number":x.value_number,"value_text":x.value_text,"active":x.active});db.commit();return RedirectResponse(f"/data?version={v.id}",303)

@app.post("/admin/config/{vid}/activate")
def activate_config(vid:int,request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db);require_role(user,"ADMIN");v=db.get(ConfigurationVersion,vid)
    if not v or v.status!="DRAFT":raise HTTPException(409,"Only a Draft configuration can be activated")
    current=active_config(db);current.status="RETIRED";v.status="ACTIVE";v.activated_at=datetime.utcnow();v.approval_status="ACTIVE";record(db,None,None,user.id,"CONFIG_ACTIVATED","ConfigurationVersion",v.id,current.id,v.id);db.commit();return RedirectResponse("/data",303)

@app.get("/admin/users",response_class=HTMLResponse)
def users_page(request:Request,db:Session=Depends(get_db)):
    user=current_user(request,db);require_role(user,"ADMIN");users=db.query(User).order_by(User.username).all();return templates.TemplateResponse("users.html",{"request":request,"user":user,"users":users,"roles":ROLE_ORDER})

@app.post("/admin/users/new")
def new_user(request:Request,username:str=Form(...),password:str=Form(...),role:str=Form(...),db:Session=Depends(get_db)):
    user=current_user(request,db);require_role(user,"ADMIN");n=normalize_username(username)
    if db.query(User).filter(User.username_normalized==n).first():raise HTTPException(409,"Username already exists")
    if role not in ROLE_ORDER:raise HTTPException(400,"Invalid role")
    u=User(username=username.strip(),username_normalized=n,password_hash=hash_password(password),role=role,active=True);db.add(u);db.flush();record(db,None,None,user.id,"USER_CREATED","User",u.id,None,{"username":u.username,"role":role});db.commit();return RedirectResponse("/admin/users",303)
