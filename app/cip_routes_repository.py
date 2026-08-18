from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session

from .cip_domain import estimate_product
from .cip_models import CIPRevisionInput, EstimateProduct, PRODUCT_CIP, PRODUCT_MEP
from .cip_revision import create_cip_estimate
from .database import get_db
from .models import Estimate, EstimateRevision


def register_repository_routes(app, core, mep_create):
    @app.get("/estimates", response_class=HTMLResponse)
    def estimates_page(request: Request, product: str = "", db: Session = Depends(get_db)):
        user = core.current_user(request, db)
        rows = []
        estimates = db.query(Estimate).filter(Estimate.deleted.is_(False)).order_by(desc(Estimate.id)).all()
        for estimate in estimates:
            rev = max(estimate.revisions, key=lambda r: r.revision_no) if estimate.revisions else None
            if not rev:
                continue
            p = estimate_product(db, estimate.id)
            if product and product in (PRODUCT_MEP, PRODUCT_CIP) and p != product:
                continue
            deployed = rev.erp
            if p == PRODUCT_CIP:
                inp = db.get(CIPRevisionInput, rev.id)
                deployed = inp.deployed_over if inp else "—"
            rows.append({"estimate": estimate, "rev": rev, "product": p, "deployed": deployed})
        return core.templates.TemplateResponse("estimates.html", {"request": request, "user": user, "rows": rows, "product_filter": product})

    @app.get("/estimates/new", response_class=HTMLResponse)
    def estimate_type_page(request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db)
        core.require_role(user, "ADMIN", "ESTIMATOR", "REVIEWER", "APPROVER")
        return core.templates.TemplateResponse("estimate_type.html", {"request": request, "user": user})

    @app.post("/estimates/new")
    async def create_product_estimate(request: Request, db: Session = Depends(get_db)):
        user = core.current_user(request, db)
        core.require_role(user, "ADMIN", "ESTIMATOR", "REVIEWER", "APPROVER")
        form = await request.form()
        product_type = str(form.get("product_type", PRODUCT_MEP)).upper()
        if product_type == PRODUCT_MEP:
            response = mep_create(request, db)
            try:
                rid = int(response.headers["location"].rsplit("/", 1)[-1])
                rev = db.get(EstimateRevision, rid)
                if rev and not db.get(EstimateProduct, rev.estimate_id):
                    db.add(EstimateProduct(estimate_id=rev.estimate_id, product_type=PRODUCT_MEP)); db.commit()
            except Exception:
                db.rollback(); raise
            return response
        if product_type == PRODUCT_CIP:
            rev = create_cip_estimate(db, core, user)
            return RedirectResponse(f"/estimate/{rev.id}", 303)
        raise HTTPException(400, "Select MEP or CIP estimate type.")
