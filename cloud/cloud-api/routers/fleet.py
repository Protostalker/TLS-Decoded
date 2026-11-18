"""
Fleet — loading racks, tankers (with fixed physical compartments), tanker
loads, and daisy-chain delivery runs. This is the Fuel Provider view's
Phase 3: the part of the original feature list that lets a supplier define
WHERE a tanker loads from, WHAT PHYSICAL SHAPE a tanker is, what it's
carrying on a given trip, and how that one load gets split across multiple
drop-off stations in one run.

Four-step mental model, matching how this was asked for:
  1. LoadingRack  — a place to pick up fuel from (geocoded, map-pinned, same
     as a Station's pin).
  2. Tanker + TankerCompartment — the vehicle and its fixed physical
     layout (e.g. "2x10,000 gal"), defined ONCE and reused trip after trip.
     "Per tank, not per delivery."
  3. TankerLoad + TankerLoadItem — one loading event: what each compartment
     is carrying THIS trip (one or more products, %-split resolved to
     gallons client-side before it reaches here).
  4. DeliveryRun + DeliveryStop(+Item) — the daisy chain: that one load,
     dropped off across 1+ stations in order, each stop drawing specific
     product/gallons amounts out of the load. Route legs (rack -> stop 1,
     stop 1 -> stop 2, ...) are estimated once at creation time via the
     free OSM/OSRM stack (routing.py) and turned into elapsed-vs-estimate
     progress bars the same way the simpler single-station FuelOrder timer
     works (delivery.py) — no GPS, just "it's been X of an estimated Y
     minutes since this leg started."

Tenancy: racks/tankers belong to a customer_id (the fuel provider's own
company) — same pattern Station uses, scoped by assigned_station_ids'
sibling here (`_scope_customer_id`). Admins see everything; suppliers see
only their own customer's fleet. Degraded-mode gating mirrors supplier.py.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from auth import get_current_user, require_not_degraded, require_station_access
from database import get_db
from delivery import delivery_progress
from geocoding import geocode_address
from models import (
    DeliveryRun, DeliveryStop, DeliveryStopItem, LoadingRack, Notification,
    Station, Tanker, TankerCompartment, TankerLoad, TankerLoadItem, User,
)
from routers.supplier import _fire_push, _station_recipients
from routing import route as route_lookup
from schemas import (
    ArriveStopRequest, DeliveryRunCreate, DeliveryRunOut, DeliveryStopOut,
    DeliveryStopItemOut, LoadingRackCreate, LoadingRackOut, LoadingRackUpdate,
    TankerCompartmentIn, TankerCompartmentOut, TankerCreate, TankerLoadCreate,
    TankerLoadItemOut, TankerLoadOut, TankerOut,
)

router = APIRouter(dependencies=[Depends(require_not_degraded)])

# Compartment-fill tolerance — the %/max UI should always land exactly on
# capacity, but float rounding on the client is normal; a few gallons of
# slack either way isn't worth rejecting the load over.
_FILL_TOLERANCE_GALLONS = 5.0


def _require_supplier(user: User = Depends(get_current_user)) -> User:
    if user.role not in ("supplier", "admin"):
        raise HTTPException(status_code=403, detail="Supplier access required")
    return user


def _scope_customer_id(user: User) -> Optional[int]:
    """None means 'admin — no filter, see everything'."""
    return None if user.role == "admin" else user.customer_id


# ── Loading racks ─────────────────────────────────────────────────────────────

@router.get("/fleet/racks", response_model=list[LoadingRackOut])
def list_racks(user: User = Depends(_require_supplier), db: Session = Depends(get_db)):
    q = db.query(LoadingRack).filter(LoadingRack.active == True)  # noqa: E712
    cid = _scope_customer_id(user)
    if cid is not None:
        q = q.filter(LoadingRack.customer_id == cid)
    return [LoadingRackOut(id=r.id, name=r.name, address=r.address, lat=r.lat, lng=r.lng, active=r.active) for r in q.all()]


@router.post("/fleet/racks", response_model=LoadingRackOut)
def create_rack(body: LoadingRackCreate, user: User = Depends(_require_supplier), db: Session = Depends(get_db)):
    geo = geocode_address(body.address) if body.address else None
    rack = LoadingRack(
        customer_id=user.customer_id, name=body.name, address=body.address,
        lat=body.lat if body.lat is not None else (geo["lat"] if geo else None),
        lng=body.lng if body.lng is not None else (geo["lng"] if geo else None),
        active=True, created_at=datetime.now(tz=timezone.utc),
    )
    db.add(rack)
    db.commit()
    db.refresh(rack)
    return LoadingRackOut(id=rack.id, name=rack.name, address=rack.address, lat=rack.lat, lng=rack.lng, active=rack.active)


@router.put("/fleet/racks/{rack_id}", response_model=LoadingRackOut)
def update_rack(rack_id: int, body: LoadingRackUpdate, user: User = Depends(_require_supplier), db: Session = Depends(get_db)):
    rack = _get_rack_scoped(rack_id, user, db)
    if body.name is not None:
        rack.name = body.name
    if body.address is not None:
        rack.address = body.address
    if body.lat is not None:
        rack.lat = body.lat
    if body.lng is not None:
        rack.lng = body.lng
    if body.active is not None:
        rack.active = body.active
    db.commit()
    return LoadingRackOut(id=rack.id, name=rack.name, address=rack.address, lat=rack.lat, lng=rack.lng, active=rack.active)


def _get_rack_scoped(rack_id: int, user: User, db: Session) -> LoadingRack:
    rack = db.query(LoadingRack).filter(LoadingRack.id == rack_id).first()
    cid = _scope_customer_id(user)
    if not rack or (cid is not None and rack.customer_id != cid):
        raise HTTPException(status_code=404, detail="Loading rack not found")
    return rack


# ── Tankers + compartments ───────────────────────────────────────────────────

def _tanker_out(t: Tanker, compartments: list[TankerCompartment]) -> TankerOut:
    return TankerOut(
        id=t.id, label=t.label, active=t.active,
        compartments=[
            TankerCompartmentOut(id=c.id, label=c.label, capacity_gallons=c.capacity_gallons, display_order=c.display_order)
            for c in sorted(compartments, key=lambda c: (c.display_order if c.display_order is not None else 999, c.id))
        ],
    )


@router.get("/fleet/drivers")
def list_drivers(user: User = Depends(_require_supplier), db: Session = Depends(get_db)):
    """Active driver accounts this supplier can assign a run to — for the
    delivery-run builder's driver picker. Scoped the same way everything
    else in this router is (customer_id; admins see all)."""
    q = db.query(User).filter(User.role == "driver", User.active == True)  # noqa: E712
    cid = _scope_customer_id(user)
    if cid is not None:
        q = q.filter(User.customer_id == cid)
    return [{"id": d.id, "email": d.email} for d in q.order_by(User.email).all()]


@router.get("/fleet/tankers", response_model=list[TankerOut])
def list_tankers(user: User = Depends(_require_supplier), db: Session = Depends(get_db)):
    q = db.query(Tanker).filter(Tanker.active == True)  # noqa: E712
    cid = _scope_customer_id(user)
    if cid is not None:
        q = q.filter(Tanker.customer_id == cid)
    tankers = q.all()
    comps_by_tanker: dict[int, list[TankerCompartment]] = {}
    if tankers:
        rows = db.query(TankerCompartment).filter(TankerCompartment.tanker_id.in_([t.id for t in tankers])).all()
        for c in rows:
            comps_by_tanker.setdefault(c.tanker_id, []).append(c)
    return [_tanker_out(t, comps_by_tanker.get(t.id, [])) for t in tankers]


@router.post("/fleet/tankers", response_model=TankerOut)
def create_tanker(body: TankerCreate, user: User = Depends(_require_supplier), db: Session = Depends(get_db)):
    tanker = Tanker(customer_id=user.customer_id, label=body.label, active=True, created_at=datetime.now(tz=timezone.utc))
    db.add(tanker)
    db.flush()
    comps = []
    for i, c in enumerate(body.compartments):
        comp = TankerCompartment(tanker_id=tanker.id, label=c.label, capacity_gallons=c.capacity_gallons, display_order=i)
        db.add(comp)
        comps.append(comp)
    db.commit()
    for c in comps:
        db.refresh(c)
    return _tanker_out(tanker, comps)


@router.post("/fleet/tankers/{tanker_id}/compartments", response_model=TankerCompartmentOut)
def add_compartment(tanker_id: int, body: TankerCompartmentIn, user: User = Depends(_require_supplier), db: Session = Depends(get_db)):
    tanker = _get_tanker_scoped(tanker_id, user, db)
    existing_count = db.query(TankerCompartment).filter(TankerCompartment.tanker_id == tanker.id).count()
    comp = TankerCompartment(tanker_id=tanker.id, label=body.label, capacity_gallons=body.capacity_gallons, display_order=existing_count)
    db.add(comp)
    db.commit()
    db.refresh(comp)
    return TankerCompartmentOut(id=comp.id, label=comp.label, capacity_gallons=comp.capacity_gallons, display_order=comp.display_order)


def _get_tanker_scoped(tanker_id: int, user: User, db: Session) -> Tanker:
    tanker = db.query(Tanker).filter(Tanker.id == tanker_id).first()
    cid = _scope_customer_id(user)
    if not tanker or (cid is not None and tanker.customer_id != cid):
        raise HTTPException(status_code=404, detail="Tanker not found")
    return tanker


# ── Tanker loads ──────────────────────────────────────────────────────────────

def _load_out(db: Session, load: TankerLoad) -> TankerLoadOut:
    tanker = db.query(Tanker).filter(Tanker.id == load.tanker_id).first()
    rack = db.query(LoadingRack).filter(LoadingRack.id == load.loading_rack_id).first()
    items = db.query(TankerLoadItem).filter(TankerLoadItem.tanker_load_id == load.id).all()
    comp_labels = {
        c.id: c.label
        for c in db.query(TankerCompartment).filter(TankerCompartment.id.in_([i.tanker_compartment_id for i in items])).all()
    } if items else {}
    return TankerLoadOut(
        id=load.id, tanker_id=load.tanker_id, tanker_label=tanker.label if tanker else "?",
        loading_rack_id=load.loading_rack_id, loading_rack_name=rack.name if rack else "?",
        loaded_at=load.loaded_at, note=load.note,
        items=[
            TankerLoadItemOut(
                id=i.id, tanker_compartment_id=i.tanker_compartment_id,
                compartment_label=comp_labels.get(i.tanker_compartment_id, "?"),
                product=i.product, gallons=i.gallons, gallons_remaining=i.gallons_remaining,
            )
            for i in items
        ],
    )


@router.get("/fleet/loads", response_model=list[TankerLoadOut])
def list_loads(
    open_only: bool = True,
    user: User = Depends(_require_supplier), db: Session = Depends(get_db),
):
    """open_only=True (default) returns only loads with at least one item
    still carrying unallocated gallons — the ones worth building a new
    delivery run from."""
    cid = _scope_customer_id(user)
    q = db.query(TankerLoad).join(Tanker, Tanker.id == TankerLoad.tanker_id)
    if cid is not None:
        q = q.filter(Tanker.customer_id == cid)
    loads = q.order_by(TankerLoad.loaded_at.desc()).all()
    if open_only and loads:
        open_load_ids = {
            row[0] for row in
            db.query(TankerLoadItem.tanker_load_id)
            .filter(TankerLoadItem.tanker_load_id.in_([l.id for l in loads]), TankerLoadItem.gallons_remaining > 0.01)
            .all()
        }
        loads = [l for l in loads if l.id in open_load_ids]
    return [_load_out(db, l) for l in loads]


@router.get("/fleet/loads/{load_id}", response_model=TankerLoadOut)
def get_load(load_id: int, user: User = Depends(_require_supplier), db: Session = Depends(get_db)):
    load = _get_load_scoped(load_id, user, db)
    return _load_out(db, load)


def _get_load_scoped(load_id: int, user: User, db: Session) -> TankerLoad:
    load = db.query(TankerLoad).filter(TankerLoad.id == load_id).first()
    if not load:
        raise HTTPException(status_code=404, detail="Load not found")
    cid = _scope_customer_id(user)
    if cid is not None:
        tanker = db.query(Tanker).filter(Tanker.id == load.tanker_id).first()
        if not tanker or tanker.customer_id != cid:
            raise HTTPException(status_code=404, detail="Load not found")
    return load


@router.post("/fleet/loads", response_model=TankerLoadOut)
def create_load(body: TankerLoadCreate, user: User = Depends(_require_supplier), db: Session = Depends(get_db)):
    tanker = _get_tanker_scoped(body.tanker_id, user, db)
    rack = _get_rack_scoped(body.loading_rack_id, user, db)
    if not body.items:
        raise HTTPException(status_code=400, detail="A load needs at least one compartment item")

    compartments = {c.id: c for c in db.query(TankerCompartment).filter(TankerCompartment.tanker_id == tanker.id).all()}

    # Validate every item belongs to one of this tanker's own compartments,
    # and that each compartment's items sum to (about) its capacity — the
    # server's one sanity check on the %/max math the client already did.
    by_compartment: dict[int, float] = {}
    for item in body.items:
        comp = compartments.get(item.tanker_compartment_id)
        if not comp:
            raise HTTPException(status_code=400, detail=f"Compartment {item.tanker_compartment_id} doesn't belong to this tanker")
        if item.gallons <= 0:
            raise HTTPException(status_code=400, detail="Item gallons must be positive")
        by_compartment[comp.id] = by_compartment.get(comp.id, 0.0) + item.gallons

    for comp_id, total in by_compartment.items():
        comp = compartments[comp_id]
        if abs(total - comp.capacity_gallons) > _FILL_TOLERANCE_GALLONS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Compartment '{comp.label}' is {comp.capacity_gallons:.0f} gal but items sum to "
                    f"{total:.0f} gal — split must add up to the full compartment (use the Max button "
                    f"on the last product to fill the remainder)."
                ),
            )

    load = TankerLoad(
        tanker_id=tanker.id, loading_rack_id=rack.id, created_by_user_id=user.id,
        loaded_at=body.loaded_at or datetime.now(tz=timezone.utc), note=body.note,
    )
    db.add(load)
    db.flush()
    for item in body.items:
        db.add(TankerLoadItem(
            tanker_load_id=load.id, tanker_compartment_id=item.tanker_compartment_id,
            product=item.product, gallons=item.gallons, gallons_remaining=item.gallons,
        ))
    db.commit()
    db.refresh(load)
    return _load_out(db, load)


# ── Delivery runs (the daisy chain) ──────────────────────────────────────────

def _stop_out(stop: DeliveryStop, items: list[DeliveryStopItem], station_name: str) -> DeliveryStopOut:
    return DeliveryStopOut(
        id=stop.id, station_id=stop.station_id, station_name=station_name, stop_order=stop.stop_order,
        status=stop.status, started_at=stop.started_at, eta_minutes=stop.eta_minutes,
        distance_km=stop.distance_km, arrived_at=stop.arrived_at,
        items=[DeliveryStopItemOut(id=i.id, product=i.product, gallons_planned=i.gallons_planned, gallons_delivered=i.gallons_delivered) for i in items],
        delivery=delivery_progress(stop) if stop.started_at and stop.eta_minutes else None,
    )


def _run_out(db: Session, run: DeliveryRun) -> DeliveryRunOut:
    stops = db.query(DeliveryStop).filter(DeliveryStop.delivery_run_id == run.id).order_by(DeliveryStop.stop_order.asc()).all()
    items_by_stop: dict[int, list[DeliveryStopItem]] = {}
    station_names: dict[int, str] = {}
    if stops:
        all_items = db.query(DeliveryStopItem).filter(DeliveryStopItem.delivery_stop_id.in_([s.id for s in stops])).all()
        for i in all_items:
            items_by_stop.setdefault(i.delivery_stop_id, []).append(i)
        stations = db.query(Station).filter(Station.id.in_([s.station_id for s in stops])).all()
        station_names = {s.id: s.name for s in stations}
    driver_email = None
    if run.driver_user_id:
        driver = db.query(User).filter(User.id == run.driver_user_id).first()
        driver_email = driver.email if driver else None
    return DeliveryRunOut(
        id=run.id, tanker_load_id=run.tanker_load_id, status=run.status,
        created_at=run.created_at, dispatched_at=run.dispatched_at, completed_at=run.completed_at,
        driver_user_id=run.driver_user_id, driver_email=driver_email,
        stops=[_stop_out(s, items_by_stop.get(s.id, []), station_names.get(s.station_id, "?")) for s in stops],
    )


@router.get("/fleet/runs", response_model=list[DeliveryRunOut])
def list_runs(
    active_only: bool = True,
    user: User = Depends(_require_supplier), db: Session = Depends(get_db),
):
    cid = _scope_customer_id(user)
    q = db.query(DeliveryRun)
    if cid is not None:
        q = q.join(TankerLoad, TankerLoad.id == DeliveryRun.tanker_load_id).join(Tanker, Tanker.id == TankerLoad.tanker_id).filter(Tanker.customer_id == cid)
    if active_only:
        q = q.filter(DeliveryRun.status.in_(["planned", "dispatched"]))
    runs = q.order_by(DeliveryRun.created_at.desc()).all()
    return [_run_out(db, r) for r in runs]


@router.get("/fleet/runs/{run_id}", response_model=DeliveryRunOut)
def get_run(run_id: int, user: User = Depends(_require_supplier), db: Session = Depends(get_db)):
    run = _get_run_scoped(run_id, user, db)
    return _run_out(db, run)


def _get_run_scoped(run_id: int, user: User, db: Session) -> DeliveryRun:
    run = db.query(DeliveryRun).filter(DeliveryRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Delivery run not found")
    cid = _scope_customer_id(user)
    if cid is not None:
        load = db.query(TankerLoad).filter(TankerLoad.id == run.tanker_load_id).first()
        tanker = db.query(Tanker).filter(Tanker.id == load.tanker_id).first() if load else None
        if not tanker or tanker.customer_id != cid:
            raise HTTPException(status_code=404, detail="Delivery run not found")
    return run


def _notify_stop_in_transit(db: Session, run: DeliveryRun, stop: DeliveryStop, station: Station) -> None:
    """Tell the station's own recipients (their assigned users + all admins
    — see supplier.py's _station_recipients) that a tanker is now heading
    their way for this leg. Reuses the exact Notification/_fire_push pattern
    supplier.py's fuel-ordered flow uses, just with a different message/type,
    so both show up in the same notification bell."""
    recipient_ids = _station_recipients(db, station.id)
    if not recipient_ids:
        return
    eta_str = f"~{round(stop.eta_minutes)} min" if stop.eta_minutes else "ETA not available"
    message = f"A delivery is on its way to {station.name} — {eta_str}."
    now = datetime.now(tz=timezone.utc)
    for rid in recipient_ids:
        db.add(Notification(user_id=rid, station_id=station.id, type="delivery_in_transit", message=message, created_at=now))
    db.flush()
    _fire_push(db, recipient_ids, {"title": f"Fuel on the way — {station.name}", "body": eta_str, "tag": f"delivery-{run.id}-{stop.id}"})


def _notify_stop_delivered(db: Session, run: DeliveryRun, stop: DeliveryStop, station: Station) -> None:
    """Delivery confirmed at this stop — let the station know, with the
    download-report link baked right into the message (no SMTP; this is
    read in-app via the notification bell, same as everything else here)."""
    recipient_ids = _station_recipients(db, station.id)
    if not recipient_ids:
        return
    report_path = f"/api/stations/{station.id}/deliveries/{run.id}/report"
    message = f"Delivery confirmed at {station.name}. Download the report: {report_path}"
    now = datetime.now(tz=timezone.utc)
    for rid in recipient_ids:
        db.add(Notification(user_id=rid, station_id=station.id, type="delivery_confirmed", message=message, created_at=now))
    db.flush()
    _fire_push(db, recipient_ids, {"title": f"Delivery confirmed — {station.name}", "body": "Report is ready to download.", "tag": f"delivery-{run.id}-{stop.id}"})


@router.post("/fleet/runs", response_model=DeliveryRunOut)
def create_run(body: DeliveryRunCreate, user: User = Depends(_require_supplier), db: Session = Depends(get_db)):
    load = _get_load_scoped(body.tanker_load_id, user, db)
    rack = db.query(LoadingRack).filter(LoadingRack.id == load.loading_rack_id).first()
    if not body.stops:
        raise HTTPException(status_code=400, detail="A delivery run needs at least one stop")

    load_items = {i.id: i for i in db.query(TankerLoadItem).filter(TankerLoadItem.tanker_load_id == load.id).all()}

    # Validate every planned gallons amount against what's actually still
    # unallocated on the load BEFORE writing anything — a daisy chain that
    # over-promises gallons on, say, stop 3 should fail the whole run, not
    # partially commit stops 1-2 first.
    draw_totals: dict[int, float] = {}
    for stop_in in body.stops:
        require_station_access(stop_in.station_id, db, user)
        for item_in in stop_in.items:
            li = load_items.get(item_in.tanker_load_item_id)
            if not li:
                raise HTTPException(status_code=400, detail=f"Load item {item_in.tanker_load_item_id} doesn't belong to this load")
            if item_in.gallons <= 0:
                raise HTTPException(status_code=400, detail="Stop gallons must be positive")
            draw_totals[li.id] = draw_totals.get(li.id, 0.0) + item_in.gallons

    for item_id, total_draw in draw_totals.items():
        li = load_items[item_id]
        if total_draw > li.gallons_remaining + _FILL_TOLERANCE_GALLONS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Stops ask for {total_draw:.0f} gal of {li.product} from a compartment line that only "
                    f"has {li.gallons_remaining:.0f} gal left unallocated."
                ),
            )

    # Everything validated — now build it for real. Legs are rack -> stop0,
    # stop0 -> stop1, stop1 -> stop2, ... each estimated once up front via
    # OSRM; only stop 0 actually starts ticking (started_at set) immediately,
    # since the truck can only be on one leg at a time.
    driver_user_id = None
    if body.driver_user_id is not None:
        driver = db.query(User).filter(User.id == body.driver_user_id, User.role == "driver", User.active == True).first()  # noqa: E712
        if not driver:
            raise HTTPException(status_code=400, detail="driver_user_id doesn't match an active driver account")
        driver_user_id = driver.id

    now = datetime.now(tz=timezone.utc)
    run = DeliveryRun(
        tanker_load_id=load.id, supplier_user_id=user.id, driver_user_id=driver_user_id,
        status="dispatched", created_at=now, dispatched_at=now,
    )
    db.add(run)
    db.flush()

    prev_lat, prev_lng = (rack.lat, rack.lng) if rack else (None, None)
    stops_created: list[DeliveryStop] = []
    first_stop_station: Optional[Station] = None
    for idx, stop_in in enumerate(body.stops):
        station = db.query(Station).filter(Station.id == stop_in.station_id).first()
        if not station:
            raise HTTPException(status_code=404, detail=f"Station {stop_in.station_id} not found")

        eta_minutes = distance_km = None
        if prev_lat is not None and prev_lng is not None and station.lat is not None and station.lng is not None:
            result = route_lookup(prev_lat, prev_lng, station.lat, station.lng)
            if result:
                eta_minutes, distance_km = result["duration_min"], result["distance_km"]
        prev_lat, prev_lng = station.lat, station.lng

        stop = DeliveryStop(
            delivery_run_id=run.id, station_id=station.id, stop_order=idx,
            status="in_transit" if idx == 0 else "pending",
            started_at=now if idx == 0 else None,
            eta_minutes=eta_minutes, distance_km=distance_km,
        )
        db.add(stop)
        db.flush()
        for item_in in stop_in.items:
            db.add(DeliveryStopItem(
                delivery_stop_id=stop.id, tanker_load_item_id=item_in.tanker_load_item_id,
                product=load_items[item_in.tanker_load_item_id].product, gallons_planned=item_in.gallons,
            ))
        stops_created.append(stop)
        if idx == 0:
            first_stop_station = station

    for item_id, total_draw in draw_totals.items():
        load_items[item_id].gallons_remaining -= total_draw

    # The first leg starts moving immediately (stop 0 is "in_transit" from
    # the moment the run is dispatched) — tell that station right away.
    # Best-effort: a notification hiccup should never block dispatch.
    if first_stop_station is not None:
        try:
            _notify_stop_in_transit(db, run, stops_created[0], first_stop_station)
        except Exception:
            pass

    db.commit()
    return _run_out(db, run)


def arrive_stop_core(db: Session, run: DeliveryRun, stop_id: int, body: ArriveStopRequest) -> DeliveryRunOut:
    """
    Shared by both the supplier/admin endpoint below and the driver's own
    (routers/driver.py) — the two differ only in WHO is allowed to call
    this for a given run, not in what happens once they're let through.
    """
    stop = db.query(DeliveryStop).filter(DeliveryStop.id == stop_id, DeliveryStop.delivery_run_id == run.id).first()
    if not stop:
        raise HTTPException(status_code=404, detail="Stop not found on this run")
    if stop.status == "delivered":
        raise HTTPException(status_code=400, detail="Stop already marked delivered")

    now = datetime.now(tz=timezone.utc)
    stop.status = "delivered"
    stop.arrived_at = now

    overrides = {o.delivery_stop_item_id: o.gallons_delivered for o in body.items}
    items = db.query(DeliveryStopItem).filter(DeliveryStopItem.delivery_stop_id == stop.id).all()
    for i in items:
        i.gallons_delivered = overrides.get(i.id, i.gallons_planned)

    station = db.query(Station).filter(Station.id == stop.station_id).first()
    if station is not None:
        try:
            _notify_stop_delivered(db, run, stop, station)
        except Exception:
            pass  # notification hiccup should never block confirming a delivery

    # Start the next leg's clock, or close out the run if this was the last stop.
    next_stop = (
        db.query(DeliveryStop)
        .filter(DeliveryStop.delivery_run_id == run.id, DeliveryStop.stop_order == stop.stop_order + 1)
        .first()
    )
    if next_stop:
        next_stop.status = "in_transit"
        next_stop.started_at = now
        next_station = db.query(Station).filter(Station.id == next_stop.station_id).first()
        if next_station is not None:
            try:
                _notify_stop_in_transit(db, run, next_stop, next_station)
            except Exception:
                pass
    else:
        run.status = "completed"
        run.completed_at = now

    db.commit()
    return _run_out(db, run)


@router.post("/fleet/runs/{run_id}/stops/{stop_id}/arrive", response_model=DeliveryRunOut)
def arrive_stop(
    run_id: int, stop_id: int, body: ArriveStopRequest,
    user: User = Depends(_require_supplier), db: Session = Depends(get_db),
):
    run = _get_run_scoped(run_id, user, db)
    return arrive_stop_core(db, run, stop_id, body)


# ── Deletes (testing cleanup) ────────────────────────────────────────────────
#
# Hard deletes, scoped to the caller's own customer the same way every GET
# here is. Each one cascades downward so cleanup never leaves orphans:
# deleting a rack/tanker/load takes any runs built from it with it; deleting
# a run alone restores the gallons it drew from its load so that load goes
# back to "open." There's no "soft undo" here on purpose — this exists for
# clearing out test data, not for day-to-day archiving (racks/tankers still
# have `active` for that — see update_rack and the Tankers tab's own
# active-only listing).

def _cascade_delete_run(db: Session, run: DeliveryRun, restore_gallons: bool) -> None:
    """
    Deletes a run bottom-up: stop items, then stops, then the run itself,
    with a db.flush() between each stage. The flushes matter — these
    models use plain FK columns with no ORM relationship()/cascade
    declared between them, so SQLAlchemy's unit-of-work has no way to know
    "stop items must physically DELETE before their stop" and won't
    reliably order cross-table deletes within a single flush. Without the
    flushes, Postgres (and SQLite with PRAGMA foreign_keys=ON) rejects the
    batch with a FOREIGN KEY violation the instant it picks the wrong
    order — which is exactly the 500 this was causing live.
    """
    stops = db.query(DeliveryStop).filter(DeliveryStop.delivery_run_id == run.id).all()
    if stops:
        stop_ids = [s.id for s in stops]
        items = db.query(DeliveryStopItem).filter(DeliveryStopItem.delivery_stop_id.in_(stop_ids)).all()
        if restore_gallons:
            load_items = {
                li.id: li for li in
                db.query(TankerLoadItem).filter(TankerLoadItem.id.in_([i.tanker_load_item_id for i in items])).all()
            }
            for i in items:
                li = load_items.get(i.tanker_load_item_id)
                if li:
                    li.gallons_remaining += i.gallons_planned
        for i in items:
            db.delete(i)
        db.flush()  # delivery_stop_items gone before we touch delivery_stops
        for s in stops:
            db.delete(s)
        db.flush()  # delivery_stops gone before we touch delivery_runs
    db.delete(run)
    db.flush()  # delivery_runs row gone before the caller touches tanker_loads


def _cascade_delete_load(db: Session, load: TankerLoad) -> None:
    """Same bottom-up-with-flush pattern as _cascade_delete_run above, and
    for the same reason: tanker_load_items must be physically gone before
    the tanker_loads row (or its tanker/compartments) can go."""
    for run in db.query(DeliveryRun).filter(DeliveryRun.tanker_load_id == load.id).all():
        _cascade_delete_run(db, run, restore_gallons=False)  # load itself is going away too
    for item in db.query(TankerLoadItem).filter(TankerLoadItem.tanker_load_id == load.id).all():
        db.delete(item)
    db.flush()  # tanker_load_items gone before we touch tanker_loads
    db.delete(load)
    db.flush()  # tanker_loads row gone before the caller touches tankers/racks


def _commit_or_explain(db: Session) -> None:
    """A bare 500 tells nobody anything — if the cascade missed some FK
    (or the DB has rows from before this cascade logic existed, in an
    order we didn't anticipate), roll back and surface the real database
    error as a 400 instead, so it shows up directly in the UI instead of
    needing server logs to diagnose."""
    try:
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Couldn't delete — {e.__class__.__name__}: {getattr(e, 'orig', e)}")


@router.delete("/fleet/runs/{run_id}", status_code=204)
def delete_run(run_id: int, user: User = Depends(_require_supplier), db: Session = Depends(get_db)):
    """Deletes a delivery run and its stops, restoring whatever gallons it
    had drawn from its load (which keeps existing — only the run goes)."""
    run = _get_run_scoped(run_id, user, db)
    _cascade_delete_run(db, run, restore_gallons=True)
    _commit_or_explain(db)


@router.delete("/fleet/loads/{load_id}", status_code=204)
def delete_load(load_id: int, user: User = Depends(_require_supplier), db: Session = Depends(get_db)):
    """Deletes a load and everything built from it (any delivery runs,
    their stops) — the tanker and rack it used are untouched."""
    load = _get_load_scoped(load_id, user, db)
    _cascade_delete_load(db, load)
    _commit_or_explain(db)


@router.delete("/fleet/tankers/{tanker_id}", status_code=204)
def delete_tanker(tanker_id: int, user: User = Depends(_require_supplier), db: Session = Depends(get_db)):
    """Deletes a tanker, its compartments, and every load/run ever built
    from it. For retiring a tanker without losing delivery history, use
    PUT .../tankers (active=false) instead — this is for clearing test data."""
    tanker = _get_tanker_scoped(tanker_id, user, db)
    for load in db.query(TankerLoad).filter(TankerLoad.tanker_id == tanker.id).all():
        _cascade_delete_load(db, load)
    for comp in db.query(TankerCompartment).filter(TankerCompartment.tanker_id == tanker.id).all():
        db.delete(comp)
    db.flush()  # tanker_compartments gone before we touch the tankers row
    db.delete(tanker)
    _commit_or_explain(db)


@router.delete("/fleet/racks/{rack_id}", status_code=204)
def delete_rack(rack_id: int, user: User = Depends(_require_supplier), db: Session = Depends(get_db)):
    """Deletes a loading rack and every load/run ever built from it."""
    rack = _get_rack_scoped(rack_id, user, db)
    for load in db.query(TankerLoad).filter(TankerLoad.loading_rack_id == rack.id).all():
        _cascade_delete_load(db, load)
    db.flush()  # tanker_loads referencing this rack are gone before we touch the rack row
    db.delete(rack)
    _commit_or_explain(db)


# ── Reports ───────────────────────────────────────────────────────────────────
# No response_model here on purpose — these are read-only aggregate views,
# not resources with their own schema, so a plain dict keeps this from
# fighting Pydantic every time a new summary field gets added.

def _runs_query(db: Session, cid: Optional[int]):
    q = db.query(DeliveryRun)
    if cid is not None:
        q = q.join(TankerLoad, TankerLoad.id == DeliveryRun.tanker_load_id).join(Tanker, Tanker.id == TankerLoad.tanker_id).filter(Tanker.customer_id == cid)
    return q


def _delivered_stops_query(db: Session, cid: Optional[int]):
    q = db.query(DeliveryStop).join(DeliveryRun, DeliveryRun.id == DeliveryStop.delivery_run_id)
    if cid is not None:
        q = q.join(TankerLoad, TankerLoad.id == DeliveryRun.tanker_load_id).join(Tanker, Tanker.id == TankerLoad.tanker_id).filter(Tanker.customer_id == cid)
    return q.filter(DeliveryStop.status == "delivered")


@router.get("/fleet/reports/daily")
def daily_report(days: int = 7, user: User = Depends(_require_supplier), db: Session = Depends(get_db)):
    """
    Day-by-day totals for the last `days` UTC calendar days (today
    included): gallons delivered by product, stops completed, runs
    dispatched. Pricing/revenue is NOT computed — there's no reliable
    per-gallon price source wired up yet, so every response carries an
    explicit `pricing_note` instead of a silently-wrong number. The
    frontend should render that as a clearly-labeled "coming later" stub.
    """
    days = max(1, min(days, 90))
    cid = _scope_customer_id(user)
    since = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)

    stops = _delivered_stops_query(db, cid).filter(DeliveryStop.arrived_at >= since).all()
    items_by_stop: dict[int, list] = {}
    if stops:
        items = db.query(DeliveryStopItem).filter(DeliveryStopItem.delivery_stop_id.in_([s.id for s in stops])).all()
        for i in items:
            items_by_stop.setdefault(i.delivery_stop_id, []).append(i)

    buckets: dict[str, dict] = {}
    for d in range(days):
        day = (since + timedelta(days=d)).date().isoformat()
        buckets[day] = {"date": day, "stops_completed": 0, "runs_dispatched": 0, "gallons_by_product": {}}

    for s in stops:
        day = s.arrived_at.date().isoformat()
        bucket = buckets.get(day)
        if not bucket:
            continue
        bucket["stops_completed"] += 1
        for it in items_by_stop.get(s.id, []):
            gal = it.gallons_delivered if it.gallons_delivered is not None else it.gallons_planned
            bucket["gallons_by_product"][it.product] = round(bucket["gallons_by_product"].get(it.product, 0.0) + gal, 1)

    for r in _runs_query(db, cid).filter(DeliveryRun.dispatched_at >= since).all():
        if not r.dispatched_at:
            continue
        day = r.dispatched_at.date().isoformat()
        bucket = buckets.get(day)
        if bucket:
            bucket["runs_dispatched"] += 1

    rows = [buckets[k] for k in sorted(buckets.keys())]
    return {
        "days": days,
        "rows": rows,
        "total_gallons_delivered": round(sum(sum(r["gallons_by_product"].values()) for r in rows), 1),
        "total_stops_completed": sum(r["stops_completed"] for r in rows),
        "pricing_note": "Pricing/revenue totals aren't available yet — no per-gallon price source is wired up.",
    }


@router.get("/fleet/reports/shipments")
def shipments_report(days: int = 30, user: User = Depends(_require_supplier), db: Session = Depends(get_db)):
    """
    One row per completed stop ("shipment") in the last `days` days —
    station, tanker, driver, and planned-vs-delivered gallons per product
    so a shortfall or overage jumps right out as a nonzero `variance`.
    """
    days = max(1, min(days, 180))
    cid = _scope_customer_id(user)
    since = datetime.now(tz=timezone.utc) - timedelta(days=days)

    stops = (
        _delivered_stops_query(db, cid)
        .filter(DeliveryStop.arrived_at >= since)
        .order_by(DeliveryStop.arrived_at.desc())
        .all()
    )
    if not stops:
        return {"days": days, "shipments": []}

    runs = {r.id: r for r in db.query(DeliveryRun).filter(DeliveryRun.id.in_([s.delivery_run_id for s in stops])).all()}
    loads = {l.id: l for l in db.query(TankerLoad).filter(TankerLoad.id.in_([r.tanker_load_id for r in runs.values()])).all()}
    tankers = {t.id: t for t in db.query(Tanker).filter(Tanker.id.in_([l.tanker_id for l in loads.values()])).all()}
    stations = {s.id: s for s in db.query(Station).filter(Station.id.in_([s.station_id for s in stops])).all()}
    driver_ids = [r.driver_user_id for r in runs.values() if r.driver_user_id]
    drivers = {d.id: d for d in db.query(User).filter(User.id.in_(driver_ids)).all()} if driver_ids else {}
    items = db.query(DeliveryStopItem).filter(DeliveryStopItem.delivery_stop_id.in_([s.id for s in stops])).all()
    items_by_stop: dict[int, list] = {}
    for i in items:
        items_by_stop.setdefault(i.delivery_stop_id, []).append(i)

    shipments = []
    for s in stops:
        run = runs.get(s.delivery_run_id)
        load = loads.get(run.tanker_load_id) if run else None
        tanker = tankers.get(load.tanker_id) if load else None
        driver = drivers.get(run.driver_user_id) if run and run.driver_user_id else None
        station = stations.get(s.station_id)
        shipments.append({
            "stop_id": s.id, "run_id": s.delivery_run_id, "arrived_at": s.arrived_at,
            "station_name": station.name if station else "?",
            "tanker_label": tanker.label if tanker else "?",
            "driver_email": driver.email if driver else None,
            "items": [
                {
                    "product": it.product,
                    "gallons_planned": it.gallons_planned,
                    "gallons_delivered": it.gallons_delivered,
                    "variance": round((it.gallons_delivered or 0.0) - it.gallons_planned, 1),
                }
                for it in items_by_stop.get(s.id, [])
            ],
        })
    return {"days": days, "shipments": shipments}
