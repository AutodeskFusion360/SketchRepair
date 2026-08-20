# =============================================================================
# Sketch Repair
# =============================================================================
# Author:      Rohit Bapat
# Email:       rhtbapat@gmail.com
# Command:     Sketch Repair
# Description: A Fusion add-in that diagnoses and fixes common sketch quality
#              issues. Provides three tools in a persistent palette:
#              - Gap Finder: detects open endpoints between curves and fixes
#                them with coincident constraints or bridging lines,
#                individually or all at once.
#              - Overlaps: identifies fully duplicate curves across all types
#                including splines with tangent/curvature handle comparison
#                and control point splines with degree validation.
#              - Small Curves: lists curves shorter than a given threshold,
#                sorted by length, with per-unit tolerance input.
#              All tolerances accept any unit (mm, cm, m, in, ft, mil) and
#              default to the active document unit.
# =============================================================================

import adsk.core, adsk.fusion, math, os, json, threading

PALETTE_ID        = 'SketchRepairPalette'
CMD_ID            = 'SketchRepairCmd'
CMD_NAME          = 'Sketch Repair'
CMD_TOOLTIP       = ('Sketch Repair - Diagnose and fix sketch quality issues. '
                      'Gap Finder: detects open endpoints within a tolerance and fixes them '
                      'with coincident constraints or bridging lines (individually or all at once). '
                      'Overlaps: identifies fully duplicate curves including lines, arcs, circles, '
                      'ellipses, conics, fitted splines (with tangent and curvature handle comparison) '
                      'and control point splines (with degree check). '
                      'Small Curves: lists curves shorter than a given threshold, sorted by length. '
                      'All tolerances accept any unit (mm, cm, m, in, ft, mil) and default to the document unit.')
ADDIN_DIR         = os.path.dirname(os.path.realpath(__file__))
HTML_PATH         = os.path.join(ADDIN_DIR, 'SketchRepair.html')
SKETCH_POLL_EVT   = 'SketchRepairSketchChangedEvent'

_app  = None
_ui   = None
_handlers           = []
_COINCIDENT_CM      = 1e-7
_last_gaps          = []
_last_overlaps      = []
_last_selected_idx  = -1
_last_tolerance_cm  = 0.01
_last_small_curves  = []
_last_small_tol_cm  = 0.001
_active_inputs      = None
_gfx_group          = None
_sketch             = None
_poll_stop          = None
_sketch_poll_event  = None


def _dist(p1, p2):
    dx,dy,dz = p1.x-p2.x, p1.y-p2.y, p1.z-p2.z
    return math.sqrt(dx*dx+dy*dy+dz*dz)

def _collect_endpoints(sketch):
    pts = []
    for i in range(sketch.sketchCurves.count):
        c = sketch.sketchCurves.item(i)
        if c.isConstruction: continue
        ct = type(c).__name__
        if ct in ('SketchLine','SketchArc','SketchEllipticalArc','SketchConicCurve','SketchFittedSpline','SketchControlPointSpline'):
            try:
                sp_geom = c.startSketchPoint.geometry
                ep_geom = c.endSketchPoint.geometry
                pts.append((sp_geom, c, c.startSketchPoint))
                pts.append((ep_geom, c, c.endSketchPoint))
            except Exception:
                pass  # skip degenerate curves (e.g. InternalValidationError)
    return pts

def find_gaps(sketch, tolerance_cm):
    all_pts = _collect_endpoints(sketch)
    matched = [False]*len(all_pts)
    for i in range(len(all_pts)):
        if matched[i]: continue
        for j in range(i+1, len(all_pts)):
            if matched[j]: continue
            if _dist(all_pts[i][0], all_pts[j][0]) < _COINCIDENT_CM:
                matched[i] = matched[j] = True; break
    open_pts = [(p,c,sp) for k,(p,c,sp) in enumerate(all_pts) if not matched[k]]
    cands = []
    for i in range(len(open_pts)):
        for j in range(i+1, len(open_pts)):
            if open_pts[i][1] == open_pts[j][1]: continue
            d = _dist(open_pts[i][0], open_pts[j][0])
            if d <= tolerance_cm: cands.append((d,i,j))
    cands.sort(key=lambda x: x[0])
    used = [False]*len(open_pts); gaps = []
    for d,i,j in cands:
        if used[i] or used[j]: continue
        used[i] = used[j] = True
        gaps.append({'dist_mm': round(d*10,4), 'ptA': open_pts[i][0], 'ptB': open_pts[j][0],
                     'spA': open_pts[i][2], 'spB': open_pts[j][2],
                     'curveA': open_pts[i][1], 'curveB': open_pts[j][1]})
    return gaps

def _curves_are_duplicate(cA, cB):
    try:
        return _curves_are_duplicate_impl(cA, cB)
    except Exception:
        return False  # degenerate curve -- treat as not duplicate

def _curves_are_duplicate_impl(cA, cB):
    SNAP = 1e-4
    tA, tB = type(cA).__name__, type(cB).__name__
    if tA != tB: return False
    def pt(p1,p2): return math.sqrt((p1.x-p2.x)**2+(p1.y-p2.y)**2+(p1.z-p2.z)**2) < SNAP
    def ve(v1,v2): return abs(v1.x-v2.x) < SNAP and abs(v1.y-v2.y) < SNAP
    if tA == 'SketchLine':
        sA,eA = cA.startSketchPoint.geometry, cA.endSketchPoint.geometry
        sB,eB = cB.startSketchPoint.geometry, cB.endSketchPoint.geometry
        return (pt(sA,sB) and pt(eA,eB)) or (pt(sA,eB) and pt(eA,sB))
    if tA == 'SketchArc':
        sA,eA,cA2 = cA.startSketchPoint.geometry, cA.endSketchPoint.geometry, cA.centerSketchPoint.geometry
        sB,eB,cB2 = cB.startSketchPoint.geometry, cB.endSketchPoint.geometry, cB.centerSketchPoint.geometry
        return pt(cA2,cB2) and ((pt(sA,sB) and pt(eA,eB)) or (pt(sA,eB) and pt(eA,sB)))
    if tA == 'SketchCircle':
        return pt(cA.centerSketchPoint.geometry, cB.centerSketchPoint.geometry) and abs(cA.radius-cB.radius) < SNAP
    if tA == 'SketchEllipse':
        c1,c2 = cA.centerSketchPoint.geometry, cB.centerSketchPoint.geometry
        return pt(c1,c2) and abs(cA.majorAxisRadius-cB.majorAxisRadius)<SNAP and abs(cA.minorAxisRadius-cB.minorAxisRadius)<SNAP and ve(cA.majorAxis,cB.majorAxis)
    if tA == 'SketchEllipticalArc':
        sA,eA,cA2 = cA.startSketchPoint.geometry, cA.endSketchPoint.geometry, cA.centerSketchPoint.geometry
        sB,eB,cB2 = cB.startSketchPoint.geometry, cB.endSketchPoint.geometry, cB.centerSketchPoint.geometry
        return pt(cA2,cB2) and abs(cA.majorAxisRadius-cB.majorAxisRadius)<SNAP and abs(cA.minorAxisRadius-cB.minorAxisRadius)<SNAP and ve(cA.majorAxis,cB.majorAxis) and ((pt(sA,sB) and pt(eA,eB)) or (pt(sA,eB) and pt(eA,sB)))
    if tA == 'SketchConicCurve':
        sA,eA,aA = cA.startSketchPoint.geometry, cA.endSketchPoint.geometry, cA.apexSketchPoint.geometry
        sB,eB,aB = cB.startSketchPoint.geometry, cB.endSketchPoint.geometry, cB.apexSketchPoint.geometry
        return pt(aA,aB) and abs(cA.rhoValue-cB.rhoValue)<SNAP and ((pt(sA,sB) and pt(eA,eB)) or (pt(sA,eB) and pt(eA,sB)))
    if tA == 'SketchFittedSpline':
        if cA.fitPoints.count != cB.fitPoints.count: return False
        nA, nB = cA.geometry, cB.geometry
        if nA.degree != nB.degree: return False
        if nA.controlPointCount != nB.controlPointCount: return False
        n = cA.fitPoints.count
        for j in range(n):
            if not pt(cA.fitPoints.item(j).geometry, cB.fitPoints.item(j).geometry): return False
        for j in range(n):
            fpA = cA.fitPoints.item(j); fpB = cB.fitPoints.item(j)
            thA = cA.getTangentHandle(fpA); thB = cB.getTangentHandle(fpB)
            if (thA is None) != (thB is None): return False
            if thA is not None:
                if not pt(thA.startSketchPoint.geometry, thB.startSketchPoint.geometry): return False
                if not pt(thA.endSketchPoint.geometry,   thB.endSketchPoint.geometry):   return False
        for j in range(n):
            fpA = cA.fitPoints.item(j); fpB = cB.fitPoints.item(j)
            chA = cA.getCurvatureHandle(fpA); chB = cB.getCurvatureHandle(fpB)
            if (chA is None) != (chB is None): return False
            if chA is not None:
                if not pt(chA.centerSketchPoint.geometry, chB.centerSketchPoint.geometry): return False
                if abs(chA.radius - chB.radius) >= SNAP: return False
        return True
    if tA == 'SketchControlPointSpline':
        if cA.degree != cB.degree: return False
        ptsA = [cA.controlPoints[j].geometry for j in range(len(cA.controlPoints))]
        ptsB = [cB.controlPoints[j].geometry for j in range(len(cB.controlPoints))]
        if len(ptsA) != len(ptsB): return False
        return all(pt(ptsA[j], ptsB[j]) for j in range(len(ptsA)))
    return False

def find_overlaps(sketch):
    raw = []
    for i in range(sketch.sketchCurves.count):
        c = sketch.sketchCurves.item(i)
        if c.isConstruction: continue
        try:
            # Probe basic properties to filter out degenerate curves
            ct = type(c).__name__
            if ct == 'SketchControlPointSpline': _ = c.degree
            if ct == 'SketchFittedSpline': _ = c.fitPoints.count
            raw.append(c)
        except Exception:
            pass  # skip degenerate curves
    used, groups = [False]*len(raw), []
    for i in range(len(raw)):
        if used[i]: continue
        grp = [raw[i]]
        for j in range(i+1, len(raw)):
            if not used[j] and _curves_are_duplicate(raw[i], raw[j]):
                grp.append(raw[j]); used[j] = True
        if len(grp) > 1:
            used[i] = True
            groups.append({'curve_type': type(raw[i]).__name__.replace('Sketch',''), 'count': len(grp), 'curves': grp})
    return groups



def _curve_length_cm(c):
    ct = type(c).__name__
    try:
        if ct == 'SketchLine':
            g = c.geometry
            return g.startPoint.distanceTo(g.endPoint)
        elif ct == 'SketchArc':
            g = c.geometry
            return g.radius * abs(g.endAngle - g.startAngle)
        elif ct == 'SketchCircle':
            return 2 * math.pi * c.radius
        elif ct == 'SketchEllipse':
            a, b = c.majorAxisRadius, c.minorAxisRadius
            h = ((a-b)/(a+b))**2
            return math.pi * (a+b) * (1 + 3*h/(10+math.sqrt(4-3*h)))
        else:
            wg = c.worldGeometry
            ev = wg.evaluator
            ok, t0, t1 = ev.getParameterExtents()
            if not ok: return None
            ok2, L = ev.getLengthAtParameter(t0, t1)
            return L if ok2 else None
    except Exception:
        return None

_SMALL_CURVE_SKIP = {'SketchPoint', 'SketchText'}

def find_small_curves(sketch, tolerance_cm):
    results = []
    for i in range(sketch.sketchCurves.count):
        c = sketch.sketchCurves.item(i)
        if type(c).__name__ in _SMALL_CURVE_SKIP: continue
        if c.isConstruction: continue
        L = _curve_length_cm(c)
        if L is not None and L < tolerance_cm:
            results.append({'curve_type': type(c).__name__.replace('Sketch',''), 'length_mm': round(L*10,6), 'curve': c})
    results.sort(key=lambda x: x['length_mm'])
    return results

def _clear_graphics():
    if not _app: return
    design = adsk.fusion.Design.cast(_app.activeProduct)
    if design:
        root = design.rootComponent
        for i in range(root.customGraphicsGroups.count-1,-1,-1):
            try: root.customGraphicsGroups.item(i).deleteMe()
            except: pass
    if _app: _app.activeViewport.refresh()

def _sphere_mesh(cx,cy,cz,r,sl=12,st=12):
    verts,tris=[],[]
    for i in range(st+1):
        phi=math.pi*i/st
        for j in range(sl):
            theta=2*math.pi*j/sl
            verts+=[cx+r*math.sin(phi)*math.cos(theta),cy+r*math.sin(phi)*math.sin(theta),cz+r*math.cos(phi)]
    for i in range(st):
        for j in range(sl):
            a=i*sl+j;b=a+sl;nj=(j+1)%sl;c=i*sl+nj;d=b-j+nj
            tris+=[a,b,c,c,b,d]
    return verts,tris

def _show_gap_graphics(gap,gap_index):
    _clear_graphics()
    design=adsk.fusion.Design.cast(_app.activeProduct)
    if not design: return
    comp=design.rootComponent
    sketch=design.activeEditObject
    if not isinstance(sketch,adsk.fusion.Sketch):
        if comp.sketches.count==0: return
        sketch=comp.sketches.item(0)
    xform=sketch.transform
    ptA_w=gap['ptA'].copy(); ptA_w.transformBy(xform)
    ptB_w=gap['ptB'].copy(); ptB_w.transformBy(xform)
    cam=_app.activeViewport.camera
    r=cam.viewExtents*0.01; fs=cam.viewExtents*0.02
    red=adsk.fusion.CustomGraphicsSolidColorEffect.create(adsk.core.Color.create(255,50,50,255))
    amber=adsk.fusion.CustomGraphicsSolidColorEffect.create(adsk.core.Color.create(255,180,0,255))
    white=adsk.fusion.CustomGraphicsSolidColorEffect.create(adsk.core.Color.create(255,255,255,255))
    grp=comp.customGraphicsGroups.add()
    coords=adsk.fusion.CustomGraphicsCoordinates.create([ptA_w.x,ptA_w.y,ptA_w.z,ptB_w.x,ptB_w.y,ptB_w.z])
    ln=grp.addLines(coords,[],False,[]); ln.weight=4; ln.color=amber
    for pt in [ptA_w,ptB_w]:
        verts,tris=_sphere_mesh(pt.x,pt.y,pt.z,r)
        sc=adsk.fusion.CustomGraphicsCoordinates.create(verts)
        mesh=grp.addMesh(sc,tris,[],[]); mesh.color=red; mesh.setOpacity(0.7,True)
    label=f"Gap {gap_index+1}: {gap['dist_mm']:.4f} mm"
    txt_pos=adsk.core.Point3D.create(gap['ptA'].x+r*3,gap['ptA'].y+r*3,gap['ptA'].z)
    tf=adsk.core.Matrix3D.create()
    tf.setCell(0,0,1);tf.setCell(0,1,0);tf.setCell(0,2,0)
    tf.setCell(1,0,0);tf.setCell(1,1,1);tf.setCell(1,2,0)
    tf.translation=adsk.core.Vector3D.create(txt_pos.x,txt_pos.y,txt_pos.z)
    tg=comp.customGraphicsGroups.add(); tg.transform=xform
    txt=tg.addText(label,'Arial',fs,tf); txt.isBold=True; txt.color=white
    bb=adsk.fusion.CustomGraphicsBillBoard.create(None)
    bb.billBoardStyle=adsk.fusion.CustomGraphicsBillBoardStyles.ScreenBillBoardStyle
    txt.billBoarding=bb
    _app.activeViewport.refresh(); adsk.doEvents()

def _look_at_gap(gap,zoom=False):
    ptA,ptB=gap['ptA'],gap['ptB']
    design=adsk.fusion.Design.cast(_app.activeProduct)
    sketch=design.activeEditObject if design else None
    if not isinstance(sketch,adsk.fusion.Sketch):
        root=design.rootComponent if design else None
        sketch=root.sketches.item(0) if root and root.sketches.count>0 else None
    if sketch:
        xf=sketch.transform
        ptA_w=ptA.copy(); ptA_w.transformBy(xf)
        ptB_w=ptB.copy(); ptB_w.transformBy(xf)
    else: ptA_w,ptB_w=ptA,ptB
    mid=adsk.core.Point3D.create((ptA_w.x+ptB_w.x)/2,(ptA_w.y+ptB_w.y)/2,(ptA_w.z+ptB_w.z)/2)
    vp=_app.activeViewport; cam=vp.camera
    dx=mid.x-cam.target.x; dy=mid.y-cam.target.y; dz=mid.z-cam.target.z
    cam.target=adsk.core.Point3D.create(cam.target.x+dx,cam.target.y+dy,cam.target.z+dz)
    cam.eye=adsk.core.Point3D.create(cam.eye.x+dx,cam.eye.y+dy,cam.eye.z+dz)
    if zoom:
        d=math.sqrt((ptA_w.x-ptB_w.x)**2+(ptA_w.y-ptB_w.y)**2+(ptA_w.z-ptB_w.z)**2)
        cam.viewExtents=d*2.0
    cam.isSmoothTransition=True; vp.camera=cam

def _zoom_to_small_curve(curve):
    design=adsk.fusion.Design.cast(_app.activeProduct)
    sk=design.activeEditObject if design else None
    if not isinstance(sk,adsk.fusion.Sketch): return
    ct=type(curve).__name__
    xf=sk.transform
    try:
        if ct in ('SketchLine','SketchArc','SketchEllipticalArc','SketchConicCurve','SketchFittedSpline','SketchControlPointSpline'):
            pA=curve.startSketchPoint.geometry.copy(); pA.transformBy(xf)
            pB=curve.endSketchPoint.geometry.copy();   pB.transformBy(xf)
            pts=[pA,pB]
        elif ct in ('SketchCircle','SketchEllipse'):
            c=curve.centerSketchPoint.geometry.copy(); c.transformBy(xf)
            pts=[c]
        else: return
        mid_x=sum(p.x for p in pts)/len(pts)
        mid_y=sum(p.y for p in pts)/len(pts)
        mid_z=sum(p.z for p in pts)/len(pts)
        L=_curve_length_cm(curve)
        vp=_app.activeViewport; cam=vp.camera
        dx=mid_x-cam.target.x; dy=mid_y-cam.target.y; dz=mid_z-cam.target.z
        cam.target=adsk.core.Point3D.create(cam.target.x+dx,cam.target.y+dy,cam.target.z+dz)
        cam.eye=adsk.core.Point3D.create(cam.eye.x+dx,cam.eye.y+dy,cam.eye.z+dz)
        if L and L>0: cam.viewExtents=max(L*2.0,0.05)
        cam.isSmoothTransition=True; vp.camera=cam
    except Exception: pass

def _highlight_gap(gap):
    sel=_ui.activeSelections; sel.clear()
    if gap['curveA'] and gap['curveA'].isValid: sel.add(gap['curveA'])
    if gap['curveB'] and gap['curveB'].isValid and gap['curveB']!=gap['curveA']: sel.add(gap['curveB'])


def _check_sketch_changed():
    global _sketch, _last_gaps, _last_overlaps, _last_small_curves, _last_selected_idx
    design = adsk.fusion.Design.cast(_app.activeProduct)
    if not design: return
    current = design.activeEditObject
    if not isinstance(current, adsk.fusion.Sketch): return
    if _sketch is None or not _sketch.isValid or current.entityToken != _sketch.entityToken:
        _sketch = current
        _last_gaps[:] = []
        _last_overlaps[:] = []
        _last_small_curves[:] = []
        _last_selected_idx = -1
        _clear_graphics()
        _ui.activeSelections.clear()
        palette = _ui.palettes.itemById(PALETTE_ID)
        if palette and palette.isVisible:
            palette.sendInfoToHTML('sketch_changed', '{}')


class SketchChangedEventHandler(adsk.core.CustomEventHandler):
    def __init__(self): super().__init__()
    def notify(self, args):
        global _sketch, _last_gaps, _last_overlaps, _last_small_curves, _last_selected_idx
        event_type = args.additionalInfo if args.additionalInfo else ''
        _last_gaps[:] = []
        _last_overlaps[:] = []
        _last_small_curves[:] = []
        _last_selected_idx = -1
        _clear_graphics()
        _ui.activeSelections.clear()
        if event_type == 'enter':
            design = adsk.fusion.Design.cast(_app.activeProduct)
            if design:
                current = design.activeEditObject
                if isinstance(current, adsk.fusion.Sketch):
                    _sketch = current
        elif event_type == 'exit':
            _sketch = None
        palette = _ui.palettes.itemById(PALETTE_ID)
        if palette and palette.isVisible:
            palette.sendInfoToHTML('sketch_changed', '{}')


def _start_sketch_watcher():
    global _poll_stop, _sketch_poll_event
    _stop_sketch_watcher()
    try: _app.unregisterCustomEvent(SKETCH_POLL_EVT)
    except: pass
    _sketch_poll_event = _app.registerCustomEvent(SKETCH_POLL_EVT)
    h = SketchChangedEventHandler()
    _sketch_poll_event.add(h)
    _handlers.append(h)
    _poll_stop = threading.Event()
    def _poll():
        last_token = None
        while not _poll_stop.wait(0.5):
            try:
                design = adsk.fusion.Design.cast(_app.activeProduct)
                if not design: continue
                obj = design.activeEditObject
                tok = obj.entityToken if isinstance(obj, adsk.fusion.Sketch) else None
                if tok != last_token:
                    prev = last_token
                    last_token = tok
                    # Only fire when no interactive command is active
                    # to avoid interfering with primitive commands
                    # that create temporary sketches internally
                    active_cmd = _ui.activeCommand
                    safe = (active_cmd == 'SelectCommand' or
                            active_cmd == CMD_ID or
                            active_cmd == PALETTE_ID or
                            active_cmd == '')
                    if safe:
                        if prev is not None and tok is None:
                            _app.fireCustomEvent(SKETCH_POLL_EVT, 'exit')
                        elif tok is not None:
                            _app.fireCustomEvent(SKETCH_POLL_EVT, 'enter')
            except Exception: pass
    threading.Thread(target=_poll, daemon=True).start()


def _stop_sketch_watcher():
    global _poll_stop
    if _poll_stop:
        _poll_stop.set()
        _poll_stop = None
    try: _app.unregisterCustomEvent(SKETCH_POLL_EVT)
    except: pass


class SketchRepairHTMLHandler(adsk.core.HTMLEventHandler):
    def __init__(self): super().__init__()
    def notify(self, args):
        global _last_gaps, _last_selected_idx, _sketch, _last_tolerance_cm
        global _last_small_curves, _last_small_tol_cm, _last_overlaps
        try:
            html_args = adsk.core.HTMLEventArgs.cast(args)
            _check_sketch_changed()
            action = html_args.action
            data   = json.loads(html_args.data) if html_args.data else {}

            if action == 'scan':
                design = adsk.fusion.Design.cast(_app.activeProduct)
                if not design:
                    html_args.returnData = json.dumps({'ok': False, 'error': 'No active design'}); return
                sk = design.activeEditObject
                if not isinstance(sk, adsk.fusion.Sketch):
                    html_args.returnData = json.dumps({'ok': False, 'error': 'No active sketch. Enter sketch edit mode first.'}); return
                tol_val  = float(data.get('value', 0.1))
                tol_unit = data.get('unit', 'mm')
                if tol_unit not in {'mm','cm','m','in','ft','mil'}: tol_unit = 'mm'
                _last_tolerance_cm = design.unitsManager.convert(tol_val, tol_unit, 'cm')
                doc_unit = design.unitsManager.defaultLengthUnits
                if doc_unit not in {'mm','cm','m','in','ft','mil'}: doc_unit = 'mm'
                _sketch = sk
                _last_gaps = find_gaps(sk, _last_tolerance_cm)
                _last_selected_idx = -1
                _clear_graphics(); _ui.activeSelections.clear()
                gaps_out = [{'idx': i, 'dist_mm': g['dist_mm']} for i,g in enumerate(_last_gaps)]
                html_args.returnData = json.dumps({'ok': True, 'gaps': gaps_out, 'default_unit': doc_unit})

            elif action == 'select':
                idx = int(data.get('idx', -1))
                if 0 <= idx < len(_last_gaps):
                    _last_selected_idx = idx
                    gap = _last_gaps[idx]
                    _highlight_gap(gap)
                    _look_at_gap(gap, zoom=True)
                    if data.get('show_markers', True):
                        _show_gap_graphics(gap, idx)
                    else:
                        _clear_graphics()
                html_args.returnData = json.dumps({'ok': True})

            elif action in ('fix_coincident', 'fix_line'):
                idx = int(data.get('idx', _last_selected_idx))
                if idx < 0 or idx >= len(_last_gaps):
                    html_args.returnData = json.dumps({'ok': False, 'error': 'No gap selected'}); return
                gap = _last_gaps[idx]
                sk  = _sketch
                if not sk or not sk.isValid:
                    html_args.returnData = json.dumps({'ok': False, 'error': 'Sketch no longer valid'}); return
                spA = gap['spA']; spB = gap['spB']
                if not spA.isValid or not spB.isValid:
                    html_args.returnData = json.dumps({'ok': False, 'error': 'Sketch points no longer valid'}); return
                _clear_graphics()
                if action == 'fix_coincident':
                    sk.geometricConstraints.addCoincident(spA, spB)
                else:
                    ln = sk.sketchCurves.sketchLines.addByTwoPoints(spA.geometry, spB.geometry)
                    sk.geometricConstraints.addCoincident(ln.startSketchPoint, spA)
                    sk.geometricConstraints.addCoincident(ln.endSketchPoint,   spB)
                _last_gaps = find_gaps(sk, _last_tolerance_cm)
                _last_selected_idx = -1
                _ui.activeSelections.clear()
                gaps_out = [{'idx': i, 'dist_mm': g['dist_mm']} for i,g in enumerate(_last_gaps)]
                html_args.returnData = json.dumps({'ok': True, 'gaps': gaps_out})

            elif action in ('fix_all_coincident', 'fix_all_line'):
                sk = _sketch
                if not sk or not sk.isValid:
                    html_args.returnData = json.dumps({'ok': False, 'error': 'Sketch no longer valid'}); return
                fixed = 0; failed = 0
                while True:
                    current_gaps = find_gaps(sk, _last_tolerance_cm)
                    if not current_gaps: break
                    g = current_gaps[0]
                    spA, spB = g['spA'], g['spB']
                    if not spA.isValid or not spB.isValid: failed += 1; break
                    try:
                        _clear_graphics()
                        if action == 'fix_all_coincident':
                            sk.geometricConstraints.addCoincident(spA, spB)
                        else:
                            ln = sk.sketchCurves.sketchLines.addByTwoPoints(spA.geometry, spB.geometry)
                            sk.geometricConstraints.addCoincident(ln.startSketchPoint, spA)
                            sk.geometricConstraints.addCoincident(ln.endSketchPoint, spB)
                        fixed += 1
                    except Exception as e:
                        failed += 1; break
                _last_gaps = find_gaps(sk, _last_tolerance_cm)
                _last_selected_idx = -1
                _ui.activeSelections.clear()
                gaps_out = [{'idx': i, 'dist_mm': g['dist_mm']} for i,g in enumerate(_last_gaps)]
                msg = f'{fixed} gap(s) fixed' + (f', {failed} failed' if failed else '')
                html_args.returnData = json.dumps({'ok': True, 'gaps': gaps_out, 'msg': msg})

            elif action == 'toggle_markers':
                show = bool(data.get('show', True))
                if not show:
                    _clear_graphics()
                elif 0 <= _last_selected_idx < len(_last_gaps):
                    gap = _last_gaps[_last_selected_idx]
                    _show_gap_graphics(gap, _last_selected_idx)
                html_args.returnData = json.dumps({'ok': True})

            elif action == 'scan_small_curves':
                design = adsk.fusion.Design.cast(_app.activeProduct)
                if not design:
                    html_args.returnData = json.dumps({'ok': False, 'error': 'No active design'}); return
                sk = design.activeEditObject
                if not isinstance(sk, adsk.fusion.Sketch):
                    html_args.returnData = json.dumps({'ok': False, 'error': 'No active sketch. Enter sketch edit mode first.'}); return
                tol_val  = float(data.get('value', 0.01))
                tol_unit = data.get('unit', 'mm')
                if tol_unit not in {'mm','cm','m','in','ft','mil'}: tol_unit = 'mm'
                doc_unit = design.unitsManager.defaultLengthUnits
                if doc_unit not in {'mm','cm','m','in','ft','mil'}: doc_unit = 'mm'
                _sketch = sk
                _last_small_tol_cm = design.unitsManager.convert(tol_val, tol_unit, 'cm')
                _last_small_curves[:] = find_small_curves(sk, _last_small_tol_cm)
                out = [{'idx': i, 'curve_type': o['curve_type'], 'length_mm': o['length_mm']}
                       for i, o in enumerate(_last_small_curves)]
                html_args.returnData = json.dumps({'ok': True, 'curves': out, 'default_unit': doc_unit})

            elif action == 'select_small_curve':
                idx = int(data.get('idx', -1))
                if 0 <= idx < len(_last_small_curves):
                    crv = _last_small_curves[idx]['curve']
                    if crv.isValid:
                        _ui.activeSelections.clear()
                        _ui.activeSelections.add(crv)
                        _zoom_to_small_curve(crv)
                html_args.returnData = json.dumps({'ok': True})

            elif action == 'scan_overlaps':
                design = adsk.fusion.Design.cast(_app.activeProduct)
                if not design:
                    html_args.returnData = json.dumps({'ok': False, 'error': 'No active design'}); return
                sk = design.activeEditObject
                if not isinstance(sk, adsk.fusion.Sketch):
                    html_args.returnData = json.dumps({'ok': False, 'error': 'No active sketch. Enter sketch edit mode first.'}); return
                _sketch = sk
                overlaps = find_overlaps(sk)
                _last_overlaps[:] = overlaps
                out = [{'curve_type': o['curve_type'], 'count': o['count']} for o in overlaps]
                html_args.returnData = json.dumps({'ok': True, 'overlaps': out})

            elif action == 'select_overlap':
                idx = int(data.get('idx', -1))
                if 0 <= idx < len(_last_overlaps):
                    ovr = _last_overlaps[idx]
                    _ui.activeSelections.clear()
                    for crv in ovr['curves']:
                        if crv and crv.isValid: _ui.activeSelections.add(crv)
                    c = ovr['curves'][0]
                    p = c.startSketchPoint.geometry if type(c).__name__ == 'SketchLine' else c.centerSketchPoint.geometry
                    _look_at_gap({'ptA': p, 'ptB': p}, zoom=False)
                html_args.returnData = json.dumps({'ok': True})

            elif action == 'scan_damaged':
                design = adsk.fusion.Design.cast(_app.activeProduct)
                if not design:
                    html_args.returnData = json.dumps({'ok': False, 'error': 'No active design'}); return
                sk = design.activeEditObject
                if not isinstance(sk, adsk.fusion.Sketch):
                    html_args.returnData = json.dumps({'ok': False, 'error': 'No active sketch. Enter sketch edit mode first.'}); return
                _sketch = sk
                _last_damaged[:] = find_damaged_entities(sk)
                out = [{'idx': i, 'curve_type': o['curve_type'], 'reason': o['reason']}
                       for i, o in enumerate(_last_damaged)]
                html_args.returnData = json.dumps({'ok': True, 'entities': out})

            elif action == 'select_damaged':
                idx = int(data.get('idx', -1))
                if 0 <= idx < len(_last_damaged):
                    crv = _last_damaged[idx]['curve']
                    _ui.activeSelections.clear()
                    try:
                        if crv.isValid: _ui.activeSelections.add(crv)
                    except: pass
                    # Zoom: try to get any valid geometry reference
                    try: _zoom_to_small_curve(crv)
                    except: pass
                html_args.returnData = json.dumps({'ok': True})

            elif action == 'delete_damaged':
                idx = int(data.get('idx', -1))
                if idx < 0 or idx >= len(_last_damaged):
                    html_args.returnData = json.dumps({'ok': False, 'error': 'No entity selected'}); return
                crv = _last_damaged[idx]['curve']
                try:
                    crv.deleteMe()
                except Exception as e:
                    html_args.returnData = json.dumps({'ok': False, 'error': f'Delete failed: {e}'}); return
                # Re-scan after deletion
                sk = _sketch
                if sk and sk.isValid:
                    _last_damaged[:] = find_damaged_entities(sk)
                else:
                    _last_damaged.pop(idx)
                _ui.activeSelections.clear()
                out = [{'idx': i, 'curve_type': o['curve_type'], 'reason': o['reason']}
                       for i, o in enumerate(_last_damaged)]
                html_args.returnData = json.dumps({'ok': True, 'entities': out})

            else:
                html_args.returnData = json.dumps({'ok': False, 'error': f'Unknown action: {action}'})

        except Exception as e:
            import traceback
            html_args.returnData = json.dumps({'ok': False, 'error': str(e), 'trace': traceback.format_exc()})


class SketchRepairClosedHandler(adsk.core.UserInterfaceGeneralEventHandler):
    def __init__(self): super().__init__()
    def notify(self, args):
        _clear_graphics()
        _ui.activeSelections.clear()



class SketchRepairCmdExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self): super().__init__()
    def notify(self, args):
        palette = _ui.palettes.itemById(PALETTE_ID)
        if not palette:
            palette = _ui.palettes.add(PALETTE_ID, CMD_NAME, HTML_PATH, True, True, True, 340, 520, True)
            h_html   = SketchRepairHTMLHandler()
            h_closed = SketchRepairClosedHandler()
            palette.incomingFromHTML.add(h_html);   _handlers.append(h_html)
            palette.closed.add(h_closed);            _handlers.append(h_closed)
            _last_gaps[:] = []; _last_overlaps[:] = []; _last_small_curves[:] = []
            _last_selected_idx = -1; _sketch = None
            _clear_graphics(); _ui.activeSelections.clear()
            sketch_palette = _ui.palettes.itemById('QTCommandDialogContentPanelToolPropertyPanelSketch Palette')
            if sketch_palette and sketch_palette.isVisible:
                palette.snapTo(sketch_palette, adsk.core.PaletteSnapOptions.PaletteSnapOptionsRight)
            else:
                palette.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateRight
        else:
            palette.isVisible = True
            _last_gaps[:] = []; _last_overlaps[:] = []; _last_small_curves[:] = []
            _last_selected_idx = -1; _sketch = None
            _clear_graphics(); _ui.activeSelections.clear()
            palette.sendInfoToHTML('sketch_changed', '{}')


class SketchRepairCmdCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self): super().__init__()
    def notify(self, args):
        h = SketchRepairCmdExecuteHandler()
        args.command.execute.add(h); _handlers.append(h)


def run(context):
    global _app, _ui
    _app = adsk.core.Application.get(); _ui = _app.userInterface
    old = _ui.commandDefinitions.itemById(CMD_ID)
    if old: old.deleteMe()
    _handlers.clear()
    panel = _ui.allToolbarPanels.itemById('SketchModifyPanel')
    if not panel: return
    ctrl = panel.controls.itemById(CMD_ID)
    if ctrl: ctrl.deleteMe()
    cmd_def = _ui.commandDefinitions.addButtonDefinition(CMD_ID, CMD_NAME, CMD_TOOLTIP)
    h = SketchRepairCmdCreatedHandler()
    cmd_def.commandCreated.add(h); _handlers.append(h)
    panel.controls.addCommand(cmd_def).isPromotedByDefault = True
    _start_sketch_watcher()


def stop(context):
    _stop_sketch_watcher()
    _clear_graphics()
    _ui.activeSelections.clear()
    palette = _ui.palettes.itemById(PALETTE_ID)
    if palette: palette.deleteMe()
    panel = _ui.allToolbarPanels.itemById('SketchModifyPanel')
    if panel:
        ctrl = panel.controls.itemById(CMD_ID)
        if ctrl: ctrl.deleteMe()
    d = _ui.commandDefinitions.itemById(CMD_ID)
    if d: d.deleteMe()
    _handlers.clear()
